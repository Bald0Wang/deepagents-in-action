# ============================================================================
# graphs/hybrid_supervisor.py —— 实验二：混合部署拓扑（Hybrid）
#
# 同一个主 Agent 声明两个异步子 Agent：
#   - researcher : graph_id=timed_researcher，不传 url → ASGI 进程内传输（同部署，server A）
#   - remote_coder: graph_id=remote_coder，url=http://127.0.0.1:2025 → HTTP 远程传输（server B）
# 验证：一条对话里同时驱动「同部署 + 远程」两种传输，且两者并行执行。
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
        "你是混合拓扑调度员。收到任务后：\n"
        "1. 用 start_async_task 委派 researcher（本地同部署，走 ASGI）执行调研；\n"
        "2. 用 start_async_task 委派 remote_coder（远程服务，走 HTTP）执行编码；\n"
        "两个任务都要启动，然后把两个 task_id 分别告诉用户并停止。不要轮询。"
    ),
    subagents=[
        AsyncSubAgent(
            name="researcher",
            description="Local in-process research worker (~5s, ASGI transport).",
            graph_id="timed_researcher",          # ASGI：注册在 server A
        ),
        AsyncSubAgent(
            name="remote_coder",
            description="Remote coding worker (~6s, HTTP transport on another server).",
            graph_id="remote_coder",              # HTTP：注册在 server B
            url="http://127.0.0.1:2025",
        ),
    ],
)
