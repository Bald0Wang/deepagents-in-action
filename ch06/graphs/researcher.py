# ============================================================================
# graphs/researcher.py —— ch06：故意"跑得很慢"的异步子 Agent
#
# 用一个固定 sleep 8 秒的 LangGraph 图代替真实研究，让异步行为稳定可观察：
#   - supervisor 调 start_async_task 后【立刻】拿到 task_id（不等这 8 秒）
#   - 本图在后台独立 thread 中运行
#   - check_async_task 能观察到状态从 running → success
# ============================================================================

import asyncio

from langgraph.graph import END, START, MessagesState, StateGraph


async def slow_research(state: MessagesState):
    # 取用户委派的任务描述（最后一条人类消息）
    last_human = state["messages"][-1].content if state["messages"] else "No task provided."
    # 故意阻塞 8 秒——模拟长程任务
    await asyncio.sleep(8)
    return {
        "messages": [
            {
                "role": "ai",
                "content": (
                    "[researcher finished after 8s]\n"
                    f"latest task: {last_human}\n"
                    "summary: async subagents return a task ID immediately, "
                    "run in the background, and can be checked or updated later."
                ),
            }
        ]
    }


builder = StateGraph(MessagesState)
builder.add_node("slow_research", slow_research)
builder.add_edge(START, "slow_research")
builder.add_edge("slow_research", END)
graph = builder.compile()          # 变量名必须是 graph —— langgraph.json 指向它
