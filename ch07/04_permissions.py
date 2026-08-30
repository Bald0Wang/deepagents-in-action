# ============================================================================
# 04_permissions.py —— ch07 段4：Skill 权限控制
#
#   Part A: deny 模式 —— /skills/** 只读（读得到、写不进），企业知识库场景
#   Part B: interrupt 模式 —— 写 /skills/** 暂停等人工审批（人在回路）
#           演示完整审批流：触发 interrupt → 查看审批请求 → approve 落盘
#           以及 reject 分支：拒绝后文件未被修改
#
# interrupt resume 载荷格式（0.7.11 实测）：
#   Command(resume={"decisions": [{"type": "approve"} | {"type": "reject", "message": "...}]}])
# ============================================================================

from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from common import make_model, preview

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import FilesystemBackend

ROOT = Path(__file__).parent.resolve()
SKILL_PATH = "/skills/team-report/SKILL.md"
ORIGINAL = (ROOT / "skills/team-report/SKILL.md").read_text()      # 用于校验文件是否被改


def make_agent(mode: str):
    return create_deep_agent(
        model=make_model(),
        backend=FilesystemBackend(root_dir=str(ROOT), virtual_mode=True),
        skills=["/skills/"],
        permissions=[
            FilesystemPermission(operations=["write"], paths=["/skills/**"], mode=mode),
        ],
        checkpointer=MemorySaver(),      # interrupt 依赖 checkpointer
    )


def call_seq(r):
    return [(tc["name"], str(tc["args"])[:70])
            for m in r["messages"] for tc in (getattr(m, "tool_calls", None) or [])]


def part_a_deny():
    print("=" * 60)
    print("Part A: deny 模式 —— /skills/** 只读")
    print("=" * 60)
    agent = make_agent("deny")
    r = agent.invoke({"messages": [{"role": "user", "content": (
        "请做两件事并汇报各自结果：1) 读取 /skills/team-report/SKILL.md 并复述第一条规则；"
        f"2) 用 write_file 修改 {SKILL_PATH}，把「不超过 15 字」改成「不超过 20 字」。"
    )}]}, config={"configurable": {"thread_id": "skill-deny"}})
    for name, arg in call_seq(r):
        print(f"  {name:<11} {arg}")
    reply = r["messages"][-1].content
    print(f"  读取成功: {'不超过 15 字' in reply or '15 字' in reply}")
    print(f"  写入被拒: {'拒绝' in reply or 'denied' in reply.lower() or 'permission' in reply.lower()}")
    print(f"  磁盘文件未被修改: {(ROOT / 'skills/team-report/SKILL.md').read_text() == ORIGINAL}")


def part_b_interrupt():
    print()
    print("=" * 60)
    print("Part B: interrupt 模式 —— 写入需人工审批")
    print("=" * 60)
    agent = make_agent("interrupt")
    cfg = {"configurable": {"thread_id": "skill-approval"}}

    # 第一跳：Agent 尝试写 → 执行流暂停，invoke 返回（不阻塞）
    r1 = agent.invoke({"messages": [{"role": "user", "content": (
        f"请用 write_file 修改 {SKILL_PATH}，把「不超过 15 字」改成「不超过 20 字」，改完告诉我。"
    )}]}, config=cfg)
    snap = agent.get_state(cfg)
    print(f"  执行流已暂停（next={snap.next}）")
    # 0.7.11：审批请求在 state.tasks[*].interrupts[*].value，结构 {"action_requests": [...]}
    for t in snap.tasks:
        for it in (getattr(t, "interrupts", None) or []):
            req = it.value if hasattr(it, "value") else it
            actions = req.get("action_requests", []) if isinstance(req, dict) else []
            for a in actions:
                print(f"  审批请求: {a.get('name')} → {preview(str(a.get('args')), 90)}")

    # 审批人：批准 → 写入落盘
    r2 = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=cfg)
    changed = (ROOT / "skills/team-report/SKILL.md").read_text()
    print(f"  [approve 分支] 写入已落盘: {'不超过 20 字' in changed}")
    print(f"  Agent 汇报: {preview(r2['messages'][-1].content, 100)}")

    # 恢复原始文件，再演示 reject 分支
    (ROOT / "skills/team-report/SKILL.md").write_text(ORIGINAL)
    cfg2 = {"configurable": {"thread_id": "skill-reject"}}
    agent.invoke({"messages": [{"role": "user", "content": (
        f"请用 write_file 修改 {SKILL_PATH}，把「不超过 15 字」改成「不超过 99 字」，改完告诉我。"
    )}]}, config=cfg2)
    r3 = agent.invoke(Command(resume={"decisions": [{"type": "reject", "message": "改数字要经评审会"}]}), config=cfg2)
    unchanged = (ROOT / "skills/team-report/SKILL.md").read_text() == ORIGINAL
    print(f"  [reject 分支] 文件未被修改: {unchanged}")
    print(f"  Agent 汇报: {preview(r3['messages'][-1].content, 100)}")

    # 收尾：保证仓库文件还原
    (ROOT / "skills/team-report/SKILL.md").write_text(ORIGINAL)


if __name__ == "__main__":
    part_a_deny()
    part_b_interrupt()
