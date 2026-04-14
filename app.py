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
from groq_services.groq_llm import chat, SYSTEM_PROMPT
from twilio_services.twilio_call import make_call
from barge_in import BargeInDetector, handle_barge_in
from fastapi.middleware.cors import CORSMiddleware
from routers.clients import router as clients_router
from routers.orchestrate import router as orchestrate_router
from routers.test_call import router as test_call_router
from pydantic import BaseModel


app = FastAPI(title="StockMarketVoice")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clients_router)
app.include_router(orchestrate_router)
app.include_router(test_call_router)

# Per-call conversation history (keyed by CallSid)
call_histories: dict[str, list[dict]] = {}

# Per-CallSid context: stores client_name + stock_data
# Keyed by Twilio CallSid for perfect isolation between simultaneous calls
call_contexts: dict[str, dict] = {}


# ─── Call Initiation (Atomic: register context + call) ───────────────────


class InitiateCallRequest(BaseModel):
    phone_number: str
    client_name: str
    stock_data: dict  # {"columns": [...], "rows": [...]}


@app.post("/initiate-call")
async def initiate_call_with_context(request: InitiateCallRequest):
    """
    Atomically initiate a call and register the stock context.
    1. Calls Twilio → gets unique CallSid
    2. Stores context keyed by that CallSid
    This guarantees zero context mixup even with simultaneous calls.
    """
    try:
        call_sid = make_call(request.phone_number)
        call_contexts[call_sid] = {
            "client_name": request.client_name,
            "stock_data": request.stock_data,
        }
        print(f"📋 Registered context for {request.client_name} → CallSid: {call_sid}")
        return {"status": "success", "call_sid": call_sid}
    except Exception as e:
        print(f"❌ Failed to initiate call to {request.phone_number}: {e}")
        return {"status": "error", "message": str(e)}


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

    Pipeline:
    0. On stream start → look up stock context → LLM generates greeting → TTS plays it
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
    barge_in_detector = BargeInDetector()
    cancel_event = asyncio.Event()  # Shared with TTS for barge-in cancellation

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

                # --- Bot Speaks First ---
                # Find the phone number this call is going to and inject stock context
                cancel_event = asyncio.Event()
                asyncio.create_task(
                    _bot_greeting(stream_sid, call_sid, vad, websocket, cancel_event)
                )

            elif event == "media":
                payload = data["media"]["payload"]

                # Decode Twilio audio → PCM 16kHz + float32 for VAD
                pcm_8k, pcm_16k, float32, resample_state = decode_twilio_media(
                    payload, resample_state
                )

                if vad.bot_is_speaking:
                    # During bot speech: check for barge-in
                    triggered = barge_in_detector.check(float32)
                    if triggered:
                        await handle_barge_in(
                            websocket, stream_sid, vad, cancel_event, barge_in_detector
                        )
                        # Feed current chunk to VAD to start capturing the new utterance
                        vad.process(pcm_16k, float32)
                    continue

                # Normal: feed to VAD for utterance detection
                utterance_pcm = vad.process(pcm_16k, float32)

                if utterance_pcm is not None:
                    # Fresh cancel event per utterance
                    cancel_event = asyncio.Event()
                    # Process the complete utterance in background
                    asyncio.create_task(
                        _process_utterance(
                            utterance_pcm, stream_sid, call_sid, vad, websocket, cancel_event
                        )
                    )

            elif event == "mark":
                mark_name = data.get("mark", {}).get("name", "")
                if mark_name == "bot_speech_done":
                    print("✅ Bot finished speaking")
                    vad.bot_is_speaking = False
                    barge_in_detector.reset()

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


def _build_stock_data_message(client_name: str, stock_data: dict) -> str:
    """Format the stock data into a readable message for the LLM."""
    columns = stock_data["columns"]
    rows = stock_data["rows"]

    message = f"Client Name: {client_name}\n"
    message += f"Columns: {', '.join(columns)}\n"
    message += "Rows:\n"
    for row in rows:
        message += f"  {row}\n"

    return message


