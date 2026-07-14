"""
LangChain Agent — Jeevan (AI Broker)
=====================================
Replaces the raw Groq API call with a LangChain `create_agent` setup.

Architecture:
  - Supabase stock-purchase data  →  injected in the system prompt (ground truth, no hallucination)
  - Live market data              →  fetched via tools only when the user asks

Tools:
  1. get_live_stock_price(symbol)    - Current price, day high/low, prev close
  2. get_stock_metrics(symbol)       - P/E ratio, market cap, dividend yield
  3. get_market_status()             - Is NSE open right now?
  4. get_stock_history(symbol, days) - Recent closing prices

Public API (same call signature as before for app.py compatibility):
  - SYSTEM_PROMPT_BASE              - exported for backward compat
  - initialize_agent_for_call(call_sid, stock_data_str)
  - chat(user_message, call_sid)    - replaces old chat(user_message, chat_history)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Union

import yfinance as yf
from langchain_core.messages import RemoveMessage, AIMessage
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

import config

# ─── Globals ─────────────────────────────────────────────────────────────────

# InMemorySaver acts as the per-call conversation store keyed by thread_id (call_sid)
_checkpointer = InMemorySaver()

# Maps call_sid → compiled agent instance (each call gets its own system-prompt
# with that client's stock data baked in)
_agent_registry: dict[str, object] = {}


# ─── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT_BASE = """You are Jeevan, a professional AI investment assistant acting as a broker.
You are making an outbound call to a client to inform them about the stocks they bought today.

YOUR ROLE:
- You INITIATE the conversation. The very first message you receive will contain the client's name and their stock data.
- Greet the customer warmly BY NAME and provide a brief, high-level summary of their stock purchases for today.
- DO NOT read every stock line by line. Mention the number of stocks bought and highlight the top 2-3 by value. Then ask if they'd like a detailed breakdown.

TOOL USAGE RULES:
- You have access to live market data tools. Use them ONLY when the user explicitly asks for live/current information (e.g., "What is ITC trading at?", "Is the market open?").
- NEVER call a tool to verify data that is already provided in the stock data below. The provided data is authoritative.
- NEVER hallucinate stock prices or metrics. If you cannot get the data via a tool, say so clearly.
- When using a tool, use the NSE ticker symbol (e.g., "ITC", "TATASTEEL"). The tools will handle the ".NS" suffix automatically.

LANGUAGE RULES:
- By default, speak entirely in English.
- If the user speaks in Hinglish, reply in Hinglish. However, YOU MUST speak all numbers in English.
- If the user explicitly says "speak in Hindi", then switch and speak everything in Hindi.

CONVERSATION RULES:
1. You are on a live voice call — keep ALL responses to a maximum of 3-4 sentences.
2. Maintain a respectful, professional broker tone throughout the conversation.
3. The user may ask follow-up questions about their stocks — answer using ONLY the provided data, or use tools for live data.
4. CRITICAL: NEVER suggest, recommend, or advise the user to buy or sell any stock.
5. CRITICAL: ONLY provide information about the stocks the user has already bought today, or live market data via tools.
6. If the user asks about something outside of today's stock data or live market data, politely decline.
7. Speak naturally as if you are a real person on the phone — avoid robotic phrasing.
8. CRITICAL: All prices and values in the provided data are in Indian Rupees (INR).

