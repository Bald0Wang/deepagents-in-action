"""LLM 集成测试（需 DeepSeek Key，RUN_LLM_TESTS=1 开启）。

覆盖：三级渐进式加载 / description 误触发与精准匹配 / last-wins /
deny 只读 / interrupt 审批流 / 子 Agent 继承自报。
"""

import os
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from common import make_model

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import FilesystemBackend

CH07 = Path(__file__).resolve().parent.parent
CODE = "```python\ndef div(a, b):\n    return a / b\n```"
ORIGINAL_TEAM_REPORT = (CH07 / "skills/team-report/SKILL.md").read_text()

needs_llm = pytest.mark.skipif(
    os.environ.get("RUN_LLM_TESTS") != "1",
    reason="需要 DeepSeek API Key，设置 RUN_LLM_TESTS=1 开启",
)


def make_agent(**kwargs):
    base = dict(
        model=make_model(),
        backend=FilesystemBackend(root_dir=str(CH07), virtual_mode=True),
    )
    base.update(kwargs)
    return create_deep_agent(**base)


def read_paths(r):
    return [str(tc["args"].get("file_path", ""))
            for m in r["messages"] for tc in (getattr(m, "tool_calls", None) or [])]


@needs_llm
def test_three_level_progressive_disclosure():
    agent = make_agent(skills=["/skills/"])
    r = agent.invoke({"messages": [{"role": "user", "content": f"请审查这段代码：{CODE}"}]})
    paths = read_paths(r)
    assert any(p.endswith("/skills/code-review/SKILL.md") for p in paths), "Level 2 未发生"
    assert any("references/checklist.md" in p for p in paths), "Level 3 references 未读"
    assert any("assets/report-template.md" in p for p in paths), "Level 3 assets 未读"
    # 模板遵循（模型可能加一句导语，用包含式判断）
    assert "# 代码审查报告" in r["messages"][-1].content
    assert "评分总览" in r["messages"][-1].content


@needs_llm
def test_unrelated_query_does_not_activate():
    agent = make_agent(skills=["/skills/"])
    r = agent.invoke({"messages": [{"role": "user", "content": "1 加 1 等于几？直接回答。"}]})
    assert not any(p.endswith("SKILL.md") for p in read_paths(r))


@needs_llm
def test_last_wins_project_overrides_shared():
    agent = make_agent(skills=["/skills_shared/", "/skills_project/"])
    r = agent.invoke({"messages": [{"role": "user", "content": f"请审查这段代码：{CODE}"}]})
    paths = read_paths(r)
    assert any("skills_project/code-review/SKILL.md" in p for p in paths)
    assert "PROJECT-VERSION" in r["messages"][-1].content


@needs_llm
def test_deny_keeps_skills_readonly():
    agent = make_agent(
        skills=["/skills/"],
        permissions=[FilesystemPermission(operations=["write"], paths=["/skills/**"], mode="deny")],
        checkpointer=MemorySaver(),
    )
    r = agent.invoke(
        {"messages": [{"role": "user", "content":
            "读取 /skills/team-report/SKILL.md 复述第 3 条规则；"
            "然后尝试用 write_file 把「15 字」改成「20 字」，报告结果。"}]},
        config={"configurable": {"thread_id": "t-deny"}},
    )
    assert any(p.endswith("SKILL.md") for p in read_paths(r))       # 读得进
    assert (CH07 / "skills/team-report/SKILL.md").read_text() == ORIGINAL_TEAM_REPORT  # 写不进


@needs_llm
def test_interrupt_approve_and_reject():
    agent = make_agent(
        skills=["/skills/"],
        permissions=[FilesystemPermission(operations=["write"], paths=["/skills/**"], mode="interrupt")],
        checkpointer=MemorySaver(),
    )
    skill_path = CH07 / "skills/team-report/SKILL.md"
    try:
        # approve 分支
        cfg = {"configurable": {"thread_id": "t-appr"}}
        agent.invoke(
            {"messages": [{"role": "user", "content":
                f"用 write_file 修改 /skills/team-report/SKILL.md，把「不超过 15 字」改成「不超过 20 字」。"}]},
            config=cfg,
        )
        snap = agent.get_state(cfg)
        assert snap.next, "应已暂停等待审批"
        agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=cfg)
        assert "不超过 20 字" in skill_path.read_text(), "批准后应落盘"
    finally:
        skill_path.write_text(ORIGINAL_TEAM_REPORT)

    # reject 分支
    cfg2 = {"configurable": {"thread_id": "t-rej"}}
    agent.invoke(
        {"messages": [{"role": "user", "content":
            f"用 write_file 修改 /skills/team-report/SKILL.md，把「不超过 15 字」改成「不超过 99 字」。"}]},
        config=cfg2,
    )
    agent.invoke(Command(resume={"decisions": [{"type": "reject", "message": "需评审"}]}), config=cfg2)
    assert skill_path.read_text() == ORIGINAL_TEAM_REPORT, "拒绝后文件不应变化"


@needs_llm
def test_gp_subagent_inherits_skills():
    agent = make_agent(skills=["/skills/"])
    r = agent.invoke({"messages": [{"role": "user", "content": (
        "把这个任务委派给 general-purpose 子 Agent：审查代码 " + CODE +
        "。请子 Agent 在汇报第一行回答：系统提示词里有没有 Skills 列表（有的话列出技能名）。"
    )}]})
    tool_text = " ".join(str(m.content) for m in r["messages"] if m.type == "tool")
    assert "有" in tool_text[:80] and ("code-review" in tool_text or "team-report" in tool_text)
