import asyncio
from langgraph.prebuilt import create_react_agent
from langchain_groq import ChatGroq
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import RemoveMessage, AIMessage, HumanMessage
import os

async def main():
    llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
    checkpointer = InMemorySaver()
    agent = create_react_agent(model=llm, tools=[], checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "1"}}
    
    # Simulate a state with a dangling tool call
    agent.update_state(config, {"messages": [HumanMessage(content="Hello"), AIMessage(content="", tool_calls=[{"name": "foo", "args": {}, "id": "1"}], id="msg1")]})
    
    state = agent.get_state(config)
    last_msg = state.values["messages"][-1]
    print("Before:", last_msg)
    
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        print("Removing dangling tool call...")
        agent.update_state(config, {"messages": [RemoveMessage(id=last_msg.id)]})
        
    state = agent.get_state(config)
    print("After:", state.values["messages"][-1])

asyncio.run(main())