--- TODAY'S STOCK DATA FOR THIS CLIENT ---
{stock_data}
--- END OF STOCK DATA ---"""

# Kept for backward-compat imports in app.py (it imports SYSTEM_PROMPT)
SYSTEM_PROMPT = SYSTEM_PROMPT_BASE


# ─── Helper ───────────────────────────────────────────────────────────────────

def _normalize_symbol(symbol: str) -> str:
    """Ensure symbol has .NS suffix for NSE stocks."""
    symbol = symbol.strip().upper()
    if not symbol.endswith(".NS") and not symbol.endswith(".BO"):
        symbol = symbol + ".NS"
    return symbol


# ─── Tools ───────────────────────────────────────────────────────────────────

@tool
def get_live_stock_price(symbol: Annotated[str, "NSE ticker symbol, e.g. 'ITC' or 'TATASTEEL'"]) -> str:
    """
    Get the current live market price of an NSE-listed stock.
    Returns current price, day's high, day's low, previous close, and percentage change.
    Use this when the user asks what a stock is trading at right now.
    """
    try:
        ticker_sym = _normalize_symbol(symbol)
        ticker = yf.Ticker(ticker_sym)
        info = ticker.info

        current_price = info.get("currentPrice") or info.get("regularMarketPrice")
        if current_price is None:
            # Fallback to BSE (.BO) if NSE (.NS) fails (Yahoo Finance bug with some tickers like ZOMATO)
            ticker_sym = ticker_sym.replace(".NS", ".BO")
            ticker = yf.Ticker(ticker_sym)
            info = ticker.info
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            
        if current_price is None:
            return f"Could not fetch live price for {symbol}. The market may be closed or the symbol may be incorrect."

        change = current_price - prev_close if prev_close else 0
        pct_change = (change / prev_close * 100) if prev_close else 0
        direction = "▲" if change >= 0 else "▼"

        return (
            f"{symbol} (Live Data): "
            f"Current Price: ₹{current_price:.2f} "
            f"{direction} {abs(pct_change):.2f}% (₹{abs(change):.2f}) | "
            f"Day High: ₹{day_high:.2f} | Day Low: ₹{day_low:.2f} | "
            f"Prev Close: ₹{prev_close:.2f}"
        )
    except Exception as e:
        return f"Error fetching live price for {symbol}: {str(e)}"


@tool
def get_stock_metrics(symbol: Annotated[str, "NSE ticker symbol, e.g. 'ITC' or 'RELIANCE'"]) -> str:
    """
    Get fundamental metrics for an NSE-listed stock.
    Returns market cap, trailing P/E ratio, and dividend yield.
    Use this when the user asks about a stock's valuation or fundamentals.
    """
    try:
        ticker_sym = _normalize_symbol(symbol)
        ticker = yf.Ticker(ticker_sym)
        info = ticker.info

        market_cap = info.get("marketCap")
        if market_cap is None and info.get("trailingPE") is None:
            # Fallback to .BO
            ticker_sym = ticker_sym.replace(".NS", ".BO")
            ticker = yf.Ticker(ticker_sym)
            info = ticker.info
            market_cap = info.get("marketCap")

        pe_ratio = info.get("trailingPE")
        dividend_yield = info.get("dividendYield")
        company_name = info.get("longName") or info.get("shortName") or symbol

        if market_cap is None and pe_ratio is None:
            return f"Could not fetch metrics for {symbol}. Symbol may be incorrect."

        market_cap_str = f"₹{market_cap / 1e12:.2f} Trillion" if market_cap and market_cap > 1e12 else \
                         f"₹{market_cap / 1e9:.2f} Billion" if market_cap else "N/A"
        pe_str = f"{pe_ratio:.2f}" if pe_ratio else "N/A"
        div_str = f"{dividend_yield * 100:.2f}%" if dividend_yield else "N/A"

        return (
            f"{company_name} ({symbol}) Fundamentals: "
            f"Market Cap: {market_cap_str} | "
            f"Trailing P/E: {pe_str} | "
            f"Dividend Yield: {div_str}"
        )
    except Exception as e:
        return f"Error fetching metrics for {symbol}: {str(e)}"


@tool
def get_market_status() -> str:
    """
    Check if the NSE (National Stock Exchange of India) is currently open for trading.
    Use this when the user asks if the market is open or what the market hours are.
    """
    try:
        from nsepython import nse_marketStatus
        status_data = nse_marketStatus()
        # nsepython returns a dict with market status info
        if isinstance(status_data, dict):
            market_state = status_data.get("marketState", [])
            if market_state:
                first = market_state[0] if isinstance(market_state, list) else market_state
                market = first.get("market", "NSE")
                state = first.get("marketStatus", "Unknown")
                trade_date = first.get("tradeDate", "")
                return f"Market Status: {market} is currently {state}. Trade Date: {trade_date}."
            return f"Market Status: {status_data}"
        return f"Market Status: {status_data}"
    except Exception as nsepy_err:
        # Fallback: compute based on IST time
        try:
            from datetime import time as dtime
            now_utc = datetime.now(timezone.utc)
            # IST = UTC+5:30
            ist_hour = (now_utc.hour + 5) % 24
            ist_minute = now_utc.minute + 30
            if ist_minute >= 60:
                ist_hour = (ist_hour + 1) % 24
                ist_minute -= 60

            weekday = now_utc.weekday()  # 0=Mon, 6=Sun
            if weekday >= 5:
                return "NSE is CLOSED (weekend). Market hours are Monday to Friday, 9:15 AM to 3:30 PM IST."

            market_open = (ist_hour == 9 and ist_minute >= 15) or (10 <= ist_hour <= 14) or \
                          (ist_hour == 15 and ist_minute <= 30)
            if market_open:
                return f"NSE appears to be OPEN (current IST time: {ist_hour:02d}:{ist_minute:02d}). Market hours: 9:15 AM – 3:30 PM IST."
            else:
                return f"NSE appears to be CLOSED (current IST time: {ist_hour:02d}:{ist_minute:02d}). Market hours: 9:15 AM – 3:30 PM IST, Mon–Fri."
        except Exception:
            return f"Could not determine market status. Error: {str(nsepy_err)}"


@tool
def get_stock_history(
    symbol: Annotated[str, "NSE ticker symbol, e.g. 'ITC'"],
    days: Annotated[Union[int, str], "Number of recent trading days to fetch (1-30)"] = 5
) -> str:
    """
    Get recent closing price history for an NSE-listed stock.
    Use this when the user asks how a stock has performed recently, its trend, or weekly/monthly movement.
    """
    try:
        try:
            days_int = int(days)
        except (ValueError, TypeError):
            days_int = 5
            
        days_int = max(1, min(days_int, 30))  # clamp 1–30
        ticker_sym = _normalize_symbol(symbol)
        ticker = yf.Ticker(ticker_sym)
        hist = ticker.history(period=f"{days_int}d")

        if hist.empty:
            # Fallback to .BO
            ticker_sym = ticker_sym.replace(".NS", ".BO")
            ticker = yf.Ticker(ticker_sym)
            hist = ticker.history(period=f"{days_int}d")

        if hist.empty:
            return f"No historical data found for {symbol} in the last {days_int} days."

        rows = []
        for date, row in hist.iterrows():
            date_str = date.strftime("%d %b")
            rows.append(f"{date_str}: ₹{row['Close']:.2f}")

        first_close = hist["Close"].iloc[0]
        last_close = hist["Close"].iloc[-1]
        total_change = last_close - first_close
        total_pct = (total_change / first_close * 100) if first_close else 0
        direction = "up" if total_change >= 0 else "down"

        history_str = " | ".join(rows)
        return (
            f"{symbol} last {len(hist)} trading days: {history_str}. "
            f"Overall {direction} ₹{abs(total_change):.2f} ({abs(total_pct):.2f}%) over this period."
        )
    except Exception as e:
        return f"Error fetching history for {symbol}: {str(e)}"


# ─── All tools list ───────────────────────────────────────────────────────────

STOCK_TOOLS = [
    get_live_stock_price,
    get_stock_metrics,
    get_market_status,
    get_stock_history,
]


# ─── Agent Factory ────────────────────────────────────────────────────────────

def initialize_agent_for_call(call_sid: str, stock_data_str: str) -> None:
    """
    Create a LangChain agent for this specific call and register it.
    The system prompt has the client's stock data baked in — no hallucination possible.

    Args:
        call_sid: Twilio CallSid used as the LangGraph thread_id.
        stock_data_str: Pre-formatted stock data string (from _build_stock_data_message).
    """
    system_prompt = SYSTEM_PROMPT_BASE.format(stock_data=stock_data_str)

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.7,
        max_tokens=200,
    )

    agent = create_react_agent(
        model=llm,
        tools=STOCK_TOOLS,
        prompt=system_prompt,
        checkpointer=_checkpointer,
    )

    _agent_registry[call_sid] = agent
    print(f"✅ [Agent] Initialized agent for call {call_sid}")


def cleanup_agent_for_call(call_sid: str) -> None:
    """Remove the agent from the registry when the call ends."""
    _agent_registry.pop(call_sid, None)
    print(f"🗑 [Agent] Cleaned up agent for call {call_sid}")


# ─── Public chat() — drop-in replacement ─────────────────────────────────────

async def chat(user_message: str, call_sid: str) -> str:
    """
    Send a user message to the Jeevan agent and get a response.
    Uses stream_events internally so every agent step is printed to the server logs:
      - 🧠 [Agent thinking] — when the LLM is deciding what to do
      - 🔧 [Tool call] — which tool was chosen and with what input
      - 📦 [Tool result] — what the tool returned
      - ✅ [Agent reply] — the final text response

    Args:
        user_message: The user's transcribed speech text.
        call_sid: Twilio CallSid — used as LangGraph thread_id for conversation memory.

    Returns:
        The agent's final text response.
    """
    agent = _agent_registry.get(call_sid)
    if agent is None:
        print(f"⚠ [Agent] No agent found for call {call_sid}. Creating a fallback agent.")
        initialize_agent_for_call(call_sid, "No stock purchase data available for this client today.")
        agent = _agent_registry[call_sid]

    try:
        config_dict = {"configurable": {"thread_id": call_sid}}
        ai_reply = ""

        # --- Handle Barge-in State Cleanup ---
        # If the user barges-in while the agent was running a tool, the agent's state
        # is suspended with a dangling LLM tool_call message that hasn't been resolved yet.
        # We must prune it before submitting the new user utterance, or LangGraph errors out.
        state = agent.get_state(config_dict)
        if state and getattr(state, "values", {}).get("messages"):
            last_msg = state.values["messages"][-1]
            if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
                print(f"🧹 [Agent] Pruning dangling tool_call from interrupted barge-in.")
                agent.update_state(config_dict, {"messages": [RemoveMessage(id=last_msg.id)]})
        # -------------------------------------

        # astream_events is an async generator — 'async for' is required.
        # No latency cost: it runs the same computation, just fires events mid-flight.
        async for event in agent.astream_events(
            {"messages": [{"role": "user", "content": user_message}]},
            config=config_dict,
            version="v2",
        ):
            kind = event.get("event", "")
            name = event.get("name", "")

            # ── LLM starts generating ───────────────────────────────────────
            if kind == "on_chat_model_start":
                print(f"🧠 [Agent thinking] LLM is processing the message...")

            # ── LLM decided to call a tool ──────────────────────────────────
            elif kind == "on_tool_start":
                tool_input = event.get("data", {}).get("input", {})
                print(f"🔧 [Tool call] → {name}  |  Input: {tool_input}")

            # ── Tool returned a result ──────────────────────────────────────
            elif kind == "on_tool_end":
                tool_output = event.get("data", {}).get("output", "")
                # Truncate long outputs for log readability
                output_preview = str(tool_output)[:300]
                if len(str(tool_output)) > 300:
                    output_preview += "..."
                print(f"📦 [Tool result] ← {name}  |  Output: {output_preview}")

            # ── LLM finished generating the final reply ─────────────────────
            elif kind == "on_chat_model_end":
                # Extract the content from the last generation
                output = event.get("data", {}).get("output")
                if output is not None:
                    if hasattr(output, "content"):
                        ai_reply = output.content
                    elif hasattr(output, "generations"):
                        # Handle GenerationChunk / ChatGenerationChunk
                        gens = output.generations
                        if gens and gens[0]:
                            gen = gens[0][0] if isinstance(gens[0], list) else gens[0]
                            ai_reply = getattr(gen, "text", "") or getattr(
                                getattr(gen, "message", None), "content", ""
                            )

        # Fallback: if stream gave us nothing useful, use ainvoke
        if not ai_reply or not ai_reply.strip():
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_message}]},
                config=config_dict,
            )
            messages = result.get("messages", [])
            if messages:
                last_message = messages[-1]
                if hasattr(last_message, "content"):
                    ai_reply = last_message.content
                elif isinstance(last_message, dict):
                    ai_reply = last_message.get("content", "")

        if not ai_reply:
            ai_reply = "I'm having trouble processing that. Could you please repeat?"

        print(f"✅ [Agent reply] {ai_reply}")
        return ai_reply

    except Exception as e:
        print(f"❌ [Agent] Error: {e}")
        return "Sorry, I am having trouble processing your request right now."