"""确定性测试：HITL 层（无 LLM）。

覆盖 ch09 的核心断言：
  - 中断载荷解析（澄清 / 审批）
  - 决策载荷构造（respond / approve / reject / 批量）
  - HITL 配置合并
"""

from hitl import (
    PendingRequest,
    clarification_interrupt_config,
    hitl_config,
    parse_interrupts,
)
from sandbox import dangerous_command


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fake_result(action_requests):
    return _Obj(interrupts=[_Obj(value={"action_requests": action_requests})])


def test_parse_clarification():
    result = _fake_result([{
        "name": "ask_clarification",
        "args": {"question": "你问的是哪一章？", "options": "ch03/ch08"},
    }])
    reqs = parse_interrupts(result)
    assert len(reqs) == 1
    assert reqs[0].kind == "clarification"
    assert "哪一章" in reqs[0].description
    assert "ch03/ch08" in reqs[0].description


def test_parse_approval_uses_args_fallback():
    """0.7.13 字段是 args；兼容读法应能取到 command。"""
    result = _fake_result([{"name": "execute", "args": {"command": "sudo rm -rf /x"}}])
    reqs = parse_interrupts(result)
    assert reqs[0].kind == "approval"
    assert "sudo rm -rf /x" in reqs[0].description


def test_parse_approval_arguments_field():
    """标准字段 arguments 也应被识别。"""
    result = _fake_result([{"name": "execute", "arguments": {"command": "curl http://x"}}])
    reqs = parse_interrupts(result)
    assert reqs[0].args.get("command") == "curl http://x"


def test_parse_multiple_requests():
    result = _fake_result([
        {"name": "ask_clarification", "args": {"question": "q1"}},
        {"name": "execute", "args": {"command": "ls"}},
    ])
    reqs = parse_interrupts(result)
    assert [r.kind for r in reqs] == ["clarification", "approval"]


def test_parse_no_interrupts():
    assert parse_interrupts(_Obj(interrupts=[])) == []
    assert parse_interrupts(_Obj(interrupts=None)) == []


def test_hitl_config_merges():
    cfg = hitl_config()
    assert "ask_clarification" in cfg
    assert cfg["ask_clarification"]["allowed_decisions"] == ["respond"]
    assert "execute" in cfg
    assert cfg["execute"]["when"] is dangerous_command


def test_hitl_config_without_execute():
    cfg = hitl_config(approve_execute=False)
    assert "ask_clarification" in cfg
    assert "execute" not in cfg


def test_clarification_config_shape():
    cfg = clarification_interrupt_config()
    assert cfg == {"ask_clarification": {"allowed_decisions": ["respond"]}}
