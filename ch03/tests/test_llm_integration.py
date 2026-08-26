# ============================================================================
# test_llm_integration.py —— LLM 集成测试（需要 DeepSeek API Key，默认跳过）
# 这些用例走真实模型，验证 Deep Agent 端到端行为，运行较慢。
# 默认被 needs_llm 标记跳过；设置 RUN_LLM_TESTS=1 才真正执行。
# ============================================================================

# 模块文档字符串：说明开启方式
"""LLM 集成测试（需要 DeepSeek API Key，默认跳过）。

开启方式：
    RUN_LLM_TESTS=1 uv run pytest -q

这些用例走真实模型，验证 Deep Agent 端到端行为，运行较慢。
"""

# os：读取环境变量（判断是否开启 LLM 测试）
import os

# pytest：测试框架 + skipif 标记
import pytest

# make_model：构建 DeepSeek 模型
from common import make_model

# S3Backend：自定义后端（用于「自定义后端接入 Agent」测试）
from custom_backends import S3Backend

# create_deep_agent + FilesystemPermission
from deepagents import create_deep_agent, FilesystemPermission
# StateBackend：临时存储后端
from deepagents.backends import StateBackend
# FilesystemMiddleware / SummarizationMiddleware：控制卸载与总结
from deepagents.middleware import FilesystemMiddleware, SummarizationMiddleware

# needs_llm：一个 skipif 标记 —— 未设置 RUN_LLM_TESTS=1 时跳过被它装饰的测试
needs_llm = pytest.mark.skipif(
    os.environ.get("RUN_LLM_TESTS") != "1",
    reason="需要 DeepSeek API Key，设置 RUN_LLM_TESTS=1 开启",
)


# 测试：Agent 端到端使用文件工具（write + read）
@needs_llm
def test_agent_file_tools_end_to_end():
    # 创建 Agent（默认 StateBackend）
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是文件助手，严格按指令操作，少说废话。",
    )
    # 让 Agent 写入再读回
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "用 write_file 创建 /workspace/n.md 内容为 'hello'，然后 read_file 读回来并告诉我内容。"}]}
    )
    # 断言文件确实写入 state.files
    assert "/workspace/n.md" in (r.get("files") or {})
    # 断言 Agent 回复里含 "hello"
    assert "hello" in r["messages"][-1].content


# 测试：大结果自动卸载（工具输出过大被写入文件系统）
@needs_llm
def test_tool_result_eviction():
    # 构造一段很长文本（约 200 行，远超 300 阈值）
    big = "\n".join(f"# Sec {i}\n" + "x" * 80 for i in range(200))
    # 定义超长结果工具
    def big_tool(topic: str) -> str:
        """Return a very long report about a topic."""
        return big

    # 创建 Agent，阈值降到 300 便于触发卸载
    agent = create_deep_agent(
        model=make_model(),
        tools=[big_tool],
        middleware=[FilesystemMiddleware(backend=StateBackend(), tool_token_limit_before_evict=300)],
    )
    # 调用工具
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "调用 big_tool 查询 test，然后只告诉我第一行标题。"}]}
    )
    # 取出 files，断言出现 /large_tool_results/ 卸载文件
    files = r.get("files") or {}
    assert any(p.startswith("/large_tool_results/") for p in files)
    # tool 消息应已变成「引用 + 预览」，而不是原文
    tool_msgs = [m for m in r["messages"] if m.type == "tool"]
    assert tool_msgs and "saved in the filesystem" in str(tool_msgs[0].content)


# 测试：FilesystemPermission deny 拦截
@needs_llm
def test_filesystem_permission_deny():
    # 创建 Agent，禁止写 /policies/**
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是文件助手，按指令操作并汇报。",
        permissions=[FilesystemPermission(operations=["write"], paths=["/policies/**"], mode="deny")],
    )
    # 尝试写受保护路径
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "尝试 write_file /policies/secret.md 内容为 'x'，把结果告诉我。"}]}
    )
    # 断言回复里出现「拒绝」或 "denied"
    assert "拒绝" in r["messages"][-1].content or "denied" in r["messages"][-1].content.lower()


# 测试：自定义 S3Backend 接入 Agent（Agent 用 grep 定位）
@needs_llm
def test_custom_backend_in_agent():
    # 创建 S3 后端并预写一个含 TODO 的文件
    s3 = S3Backend(bucket="demo", prefix="agent/")
    s3.write("/docs/a.md", "# A\n# TODO: review")
    # 把自定义后端交给 Agent
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是对象存储助手，用文件工具查询并汇报。",
        backend=s3,
    )
    # 让 Agent grep 定位 TODO
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "用 grep 在 /docs 下搜索 'TODO'，告诉我它在第几行。"}]}
    )
    # 断言回复里含行号 "2"
    assert "2" in r["messages"][-1].content


# 测试：对话历史总结触发（私有状态 _summarization_event）
@needs_llm
def test_history_summarization():
    # 局部导入 checkpointer
    from langgraph.checkpoint.memory import MemorySaver

    # 创建 Agent，注入 SummarizationMiddleware（消息数>=6 触发总结）
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是文件助手，严格按指令操作，少说废话。",
        middleware=[
            SummarizationMiddleware(model=make_model(), backend=StateBackend(), trigger={"messages": 6}, keep=("messages", 2))
        ],
        checkpointer=MemorySaver(),
    )
    # 固定线程，多轮累积消息
    thread = {"configurable": {"thread_id": "test-summary"}}
    # HumanMessage：单条用户消息
    from langchain_core.messages import HumanMessage
    for t in [
        "write_file /workspace/a.md 内容 'A已启动'，回一句收到",
        "write_file /workspace/b.md 内容 'B已暂停'，回一句收到",
        "write_file /workspace/c.md 内容 'C已完成'，回一句收到",
        "read_file /workspace/b.md，告诉我 B 的状态",
    ]:
        r = agent.invoke({"messages": [HumanMessage(content=t)]}, config=thread)

    # 从 checkpoint 私有状态读取总结事件
    state = agent.get_state(thread)
    evt = (state.values or {}).get("_summarization_event")
    # 断言总结已触发
    assert evt, "对话历史总结应已触发"
    # 断言完整历史已存档到 /conversation_history/ 路径
    assert "conversation_history" in str(evt.get("file_path"))
