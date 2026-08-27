# ============================================================================
# graphs/supervisor.py —— ch06：主 Agent（Supervisor）
#
# 关键点：
#   1. AsyncSubAgent(graph_id="researcher") 必须与 langgraph.json 里
#      "graphs" 的键名一致 —— 否则 start_async_task 报找不到 Agent；
#   2. 不传 url → 走 ASGI 进程内传输（同部署形态）；
#   3. system_prompt 明确行为规则：派完任务立刻交还控制权，
#      不主动轮询；汇报进度前必须实时 check。
#
# 模型：沿用 DeepSeek 官方接口（.env 由 langgraph.json 注入本进程）。
# 注意：langgraph dev 下【不要】传 checkpointer —— 平台自带持久化，传了会报错。
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
        "你是异步子 Agent 演示的 supervisor。规则：\n"
        "1. 用户要求执行长耗时研究类任务时，必须立即用 start_async_task 委派给 "
        "researcher，然后把 task_id 原样告诉用户并停止——绝不要截断或改写 task_id。\n"
        "2. 派出任务后不要主动 check_async_task，除非用户明确问进度。\n"
        "3. 用户要求修改后台任务时，用 update_async_task 在原任务上追加指令。\n"
        "4. 回答任务进度前必须先调用 check_async_task 或 list_async_tasks 获取实时状态，"
        "对话历史里的状态永远是过时的。"
    ),
    subagents=[
        AsyncSubAgent(
            name="researcher",
            description=(
                "Use for any long-running background research or async demo task. "
                "This agent intentionally sleeps before returning so the async "
                "behavior is easy to observe."
            ),
            graph_id="researcher",   # 与 langgraph.json 中 graphs 键名一致
        )
    ],
)
