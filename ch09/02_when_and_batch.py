# ============================================================================
# 02_when_and_batch.py —— ch09 段2：条件中断 + 批量工具调用
#
#   Part A: when 谓词 —— 只拦截真正危险的调用（工作区外写入才暂停），
#           安全调用自动放行（审批界面不出现噪音）
#   Part B: 批量打包 —— 一次任务触发多个敏感工具时，中断合并成一个批次，
#           decisions 按顺序一一对应（approve 一个、reject 一个）
# ============================================================================

import uuid

from langchain.agents.middleware import ToolCallRequest
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from common import make_model, preview

from deepagents import create_deep_agent


@tool
def save_file(path: str, content: str) -> str:
    """保存文件到指定路径。"""
    return f"wrote {path}"


@tool
def delete_file(path: str) -> str:
    """删除文件。"""
    return f"已删除 {path}"


@tool
def send_email(to: str, subject: str) -> str:
    """发邮件。"""
    return f"已发送至 {to}"


def part_a_when_predicate():
    print("=" * 60)
    print("Part A: when 谓词 —— 只拦截工作区外的写入")
    print("=" * 60)

    def writes_outside_workspace(request: ToolCallRequest) -> bool:
        """只有写入工作区外的路径时才暂停。"""
        path = request.tool_call["args"].get("path", "")
        return not path.startswith("/workspace/")

    agent = create_deep_agent(
        model=make_model(),
        tools=[save_file],
        interrupt_on={
            "save_file": {
                "allowed_decisions": ["approve", "reject"],
                "when": writes_outside_workspace,
            },
        },
        checkpointer=MemorySaver(),
    )
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}

    # 安全调用：/workspace/ 内 → when 返回 False → 自动放行，不中断
    r1 = agent.invoke({"messages": [{"role": "user", "content": "用 save_file 把 'a' 保存到 /workspace/a.txt"}]},
                      config=cfg, version="v2")
    print(f"  工作区内写入被中断: {bool(getattr(r1, 'interrupts', None))}（期望 False，直接放行）")
    done = any("wrote /workspace/a.txt" in str(m.content)
               for m in r1.value["messages"] if m.type == "tool")
    print(f"  文件已实际写入: {done}")

    # 危险调用：/etc/ 下 → when 返回 True → 中断
    r2 = agent.invoke({"messages": [{"role": "user", "content": "用 save_file 把 'x' 保存到 /etc/hosts"}]},
                      config=cfg, version="v2")
    print(f"  工作区外写入被中断: {bool(r2.interrupts)}（期望 True）")
    if r2.interrupts:
        r3 = agent.invoke(Command(resume={"decisions": [{
            "type": "reject", "message": "系统文件禁止修改",
        }]}), config=cfg, version="v2")
        never = not any("wrote /etc/hosts" in str(m.content)
                        for m in r3.value["messages"] if m.type == "tool")
        print(f"  /etc/hosts 未被写入: {never}")
        print(f"  Agent 回复: {preview(r3.value['messages'][-1].content, 90)}")


def part_b_batch_interrupts():
    print()
    print("=" * 60)
    print("Part B: 批量打包 —— 多个敏感调用合并成一个中断批次")
    print("=" * 60)
    agent = create_deep_agent(
        model=make_model(),
        tools=[delete_file, send_email],
        interrupt_on={
            "delete_file": {"allowed_decisions": ["approve", "reject"]},
            "send_email": {"allowed_decisions": ["approve", "reject"]},
        },
        checkpointer=MemorySaver(),
        system_prompt="一次任务内的多个操作并行发起；审批结果是最终事实。",
    )
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    r = agent.invoke({"messages": [{"role": "user", "content": (
        "同时做两件事：删除 /tmp/old.log，然后给 admin@x.com 发主题'清理完成'的邮件。一次任务里完成。"
    )}]}, config=cfg, version="v2")

    if not r.interrupts:
        print("  ⚠ 模型未发起任何敏感调用，本次未触发中断")
        return
    ars = r.interrupts[0].value["action_requests"]
    print(f"  进入审批批次的调用: {len(ars)} → {[a['name'] for a in ars]}")

    # decisions 必须按 action_requests 动态构造、一一对应：
    # delete_file → approve；send_email → reject（附原因）
    decisions = [
        {"type": "approve"} if a["name"] == "delete_file"
        else {"type": "reject", "message": "先不发邮件，等确认后再说"}
        for a in ars
    ]
    r2 = agent.invoke(Command(resume={"decisions": decisions}), config=cfg, version="v2")
    tools_out = [str(m.content) for m in r2.value["messages"] if m.type == "tool"]
    deleted = any("已删除 /tmp/old.log" in c for c in tools_out)
    emailed = any("已发送至 admin@x.com" in c for c in tools_out)
    batched = len(ars) > 1
    print(f"  {'✅ 多调用合并为一个批次' if batched else '（本次模型串行发起，仅 1 个调用进入批次）'}")
    print(f"  删除已执行: {deleted} | 邮件未发送: {not emailed}")
    print(f"  最终回复: {preview(r2.value['messages'][-1].content, 110)}")
    print("  要点：decisions 数量/顺序必须与 action_requests 一一对应（错配直接 ValueError）")


if __name__ == "__main__":
    part_a_when_predicate()
    part_b_batch_interrupts()
