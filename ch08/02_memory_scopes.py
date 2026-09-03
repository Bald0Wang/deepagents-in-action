# ============================================================================
# 02_memory_scopes.py —— ch08 段2：CompositeBackend 长期记忆 + 三种作用域
#
#   Part A: 用户级记忆 —— user-A 的偏好跨线程可用，user-B 看不到（隔离）
#   Part B: Agent 级记忆 —— namespace=(assistant_id,)，所有用户共享
#   Part C: 路径路由 —— /workspace/ 临时（换线程丢）、/memories/ 持久（换线程在）
#
# 技巧：用 store.put + create_file_data 预填记忆文件，让断言路径确定。
# ============================================================================

from dataclasses import dataclass

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from common import make_model, preview

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from deepagents.backends.utils import create_file_data


# ---------------------- 运行时身份与 namespace（课程推荐的三件套） ----------------------
@dataclass(frozen=True)
class MemoryContext:
    user_id: str = "local-user"
    org_id: str = "default-org"


def assistant_namespace(rt):
    if rt.server_info:
        return (rt.server_info.assistant_id,)
    return ("local-agent",)          # 本地兜底


def user_namespace(rt):
    if rt.server_info and rt.server_info.user:
        return (rt.server_info.user.identity,)
    return (getattr(rt.context, "user_id", "local-user"),)


def org_namespace(rt):
    return (getattr(rt.context, "org_id", "default-org"),)


def make_scoped_agent(store, routes):
    return create_deep_agent(
        model=make_model(),
        context_schema=MemoryContext,
        checkpointer=MemorySaver(),
        system_prompt="你是助手。按用户指令读写文件并如实汇报。",
        backend=CompositeBackend(default=StateBackend(), routes=routes),
        store=store,
    )


def part_a_user_scoped():
    print("=" * 60)
    print("Part A: 用户级记忆（namespace=(user_id,)，A/B 隔离）")
    print("=" * 60)
    store = InMemoryStore()
    # 预填 user-A 的偏好（应用代码写入，路径确定）
    store.put(("user-A",), "/preferences.md",
              create_file_data("# 用户A的偏好\n- 回答使用中文\n- 代码示例用 Python\n"))
    agent = make_scoped_agent(store, {"/memories/": StoreBackend(namespace=user_namespace)})

    ctx_a = MemoryContext(user_id="user-A")
    ctx_b = MemoryContext(user_id="user-B")
    # user-A 新线程读自己的记忆 → 能读到
    r1 = agent.invoke({"messages": [{"role": "user", "content": "read_file /memories/preferences.md，复述内容要点。"}]},
                      context=ctx_a, config={"configurable": {"thread_id": "a-t1"}})
    print(f"  user-A 读取: {preview(r1['messages'][-1].content, 70)}")
    # user-B 读同一路径 → 隔离，读不到
    r2 = agent.invoke({"messages": [{"role": "user", "content": "read_file /memories/preferences.md，如果不存在就说'不存在'。"}]},
                      context=ctx_b, config={"configurable": {"thread_id": "b-t1"}})
    print(f"  user-B 读取: {preview(r2['messages'][-1].content, 60)}（期望：不存在）")


def part_b_agent_scoped():
    print()
    print("=" * 60)
    print("Part B: Agent 级记忆（namespace=(assistant_id,)，全员共享）")
    print("=" * 60)
    store = InMemoryStore()
    # 预填 Agent 级知识（所有用户共享同一份）
    store.put(("local-agent",), "/AGENTS.md",
              create_file_data("# Agent 知识\n- 本 Agent 专精 LangGraph 生态答疑\n- 回答保持三段式结构\n"))
    agent = make_scoped_agent(store, {"/memories/": StoreBackend(namespace=assistant_namespace)})

    # 两个不同用户、不同线程，读到同一份 Agent 记忆
    for uid in ["user-A", "user-B"]:
        r = agent.invoke({"messages": [{"role": "user", "content": "read_file /memories/AGENTS.md，用一句话概括这个文件。"}]},
                          context=MemoryContext(user_id=uid),
                          config={"configurable": {"thread_id": f"{uid}-t1"}})
        print(f"  {uid} 读取: {preview(r['messages'][-1].content, 60)}")


def part_c_path_routing():
    print()
    print("=" * 60)
    print("Part C: 路径路由（同一次对话写两个路径，换线程对比）")
    print("=" * 60)
    store = InMemoryStore()
    agent = make_scoped_agent(store, {"/memories/": StoreBackend(namespace=user_namespace)})
    t1 = {"configurable": {"thread_id": "route-1"}}
    t2 = {"configurable": {"thread_id": "route-2"}}
    ctx = MemoryContext(user_id="router")

    agent.invoke({"messages": [{"role": "user", "content": (
        "写两个文件：1) write_file /workspace/draft.md 内容 '临时草稿'；"
        "2) write_file /memories/keep.md 内容 '长期记忆'。完成后回一句。"
    )}]}, context=ctx, config=t1)

    r = agent.invoke({"messages": [{"role": "user", "content": (
        "分别 read_file /workspace/draft.md 和 /memories/keep.md，逐个告诉我存在还是不存在。"
    )}]}, context=ctx, config=t2)
    print(f"  全新线程读两个文件: {preview(r['messages'][-1].content, 140)}")
    print(f"  （期望：draft.md 不存在（State 短期）；keep.md 存在（Store 长期））")
    print(f"  store 条目: {[i.key for i in store.search(('router',))]}")


if __name__ == "__main__":
    part_a_user_scoped()
    part_b_agent_scoped()
    part_c_path_routing()
