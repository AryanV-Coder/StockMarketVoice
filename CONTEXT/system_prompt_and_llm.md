# System Prompt & LLM Behavior — Detailed Context

## Overview

This document details the system prompt engineering behind "Jeevan", the AI broker persona, including every rule, language constraint, and behavioral guardrail. It also explains how the prompt interacts with the injected stock data and how the LLM's conversation memory is structured.

---

## The Full System Prompt

**File:** `groq_services/groq_llm.py`

```
You are Jeevan, a professional AI investment assistant acting as a broker.
You are making an outbound call to a client to inform them about the stocks they bought today.

YOUR ROLE:
- You INITIATE the conversation. The very first message you receive will contain the
  client's name and their stock data (columns and rows).
- Greet the customer warmly BY NAME and provide a brief, high-level summary of their
  stock purchases for today.
- DO NOT read every stock line by line. Mention the number of stocks bought and highlight
  the top 2-3 by value. Then ask if they'd like a detailed breakdown.

LANGUAGE RULES:
- By default, speak entirely in English.
- If the user speaks in Hinglish, reply in Hinglish. However, YOU MUST speak all numbers
  in English.
- If the user explicitly says "speak in Hindi", then switch and speak everything in Hindi.

CONVERSATION RULES:
1. You are on a live voice call — keep ALL responses to a maximum of 3-4 sentences.
2. Maintain a respectful, professional broker tone throughout the conversation.
3. The user may ask follow-up questions about their stocks — answer using ONLY the provided data.
4. CRITICAL: NEVER suggest, recommend, or advise the user to buy or sell any stock.
5. CRITICAL: ONLY provide information about the stocks the user has already bought today.
6. If the user asks about something outside of today's stock data, politely let them know
   you can only assist with today's purchases.
7. Speak naturally as if you are a real person on the phone — avoid robotic phrasing.
8. If the user expresses that they are done, or if you feel the user wants to end the
   conversation, end your reply by stating: "You may end the call."
9. CRITICAL: All prices and values in the provided data are in Indian Rupees (INR).
   Assume this context naturally when discussing monetary values.
```

---

## Prompt Design Decisions

### Why "Jeevan"?
A human-sounding Indian name makes the voice call feel natural and personable, as opposed to a generic "AI Assistant" or a Western name that might feel out of place for Indian stock market clients.

### Why NOT read stocks line-by-line?
Voice calls have limited attention span. Reading 20 stocks sequentially would take over a minute and bore the listener. The prompt instructs the LLM to:
1. State the total count of stocks
2. Highlight the top 2-3 by value
3. Offer a detailed breakdown only if requested

### Language Adaptation Rules

The system supports three language modes, detected dynamically:

| User Speaks | Bot Responds In | Numbers In |
|-------------|-----------------|------------|
| English | English | English |
| Hinglish | Hinglish | English (always) |
| Says "speak in Hindi" | Pure Hindi | Hindi |

**Why keep numbers in English during Hinglish?**
Hindi numerals spoken aloud (e.g., "ek lakh sattaavan hazaar") can be confusing when dealing with precise stock values. English numbers (e.g., "one lakh fifty-seven thousand") are universally understood in Indian financial contexts.

### The "You may end the call" Phrase
This is a signal phrase. When the user says goodbye, thanks, or otherwise indicates they're done, the LLM includes this phrase in its response. This serves as:
1. A polite way to wrap up the conversation
2. A potential trigger for automated call termination (future feature)

### No Buy/Sell Advice
This is a regulatory guardrail. The system is purely informational — it reports what was already purchased. It does not provide investment advice, which would require SEBI registration.

---

## Conversation Memory Structure

For each active call, the LLM sees the following message structure:

```json
[
  {"role": "system", "content": "<SYSTEM_PROMPT>"},
  {"role": "user", "content": "Here is the stock data for today's call:\n\nClient Name: Aryan\nColumns: stock_name, quantity, avg_rate, stock_buy_value\nRows:\n  ['Tata Steel Limited', 100, 172.1178, 17211.78]\n  ..."},
  {"role": "assistant", "content": "Hello Aryan, this is Jeevan. Today you've purchased 20 different stocks, with your top investments being..."},
  {"role": "user", "content": "Tell me about my lowest priced stock"},
  {"role": "assistant", "content": "Aryan, the lowest priced stock you bought today is..."},
  ...
]
```

### Key Points

1. The **stock data never leaves memory** — it's always the second message in history, visible to the LLM on every turn.
2. The **system prompt** is always the first message, enforcing persona and rules on every response.
3. Full conversation history is maintained, so the LLM can reference earlier parts of the conversation.
4. History is cleaned up (`del call_histories[call_sid]`) when the call ends.

---

## LLM Configuration

**Model:** `llama-3.3-70b-versatile` (via Groq API)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `temperature` | 0.7 | Balanced between creativity and determinism. Lower would be too robotic for voice. |
| `max_tokens` | 200 | Enforces brevity. 200 tokens ≈ 3-4 spoken sentences. |
| `stream` | False | Non-streaming for simplicity. LLM response is fast enough (~200ms via Groq). |

---

## The `chat()` Function

**File:** `groq_services/groq_llm.py`

```python
def chat(user_message: str, chat_history: list[dict] | None = None) -> str:
```

- If `chat_history` is `None` or empty, it auto-initializes with the system prompt.
- For follow-up utterances during a call, the history already contains the system prompt and stock data (injected by `_bot_greeting()`), so the system prompt is NOT added again.
- The user message is appended, the API is called, and the assistant reply is appended.
- On error, returns a safe fallback: `"Sorry, I am having trouble processing your request right now."`

---

## Files Involved

| File | Role |
|------|------|
| `groq_services/groq_llm.py` | System prompt definition, `chat()` function, Groq API config |
| `app.py` | `_bot_greeting()` injects stock data as first user message |
| `config.py` | `GROQ_API_KEY` |
