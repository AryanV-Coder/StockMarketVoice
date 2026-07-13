# System Prompt & LLM Behavior — Detailed Context

## Overview

This document details the system prompt engineering behind "Jeevan", the AI broker persona, the LangChain agent architecture, the 4 live-data tools, and how conversation memory is structured per call.

---

## Architecture: LangChain Agent

The plain Groq API call has been replaced with a **LangChain `create_agent`** setup.

**File:** `groq_services/groq_llm.py`

```
Supabase stock data (columns/rows)
         │
         ▼ injected into system prompt at call start
┌────────────────────────────────────────────────┐
│         LangChain Agent (Jeevan)               │
│  model: groq/llama-3.3-70b-versatile           │
│  system_prompt: Jeevan persona + stock data    │
│                                                 │
│  TOOLS (called on demand):                     │
│  ├── get_live_stock_price(symbol)              │
│  ├── get_stock_metrics(symbol)                 │
│  ├── get_market_status()                       │
│  └── get_stock_history(symbol, days)           │
└────────────────────────────────────────────────┘
         │
         ▼
    ai_reply (str) → TTS → Twilio
```

### Design rule: Zero Hallucination
- **Supabase data** (what client bought) → baked into the system prompt at call start — agent reads from this, never invents it
- **Live market data** (current price, P/E, market status) → fetched by tools only when the user explicitly asks

---

## The Full System Prompt

**File:** `groq_services/groq_llm.py` → `SYSTEM_PROMPT_BASE`

The system prompt is a template with a `{stock_data}` placeholder. At call start, `initialize_agent_for_call()` renders it with the actual client data and bakes it into the agent's system prompt.

```
You are Jeevan, a professional AI investment assistant acting as a broker...

TOOL USAGE RULES:
- Use tools ONLY when the user explicitly asks for live/current information.
- NEVER call a tool to verify data already provided in the stock data below.
- NEVER hallucinate stock prices or metrics.
- When using a tool, use the NSE ticker symbol (e.g., "ITC", "TATASTEEL").

... [persona, language, conversation rules] ...

--- TODAY'S STOCK DATA FOR THIS CLIENT ---
{stock_data}
--- END OF STOCK DATA ---
```

---

## Tools

All tools are defined with `@tool` decorator and use `yfinance` (.NS suffix for NSE) and `nsepython`.

| Tool | Library | Triggered when |
|---|---|---|
| `get_live_stock_price(symbol)` | yfinance | User asks current price of a stock |
| `get_stock_metrics(symbol)` | yfinance | User asks P/E, market cap, dividend yield |
| `get_market_status()` | nsepython (+ IST fallback) | User asks if market is open |
| `get_stock_history(symbol, days)` | yfinance | User asks about recent trend/movement |

Symbol normalization: tools accept `"ITC"` or `"ITC.NS"` — `.NS` suffix is auto-appended.

---

## Conversation Memory

Conversation state is managed by **LangGraph's `InMemorySaver`** checkpointer, keyed by `call_sid` (the Twilio CallSid used as `thread_id`). The manual `call_histories` dict has been removed from `app.py`.

### Per-call flow

```
1. Call answered → _bot_greeting()
   └── initialize_agent_for_call(call_sid, stock_data_str)
       │  Creates agent with system_prompt = persona + stock data
       └── chat("Begin the call...", call_sid)
           └── agent.invoke({messages: [...]}, config={thread_id: call_sid})
               └── LLM generates greeting → TTS

2. User speaks → _process_utterance()
   └── chat(user_text, call_sid)
       └── agent.invoke({messages: [...]}, config={thread_id: call_sid})
           │  Agent may call tools internally before replying
           └── LLM reply → TTS

3. Call ends → cleanup_agent_for_call(call_sid)
   └── Removes agent from _agent_registry
       (InMemorySaver thread state is GC'd naturally)
```

---

## Public API (`groq_services/groq_llm.py`)

| Symbol | Type | Description |
|---|---|---|
| `SYSTEM_PROMPT_BASE` | `str` | Template with `{stock_data}` placeholder |
| `SYSTEM_PROMPT` | `str` | Alias of `SYSTEM_PROMPT_BASE` (backward compat) |
| `STOCK_TOOLS` | `list` | All 4 tool functions |
| `initialize_agent_for_call(call_sid, stock_data_str)` | `None` | Creates and registers agent for this call |
| `cleanup_agent_for_call(call_sid)` | `None` | Removes agent from registry |
| `chat(user_message, call_sid)` | `str` | Sends message to agent, returns text reply |

> **Breaking change from old API:** `chat()` now takes `call_sid: str` as second arg instead of `chat_history: list[dict]`.

---

## LLM Configuration

**Model:** `groq/llama-3.3-70b-versatile` (via `langchain-groq`)

| Parameter | Value | Rationale |
|---|---|---|
| `temperature` | 0.7 | Balanced creativity/determinism |
| `max_tokens` | 200 | Enforces brevity for voice calls |
| `stream` | False | Non-streaming; Groq latency ~200ms |
| `checkpointer` | `InMemorySaver()` | Shared global; keyed by `call_sid` as `thread_id` |

---

## Files Involved

| File | Role |
|---|---|
| `groq_services/groq_llm.py` | System prompt, 4 tools, agent factory, `chat()` |
| `app.py` | `_bot_greeting()` calls `initialize_agent_for_call()`, `_process_utterance()` calls `chat(text, call_sid)` |
| `config.py` | `GROQ_API_KEY` |
| `requirements.txt` | `langchain`, `langchain-groq`, `langgraph`, `yfinance`, `nsepython` |
