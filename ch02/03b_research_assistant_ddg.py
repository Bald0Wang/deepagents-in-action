"""ch02 - 实战：研究助手（DuckDuckGo 版，免 Key）。

不想申请 Tavily Key 的小伙伴用这个。
依赖：uv add ddgs（免 API Key，直接联网搜索）。
运行：uv run --env-file .env 03b_research_assistant_ddg.py
"""

import os
import time

from ddgs import DDGS
from langchain_openai import ChatOpenAI

from deepagents import create_deep_agent

# 1. 配置模型（通过 DeepSeek 官方平台接入，兼容 OpenAI 接口）
model = ChatOpenAI(
    model=os.environ.get("MODEL_NAME", "deepseek-v4-flash"),
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com/v1",
)

# 2. 定义搜索工具（DuckDuckGo，免 Key）
def internet_search(
    query: str,
    max_results: int = 5,
):
    """Run a web search for the given query.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return.
    """
    # 默认 auto 后端偶发超时（mojeek 不稳定），这里加重试 + 兜底后端
    backends = ["auto", "bing", "brave"]
    last_err = None
    for backend in backends:
        for attempt in range(2):
            try:
                with DDGS(timeout=20) as ddgs:
                    raw = list(ddgs.text(query, max_results=max_results, backend=backend))
                if raw:
                    return {
                        "query": query,
                        "results": [
                            {"title": r.get("title"), "url": r.get("href"), "content": r.get("body")}
                            for r in raw
                        ],
                    }
            except Exception as e:  # noqa: BLE001 - 网络兜底，切换后端继续
                last_err = e
                time.sleep(1)
    return {"query": query, "results": [], "error": str(last_err)}

# 3. 定义系统提示词
research_instructions = """你是一位专业的研究员。
你的工作是进行深入研究，然后撰写一份完整的研究报告。

你可以使用 internet_search 工具搜索互联网获取信息。
"""

# 4. 创建 Agent
agent = create_deep_agent(
    model=model,
    tools=[internet_search],
    system_prompt=research_instructions,
)

# 5. 运行
if __name__ == "__main__":
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "什么是 LangGraph？"}]}
    )
    print(result["messages"][-1].content)
