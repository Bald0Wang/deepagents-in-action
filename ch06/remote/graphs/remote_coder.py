# ============================================================================
# remote/graphs/remote_coder.py —— 实验二：独立部署在 server B (port 2025) 的远程子 Agent
# 固定 sleep 6 秒（与本地 5 秒区分开），输出带 SERVER-B 标记，验证任务真的跑在另一台服务上。
# ============================================================================

import asyncio

from langgraph.graph import END, START, MessagesState, StateGraph

SLEEP_SECONDS = 6


async def remote_code(state: MessagesState):
    last_human = state["messages"][-1].content if state["messages"] else "No task provided."
    await asyncio.sleep(SLEEP_SECONDS)
    return {
        "messages": [
            {
                "role": "ai",
                "content": (
                    f"[remote_coder finished after {SLEEP_SECONDS}s ON SERVER B]\n"
                    f"task: {last_human}\n"
                    "code artifact written (simulated)."
                ),
            }
        ]
    }


builder = StateGraph(MessagesState)
builder.add_node("remote_code", remote_code)
builder.add_edge(START, "remote_code")
builder.add_edge("remote_code", END)
graph = builder.compile()
