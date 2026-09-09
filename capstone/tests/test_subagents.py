"""确定性测试：子 Agent 与路由（无 LLM）。

覆盖 ch05/ch07 的核心断言：
  - ch02-ch10 每章一个子 Agent
  - description 具体（含章节号与关键词）
  - 子 Agent 不指定 tools（继承语义）
  - 子 Agent 独立 HITL
  - 路由表覆盖全部章节
"""

import yaml

from config import CHAPTERS, SKILLS_SRC
from subagents import build_all_subagents, build_chapter_subagent, routing_prompt


def test_one_subagent_per_chapter():
    subs = build_all_subagents()
    assert len(subs) == len(CHAPTERS) == 9
    assert [s["name"] for s in subs] == [f"{c.key}-ta" for c in CHAPTERS]


def test_descriptions_are_specific():
    """ch05：description 要具体——含章节号、标题与能力摘要关键词。"""
    for sub, chapter in zip(build_all_subagents(), CHAPTERS):
        desc = sub["description"]
        assert chapter.key in desc
        assert chapter.title in desc
        assert len(desc) > 40


def test_subagents_inherit_tools():
    """ch05：不指定 tools → 继承主 Agent 工具。"""
    for sub in build_all_subagents():
        assert "tools" not in sub


def test_subagent_system_prompt_points_to_knowledge():
    for sub, chapter in zip(build_all_subagents(), CHAPTERS):
        assert chapter.knowledge in sub["system_prompt"]
        # 要求「只依据知识库、不臆造」
        assert "知识库" in sub["system_prompt"]


def test_subagent_has_independent_hitl():
    """ch09：子 Agent 的 interrupt_on 不继承主 Agent，需单独配置。"""
    for sub in build_all_subagents():
        assert "ask_clarification" in sub["interrupt_on"]
        assert "execute" in sub["interrupt_on"]


def test_subagent_without_hitl():
    sub = build_chapter_subagent(CHAPTERS[0], hitl=False)
    assert "interrupt_on" not in sub


def test_routing_prompt_covers_all_chapters():
    prompt = routing_prompt()
    for c in CHAPTERS:
        assert c.key in prompt
        assert f"{c.key}-ta" in prompt


def test_knowledge_map_skill_spec():
    """ch07 规范：frontmatter / name 与目录名一致 / description 非空且有界。"""
    skill_dir = SKILLS_SRC / "knowledge-map"
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---")
    _, frontmatter, body = text.split("---", 2)
    meta = yaml.safe_load(frontmatter)
    assert meta["name"] == skill_dir.name == "knowledge-map"
    assert 1 <= len(meta["name"]) <= 64
    assert meta["description"].strip()
    assert len(meta["description"]) <= 1024
    # 三级结构：references/ 与 assets/ 存在
    assert (skill_dir / "references" / "graph-design.md").exists()
    assert (skill_dir / "assets" / "knowledge-graph.mmd").exists()
    assert (skill_dir / "assets" / "mindmap.mmd").exists()
    assert "Instructions" in body
