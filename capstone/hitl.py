# ============================================================================
# hitl.py —— Human-in-the-Loop 层（对应 ch09）
#
# 作业要求「HITL 对于不清晰的问题让用户补充提问」，本项目用两种机制实现：
#
#   1. 澄清提问（ask_clarification 工具 + respond 决策）
#      问题不清晰时，Agent 调用 ask_clarification，执行流暂停；
#      用户补充信息后，用 Command(resume={"decisions": [{"type": "respond",
#      "message": "..."}]}) 恢复，人的回答直接成为工具结果（ch09 实验D）。
#
#   2. 危险操作审批（execute / 写受保护路径）
#      execute 命中危险模式时中断，用户 approve / reject（ch09 实验A/C）。
#
# 关键 API 事实（ch09 实测，deepagents 0.7.13）：
#   - invoke(..., version="v2") 返回对象，中断在 result.interrupts[0].value；
#   - value = {"action_requests": [{name, args, ...}], "review_configs": [...]}
#   - 恢复：agent.invoke(Command(resume={"decisions": [...]}), config=cfg, version="v2")
#   - decisions 数量/顺序必须与 action_requests 一一对应；
#   - 恢复时节点会重放，副作用要么幂等、要么放在 interrupt 之后。
# ============================================================================

"""HITL 层：澄清追问（respond）+ 危险操作审批（approve/reject）。"""

from dataclasses import dataclass

from langchain.tools import tool
from langgraph.types import Command

from deepagents import create_deep_agent

from common import preview
from sandbox import execute_interrupt_config


# ---------------------------------------------------------------------------
# 一、澄清工具：不清晰的问题先问用户（ch09 实验D 的 ask_user 模式）
# ---------------------------------------------------------------------------
@tool
def ask_clarification(question: str, options: str = "") -> str:
    """向用户提出澄清问题，等待用户补充信息后再继续。

    当用户的问题缺少关键信息（例如：问的是哪一章？哪种后端？具体报错是什么？）
    导致无法给出准确回答时调用本工具。一次只问最关键的 1 个问题。

    Args:
        question: 要问用户的问题，要具体、可回答。
        options: 可选的候选项，用「/」分隔，例如 "StateBackend/StoreBackend"。
    """
    # 真实回答由 HITL 的 respond 决策提供（人的回答成为本工具的返回值）
    return "等待用户补充信息……"


def clarification_interrupt_config() -> dict:
    """``ask_clarification`` 的 HITL 配置：只允许 respond 决策。"""
    return {"ask_clarification": {"allowed_decisions": ["respond"]}}


# ---------------------------------------------------------------------------
# 二、合并 HITL 配置：澄清 + 执行审批
# ---------------------------------------------------------------------------
def hitl_config(*, approve_execute: bool = True) -> dict:
    """合并本项目的 HITL 配置。

    Args:
        approve_execute: True 时对危险 execute 触发审批（由 when 谓词过滤）。

    Returns:
        传给 ``create_deep_agent(interrupt_on=...)`` 的配置。
    """
    config: dict = clarification_interrupt_config()
    if approve_execute:
        config.update(execute_interrupt_config())
    return config


# ---------------------------------------------------------------------------
# 三、审批/澄清请求的解析辅助（宿主平面，便于 CLI 与测试）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PendingRequest:
    """一个待处理的中断请求。"""

    kind: str          # "clarification" | "approval" | "unknown"
    tool_name: str     # 触发中断的工具名
    args: dict         # 工具参数
    description: str   # 展示给用户的可读描述


def _get_args(action_request: dict) -> dict:
    """字段兼容：arguments（LangChain 标准）回退 args（0.7.13 实际字段）。"""
    return action_request.get("arguments") or action_request.get("args") or {}


def parse_interrupts(result) -> list[PendingRequest]:
    """从 ``version="v2"`` 的 invoke 结果里解析待处理请求。

    对应 ch09：中断信息在 ``result.interrupts[0].value["action_requests"]``。
    """
    requests: list[PendingRequest] = []
    for interrupt_obj in (getattr(result, "interrupts", None) or []):
        value = getattr(interrupt_obj, "value", interrupt_obj)
        if not isinstance(value, dict):
            continue
        for action in value.get("action_requests", []) or []:
            name = action.get("name", "?")
            args = _get_args(action)
            if name == "ask_clarification":
                kind = "clarification"
                desc = args.get("question", "")
                options = args.get("options") or ""
                if options:
                    desc = f"{desc}（可选：{options}）"
            elif name == "execute":
                kind = "approval"
                desc = f"请求执行命令：{args.get('command', '')}"
            else:
                kind = "approval"
                desc = f"请求调用 {name}：{preview(str(args), 120)}"
            requests.append(PendingRequest(kind=kind, tool_name=name, args=args, description=desc))
    return requests


def resume_with_answer(agent, cfg: dict, message: str):
    """用 ``respond`` 决策恢复（回答澄清问题）。"""
    return agent.invoke(
        Command(resume={"decisions": [{"type": "respond", "message": message}]}),
        config=cfg,
        version="v2",
    )


def resume_with_decision(agent, cfg: dict, *, approve: bool, message: str = "") -> object:
    """用 ``approve`` / ``reject`` 决策恢复（审批执行请求）。"""
    decision: dict = {"type": "approve"} if approve else {"type": "reject"}
    if message:
        decision["message"] = message
    return agent.invoke(
        Command(resume={"decisions": [decision]}),
        config=cfg,
        version="v2",
    )


def resume_batch(agent, cfg: dict, decisions: list[dict]) -> object:
    """按顺序提交多个决策（对应 ch09 的批量中断：数量/顺序必须一一对应）。"""
    return agent.invoke(Command(resume={"decisions": decisions}), config=cfg, version="v2")


# ---------------------------------------------------------------------------
# 四、离线演示（无需模型：直接构造并解析一个中断载荷）
# ---------------------------------------------------------------------------
def demo_offline() -> None:
    """离线演示中断载荷的解析（用轻量对象模拟 result.interrupts）。"""
    print("=" * 60)
    print("HITL 离线演示：中断载荷解析")
    print("=" * 60)

    class _Obj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    fake = _Obj(interrupts=[
        _Obj(value={"action_requests": [
            {"name": "ask_clarification",
             "args": {"question": "你问的是哪种后端？", "options": "StateBackend/StoreBackend"}},
            {"name": "execute", "args": {"command": "rm -rf /tmp/x"}},
        ]})
    ])
    for req in parse_interrupts(fake):
        print(f"  [{req.kind}] {req.tool_name} → {req.description}")


if __name__ == "__main__":
    demo_offline()
