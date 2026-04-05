# Conversation Pipeline — Detailed Context

## Overview

The conversation pipeline is the core real-time voice interaction system. It handles the entire flow from the moment a call is answered to the moment it ends: audio decoding, voice activity detection, speech-to-text, LLM response generation, text-to-speech, and audio streaming back to the caller.

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  Twilio (Phone Network)                                              │
│  ┌────────────┐     ┌────────────┐                                   │
│  │ Outbound   │────>│ /voice     │  TwiML webhook (POST)             │
│  │ Call       │     │ webhook    │  Returns <Connect><Stream>        │
│  └────────────┘     └─────┬──────┘                                   │
│                           │                                          │
│                    WebSocket /media-stream                            │
│                           │                                          │
│  ┌────────────────────────▼──────────────────────────────────────┐   │
│  │                    app.py — media_stream()                    │   │
│  │                                                               │   │
│  │   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌──────────┐ │   │
│  │   │ Decode  │───>│  VAD    │───>│  STT    │───>│   LLM    │ │   │
│  │   │ μ-law   │    │ Silero  │    │ Sarvam  │    │   Groq   │ │   │
│  │   └─────────┘    └─────────┘    └─────────┘    └────┬─────┘ │   │
│  │                                                      │       │   │
│  │                                                      ▼       │   │
│  │   ┌──────────┐    ┌──────────────────────────────────────┐   │   │
│  │   │ Encode   │<───│  TTS (Sarvam Streaming WebSocket)    │   │   │
│  │   │ to μ-law │    │  Output: μ-law 8kHz                  │   │   │
│  │   └────┬─────┘    └──────────────────────────────────────┘   │   │
│  │        │                                                      │   │
│  │        ▼  Send audio chunks back to Twilio via WebSocket      │   │
│  └───────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Breakdown

### Phase 0: Bot Speaks First (Greeting)

**File:** `app.py` → `_bot_greeting()`

When the WebSocket stream starts (Twilio `"start"` event), the bot immediately speaks before the user says anything:

1. The `call_sid` from the Twilio stream is used to look up stock context from `call_contexts` (populated by `/initiate-call`).
2. The stock data (columns + rows) is formatted into a human-readable string via `_build_stock_data_message()`.
3. The chat history is initialized with:
   - `system` message: The full Jeevan system prompt (from `groq_services/groq_llm.py`)
   - `user` message: The formatted stock data (injected as if the user provided it)
4. Groq LLM generates a greeting (summarizing the stocks).
5. The greeting text is streamed through Sarvam TTS → audio chunks sent to Twilio.
6. A `"mark"` event (`bot_speech_done`) is sent to Twilio to track when playback ends.

### Phase 1: Receiving Audio from Twilio

**File:** `app.py` → `media_stream()` WebSocket handler

- Twilio sends `"media"` events containing base64-encoded **μ-law 8kHz mono** audio chunks.
- While the bot is speaking (`vad.bot_is_speaking == True`), incoming audio is ignored to prevent echo.

### Phase 2: Audio Decoding

**File:** `audio_utils.py` → `decode_twilio_media()`

Each Twilio media payload goes through:

1. **Base64 decode** → raw μ-law bytes
2. **μ-law to PCM 16-bit** (`audioop.ulaw2lin`) → 8kHz PCM
3. **Resample 8kHz → 16kHz** (`audioop.ratecv`) → 16kHz PCM (needed for STT and VAD)
4. **PCM to float32** (`numpy`) → normalized float32 array (needed for Silero VAD)

The function returns all three formats simultaneously: `pcm_8k`, `pcm_16k`, `float32`, plus a `resample_state` for seamless chunk-by-chunk resampling.

### Phase 3: Voice Activity Detection (VAD)

**File:** `vad_service.py` → `VADProcessor.process()`

- Uses **Silero VAD** (ONNX model, loaded once globally, runs on a single thread).
- Audio is processed in **512-sample windows** (32ms at 16kHz).
- Each window produces a speech probability (0.0 to 1.0).
- **Speech threshold:** 0.5
- **Silence duration to end speech:** 700ms (~22 consecutive silent windows)
- When silence is detected after speech, the accumulated PCM buffer is returned as a complete utterance.
- State is reset after each utterance (`_reset()`), including resetting the Silero model state.

