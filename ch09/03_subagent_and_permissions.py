# ============================================================================
# 03_subagent_and_permissions.py —— ch09 段3：子 Agent 独立配置 + 权限中断合并
#
#   Part A: 子 Agent 更严格 —— 主 Agent 读文件不拦（False），
#           子 Agent 读同一文件要审批（独立 interrupt_on 覆盖）
#   Part B: 文件系统权限中断 —— FilesystemPermission(mode="interrupt")
#           与 interrupt_on 合并：一次人工审查同时覆盖自定义工具 + 受保护路径
# ============================================================================

import uuid

from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from common import make_model, preview

from deepagents import FilesystemPermission, create_deep_agent


@tool
def read_secret(path: str) -> str:
    """读取文件内容。"""
    return f"[{path}] 的内容：SECRET-DATA-1234"


def part_a_subagent_stricter():
    print("=" * 60)
    print("Part A: 子 Agent 更严格（主宽松 / 子严格）")
    print("=" * 60)
    agent = create_deep_agent(
        model=make_model(),
        tools=[read_secret],
        interrupt_on={"read_secret": False},          # 主 Agent：读不拦
        subagents=[{
            "name": "auditor",
            "description": "读取敏感文件并汇报",
            "system_prompt": "你是审计员，用 read_secret 读取指定路径并原样汇报内容。",
            "tools": [read_secret],
            "interrupt_on": {                          # 子 Agent：读要审批
                "read_secret": {"allowed_decisions": ["approve", "reject"]},
            },
        }],
        checkpointer=MemorySaver(),
    )

    # 对照1：主 Agent 自己读 → 不中断
    cfg1 = {"configurable": {"thread_id": str(uuid.uuid4())}}
    r1 = agent.invoke({"messages": [{"role": "user", "content":
        "你自己直接读 /secrets/api.txt 并汇报（不要委派）。"}]}, config=cfg1, version="v2")
    print(f"  主 Agent 读取被中断: {bool(getattr(r1, 'interrupts', None))}（期望 False）")

    # 对照2：委派给子 Agent 读 → 中断
    cfg2 = {"configurable": {"thread_id": str(uuid.uuid4())}}
    r2 = agent.invoke({"messages": [{"role": "user", "content":
        "把这个任务委派给 auditor：读取 /secrets/api.txt 并汇报内容。"}]}, config=cfg2, version="v2")
    print(f"  子 Agent 读取被中断: {bool(r2.interrupts)}（期望 True）")
    if r2.interrupts:
        names = [a["name"] for a in r2.interrupts[0].value["action_requests"]]
        print(f"  中断动作: {names}")
        # approve 后子 Agent 完成
        r3 = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}),
                          config=cfg2, version="v2")
        ok = "SECRET-DATA-1234" in r3.value["messages"][-1].content
        print(f"  批准后拿到密文内容: {ok}")
        print(f"  汇报预览: {preview(r3.value['messages'][-1].content, 90)}")


def part_b_permission_interrupt_merged():
    print()
    print("=" * 60)
    print("Part B: 文件系统权限中断（与 interrupt_on 合并）")
    print("=" * 60)
    agent = create_deep_agent(
        model=make_model(),
        tools=[read_secret],
        # 两条防线合并：自定义工具走 interrupt_on；/secrets/** 的写入走权限 interrupt
        interrupt_on={"read_secret": False},
        permissions=[
            FilesystemPermission(operations=["write"], paths=["/secrets/**"], mode="interrupt"),
        ],
        checkpointer=MemorySaver(),
        system_prompt="你是运维助手，按指令操作文件并汇报结果。",
    )
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}

    # 1) 读 /secrets/ 下的文件：interrupt_on=False → 不拦
    r1 = agent.invoke({"messages": [{"role": "user", "content":
        "read_file /secrets/api.txt 然后汇报内容。"}]}, config=cfg, version="v2")
    print(f"  读取 /secrets/ 被中断: {bool(getattr(r1, 'interrupts', None))}（interrupt_on=False，期望 False）")

    # 2) 写 /secrets/ 下的文件：命中权限规则 mode=interrupt → 拦
    r2 = agent.invoke({"messages": [{"role": "user", "content":
        "用 write_file 把 'rotated' 写入 /secrets/api.txt。"}]}, config=cfg, version="v2")
    print(f"  写入 /secrets/ 被中断: {bool(r2.interrupts)}（权限规则，期望 True）")
    if r2.interrupts:
        ars = r2.interrupts[0].value["action_requests"]
        print(f"  中断动作（与 interrupt_on 同格式）: {[a['name'] for a in ars]}")
        r3 = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}),
                          config=cfg, version="v2")
        written = any("Updated file /secrets/api.txt" in str(m.content)
                      for m in r3.value["messages"] if m.type == "tool")
        print(f"  批准后写入完成: {written}")


if __name__ == "__main__":
    part_a_subagent_stricter()
    part_b_permission_interrupt_merged()