async def _bot_greeting(
    stream_sid: str,
    call_sid: str,
    vad: VADProcessor,
    websocket: WebSocket,
    cancel_event: asyncio.Event,
):
    """
    Bot speaks first: look up stock context by CallSid (perfect isolation),
    inject it into chat history, get LLM greeting, and play it via TTS.
    Can be interrupted by barge-in via cancel_event.
    """
    vad.bot_is_speaking = True

    try:
        # Look up context by this call's unique CallSid
        context = call_contexts.pop(call_sid, None)

        if context is None:
            print(f"⚠ No call context found for CallSid {call_sid}, using generic greeting")
            stock_message = "No stock purchase data was found in our database for this client today. Inform them politely that there are no stock records for today and ask if there's anything else you can help with."
            client_name = "Customer"
        else:
            client_name = context["client_name"]
            stock_data = context["stock_data"]
            if "columns" in stock_data and "rows" in stock_data and stock_data["rows"]:
                stock_message = _build_stock_data_message(client_name, stock_data)
            else:
                print(f"⚠ No valid stock data (missing columns/rows) for {client_name}")
                stock_message = f"Client Name: {client_name}\nNo stock purchase data was found in our database for {client_name} today. Inform them politely that there are no stock records for today and ask if there's anything else you can help with."


        print(f"📊 Injecting stock data for {client_name} into conversation")

        # Initialize chat history with system prompt + stock data as first user message
        if call_sid not in call_histories:
            call_histories[call_sid] = []

        history = call_histories[call_sid]
        history.append({"role": "system", "content": SYSTEM_PROMPT})
        history.append({
            "role": "user",
            "content": f"Here is the stock data for today's call:\n\n{stock_message}"
        })

        # Get the LLM's opening greeting
        try:
            from groq import Groq
            groq_client = Groq(api_key=config.GROQ_API_KEY)
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=history,
                stream=False,
                temperature=0.7,
                max_tokens=200,
            )
            ai_greeting = response.choices[0].message.content
            history.append({"role": "assistant", "content": ai_greeting})
            print(f"✅ [Bot Greeting] {ai_greeting}")
        except Exception as e:
            print(f"❌ LLM greeting error: {e}")
            ai_greeting = f"Hello {client_name}, this is Jeevan from your brokerage. I have your stock update for today."

        # Stream TTS greeting to Twilio (cancellable by barge-in)
        async def send_audio_chunk(audio_bytes: bytes):
            payload = base64.b64encode(audio_bytes).decode("utf-8")
            media_message = {
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": payload},
            }
            await websocket.send_json(media_message)

        success = await stream_tts(ai_greeting, send_audio_chunk, cancel_event=cancel_event)

        # Only send mark if TTS wasn't cancelled (barge-in handles its own reset)
        if success:
            mark_message = {
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {"name": "bot_speech_done"},
            }
            await websocket.send_json(mark_message)

    except Exception as e:
        print(f"🔥 Error in bot greeting: {e}")

        # Recover: inject a "no data" context so the LLM doesn't hallucinate
        if call_sid not in call_histories:
            call_histories[call_sid] = []
        history = call_histories[call_sid]
        if not history:
            history.append({"role": "system", "content": SYSTEM_PROMPT})
        history.append({
            "role": "user",
            "content": f"Client Name: {client_name}\nNo stock purchase data was found in our database for this client today. Inform them politely that there are no stock records for today and ask if there's anything else you can help with."
        })

        # Speak a safe fallback greeting
        fallback = f"Hello {client_name}, this is Jeevan from your brokerage. I unfortunately don't have any stock purchase records for you today. Is there anything else I can help you with?"
        history.append({"role": "assistant", "content": fallback})

        try:
            async def send_audio_chunk(audio_bytes: bytes):
                payload = base64.b64encode(audio_bytes).decode("utf-8")
                await websocket.send_json({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": payload},
                })

            success = await stream_tts(fallback, send_audio_chunk, cancel_event=cancel_event)
            if success:
                await websocket.send_json({
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "bot_speech_done"},
                })
            else:
                vad.bot_is_speaking = False
        except Exception as tts_err:
            print(f"🔥 Fallback TTS also failed: {tts_err}")
            vad.bot_is_speaking = False


async def _process_utterance(
    utterance_pcm: bytes,
    stream_sid: str,
    call_sid: str,
    vad: VADProcessor,
    websocket: WebSocket,
    cancel_event: asyncio.Event,
):
    """
    Process a complete user utterance:
    STT → LLM → streaming TTS → send audio to Twilio
    Can be interrupted by barge-in via cancel_event.
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
        #    Chat history already has system prompt + stock data from the greeting phase
        if call_sid not in call_histories:
            call_histories[call_sid] = []
        ai_reply = chat(text, call_histories[call_sid])
        print(f"✅ [AI Reply] {ai_reply}")

        # 4. Stream TTS audio back to Twilio (cancellable by barge-in)
        async def send_audio_chunk(audio_bytes: bytes):
            """Callback: send raw mulaw audio chunk to Twilio."""
            payload = base64.b64encode(audio_bytes).decode("utf-8")
            media_message = {
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": payload},
            }
            await websocket.send_json(media_message)

        success = await stream_tts(ai_reply, send_audio_chunk, cancel_event=cancel_event)

        # 5. Only send mark if TTS wasn't cancelled (barge-in handles its own reset)
        if success:
            mark_message = {
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {"name": "bot_speech_done"},
            }
            await websocket.send_json(mark_message)
        else:
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

@app.get("/start-server")
def start_server():
    print("✅ Server started successfully")
    return {"status": "success", "message": "Server started successfully"}