"""
Barge-in Feature (Future Enhancement)
======================================

Allows the user to interrupt the bot mid-speech. When the user starts speaking
while the bot is talking, the bot stops its current audio and starts listening
to the new input.

How to implement:
1. While bot_is_speaking = True, still run VAD on incoming audio
2. If VAD detects sustained speech (e.g., >300ms), trigger barge-in:
   a. Send a "clear" event to Twilio to stop the current audio playback
   b. Cancel any pending TTS streaming
   c. Set bot_is_speaking = False
   d. Start accumulating the new utterance from VAD
3. Process the new utterance through the normal STT → LLM → TTS pipeline

Integration points in app.py:
- In the "media" event handler, instead of `continue` when bot_is_speaking,
  run VAD and check for barge-in
- In _process_utterance(), make the TTS streaming cancellable

Example Twilio "clear" event:
    {
        "event": "clear",
        "streamSid": stream_sid
    }
"""


# Minimum sustained speech duration to trigger barge-in (ms)
BARGE_IN_THRESHOLD_MS = 300


async def handle_barge_in(websocket, stream_sid: str, vad):
    """
    Send a clear event to Twilio to stop current bot audio,
    and reset VAD state for the new utterance.
    """
    # Stop Twilio's audio playback buffer
    clear_message = {
        "event": "clear",
        "streamSid": stream_sid,
    }
    await websocket.send_json(clear_message)

    # Reset bot speaking state
    vad.bot_is_speaking = False

    print("⚡ Barge-in triggered — bot audio cleared, listening to user")
