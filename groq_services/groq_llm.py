from groq import Groq
import config


client = Groq(api_key=config.GROQ_API_KEY)

SYSTEM_PROMPT = """You are an AI investment assistant for a stock market advisory firm. 
You help clients understand their investments, portfolio performance, and market trends.
Keep your responses concise and conversational since they will be spoken aloud on a phone call.
Limit responses to 2-3 sentences maximum."""


def chat(user_message: str, chat_history: list[dict] | None = None) -> str:
    """
    Send a message to Groq LLM and get a response (non-streaming).
    
    Args:
        user_message: The user's transcribed speech text.
        chat_history: Optional list of previous messages for context.
                      If None, starts a fresh conversation with the system prompt.
    
    Returns:
        The AI's response text.
    """
    if chat_history is None:
        chat_history = [{"role": "system", "content": SYSTEM_PROMPT}]
    elif len(chat_history) == 0:
        chat_history.append({"role": "system", "content": SYSTEM_PROMPT})

    chat_history.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=chat_history,
            stream=False,
            temperature=0.7,
            max_tokens=200,
        )

        ai_reply = response.choices[0].message.content
        chat_history.append({"role": "assistant", "content": ai_reply})
        
        print(f"✅ [Groq LLM] Response: {ai_reply}")
        return ai_reply

    except Exception as e:
        print(f"❌ Groq LLM Error: {e}")
        return "Sorry, I am having trouble processing your request right now."