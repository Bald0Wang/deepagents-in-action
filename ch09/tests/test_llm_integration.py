"""LLM 集成测试（RUN_LLM_TESTS=1）：interrupt_on 四决策 / when / 批量 / 子 Agent。"""

import os
import uuid

import pytest
from langchain.agents.middleware import ToolCallRequest
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from common import make_model

from deepagents import FilesystemPermission, create_deep_agent

needs_llm = pytest.mark.skipif(
    os.environ.get("RUN_LLM_TESTS") != "1",
    reason="需要 DeepSeek API Key，设置 RUN_LLM_TESTS=1 开启",
)


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """发送邮件。"""
    return f"邮件已发送至 {to}（主题：{subject}）"


@tool
def save_file(path: str, content: str) -> str:
    """保存文件到指定路径。"""
    return f"wrote {path}"


def cfg():
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


@needs_llm
def test_approve_executes_original_args():
    agent = create_deep_agent(
        model=make_model(), tools=[send_email],
        interrupt_on={"send_email": {"allowed_decisions": ["approve", "edit", "reject"]}},
        checkpointer=MemorySaver(),
    )
    c = cfg()
    r = agent.invoke({"messages": [{"role": "user", "content":
        "给 boss@corp.com 发主题'周报'、正文'x' 的邮件。"}]}, config=c, version="v2")
    assert r.interrupts
    ar = r.interrupts[0].value["action_requests"][0]
    assert ar["name"] == "send_email"
    r2 = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=c, version="v2")
    sent = [m.content for m in r2.value["messages"] if m.type == "tool"]
    assert any("boss@corp.com" in str(x) for x in sent)


@needs_llm
def test_edit_changes_executed_args():
    agent = create_deep_agent(
        model=make_model(), tools=[send_email],
        interrupt_on={"send_email": {"allowed_decisions": ["approve", "edit", "reject"]}},
        checkpointer=MemorySaver(),
        system_prompt="审批结果即最终事实，不要重复操作。",
    )
    c = cfg()
    r = agent.invoke({"messages": [{"role": "user", "content":
        "给 all@corp.com 发主题'通知'、正文'x' 的邮件。"}]}, config=c, version="v2")
    ar = r.interrupts[0].value["action_requests"][0]
    orig = ar.get("arguments") or ar.get("args")
    r2 = agent.invoke(Command(resume={"decisions": [{
        "type": "edit",
        "edited_action": {"name": ar["name"], "args": {**orig, "to": "team@corp.com"}},
    }]}), config=c, version="v2")
    sent = [str(m.content) for m in r2.value["messages"] if m.type == "tool"]
    assert any("team@corp.com" in x and "已发送" in x for x in sent)


@needs_llm
def test_reject_blocks_execution_with_feedback():
    agent = create_deep_agent(
        model=make_model(), tools=[send_email],
        interrupt_on={"send_email": {"allowed_decisions": ["approve", "reject"]}},
        checkpointer=MemorySaver(),
        system_prompt="被拒操作不要重试。",
    )
    c = cfg()
    agent.invoke({"messages": [{"role": "user", "content":
        "给 hr@corp.com 发主题'投诉'的邮件。"}]}, config=c, version="v2")
    r2 = agent.invoke(Command(resume={"decisions": [
        {"type": "reject", "message": "先当面沟通，不要发送"}]}), config=c, version="v2")
    assert not any("邮件已发送" in str(m.content)
                   for m in r2.value["messages"] if m.type == "tool")


@needs_llm
def test_when_predicate_scopes_interrupt():
    def outside(request: ToolCallRequest) -> bool:
        return not request.tool_call["args"].get("path", "").startswith("/workspace/")

    agent = create_deep_agent(
        model=make_model(), tools=[save_file],
        interrupt_on={"save_file": {"allowed_decisions": ["approve", "reject"], "when": outside}},
        checkpointer=MemorySaver(),
        system_prompt="所有文件保存必须通过 save_file 工具完成，无论路径在哪都不要自行拒绝。",
    )
    c = cfg()
    r1 = agent.invoke({"messages": [{"role": "user", "content":
        "用 save_file 把 'a' 保存到 /workspace/a.txt"}]}, config=c, version="v2")
    assert not getattr(r1, "interrupts", None)          # 安全调用放行
    r2 = agent.invoke({"messages": [{"role": "user", "content":
        "用 save_file 把 'x' 保存到 /outside/hosts"}]}, config=c, version="v2")
    assert r2.interrupts                                  # 危险调用拦截（工作区外）


@needs_llm
def test_batch_and_subagent_and_permission():
    # 子 Agent 更严格 + 权限中断合并（合在一个用例控制成本）
    @tool
    def read_secret(path: str) -> str:
        """读取文件内容。"""
        return f"[{path}] SECRET-DATA"

    agent = create_deep_agent(
        model=make_model(), tools=[read_secret],
        interrupt_on={"read_secret": False},
        subagents=[{
            "name": "auditor", "description": "读取敏感文件并汇报",
            "system_prompt": "你是审计员，用 read_secret 读取并汇报。",
            "tools": [read_secret],
            "interrupt_on": {"read_secret": {"allowed_decisions": ["approve", "reject"]}},
        }],
        permissions=[FilesystemPermission(operations=["write"], paths=["/secrets/**"], mode="interrupt")],
        checkpointer=MemorySaver(),
    )
    c = cfg()
    r = agent.invoke({"messages": [{"role": "user", "content":
        "委派给 auditor：读取 /secrets/api.txt 并汇报。"}]}, config=c, version="v2")
    assert r.interrupts
    r2 = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=c, version="v2")
    assert "SECRET-DATA" in r2.value["messages"][-1].content

    r3 = agent.invoke({"messages": [{"role": "user", "content":
        "用 write_file 把 'r' 写入 /secrets/api.txt。"}]}, config=c, version="v2")
    assert r3.interrupts                                  # 权限规则触发（与 interrupt_on 合并）
    r4 = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=c, version="v2")
    assert any("Updated file /secrets/api.txt" in str(m.content)
               for m in r4.value["messages"] if m.type == "tool")
