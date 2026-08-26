# ============================================================================
# 01_write_todos_basics.py —— ch04 段1：write_todos 工具基础
# 内容：
#   Part A: 复杂任务触发规划，观察 write_todos 调用序列（状态流转）与最终 todos
#   Part B: 任务清单的持久化（同 thread 跨 invoke 保留 / 换 thread 清空）
#
# ⚠️ 版本差异（deepagents 0.7.6 实测）：
#   课程说 write_todos 在 create_deep_agent() 时「自动注入」，但 0.7.6 的默认
#   中间件栈并不包含 TodoListMiddleware，需显式加 middleware=[TodoListMiddleware()]。
#   加入后行为与课程一致（write_todos 工具 + 规划提示词自动生效）。
# ============================================================================

from langgraph.checkpoint.memory import MemorySaver

from common import make_model

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware


# ---------------------------------------------------------------------------
# 提取一次运行中所有 write_todos 调用（观察 pending→in_progress→completed 流转）
# ---------------------------------------------------------------------------
def todo_calls(result):
    seq = []                                   # [(轮次, [(内容, 状态), ...])]
    for m in result["messages"]:
        for tc in (getattr(m, "tool_calls", None) or []):
            if tc["name"] == "write_todos":
                items = [(t.get("content", "")[:26], t.get("status")) for t in tc["args"].get("todos", [])]
                seq.append(items)
    return seq


def part_a_plan_execute_track():
    print("=" * 60)
    print("Part A: 复杂任务 → 规划 → 执行 → 状态流转")
    print("=" * 60)
    # 创建 Agent；0.7.6 需显式加 TodoListMiddleware（见文件头版本说明）
    agent = create_deep_agent(
        model=make_model(),
        middleware=[TodoListMiddleware()],
        system_prompt="你是文件助手。面对多步骤任务，必须先用 write_todos 制定计划，"
                      "逐步执行并实时更新状态（完成后立即标 completed）。",
    )
    # 一个 5 步的复杂任务（>=3 步才会触发规划提示词的引导）
    r = agent.invoke({"messages": [{"role": "user", "content": (
        "这是 5 步任务：1) write_file /workspace/plan.md 内容 '研究主题：Agent 任务规划'；"
        "2) write_file /workspace/n1.md 内容 '要点1：先拆解'；"
        "3) write_file /workspace/n2.md 内容 '要点2：再执行'；"
        "4) read_file /workspace/plan.md；5) 汇总所有要点。请先规划再执行。"
    )}]})

    print("--- write_todos 调用序列（观察状态流转）---")
    for i, items in enumerate(todo_calls(r), 1):
        print(f"  第{i}次调用:")
        for content, status in items:
            print(f"    [{status:^11}] {content}")
    print("--- 最终任务清单（result['todos']）---")
    for t in (r.get("todos") or []):
        print(f"  [{t['status']:^11}] {t['content']}")
    print("--- Agent 汇报 ---")
    print(r["messages"][-1].content)


def part_b_persistence():
    print()
    print("=" * 60)
    print("Part B: 任务清单持久化（同 thread 保留 / 换 thread 清空）")
    print("=" * 60)
    # 加 checkpointer，thread_id 区分对话线程
    agent = create_deep_agent(
        model=make_model(),
        middleware=[TodoListMiddleware()],
        system_prompt="你是文件助手，复杂任务先用 write_todos 规划，逐步执行。",
        checkpointer=MemorySaver(),
    )
    t1 = {"configurable": {"thread_id": "todo-A"}}

    # 第一轮：只完成部分步骤（前 2 步）
    r1 = agent.invoke({"messages": [{"role": "user", "content": (
        "4 步任务，本轮只做前 2 步，做完就停："
        "1) write_file /workspace/s1.md 内容 '步骤1完成'；"
        "2) write_file /workspace/s2.md 内容 '步骤2完成'。"
        "（第 3、4 步留给下一轮：读回 s1.md、汇总）请先规划。"
    )}]}, config=t1)
    print("--- 第一轮后 todos（thread todo-A）---")
    for t in (r1.get("todos") or []):
        print(f"  [{t['status']:^11}] {t['content']}")

    # 第二轮：同一 thread 继续，todos 应保留（Agent 能接着做第 3、4 步）
    r2 = agent.invoke({"messages": [{"role": "user", "content": "继续完成剩余步骤。"}]}, config=t1)
    print("--- 第二轮后 todos（同 thread，应从上轮继续）---")
    for t in (r2.get("todos") or []):
        print(f"  [{t['status']:^11}] {t['content']}")

    # 换 thread：todos 应为空（上下文隔离，互不串扰）
    r3 = agent.invoke(
        {"messages": [{"role": "user", "content": "write_file /workspace/other.md 内容 '另一线程'，简单任务直接做。"}]},
        config={"configurable": {"thread_id": "todo-B"}},
    )
    print(f"--- 新线程 todo-B 的 todos ---\n  {r3.get('todos') or '（空，未跨线程泄漏）'}")


if __name__ == "__main__":
    part_a_plan_execute_track()
    part_b_persistence()
