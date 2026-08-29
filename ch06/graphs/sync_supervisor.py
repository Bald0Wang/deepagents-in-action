# ============================================================================
# graphs/sync_supervisor.py —— 实验一（对照组）：模拟 ch05 同步 task() 的阻塞语义
#
# 主 Agent 持有一个普通同步工具 research_topic()（内部 time.sleep(5)）。
# 用户一次下达 3 个主题 → 模型逐个调用工具 → 每次调用主 Agent 都被阻塞 5 秒
# —— 这正是 ch06 描述的"同步子 Agent 瓶颈"：用户只能盯着转圈。
# ============================================================================

import time

from langchain_openai import ChatOpenAI

from deepagents import create_deep_agent

import os


def research_topic(topic: str) -> str:
    """调研指定主题（同步阻塞 5 秒，模拟长耗时子任务）。"""
    time.sleep(5)   # 同步 sleep：主 Agent 在此期间完全阻塞
    return f"[sync research done in 5s] topic: {topic}"


model = ChatOpenAI(
    model=os.environ.get("MODEL_NAME", "deepseek-v4-flash"),
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com/v1",
)

graph = create_deep_agent(
    model=model,
    tools=[research_topic],
    system_prompt=(
        "你是同步调研助手。用户会给出多个主题，你必须对每个主题各调用一次 "
        "research_topic 工具（逐个调用，不要并行承诺），全部完成后汇总每个主题的结果。"
    ),
)
