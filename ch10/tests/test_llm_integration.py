"""LLM 集成测试（RUN_LLM_TESTS=1）：execute 可见性 / 两平面闭环 / HITL。"""

import os
import tempfile
import uuid

import pytest
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from common import make_model

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend, StateBackend

needs_llm = pytest.mark.skipif(
    os.environ.get("RUN_LLM_TESTS") != "1",
    reason="需要 DeepSeek API Key，设置 RUN_LLM_TESTS=1 开启",
)


@needs_llm
def test_execute_tool_only_with_sandbox_protocol():
    task = "用 execute 工具运行 `echo ok`，告诉我输出。"
    plain = create_deep_agent(model=make_model(), backend=StateBackend(),
                              system_prompt="如实汇报可用能力。")
    r1 = plain.invoke({"messages": [{"role": "user", "content": task}]})
    assert not any(tc["name"] == "execute" for m in r1["messages"]
                   for tc in (getattr(m, "tool_calls", None) or []))

    root = tempfile.mkdtemp(prefix="sbx_it_")
    sbx = create_deep_agent(
        model=make_model(),
        backend=LocalShellBackend(root_dir=root, virtual_mode=True, inherit_env=False),
        system_prompt="你是编码助手。")
    r2 = sbx.invoke({"messages": [{"role": "user", "content": task}]})
    assert any(tc["name"] == "execute" for m in r2["messages"]
               for tc in (getattr(m, "tool_calls", None) or []))
    assert "ok" in r2["messages"][-1].content


@needs_llm
def test_two_planes_roundtrip():
    root = tempfile.mkdtemp(prefix="sbx_tp_")
    backend = LocalShellBackend(root_dir=root, virtual_mode=True, inherit_env=False)
    backend.upload_files([("/data/n.json", b'{"nums": [1, 2, 3]}')])
    agent = create_deep_agent(
        model=make_model(), backend=backend,
        system_prompt="读 /data/n.json，统计总和，把 'total=<数值>' 写入 /out/t.txt。")
    agent.invoke({"messages": [{"role": "user", "content": "请完成统计并写结果文件。"}]})
    res = backend.download_files(["/out/t.txt"])
    assert res[0].content is not None
    assert b"total=6" in res[0].content


@needs_llm
def test_execute_hitl_reject_prevents_side_effect():
    root = tempfile.mkdtemp(prefix="sbx_hr_")
    backend = LocalShellBackend(root_dir=root, virtual_mode=True, inherit_env=False)
    backend.write("/keep.txt", "v")
    agent = create_deep_agent(
        model=make_model(), backend=backend,
        interrupt_on={"execute": {"allowed_decisions": ["approve", "reject"]}},
        checkpointer=MemorySaver(),
        system_prompt="你是运维助手。")
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    r = agent.invoke({"messages": [{"role": "user", "content":
        "用 execute 运行 `rm keep.txt`。"}]}, config=cfg, version="v2")
    assert r.interrupts
    agent.invoke(Command(resume={"decisions": [
        {"type": "reject", "message": "不许删"}]}), config=cfg, version="v2")
    assert backend.read("/keep.txt").error is None
