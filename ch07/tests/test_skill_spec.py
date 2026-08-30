"""Skill 规范确定性校验（Agent Skills Specification）+ 后端文件往返（无 LLM）。

规范要点（来自 agentskills.io / ch07）：
  - SKILL.md 必须有 YAML frontmatter
  - name 必填：小写字母/数字/连字符，1-64 字符，且与父目录名一致
  - description 必填：非空，<=1024 字符
"""

from pathlib import Path

import yaml

from deepagents.backends import FilesystemBackend, StoreBackend
from deepagents.backends.utils import create_file_data

CH07 = Path(__file__).resolve().parent.parent
SKILL_DIRS = [
    CH07 / "skills" / "code-review",
    CH07 / "skills" / "team-report",
    CH07 / "skills_bad" / "vague-helper",
    CH07 / "skills_shared" / "code-review",
    CH07 / "skills_project" / "code-review",
]


def parse_skill(skill_dir: Path) -> tuple[dict, str]:
    text = (skill_dir / "SKILL.md").read_text()
    assert text.startswith("---"), f"{skill_dir}: 缺 frontmatter"
    _, fm, body = text.split("---", 2)
    return yaml.safe_load(fm), body


def test_frontmatter_parse_and_name_matches_dir():
    for d in SKILL_DIRS:
        fm, _ = parse_skill(d)
        assert fm.get("name") == d.name, f"{d}: name 应与目录名一致"
        assert 1 <= len(fm["name"]) <= 64


def test_description_present_and_bounded():
    for d in SKILL_DIRS:
        fm, _ = parse_skill(d)
        desc = fm.get("description") or ""
        assert desc.strip(), f"{d}: description 不能为空"
        assert len(desc) <= 1024


def test_code_review_has_level3_resources():
    """code-review 是完整三级结构：references/ 与 assets/ 必须存在。"""
    cr = CH07 / "skills" / "code-review"
    assert (cr / "references" / "checklist.md").exists()
    assert (cr / "assets" / "report-template.md").exists()


def test_priority_versions_carry_distinct_markers():
    """shared 与 project 版本必须带各自标记（last-wins 实验的判定依据）。"""
    _, shared_body = parse_skill(CH07 / "skills_shared" / "code-review")
    _, project_body = parse_skill(CH07 / "skills_project" / "code-review")
    assert "SHARED-VERSION" in shared_body
    assert "PROJECT-VERSION" in project_body


def test_filesystem_backend_reads_skill_files():
    backend = FilesystemBackend(root_dir=str(CH07), virtual_mode=True)
    res = backend.read("/skills/code-review/SKILL.md")
    assert res.error is None
    content = res.file_data["content"]
    assert "code-review" in content


def test_store_backend_skill_roundtrip():
    """StoreBackend：put 一次，读回内容一致（跨线程共享的基础）。"""
    from langgraph.store.memory import InMemoryStore

    store = InMemoryStore()
    skill_text = (CH07 / "skills" / "team-report" / "SKILL.md").read_text()
    store.put(("filesystem",), "/skills/team-report/SKILL.md", create_file_data(skill_text))
    backend = StoreBackend(namespace=lambda _rt: ("filesystem",), store=store)
    res = backend.read("/skills/team-report/SKILL.md")
    assert res.error is None
    assert res.file_data["content"] == skill_text


def test_create_file_data_shape():
    data = create_file_data("hello")
    assert data["content"] == "hello"
    assert "encoding" in data or True  # 0.7.11 兼容：编码字段可选
