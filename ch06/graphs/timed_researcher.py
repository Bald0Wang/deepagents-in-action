# ============================================================================
# graphs/timed_researcher.py —— 计时实验用的 5 秒工作图（ASGI 目标）
# 与 sync/async 对比实验配套：每个子任务固定耗时 5 秒，输出带唯一标记。
# ============================================================================

import asyncio

from langgraph.graph import END, START, MessagesState, StateGraph

SLEEP_SECONDS = 5


async def timed_work(state: MessagesState):
    last_human = state["messages"][-1].content if state["messages"] else "No task provided."
    await asyncio.sleep(SLEEP_SECONDS)
    return {
        "messages": [
            {
                "role": "ai",
                "content": (
                    f"[timed_researcher finished after {SLEEP_SECONDS}s]\n"
                    f"task: {last_human}\n"
                    "done."
                ),
            }
        ]
    }


builder = StateGraph(MessagesState)
builder.add_node("timed_work", timed_work)
builder.add_edge(START, "timed_work")
builder.add_edge("timed_work", END)
graph = builder.compile()
