# ============================================================================
# 03_todo_summarization_synergy.py —— ch04 段3：任务规划与上下文管理的协同
#
# 验证课程的「北极星」论断：即使对话历史被总结压缩，任务清单依然完整。
#   组合：TodoListMiddleware + FilesystemMiddleware + SummarizationMiddleware
#   方法：trigger={"messages": 6} 提前触发总结（课程默认 ("ratio", 0.85)，
#         1M 窗口的模型跑不到 85%，用消息数阈值低成本复现）
#   判据：
#     1) /conversation_history/ 出现存档文件  => 总结已触发
#     2) result["todos"] 仍包含全部 6 项任务   => 清单未被总结破坏（北极星）
#     3) Agent 在总结后仍能按清单完成剩余任务  => 方向未迷失
# ============================================================================

from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langgraph.checkpoint.memory import MemorySaver

from common import make_model, preview

from deepagents.backends import StateBackend
from deepagents.middleware import FilesystemMiddleware, SummarizationMiddleware


def main():
    print("=" * 60)
    print("规划 + 总结协同：总结触发后 todos 仍完整（北极星）")
    print("=" * 60)
    # 手动组装三层能力（等价于 create_deep_agent 内部组合的一部分）
    agent = create_agent(
        model=make_model(),
        tools=[],
        middleware=[
            TodoListMiddleware(),   # 任务规划：write_todos + 规划提示词
            FilesystemMiddleware(),  # 文件工具（也是总结存档的目标后端）
            SummarizationMiddleware(
                model=make_model(),           # 生成摘要用的模型
                backend=StateBackend(),       # 完整历史存档到该后端（必填）
                trigger={"messages": 6},      # 消息数 >=6 触发（低成本复现 85% 语义）
                keep=("messages", 2),         # 摘要后保留最近 2 条
            ),
        ],
        checkpointer=MemorySaver(),
    )
    thread = {"configurable": {"thread_id": "synergy-demo"}}

    # 6 个小任务分两轮下发：第一轮 4 个（把消息数推过阈值触发总结），第二轮继续剩余 2 个
    round1 = (
        "6 步任务，本轮先做前 4 步，请先 write_todos 规划全部 6 步：\n"
        "1) write_file /workspace/t1.md 内容 '任务1完成'\n"
        "2) write_file /workspace/t2.md 内容 '任务2完成'\n"
        "3) write_file /workspace/t3.md 内容 '任务3完成'\n"
        "4) write_file /workspace/t4.md 内容 '任务4完成'\n"
        "（第 5、6 步下一轮再做：5) 读回 t1.md；6) 汇总全部任务状态）"
    )
    r1 = agent.invoke({"messages": [{"role": "user", "content": round1}]}, config=thread)
    print("--- 第一轮后 todos ---")
    for t in (r1.get("todos") or []):
        print(f"  [{t['status']:^11}] {t['content']}")
    print(f"第一轮后文件: {sorted((r1.get('files') or {}).keys())}")

    # 第二轮：继续完成剩余 2 步（此时对话历史可能已被总结压缩）
    r2 = agent.invoke({"messages": [{"role": "user", "content": "继续完成第 5、6 步。"}]}, config=thread)
    print("--- 第二轮后 todos（北极星：清单完整、状态推进）---")
    todos = r2.get("todos") or []
    for t in todos:
        print(f"  [{t['status']:^11}] {t['content']}")

    # 判据 1：总结是否触发（/conversation_history/ 存档文件出现）
    history_files = [p for p in (r2.get("files") or {}) if "conversation_history" in p]
    print(f"[check] 总结触发（存档文件）: {history_files or '未触发'}")

    # 判据 2：todos 是否仍完整（6 项全在）
    print(f"[check] todos 完整性: {len(todos)} 项（应为 6），全部完成: {all(t['status']=='completed' for t in todos)}")

    # 判据 3：Agent 是否记得任务全貌（第 6 步汇总应提到全部 6 个任务）
    reply = r2["messages"][-1].content
    print(f"[check] Agent 汇报预览: {preview(reply, 200)}")


if __name__ == "__main__":
    main()
