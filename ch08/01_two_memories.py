# ============================================================================
# 01_two_memories.py —— ch08 段1：短期记忆 vs 长期记忆（对照实验）
#
#   Part A: Checkpointer 短期记忆 —— 同 thread 记得 / 换 thread 忘记
#   Part B: StateBackend 文件也是短期 —— 换 thread 文件消失
#   Part C: /memories/ 路由到 Store —— 换 thread 文件还在（长期记忆）
#
# ⚠️ 0.7.13 实测细节：CompositeBackend 存进 store 的 key 会剥掉路由前缀
#    （/memories/prefs.md → store key "/prefs.md"），排查数据时别找不到。
# ============================================================================

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from common import make_model, preview

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend


def part_a_checkpointer():
    print("=" * 60)
    print("Part A: Checkpointer 短期记忆（对话历史）")
    print("=" * 60)
    agent = create_deep_agent(model=make_model(), checkpointer=MemorySaver())
    t1 = {"configurable": {"thread_id": "conv-001"}}
    t2 = {"configurable": {"thread_id": "conv-002"}}
    agent.invoke({"messages": [{"role": "user", "content": "我叫张三，记住这个名字。"}]}, config=t1)
    r = agent.invoke({"messages": [{"role": "user", "content": "我叫什么名字？"}]}, config=t1)
    print(f"  同一 thread 还记得: {preview(r['messages'][-1].content, 50)}")
    r2 = agent.invoke({"messages": [{"role": "user", "content": "我叫什么名字？"}]}, config=t2)
    print(f"  换 thread 后: {preview(r2['messages'][-1].content, 60)}（期望：不知道）")


def part_b_state_files():
    print()
    print("=" * 60)
    print("Part B: StateBackend 的文件也是短期（换 thread 消失）")
    print("=" * 60)
    agent = create_deep_agent(model=make_model(), checkpointer=MemorySaver(),
                              system_prompt="你是文件助手，按指令操作文件。")
    t1 = {"configurable": {"thread_id": "file-001"}}
    t2 = {"configurable": {"thread_id": "file-002"}}
    agent.invoke({"messages": [{"role": "user", "content": "用 write_file 创建 /workspace/note.txt，内容 '桌面上的便签'，完成后回一句。"}]}, config=t1)
    r = agent.invoke({"messages": [{"role": "user", "content": "read_file /workspace/note.txt，把内容告诉我。"}]}, config=t1)
    print(f"  同一 thread 读到: {preview(r['messages'][-1].content, 60)}")
    r2 = agent.invoke({"messages": [{"role": "user", "content": "read_file /workspace/note.txt，如果不存在就说'不存在'。"}]}, config=t2)
    print(f"  换 thread 读取: {preview(r2['messages'][-1].content, 60)}（期望：不存在）")


def part_c_store_files():
    print()
    print("=" * 60)
    print("Part C: /memories/ 路由到 Store —— 长期记忆（换 thread 仍在）")
    print("=" * 60)
    store = InMemoryStore()
    agent = create_deep_agent(
        model=make_model(),
        checkpointer=MemorySaver(),
        system_prompt="你是助手。用户让你'记住'的信息，用 write_file 保存到 /memories/ 下。",
        backend=CompositeBackend(
            default=StateBackend(),
            routes={"/memories/": StoreBackend(namespace=lambda rt: ("demo-user",))},
        ),
        store=store,
    )
    t1 = {"configurable": {"thread_id": "mem-001"}}
    t2 = {"configurable": {"thread_id": "mem-002"}}
    agent.invoke({"messages": [{"role": "user", "content": "记住：我的咖啡偏好是拿铁少糖。保存到 /memories/prefs.md"}]}, config=t1)
    r = agent.invoke({"messages": [{"role": "user", "content": "read_file /memories/prefs.md，把内容告诉我。"}]}, config=t2)
    print(f"  全新 thread 读到: {preview(r['messages'][-1].content, 70)}")
    keys = [(i.namespace, i.key) for i in store.search(("demo-user",))]
    print(f"  store 中的条目: {keys}（注意 key 已剥掉 /memories/ 前缀）")


if __name__ == "__main__":
    part_a_checkpointer()
    part_b_state_files()
    part_c_store_files()
