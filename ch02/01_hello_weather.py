"""ch02 - Hello World：最简单的 Deep Agent。

运行：uv run --env-file .env 01_hello_weather.py
"""

import os

from langchain_openai import ChatOpenAI

from deepagents import create_deep_agent

# 通过 DeepSeek 官方平台接入模型（兼容 OpenAI 接口），模型名由 MODEL_NAME 环境变量控制
model = ChatOpenAI(
    model=os.environ.get("MODEL_NAME", "deepseek-v4-flash"),
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com/v1",
)


def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"


agent = create_deep_agent(
    model=model,
    tools=[get_weather],
    system_prompt="You are a helpful assistant.",
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "银川今天天气怎么样？"}]}
)

print(result["messages"][-1].content)
