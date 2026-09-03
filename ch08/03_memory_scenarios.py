# ============================================================================
# 03_memory_scenarios.py —— ch08 段3：四种实用场景中的三个（本地可完整验证）
#
#   场景1: 用户偏好记忆 —— 对话1说偏好 → 对话2（全新线程）自动应用
#   场景2: 自我改进的 Agent —— 用户纠错 → edit_file 更新 AGENTS.md → 新对话遵循
#   场景3: 知识库累积 —— 三个对话逐次追加，最后读出完整知识
#   （场景4 研究持续推进 = 场景3 的多文件版，机制相同不再重复）
#
# 关键：memory= 参数声明记忆路径，启动时自动注入系统提示词（<agent_memory>），
#       Agent 用 edit_file 更新后持久化到下次对话。
# ============================================================================

from dataclasses import dataclass

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from common import make_model, preview

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from deepagents.backends.utils import create_file_data


@dataclass(frozen=True)
class MemoryContext:
    user_id: str = "local-user"


def user_namespace(rt):
    if rt.server_info and rt.server_info.user:
        return (rt.server_info.user.identity,)
    return (getattr(rt.context, "user_id", "local-user"),)


def make_memory_agent(store, memory_paths, seed=None):
    """带长期记忆的 Agent。seed: 预填的 {store_key: content}。"""
    for key, content in (seed or {}).items():
        store.put(("demo-user",), key, create_file_data(content))
    return create_deep_agent(
        model=make_model(),
        context_schema=MemoryContext,
        memory=memory_paths,                 # 启动时自动加载进系统提示词
        checkpointer=MemorySaver(),
        backend=CompositeBackend(
            default=StateBackend(),
            routes={"/memories/": StoreBackend(namespace=user_namespace)},
        ),
        store=store,
    )


def scenario1_preferences():
    print("=" * 60)
    print("场景1: 用户偏好记忆（对话1 记住 → 对话2 应用）")
    print("=" * 60)
    store = InMemoryStore()
    agent = make_memory_agent(store, memory_paths=["/memories/preferences.md"])
    ctx = MemoryContext(user_id="demo-user")

    agent.invoke({"messages": [{"role": "user", "content":
        "记住我的偏好：代码注释用中文，变量名用英文。保存到 /memories/preferences.md。"}]},
        context=ctx, config={"configurable": {"thread_id": "s1-conv1"}})

    r = agent.invoke({"messages": [{"role": "user", "content":
        "用 Python 写一个两数相加的函数（注意应用我的偏好）。"}]},
        context=ctx, config={"configurable": {"thread_id": "s1-conv2"}})   # 全新对话！
    reply = r["messages"][-1].content
    print(f"  新对话的代码注释是中文: {'# ' in reply and any(ord(c) > 0x4e00 for c in reply.split('#')[-1] if c.strip()[:1]) or '两数相加' in reply}")
    print(f"  回复预览: {preview(reply, 160)}")


def scenario2_self_improving():
    print()
    print("=" * 60)
    print("场景2: 自我改进的 Agent（纠错 → 更新 AGENTS.md → 新对话遵循）")
    print("=" * 60)
    store = InMemoryStore()
    agent = make_memory_agent(
        store,
        memory_paths=["/memories/AGENTS.md"],
        seed={"/AGENTS.md": "# Agent 行为准则\n- 回答末尾附一句英文格言\n"},
    )
    ctx = MemoryContext(user_id="demo-user")

    # 对话1：用户纠错 → Agent 应更新记忆文件
    agent.invoke({"messages": [{"role": "user", "content":
        "以后不要附英文格言了，改成在开头先给一句话结论。请更新你的行为准则文件 /memories/AGENTS.md。"}]},
        context=ctx, config={"configurable": {"thread_id": "s2-conv1"}})
    updated = next(iter(store.search(("demo-user",)))).value["content"]
    print(f"  AGENTS.md 已更新: {'结论' in updated and '格言' not in updated}")

    # 对话2：新对话应遵循新准则
    r = agent.invoke({"messages": [{"role": "user", "content": "Python 的 GIL 是什么？"}]},
                     context=ctx, config={"configurable": {"thread_id": "s2-conv2"}})
    print(f"  新对话回复预览: {preview(r['messages'][-1].content, 100)}")
    print(f"  （观察：开头是否先给一句话结论、结尾是否已无英文格言）")


def scenario3_knowledge_accumulation():
    print()
    print("=" * 60)
    print("场景3: 知识库累积（三次对话逐次追加）")
    print("=" * 60)
    store = InMemoryStore()
    agent = make_memory_agent(store, memory_paths=["/memories/project/tech-stack.md"])
    ctx = MemoryContext(user_id="demo-user")

    # 对话1：前端技术栈
    agent.invoke({"messages": [{"role": "user", "content":
        "记录到 /memories/project/tech-stack.md：前端用 React + TypeScript。"}]},
        context=ctx, config={"configurable": {"thread_id": "s3-c1"}})
    # 对话2：追加后端
    agent.invoke({"messages": [{"role": "user", "content":
        "在 /memories/project/tech-stack.md 里补充：后端用 FastAPI + PostgreSQL。"}]},
        context=ctx, config={"configurable": {"thread_id": "s3-c2"}})
    # 对话3：读出完整知识
    r = agent.invoke({"messages": [{"role": "user", "content":
        "读 /memories/project/tech-stack.md，总结我们项目的完整技术栈。"}]},
        context=ctx, config={"configurable": {"thread_id": "s3-c3"}})
    final = next(iter(store.search(("demo-user",)))).value["content"]
    print(f"  记忆文件最终内容: {preview(final, 120)}")
    print(f"  对话3 总结: {preview(r['messages'][-1].content, 120)}")
    print(f"  前后端都在: {'React' in final and 'FastAPI' in final}")


if __name__ == "__main__":
    scenario1_preferences()
    scenario2_self_improving()
    scenario3_knowledge_accumulation()
