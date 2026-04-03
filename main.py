import os
import requests
import tempfile
from fastapi import FastAPI, Request, Form
from fastapi.responses import Response, FileResponse

import config
from sarvam_services.sarvam_stt import transcribe_audio
from sarvam_services.sarvam_tts import text_to_speech, AUDIO_DIR
from groq_services.groq_llm import chat
from twilio_services.twilio_call import make_call


app = FastAPI(title="StockMarketVoice")

# Per-call conversation history (keyed by CallSid)
call_histories: dict[str, list[dict]] = {}


# ─── Twilio Webhook Routes ───────────────────────────────────────────────


@app.post("/voice")
async def voice_webhook():
    """
    Twilio calls this when the outbound call is answered.
    Greets the user and starts recording their speech.
    """
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Aditi">Namaste! Main aapka AI investment assistant hoon. Kripya beep ke baad bolein.</Say>
    <Record maxLength="15" timeout="3" action="/process_recording" />
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.post("/process_recording")
async def process_recording(request: Request):
    """
    Twilio calls this after recording the user's speech.
    Pipeline: Download audio → STT → LLM → TTS → Play back → Record again
    """
    form_data = await request.form()
    recording_url = form_data.get("RecordingUrl")
    call_sid = form_data.get("CallSid", "unknown")

    if not recording_url:
        print("❌ No RecordingUrl in request")
        return _error_response()

    try:
        # 1. Download the recording from Twilio
        print(f"📥 [Recording URL] {recording_url}")
        audio_path = _download_recording(recording_url)
        print(f"✅ [Downloaded] {audio_path}")

        # 2. Transcribe with Sarvam STT
        text = transcribe_audio(audio_path)
        print(f"✅ [Transcribed] {text}")

        # Clean up the temp file
        os.remove(audio_path)

        if not text or text.strip() == "":
            twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Aditi">Maaf kijiye, main samajh nahi paayi. Kripya dobara bolein.</Say>
    <Record maxLength="15" timeout="3" action="/process_recording" />
</Response>"""
            return Response(content=twiml, media_type="application/xml")

        # 3. Get AI response from Groq (maintain per-call conversation history)
        if call_sid not in call_histories:
            call_histories[call_sid] = []  # chat() will prepend system prompt
        ai_reply = chat(text, call_histories[call_sid])
        print(f"✅ [AI Reply] {ai_reply}")

        # 4. Convert AI reply to speech with Sarvam TTS
        audio_filename = text_to_speech(ai_reply)
        if not audio_filename:
            return _error_response()

        # 5. Build the audio URL for Twilio to play
        audio_url = f"{config.SERVER_URL}/audio/{audio_filename}"
        print(f"✅ [Audio URL] {audio_url}")

        # 6. Play the audio and loop back to record
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Pause length="1"/>
    <Record maxLength="15" timeout="3" action="/process_recording" />
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    except Exception as e:
        print(f"🔥 ERROR in /process_recording: {e}")
        return _error_response()


# ─── Audio Serving ────────────────────────────────────────────────────────


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Serve generated TTS audio files to Twilio."""
    filepath = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(filepath):
        return Response(content="File not found", status_code=404)
    return FileResponse(filepath, media_type="audio/wav")


# ─── API Endpoints ────────────────────────────────────────────────────────


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


# ─── Helpers ──────────────────────────────────────────────────────────────


def _download_recording(recording_url: str) -> str:
    """Download Twilio recording to a temp file and return the path."""
    # Twilio recording URLs need .wav appended and auth
    audio_url = f"{recording_url}.wav"
    response = requests.get(
        audio_url,
        auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
    )
    response.raise_for_status()

    tmp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_file.write(response.content)
    tmp_file.close()
    return tmp_file.name


def _error_response() -> Response:
    """Return a TwiML error response that redirects back to /voice."""
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Aditi">Maaf kijiye, kuch galat ho gaya. Kripya dobara try karein.</Say>
    <Redirect>/voice</Redirect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")
