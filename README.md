# StockMarketVoice

A headless, modular voice AI service that initiates automated outbound calls to users. The system leverages Twilio Media Streams, Sarvam AI, Groq LLM, Silero VAD, and Supabase to deliver a real-time conversational pipeline over automated voice calls.

## Features

- **Automated Outbound Calling**: Trigger outbound calls seamlessly via local orchestration scripts.
- **Dynamic Data Injection**: The system securely pulls real-time user stock data (Supabase PostgreSQL) directly into the AI's context before the call starts.
- **Bot-Speaks-First Flow**: The system proactively initiates the call, greeting the user by name and verbally summarizing their latest stock purchases.
- **Multi-Lingual Adaptability**: Supports English, Hindi, and Hinglish. The system now automatically detects the user's spoken language via STT and forwards the language code to the TTS engine to ensure a consistent conversational language.
- **Real-Time Voice Streaming**: Utilizes Twilio Media Streams (WebSocket) for bidirectional, low-latency audio transmission.
- **Voice Activity Detection (VAD)**: Real-time speech start/end detection using Silero ONNX to efficiently chunk audio.
- **Advanced STT & TTS**: High-quality Indian context speech-to-text and text-to-speech rendering via the Sarvam AI API, with integrated language cross-pollination.
- **Intelligent LLM Engine**: Conversational AI responses are generated using the Groq API (Llama 3.3 70B) for near-instant broker-like responses.
- **Real-Time Barge-In Support**: Allows users to interrupt the bot mid-speech. The system detects sustained user speech (300ms threshold), immediately stops the bot's audio playback (Twilio 'clear'), and switches to listening mode.
- **Graceful Data Failover**: Robust error handling for cases where client stock data is missing or malformed. Instead of crashing, the system detects the anomaly and provides a polite conversational fallback explaining that record data is currently unavailable.
- **Web Dashboard for Call Management**: A responsive, Vite-powered frontend UI to effortlessly test individual calls and trigger batch outbound orchestrations without resorting to the CLI.

## System Architecture

1. **Context Registration**: A calling script fetches client and stock data from Supabase directly via the server endpoints and registers it into temporary memory.
2. **Call Initiation**: System POSTs to Twilio, initiating an outbound call.
3. **Setup & Bot Greeting**: Call connects; Twilio calls the `/voice` webhook and is instructed to `Connect->Stream` to our `/media-stream` WebSocket endpoint. The bot processes the registered stock context, generates a greeting, and speaks FIRST.
4. **Audio Handling**: Twilio streams raw μ-law 8kHz audio. We convert to 16kHz for Voice Activity Detection and speech capture.
5. **VAD Triggered Generation**: Upon detecting user speech completion, the audio chunk is transcribed to text (Sarvam STT). The STT engine detects the language code (e.g., Hindi, English), which is then passed to the LLM (Groq) and subsequently used by the TTS engine (Sarvam) to maintain language consistency.
6. **Streaming Playback**: The generated LLM text is continuously streamed to Sarvam TTS using the detected user language, converted into μ-law 8kHz audio, and immediately streamed back over the WebSocket to Twilio for near-instant playback.

## Project Structure

- `app.py` - Core FastAPI app initializing routes, managing context registrations, and orchestrating the WebSocket pipeline.
- `orchestrate_calls.py` - Main automation orchestrator. Automatically loops through all clients, registers their context, and initiates calls.
- `test_single_call.py` - Direct CLI script to manually input a phone number and client name to test individual deployments.
- `frontend/` - Responsive web dashboard for testing single calls and initiating batch orchestrations over the web.
- `config.py` - Environment configuration layer.
- `audio_utils.py` - Core audio format conversion (μ-law ↔ PCM) functions.
- `vad_service.py` - Manages Voice Activity Detection state using Silero.
- `barge_in.py` - Core logic for monitoring and handling user interruptions during bot speech.
- `groq_services/` - LLM interaction code and Master System Prompts.
- `sarvam_services/` - STT and TTS handlers.
- `twilio_services/` - Outbound call management.
- `routers/` - Contains domain-specific FastAPI endpoints (like the `clients.py` module connecting to Supabase).
- `supabase/` - Database mapping and native connection layer via explicit `psycopg2` configurations.

## Setup & Installation

### Requirements
- Python 3.11+
- Twilio Account + Phone Number
- Sarvam AI API Key
- Groq AI API Key
- PostgreSQL / Supabase Credentials

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

3. Create the `.env` file and populate the variables:
```env
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_PHONE_NUMBER=your_twilio_phone_number
SARVAM_API_KEY=your_sarvam_api_key
GROQ_API_KEY=your_groq_api_key
SERVER_URL=https://your-ngrok-domain.ngrok-free.app

# PostgreSQL
host=supabase.host.com
database=postgres
user=postgres
password=your_password
port=5432
```

### Running the App

1. Expose your local environment via Ngrok (or an equivalent service):
```bash
ngrok http 8000
```
Update your `SERVER_URL` in `.env` with the HTTPS domain Ngrok generates.

2. Start the FastAPI service:
```bash
uvicorn app:app --reload --port 8000
```

3. Start Automated Calls:
You can trigger calls either via the command line or using the Web Dashboard.

**Option A: Using the CLI**
```bash
# To test a single manual phone number
python test_single_call.py

# To automatically fetch all clients from the DB and call them one-by-one
python orchestrate_calls.py
```

**Option B: Using the Web Dashboard**
Open a new terminal and navigate to the frontend directory:
```bash
cd frontend
npm install
npm run dev
```
Navigate to the provided localhost URL to use the web interface.
```