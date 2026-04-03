import os
from sarvamai import SarvamAI
from sarvamai.core.api_error import ApiError
import config


client = SarvamAI(api_subscription_key=config.SARVAM_API_KEY)


def transcribe_audio(audio_path: str) -> str:
    """
    Transcribe audio from a file path using Sarvam AI's Saaras model.
    Returns the transcribed text, or empty string on failure.
    """
    try:
        with open(audio_path, "rb") as f:
            response = client.speech_to_text.transcribe(
                file=f,
                model="saaras:v3",
                mode="transcribe",
            )

        lang = response.language_code or "unknown"
        print(f"[Sarvam STT] Detected language: {lang}")
        return response.transcript

    except ApiError as e:
        if e.status_code == 429:
            print("🛑 RATE LIMIT: Sarvam STT API — too many requests")
        else:
            print(f"❌ Sarvam STT API Error ({e.status_code}): {e.body}")
        return ""

    except Exception as e:
        print(f"❌ Unexpected Sarvam STT Error: {e}")
        return ""
