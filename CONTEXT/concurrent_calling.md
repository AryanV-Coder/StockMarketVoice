# Concurrent Calling & Call Isolation — Detailed Context

## Overview

This document explains how the system handles multiple outbound calls, either sequentially or concurrently, and the isolation mechanism that prevents context mixup between calls.

---

## The Problem: Context Mixup

When making outbound calls, there is a critical time gap between:
1. **Registering context** (stock data for a specific client)
2. **The client actually picking up** (could be 5-30 seconds later)

If a naive approach is used (e.g., storing context by phone number or using a "last registered" lookup), the following race condition occurs:

```
Time 0s:  Register context for Client A (phone: 9876543210)
Time 1s:  Twilio starts calling Client A
Time 2s:  Register context for Client B (phone: 9123456789)  ← overwrites "latest"
Time 3s:  Twilio starts calling Client B
Time 8s:  Client A picks up → WebSocket connects → looks up "latest" context
          → GETS CLIENT B'S DATA! ❌
```

---

## The Solution: CallSid-Based Isolation

### How It Works

Twilio assigns a globally unique `CallSid` the instant a call is created — before the phone even rings. We use this as the isolation key.

```
Time 0s:  POST /initiate-call {phone: A, name: A, stocks: A}
          → Twilio returns CallSid = "CA_AAA"
          → call_contexts["CA_AAA"] = {name: A, stocks: A}

Time 1s:  POST /initiate-call {phone: B, name: B, stocks: B}
          → Twilio returns CallSid = "CA_BBB"
          → call_contexts["CA_BBB"] = {name: B, stocks: B}

Time 8s:  Client A picks up → WebSocket start event carries callSid = "CA_AAA"
          → call_contexts.pop("CA_AAA") → gets Client A's data ✅

Time 12s: Client B picks up → WebSocket start event carries callSid = "CA_BBB"
          → call_contexts.pop("CA_BBB") → gets Client B's data ✅
```

Each call's context is tied to its unique CallSid. No ambiguity, no race conditions.

---

## Implementation Details

### The Atomic `/initiate-call` Endpoint

**File:** `app.py`

```python
@app.post("/initiate-call")
async def initiate_call_with_context(request: InitiateCallRequest):
    call_sid = make_call(request.phone_number)     # 1. Call Twilio → get CallSid
    call_contexts[call_sid] = {                     # 2. Store context by CallSid
        "client_name": request.client_name,
        "stock_data": request.stock_data,
    }
    return {"status": "success", "call_sid": call_sid}
```

This is **atomic**: the context is stored in the same request that creates the call. There is no window for another call to interfere.

### Context Lookup on Call Answer

**File:** `app.py` → `_bot_greeting()`

When the WebSocket stream starts, the `"start"` event from Twilio includes the `callSid`:

```python
elif event == "start":
    call_sid = data.get("start", {}).get("callSid", "unknown")
    asyncio.create_task(_bot_greeting(stream_sid, call_sid, vad, websocket))
```

Inside `_bot_greeting()`:

```python
context = call_contexts.pop(call_sid, None)  # O(1) lookup, removes after use
```

- `.pop()` is used instead of `.get()` to free memory after use.
- If no context is found (e.g., a call made via a different mechanism), a generic greeting is used.

### Memory Lifecycle

```
call_contexts[CallSid]  ──────────►  call_histories[CallSid]  ──────────►  deleted
      │                                       │                                │
 Created at call                     Created at greeting              Deleted at stream
 initiation                         (stock data injected             stop event
 (lives ~5-30 sec)                   into LLM history)               (call ends)
```

1. **`call_contexts`**: Temporary. Lives from call initiation until the person answers (~5-30s). Removed via `.pop()`.
2. **`call_histories`**: Persistent for the call's lifetime. Contains the full LLM conversation including stock data. Cleaned up when the stream stops:
   ```python
   elif event == "stop":
       if call_sid and call_sid in call_histories:
           del call_histories[call_sid]
   ```

---

## Orchestration Scripts

### `orchestrate_calls.py` — Batch Calling

Loops through all clients in the database and calls them:

```python
for client in clients:
    stock_data = fetch_client_stock_data(phone_number)
    call_sid = initiate_call(str(phone_number), client_name, stock_data)
```

Each call goes through the single `/initiate-call` endpoint, which atomically registers context and starts the call.

**Optional wait between calls** (currently commented out):
```python
# if i < len(clients):
#     wait_time = 120
#     time.sleep(wait_time)
```

Without the wait, all calls fire rapidly. Thanks to CallSid isolation, this is safe — every call gets its own unique context regardless of timing.

### `test_single_call.py` — Manual Testing

Takes phone number and client name from console input:

```python
phone_number = input("Enter phone number: ").strip()
client_name = input("Enter client name: ").strip()
stock_data = fetch_stock_data(phone_number)
initiate_call(phone_number, client_name, stock_data)
```

Uses the same `/initiate-call` endpoint. The flow is identical to batch calling, just for one person.

---

## Concurrency Model

### Server-Side (FastAPI + asyncio)

- FastAPI runs on a single-process `uvicorn` server.
- Each WebSocket connection (`/media-stream`) runs in its own async coroutine.
- Multiple calls can be active simultaneously — each has its own:
  - `VADProcessor` instance (created per WebSocket connection)
  - `stream_sid` and `call_sid` (local variables)
  - `resample_state` (local variable)
  - Chat history in `call_histories[call_sid]` (keyed by unique CallSid)
- Background tasks (`_bot_greeting`, `_process_utterance`) are spawned via `asyncio.create_task()`.

### Shared State

| Resource | Shared? | Thread-Safe? | Notes |
|----------|---------|--------------|-------|
| `call_contexts` | Yes (global dict) | Yes (single-threaded asyncio) | Temporary, pop-on-use |
| `call_histories` | Yes (global dict) | Yes (single-threaded asyncio) | Cleaned up on stream stop |
| Silero VAD model (`_model`) | Yes (global) | ⚠️ Single-threaded only | `torch.set_num_threads(1)` enforced |
| Groq API client | Per-call (created in `_bot_greeting`) | Yes | Stateless HTTP calls |
| Sarvam API client | Per-call (created in `stream_tts`) | Yes | Stateless async WebSocket |

### Why This Works Without Locks

Python's `asyncio` is single-threaded. All coroutines run on the same event loop. Dictionary operations like `call_contexts.pop()` and `call_histories[call_sid]` are never interrupted mid-operation. No locks needed.

---

## Scaling Considerations

### Current Limitations

1. **Single process**: All calls share one uvicorn worker. CPU-bound operations (VAD inference) can block the event loop.
2. **In-memory state**: `call_contexts` and `call_histories` live in RAM. If the server restarts mid-call, all context is lost.
3. **No call queue**: If 100 clients exist, all 100 Twilio calls fire immediately (unless the wait is uncommented).

### Future Improvements

1. **Connection pooling** for PostgreSQL (e.g., `asyncpg` with a pool) instead of creating/closing connections per request.
2. **Redis** for `call_contexts` if scaling to multiple server instances.
3. **Rate limiting** on `/initiate-call` to respect Twilio's concurrent call limits.
4. **Multiple uvicorn workers** with shared state via Redis.

---

## Files Involved

| File | Role |
|------|------|
| `app.py` | `/initiate-call` endpoint, `call_contexts` dict, `_bot_greeting()` pop logic |
| `orchestrate_calls.py` | Batch calling orchestrator |
| `test_single_call.py` | Manual single-call testing |
| `twilio_services/twilio_call.py` | `make_call()` → Twilio API → returns CallSid |
| `config.py` | Server URL, Twilio credentials |