### Phase 4: Speech-to-Text (STT)

**File:** `sarvam_services/sarvam_stt.py` → `transcribe_audio()`

1. The accumulated PCM utterance is wrapped into a WAV file in-memory (`save_pcm_as_wav`).
2. Saved to a temporary file on disk.
3. Sent to **Sarvam AI** (`saaras:v3` model) via REST API.
4. Sarvam auto-detects the spoken language (Hindi, English, Hinglish, etc.) and returns the transcript.
5. The temp file is deleted after transcription.
6. Empty transcriptions are silently skipped.

### Phase 5: LLM Response Generation

**File:** `groq_services/groq_llm.py` → `chat()`

- The transcribed text is appended to the existing `call_histories[call_sid]` as a `"user"` message.
- The full conversation history (including system prompt + stock data from Phase 0) is sent to **Groq** (`llama-3.3-70b-versatile`).
- Parameters: `temperature=0.7`, `max_tokens=200`
- The AI reply is appended to the history as an `"assistant"` message.
- The LLM has full context of the stock data and all prior conversation turns.

### Phase 6: Text-to-Speech (TTS) Streaming

**File:** `sarvam_services/sarvam_tts.py` → `stream_tts()`

1. Opens an **async WebSocket** connection to Sarvam AI (`bulbul:v3` model).
2. Configured with: `target_language_code="hi-IN"`, `speaker="shubh"`, `output_audio_codec="mulaw"`, `speech_sample_rate=8000`.
3. The LLM's reply text is sent to Sarvam via `ws.convert(text)` and `ws.flush()`.
4. Audio chunks are received as `AudioOutput` messages, each containing base64-encoded μ-law audio.
5. Each chunk is decoded and passed to the `on_audio_chunk` callback.

### Phase 7: Sending Audio Back to Twilio

**File:** `app.py` → `send_audio_chunk()` callback (inside `_process_utterance` and `_bot_greeting`)

1. Each TTS audio chunk is base64-encoded.
2. Wrapped in a Twilio media event JSON: `{"event": "media", "streamSid": ..., "media": {"payload": ...}}`
3. Sent over the WebSocket to Twilio for immediate playback.
4. After all chunks are sent, a `"mark"` event (`bot_speech_done`) is sent.
5. When Twilio confirms the mark, `vad.bot_is_speaking` is set to `False`, re-enabling user audio processing.

---

## Key Design Decisions

### Why μ-law 8kHz?
Twilio Media Streams natively use μ-law encoding at 8kHz. By configuring Sarvam TTS to output in the same format, we avoid any server-side re-encoding and can stream audio directly.

### Why 16kHz internally?
Silero VAD and Sarvam STT both require 16kHz audio. The system upsamples from 8kHz to 16kHz on ingest and produces 8kHz μ-law on output.

### Why non-streaming STT but streaming TTS?
- **STT (non-streaming):** Sarvam's STT API is REST-based. The VAD collects a complete utterance first, so there's no benefit to streaming STT.
- **TTS (streaming):** Streaming TTS allows the bot to start speaking before the entire response is generated, reducing perceived latency.

### Bot-speaks-first pattern
The bot initiates conversation because this is an outbound call — the user doesn't know what the call is about until the bot explains. The LLM receives the stock data before the user says anything, generates a greeting, and speaks it immediately.

---

## Files Involved

| File | Role |
|------|------|
| `app.py` | WebSocket handler, utterance processing, bot greeting orchestration |
| `audio_utils.py` | μ-law ↔ PCM conversion, resampling, WAV packaging |
| `vad_service.py` | Silero VAD inference, speech boundary detection |
| `sarvam_services/sarvam_stt.py` | Speech-to-text via Sarvam REST API |
| `sarvam_services/sarvam_tts.py` | Text-to-speech via Sarvam streaming WebSocket |
| `groq_services/groq_llm.py` | LLM chat with Groq, system prompt definition |
| `config.py` | API keys and server URL |
