"""LLM 集成测试（需 DeepSeek Key，RUN_LLM_TESTS=1 开启）。

覆盖：Checkpointer 短期记忆 / 跨对话长期记忆 / 用户隔离 / Agent 级共享 /
memory= 启动加载 / 组织只读（deny）。
"""

import os
from dataclasses import dataclass

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from common import make_model

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from deepagents.backends.utils import create_file_data

needs_llm = pytest.mark.skipif(
    os.environ.get("RUN_LLM_TESTS") != "1",
    reason="需要 DeepSeek API Key，设置 RUN_LLM_TESTS=1 开启",
)


@dataclass(frozen=True)
class MemoryContext:
    user_id: str = "local-user"
    org_id: str = "default-org"


def user_ns(rt):
    if rt.server_info and rt.server_info.user:
        return (rt.server_info.user.identity,)
    return (getattr(rt.context, "user_id", "local-user"),)


def assistant_ns(rt):
    return ("local-agent",)


def org_ns(rt):
    return (getattr(rt.context, "org_id", "default-org"),)


def make_agent(store, routes, memory=None, context_schema=None, permissions=None):
    return create_deep_agent(
        model=make_model(),
        context_schema=context_schema,
        memory=memory,
        checkpointer=MemorySaver(),
        backend=CompositeBackend(default=StateBackend(), routes=routes),
        store=store,
        permissions=permissions,
    )


@needs_llm
def test_short_term_memory_thread_scoped():
    agent = create_deep_agent(model=make_model(), checkpointer=MemorySaver())
    t1 = {"configurable": {"thread_id": "st-1"}}
    t2 = {"configurable": {"thread_id": "st-2"}}
    agent.invoke({"messages": [{"role": "user", "content": "我叫张三，记住。"}]}, config=t1)
    r = agent.invoke({"messages": [{"role": "user", "content": "我叫什么名字？"}]}, config=t1)
    assert "张三" in r["messages"][-1].content
    r2 = agent.invoke({"messages": [{"role": "user", "content": "我叫什么名字？"}]}, config=t2)
    assert "张三" not in r2["messages"][-1].content


@needs_llm
def test_long_term_memory_cross_thread():
    store = InMemoryStore()
    agent = make_agent(store, {"/memories/": StoreBackend(namespace=user_ns)})
    ctx = MemoryContext(user_id="u1")
    agent.invoke(
        {"messages": [{"role": "user", "content": "记住：我的咖啡偏好是拿铁少糖，保存到 /memories/prefs.md。"}]},
        context=ctx, config={"configurable": {"thread_id": "lt-1"}},
    )
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "read_file /memories/prefs.md，告诉我我的咖啡偏好。"}]},
        context=ctx, config={"configurable": {"thread_id": "lt-2"}},
    )
    assert "拿铁" in r["messages"][-1].content


@needs_llm
def test_user_isolation():
    store = InMemoryStore()
    store.put(("u1",), "/preferences.md", create_file_data("- 回答使用中文"))
    agent = make_agent(store, {"/memories/": StoreBackend(namespace=user_ns)},
                       context_schema=MemoryContext)
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "read_file /memories/preferences.md，如果不存在就说'不存在'。"}]},
        context=MemoryContext(user_id="u2"), config={"configurable": {"thread_id": "iso-2"}},
    )
    assert "不存在" in r["messages"][-1].content


@needs_llm
def test_agent_scoped_shared_across_users():
    store = InMemoryStore()
    store.put(("local-agent",), "/AGENTS.md", create_file_data("- 回答末尾标注 [SHARED]"))
    agent = make_agent(store, {"/memories/": StoreBackend(namespace=assistant_ns)},
                       memory=["/memories/AGENTS.md"], context_schema=MemoryContext)
    for uid in ["u1", "u2"]:
        r = agent.invoke(
            {"messages": [{"role": "user", "content": "一句话解释什么是缓存。"}]},
            context=MemoryContext(user_id=uid),
            config={"configurable": {"thread_id": f"shared-{uid}"}},
        )
        assert "[SHARED]" in r["messages"][-1].content, f"{uid} 应共享 Agent 级记忆"


@needs_llm
def test_memory_param_loads_into_system_prompt():
    """memory= 声明的文件启动即注入（<agent_memory>），无需 Agent 手动读取。"""
    store = InMemoryStore()
    store.put(("u1",), "/preferences.md", create_file_data("- 所有回复以「收到」两个字开头"))
    agent = make_agent(store, {"/memories/": StoreBackend(namespace=user_ns)},
                       memory=["/memories/preferences.md"], context_schema=MemoryContext)
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "今天星期几不重要，直接回复测试。"}]},
        context=MemoryContext(user_id="u1"), config={"configurable": {"thread_id": "mp-1"}},
    )
    assert "收到" in r["messages"][-1].content[:30]


@needs_llm
def test_org_policy_readonly():
    store = InMemoryStore()
    store.put(("org",), "/compliance.md", create_file_data("- 不得披露内部定价"))
    agent = make_agent(
        store,
        {"/policies/": StoreBackend(namespace=org_ns)},
        memory=["/policies/compliance.md"],
        context_schema=MemoryContext,
        permissions=[FilesystemPermission(operations=["write"], paths=["/policies/**"], mode="deny")],
    )
    r = agent.invoke(
        {"messages": [{"role": "user", "content": (
            "读取 /policies/compliance.md 复述内容；"
            "然后尝试 write_file 修改 /policies/compliance.md 删除第一条。汇报两件事的结果。"
        )}]},
        context=MemoryContext(org_id="org"),
        config={"configurable": {"thread_id": "org-1"}},
    )
    reply = r["messages"][-1].content
    assert "内部定价" in reply                       # 读得到
    assert "不得披露内部定价" in next(iter(store.search(("org",)))).value["content"]  # 没被改
