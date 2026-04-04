# StockMarketVoice

A headless, modular voice AI service that initiates automated outbound calls to users. The system leverages Twilio Media Streams, Sarvam AI, Groq LLM, and Silero VAD to deliver a real-time conversational pipeline over automated voice calls.

## Features

- **Automated Outbound Calling**: Trigger outbound calls using the `/call` endpoint.
- **Real-Time Voice Streaming**: Utilizes Twilio Media Streams (WebSocket) for bidirectional, low-latency audio transmission.
- **Voice Activity Detection (VAD)**: Real-time speech start/end detection using Silero ONNX to efficiently chunk audio.
- **Advanced STT & TTS**: High-quality Indian context speech-to-text and text-to-speech rendering via the Sarvam AI API.
- **Intelligent LLM Engine**: Conversational AI responses are generated using the Groq API for near-instant responses.
- **Barge-In Ready**: The core pipeline is architected to allow the inclusion of user interruption logic in future updates.

## System Architecture

1. **Call Initiation**: System POSTs to Twilio, initiating an outbound call.
2. **Setup**: Call connects; Twilio calls the `/voice` webhook and is instructed to `Connect->Stream` to our `/media-stream` WebSocket endpoint.
3. **Audio Handling**: Twilio streams raw μ-law 8kHz audio. We convert to 16kHz for Voice Activity Detection and speech capture.
4. **VAD Triggered Generation**: Upon detecting speech completion, the audio chunk is transcribed to text (Sarvam STT) and processed by the LLM (Groq).
5. **Streaming Playback**: The generated LLM text is continuously streamed to Sarvam TTS, converted into μ-law 8kHz audio, and immediately streamed back over the WebSocket to Twilio for near-instant playback.

## Project Structure

- `main.py` - Core FastAPI app initializing routes and orchestrating the WebSocket pipeline.
- `config.py` - Environment configuration layer.
- `audio_utils.py` - Core audio format conversion (μ-law ↔ PCM) functions.
- `vad_service.py` - Manages Voice Activity Detection state using Silero.
- `test_call.py` - Utility testing script to quickly trigger the outbound process.
- `barge_in.py` - Optional design and logic notes for implementing barge-in functionality.
- `groq_services/` - LLM interaction code.
- `sarvam_services/` - STT and TTS handlers.
- `twilio_services/` - Outbound call management.

## Setup & Installation

### Requirements
- Python 3.11+
- Twilio Account + Phone Number
- Sarvam AI API Key
- Groq AI API Key

### Installation

1. Establish your virtual environment (Python 3.11 recommended due to audio dependency optimizations):
```bash
python3.11 -m venv venv
source venv/bin/activate
```

2. Install python dependencies:
```bash
pip install -r requirements.txt
```

3. Create the `.env` file from the supplied keys. Populate the variables as needed:
```env
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_PHONE_NUMBER=your_twilio_phone_number
SARVAM_API_KEY=your_sarvam_api_key
GROQ_API_KEY=your_groq_api_key
SERVER_URL=https://your-ngrok-domain.ngrok-free.app
TEST_PHONE_NUMBER=your_personal_test_phone_number
```

### Running the App

1. Expose your local environment via Ngrok (or an equivalent service):
```bash
ngrok http 8000
```
Update your `SERVER_URL` in `.env` with the HTTPS domain Ngrok generates.

2. Start the FastAPI service:
```bash
uvicorn main:app --reload --port 8000
```

3. Initiate a Test Call via the provided test script:
```bash
python test_call.py
```