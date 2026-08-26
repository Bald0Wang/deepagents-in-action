"""ch02 - 实战：构建一个研究助手（完整代码）。

需要先配置 TAVILY_API_KEY（https://app.tavily.com 免费注册）。
运行：uv run --env-file .env 03_research_assistant.py
"""

import os
from typing import Literal

from langchain_openai import ChatOpenAI
from tavily import TavilyClient

from deepagents import create_deep_agent

# 1. 配置模型（通过 DeepSeek 官方平台接入，兼容 OpenAI 接口）
model = ChatOpenAI(
    model=os.environ.get("MODEL_NAME", "deepseek-v4-flash"),
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com/v1",
)

# 2. 初始化搜索客户端
tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

# 3. 定义搜索工具
def internet_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
):
    """Run a web search for the given query.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return.
        topic: The topic category for the search.
        include_raw_content: Whether to include raw page content.
    """
    return tavily_client.search(
        query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        topic=topic,
    )

# 4. 定义系统提示词
research_instructions = """你是一位专业的研究员。
你的工作是进行深入研究，然后撰写一份完整的研究报告。

你可以使用 internet_search 工具搜索互联网获取信息。
"""

# 5. 创建 Agent
agent = create_deep_agent(
    model=model,
    tools=[internet_search],
    system_prompt=research_instructions,
)

# 6. 运行
if __name__ == "__main__":
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "什么是 LangGraph？"}]}
    )
    print(result["messages"][-1].content)
