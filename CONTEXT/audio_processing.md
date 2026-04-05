# Audio Processing — Detailed Context

## Overview

This document covers the audio format conversions that bridge Twilio's telephony audio with the AI services (Sarvam STT/TTS, Silero VAD). Understanding these conversions is critical because a mismatch at any stage produces noise, silence, or crashes.

---

## Audio Format Matrix

| Component | Format | Sample Rate | Encoding | Direction |
|-----------|--------|-------------|----------|-----------|
| Twilio inbound | μ-law | 8kHz | base64 | Phone → Server |
| Twilio outbound | μ-law | 8kHz | base64 | Server → Phone |
| Silero VAD | float32 | 16kHz | numpy array | Internal |
| Sarvam STT | PCM 16-bit | 16kHz | WAV file | Server → Sarvam |
| Sarvam TTS (streaming) | μ-law | 8kHz | base64 chunks | Sarvam → Server |

---

## Inbound Audio Path (Phone → AI)

**File:** `audio_utils.py` → `decode_twilio_media()`

```
Twilio payload (base64 μ-law 8kHz)
        │
        ▼ base64.b64decode()
Raw μ-law bytes (8kHz)
        │
        ▼ audioop.ulaw2lin(bytes, 2)
PCM 16-bit (8kHz)  ← pcm_8k
        │
        ▼ audioop.ratecv(bytes, 2, 1, 8000, 16000, state)
PCM 16-bit (16kHz) ← pcm_16k  (used for STT utterance accumulation)
        │
        ▼ np.frombuffer(dtype=int16) / 32768.0
float32 numpy array (16kHz) ← float32  (used for VAD inference)
```

### Resampling State

`audioop.ratecv` maintains internal state for seamless chunk-by-chunk resampling. The `resample_state` is passed between calls to avoid audio artifacts at chunk boundaries. It's initialized as `None` and updated with each call.

### Why Three Outputs?

- `pcm_8k`: Not currently used in the main pipeline but available for future needs (e.g., storing raw call audio).
- `pcm_16k`: Accumulated by VAD into the utterance buffer, then wrapped in WAV for STT.
- `float32`: Fed directly into Silero VAD for speech probability inference.

---

## VAD Processing

**File:** `vad_service.py` → `VADProcessor`

### Window Processing

Silero VAD requires exactly **512 samples per window** (32ms at 16kHz). Since Twilio sends variable-size chunks (typically 160 bytes of μ-law = 160 samples at 8kHz = 320 samples at 16kHz), the VAD accumulates samples in `_vad_buffer` and processes complete 512-sample windows.

```python
while len(self._vad_buffer) >= WINDOW_SIZE:  # WINDOW_SIZE = 512
    window = self._vad_buffer[:WINDOW_SIZE]
    self._vad_buffer = self._vad_buffer[WINDOW_SIZE:]
    tensor = torch.from_numpy(window)
    speech_prob = _model(tensor, SAMPLE_RATE).item()
```

### Speech Detection Logic

```
                  speech_prob > 0.5
                        │
          ┌─────────────┼─────────────┐
          │ YES                        │ NO
          ▼                            ▼
   is_speaking = True          if is_speaking:
   silent_count = 0              silent_count += 1
   accumulate audio
          │                            │
          │                     silent_count >= 22?
          │                     (700ms of silence)
          │                            │
          │                   ┌────────┼────────┐
          │                   │ NO     │        │ YES
          │                   │        │        ▼
          │                   │        │  Return utterance
          │                   │        │  Reset state
          │                   ▼        │
          └───────────────────┘        │
                                       │
                              Continue listening
```

### Configuration

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `SAMPLE_RATE` | 16000 | Fixed by Silero VAD requirement |
| `WINDOW_SIZE` | 512 | 32ms window, required by Silero |
| `SPEECH_THRESHOLD` | 0.5 | Probability cutoff for speech detection |
| `SILENCE_DURATION_MS` | 700 | Time to wait before considering speech ended |
| `SILENCE_CHUNKS` | ~22 | Number of 32ms windows in 700ms |

---

## Outbound Audio Path (AI → Phone)

### TTS Streaming

**File:** `sarvam_services/sarvam_tts.py` → `stream_tts()`

Sarvam TTS is configured to output **μ-law 8kHz** directly — the exact format Twilio expects. This eliminates any server-side re-encoding:

```python
await ws.configure(
    target_language_code="hi-IN",
    speaker="shubh",
    output_audio_codec="mulaw",   # ← Matches Twilio's expected format
    speech_sample_rate=8000,       # ← Matches Twilio's expected rate
)
```

Each `AudioOutput` message from Sarvam contains base64-encoded μ-law audio, which is decoded and immediately forwarded to Twilio:

```python
audio_bytes = base64.b64decode(message.data.audio)
await on_audio_chunk(audio_bytes)  # callback re-encodes to base64 for Twilio
```

### The Double Base64

Note the seemingly redundant encode/decode cycle:
1. Sarvam sends audio as base64 → we decode to raw bytes
2. We re-encode to base64 → send to Twilio

This happens because the Sarvam SDK gives us base64, but we need raw bytes to potentially manipulate, and Twilio's WebSocket protocol expects its own base64 payload format.

---

## WAV Packaging for STT

**File:** `audio_utils.py` → `save_pcm_as_wav()`

Sarvam STT expects a WAV file. The accumulated PCM buffer is wrapped with a WAV header:

```python
buf = io.BytesIO()
with wave.open(buf, "wb") as wf:
    wf.setnchannels(1)       # mono
    wf.setsampwidth(2)       # 16-bit
    wf.setframerate(16000)   # 16kHz (upsampled from Twilio's 8kHz)
    wf.writeframes(pcm_bytes)
```

This is done in-memory. The result is written to a temporary file, sent to Sarvam, and immediately deleted.

---

## Bot Speaking Guard

The `vad.bot_is_speaking` flag prevents echo and self-triggering:

1. Set to `True` when the bot starts generating a response
2. While `True`, incoming Twilio audio is completely ignored (no VAD processing)
3. Set to `False` when Twilio confirms playback is complete (via `"mark"` event)

Without this guard, the bot would hear its own TTS output through the phone, transcribe it, and respond to itself in an infinite loop.

---

## Files Involved

| File | Role |
|------|------|
| `audio_utils.py` | All format conversions: μ-law ↔ PCM, resampling, WAV packaging |
| `vad_service.py` | Silero VAD inference, speech boundary detection |
| `sarvam_services/sarvam_tts.py` | TTS streaming with μ-law 8kHz output |
| `sarvam_services/sarvam_stt.py` | STT via WAV file upload |
| `app.py` | Orchestrates the audio pipeline, manages bot speaking guard |
