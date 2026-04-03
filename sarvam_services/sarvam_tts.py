import base64
import os
import uuid
from sarvamai import SarvamAI
from sarvamai.core.api_error import ApiError
import config


client = SarvamAI(api_subscription_key=config.SARVAM_API_KEY)

# Directory to store generated audio files
AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "audio_files")
os.makedirs(AUDIO_DIR, exist_ok=True)


def text_to_speech(text: str, language: str = "hi-IN", speaker: str = "shubh") -> str | None:
    """
    Convert text to speech using Sarvam AI (non-streaming REST API).
    Saves the audio as a WAV file and returns the filename.
    Returns None on failure.
    """
    try:
        response = client.text_to_speech.convert(
            text=text,
            target_language_code=language,
            speaker=speaker,
            model="bulbul:v3",
            speech_sample_rate=8000,  # Twilio expects 8kHz
            output_audio_codec="wav",
        )

        if not response.audios:
            print("❌ Sarvam TTS returned no audio")
            return None

        # Decode the base64 audio and save to file
        audio_bytes = base64.b64decode(response.audios[0])
        filename = f"{uuid.uuid4().hex}.wav"
        filepath = os.path.join(AUDIO_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(audio_bytes)

        print(f"✅ [Sarvam TTS] Saved audio: {filename}")
        return filename

    except ApiError as e:
        if e.status_code == 429:
            print("🛑 RATE LIMIT: Sarvam TTS API — too many requests")
        else:
            print(f"❌ Sarvam TTS API Error ({e.status_code}): {e.body}")
        return None

    except Exception as e:
        print(f"❌ Unexpected Sarvam TTS Error: {e}")
        return None
