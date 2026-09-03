# ============================================================================
# 05_episodic_and_consolidation.py —— ch08 高级用法补全（一）
#
#   Part A: 情景记忆（Episodic Memory）
#     思路：每次对话结束追加一篇「情景日志」到 /memories/episodes/<id>.md
#     （保留完整经历：发生了什么、结论如何），再给 Agent 配一个自定义检索工具
#     search_episodes()，让它能"回忆起上次是怎么解决问题的"。
#     （课程版本用部署端 threads.search 检索历史线程；本地 invoke 环境用
#      文件式情景日志实现同一语义 —— 也是课程「追加式记录，再后台合并」推荐模式）
#
#   Part B: 后台记忆整合（Background Consolidation）
#     热路径：两次对话各自把要点写进事件日志（互不冲突，文件名唯一）
#     整合：独立"整合 Agent"读取全部事件日志 → 去重合并成稳定记忆 preferences.md
#     生效：第三次对话（memory= 加载整合结果）直接遵循合并后的偏好
# ============================================================================

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from _tool_helpers import make_search_episodes_tool, seed_episode
from common import make_model, preview

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

NS = ("demo-user",)          # store namespace（剥前缀后的 key 都挂在这里）


def make_store():
    return InMemoryStore()


def make_agent(store, memory=None, tools=None, system_prompt=None):
    return create_deep_agent(
        model=make_model(),
        memory=memory,
        tools=tools or [],
        checkpointer=MemorySaver(),
        system_prompt=system_prompt or "你是助手，按用户指令工作并如实汇报。",
        backend=CompositeBackend(
            default=StateBackend(),
            routes={"/memories/": StoreBackend(namespace=lambda rt: NS)},
        ),
        store=store,
    )


def part_a_episodic_memory():
    print("=" * 60)
    print("Part A: 情景记忆（episode 日志 + 检索工具）")
    print("=" * 60)
    store = make_store()
    # 归档两篇历史情景（保留"如何解决"的过程，而非仅结论）
    seed_episode(store, NS, "e001", "2026-09-01",
                 "用户问 Python GIL 是什么。我先给一句话结论，再解释了"
                 "「同一时刻仅一个线程执行字节码」，最后建议 IO 密集用 threading、"
                 "CPU 密集用 multiprocessing。用户满意。")
    seed_episode(store, NS, "e002", "2026-09-02",
                 "用户要排序函数。我默认给了 list.sort()，用户纠正：小数据集"
                 "希望用 sorted() 保持原列表不变。已记住该偏好。")

    agent = make_agent(store, tools=[make_search_episodes_tool(store, NS)])
    r = agent.invoke({"messages": [{"role": "user", "content": (
        "上次我问我 GIL 的时候，你当时是怎么建议的？先调用 search_episodes 查情景，再回答。"
    )}]}, config={"configurable": {"thread_id": "ep-1"}})
    reply = r["messages"][-1].content
    print(f"  调用了情景检索: {any(tc['name'] == 'search_episodes' for m in r['messages'] for tc in (getattr(m, 'tool_calls', None) or []))}")
    print(f"  回忆起当时的建议: {'multiprocessing' in reply or 'threading' in reply}")
    print(f"  回复预览: {preview(reply, 130)}")


def part_b_background_consolidation():
    print()
    print("=" * 60)
    print("Part B: 后台记忆整合（热路径事件日志 → 整合 Agent → 稳定记忆）")
    print("=" * 60)
    store = make_store()

    # ── 热路径：两次对话，各自把要点写入唯一命名的事件日志（互不冲突）──
    main = make_agent(store, system_prompt=(
        "你是助手。完成用户请求后，必须把本次学到的用户偏好写入指定的事件日志文件"
        "（write_file 追加式记录），然后才回复。"
    ))
    main.invoke({"messages": [{"role": "user", "content": (
        "帮我写个排序函数。记住：小数据我喜欢用 sorted() 不改原列表。"
        "把这条偏好写入 /memories/events/ev-001.md 后再回复。"
    )}]}, config={"configurable": {"thread_id": "bg-1"}})
    main.invoke({"messages": [{"role": "user", "content": (
        "再帮我写个 HTTP 重试逻辑。记住：重试间隔用指数退避。"
        "把这条偏好写入 /memories/events/ev-002.md 后再回复。"
    )}]}, config={"configurable": {"thread_id": "bg-2"}})
    events = [i.key for i in store.search(NS) if i.key.startswith("/events/")]
    print(f"  热路径产出事件日志: {sorted(events)}（两文件并存，零冲突）")

    # ── 整合：独立整合 Agent 读取全部事件 → 合并为稳定记忆 ──
    consolidator = make_agent(store, system_prompt=(
        "你是记忆整合器。读取 /memories/events/ 下所有日志，"
        "把用户偏好去重合并成一份简洁清单，写入 /memories/preferences.md"
        "（标题 # 用户偏好，每条一行），完成后汇报合并了哪几条。"
    ))
    rc = consolidator.invoke({"messages": [{"role": "user", "content": "请整合事件日志并更新稳定记忆。"}]},
                             config={"configurable": {"thread_id": "consol-1"}})
    consolidated = next((i.value["content"] for i in store.search(NS)
                         if i.key == "/preferences.md"), "")
    print(f"  整合产物存在: {bool(consolidated)}")
    print(f"  两条偏好都在: {'sorted()' in consolidated and '指数退避' in consolidated}")
    print(f"  整合器汇报: {preview(rc['messages'][-1].content, 90)}")

    # ── 生效：第三次对话（memory= 启动加载整合结果）──
    user3 = make_agent(store, memory=["/memories/preferences.md"])
    r3 = user3.invoke({"messages": [{"role": "user", "content": (
        "按我的偏好写一个列表去重的函数，一句话说明你遵循了哪条偏好。"
    )}]}, config={"configurable": {"thread_id": "bg-3"}})
    print(f"  新对话遵循整合记忆: {'sorted()' in r3['messages'][-1].content or '不改原列表' in r3['messages'][-1].content}")
    print(f"  回复预览: {preview(r3['messages'][-1].content, 110)}")


if __name__ == "__main__":
    part_a_episodic_memory()
    part_b_background_consolidation()
