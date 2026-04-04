import os
import json
import asyncio
import base64
import tempfile
from fastapi import FastAPI, WebSocket, Request, Form
from fastapi.responses import Response, FileResponse

import config
from audio_utils import decode_twilio_media, save_pcm_as_wav
from vad_service import VADProcessor
from sarvam_services.sarvam_stt import transcribe_audio
from sarvam_services.sarvam_tts import stream_tts, AUDIO_DIR
from groq_services.groq_llm import chat
from twilio_services.twilio_call import make_call


app = FastAPI(title="StockMarketVoice")

# Per-call conversation history (keyed by CallSid)
call_histories: dict[str, list[dict]] = {}


# ─── Twilio Webhook ──────────────────────────────────────────────────────


@app.post("/voice")
async def voice_webhook():
    """
    Twilio calls this when the outbound call is answered.
    Returns TwiML that opens a bidirectional media stream.
    """
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://{config.SERVER_URL.replace('https://', '').replace('http://', '')}/media-stream" />
    </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


# ─── Media Stream WebSocket ──────────────────────────────────────────────


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """
    Bidirectional WebSocket handler for Twilio Media Streams.

    Pipeline per utterance:
    1. Receive μ-law audio chunks from Twilio
    2. Convert to PCM 16kHz → feed to Silero VAD
    3. VAD detects end of speech → save as WAV → Sarvam STT
    4. Groq LLM generates response
    5. Sarvam TTS streams audio → convert to μ-law → send back to Twilio
    """
    await websocket.accept()
    print("🔌 WebSocket connected")

    stream_sid = None
    call_sid = None
    vad = VADProcessor()
    resample_state = None

    try:
        async for raw_message in websocket.iter_text():
            data = json.loads(raw_message)
            event = data.get("event")

            if event == "connected":
                print("✅ Twilio stream connected")

            elif event == "start":
                stream_sid = data["streamSid"]
                call_sid = data.get("start", {}).get("callSid", "unknown")
                print(f"▶ Stream started | streamSid={stream_sid} | callSid={call_sid}")

            elif event == "media":
                if vad.bot_is_speaking:
                    continue

                payload = data["media"]["payload"]

                # Decode Twilio audio → PCM 16kHz + float32 for VAD
                pcm_8k, pcm_16k, float32, resample_state = decode_twilio_media(
                    payload, resample_state
                )

                # Feed to VAD — returns accumulated utterance when speech ends
                utterance_pcm = vad.process(pcm_16k, float32)

                if utterance_pcm is not None:
                    # Process the complete utterance in background
                    asyncio.create_task(
                        _process_utterance(
                            utterance_pcm, stream_sid, call_sid, vad, websocket
                        )
                    )

            elif event == "mark":
                mark_name = data.get("mark", {}).get("name", "")
                if mark_name == "bot_speech_done":
                    print("✅ Bot finished speaking")
                    vad.bot_is_speaking = False

            elif event == "stop":
                print("⏹ Stream stopped")
                # Clean up conversation history
                if call_sid and call_sid in call_histories:
                    del call_histories[call_sid]
                break

    except Exception as e:
        print(f"🔥 WebSocket error: {e}")
    finally:
        print("🔌 WebSocket disconnected")


async def _process_utterance(
    utterance_pcm: bytes,
    stream_sid: str,
    call_sid: str,
    vad: VADProcessor,
    websocket: WebSocket,
):
    """
    Process a complete user utterance:
    STT → LLM → streaming TTS → send audio to Twilio
    """
    vad.bot_is_speaking = True

    try:
        # 1. Save PCM as WAV for Sarvam STT
        wav_bytes = save_pcm_as_wav(utterance_pcm, sample_rate=16000)
        tmp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_file.write(wav_bytes)
        tmp_file.close()

        # 2. Transcribe with Sarvam STT (REST, non-streaming)
        text = transcribe_audio(tmp_file.name)
        os.remove(tmp_file.name)
        print(f"✅ [Transcribed] {text}")

        if not text or text.strip() == "":
            print("⚠ Empty transcription, skipping")
            vad.bot_is_speaking = False
            return

        # 3. Get AI response from Groq LLM (non-streaming)
        if call_sid not in call_histories:
            call_histories[call_sid] = []
        ai_reply = chat(text, call_histories[call_sid])
        print(f"✅ [AI Reply] {ai_reply}")

        # 4. Stream TTS audio back to Twilio
        #    Sarvam TTS is configured to output mulaw 8kHz — exactly what Twilio expects
        async def send_audio_chunk(audio_bytes: bytes):
            """Callback: send raw mulaw audio chunk to Twilio."""
            payload = base64.b64encode(audio_bytes).decode("utf-8")
            media_message = {
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": payload},
            }
            await websocket.send_json(media_message)

        success = await stream_tts(ai_reply, send_audio_chunk)

        # 5. Send mark event to know when Twilio finishes playing
        mark_message = {
            "event": "mark",
            "streamSid": stream_sid,
            "mark": {"name": "bot_speech_done"},
        }
        await websocket.send_json(mark_message)

        if not success:
            vad.bot_is_speaking = False

    except Exception as e:
        print(f"🔥 Error processing utterance: {e}")
        vad.bot_is_speaking = False




# ─── Audio Serving (kept for fallback / REST TTS) ────────────────────────


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Serve generated TTS audio files."""
    filepath = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(filepath):
        return Response(content="File not found", status_code=404)
    return FileResponse(filepath, media_type="audio/wav")


# ─── API Endpoints ───────────────────────────────────────────────────────


@app.post("/call")
async def initiate_call(phone_number: str = Form(...)):
    """
    Trigger an outbound call to a client.
    POST /call with form data: phone_number=9876543210
    """
    try:
        call_sid = make_call(phone_number)
        return {"status": "success", "call_sid": call_sid}
    except Exception as e:
        print(f"❌ Failed to initiate call: {e}")
        return {"status": "error", "message": str(e)}
