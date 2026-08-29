# ============================================================================
# graphs/async_supervisor.py —— 实验一（实验组）：异步并行委派
#
# AsyncSubAgent 指向 timed_researcher（5 秒工作图，ASGI 同部署）。
# 用户一次下达 3 个主题 → 主 Agent 连发 3 个 start_async_task → 立即返回 3 个
# task_id（主对话不阻塞）→ 3 个子任务在后台【并行】跑（需 worker 槽位足够）。
# ============================================================================

import os

from langchain_openai import ChatOpenAI

from deepagents import AsyncSubAgent, create_deep_agent

model = ChatOpenAI(
    model=os.environ.get("MODEL_NAME", "deepseek-v4-flash"),
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com/v1",
)

graph = create_deep_agent(
    model=model,
    system_prompt=(
        "你是异步调度员。用户会给出多个主题；你必须为每个主题各调用一次 "
        "start_async_task（委派给 researcher，一个主题一个任务），"
        "全部启动后立刻把每个主题对应的 task_id 告诉用户并停止。"
        "不要等待结果、不要轮询。"
    ),
    subagents=[
        AsyncSubAgent(
            name="researcher",
            description=(
                "Long-running background research worker. Each run takes ~5 seconds. "
                "Use for parallel background research tasks."
            ),
            graph_id="timed_researcher",   # 必须与 langgraph.json 注册名一致；ASGI 同部署
        )
    ],
)
