from langchain_ollama import ChatOllama
from browser_use import Agent
import asyncio

# Initialize the model
llm=ChatOllama(
    base_url="http://192.168.30.16:11434",
    model="qwen3:235b", 
    num_ctx=32000,
    temperature=0.2,
    timeout=120)

# Create agent with the model
async def main():
    agent = Agent(
        task="Compare the price of gpt-4o and DeepSeek-V3",
        llm=llm,
        enable_memory=False
    )
    result = await agent.run()
    print(result)

asyncio.run(main())