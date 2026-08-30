# ============================================================================
# 01_progressive_disclosure.py —— ch07 段1：Skills 是什么 + Progressive Disclosure
#
#   Part A: 三级加载验证 —— 用工具调用序列证明：
#     Level 1（启动）：frontmatter 的 name+description 注入系统提示词
#     Level 2（匹配）：Agent 主动 read_file SKILL.md 正文
#     Level 3（按需）：正文引用到的 references/ 与 assets/ 才被读取
#   Part B: description 质量 —— 好 description（具体触发条件）vs
#     差 description（"帮助处理各种任务"）是否被激活
# ============================================================================

from pathlib import Path

from common import make_model, preview

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

ROOT = Path(__file__).parent.resolve()          # ch07 根目录 = Backend 根


def call_seq(r):
    """提取一次运行的工具调用序列（渐进式加载的证据就在这里）。"""
    return [(tc["name"], str(tc["args"].get("file_path", "")))
            for m in r["messages"] for tc in (getattr(m, "tool_calls", None) or [])]


def part_a_three_levels():
    print("=" * 60)
    print("Part A: 三级渐进式加载（工具调用序列为证）")
    print("=" * 60)
    backend = FilesystemBackend(root_dir=str(ROOT), virtual_mode=True)
    agent = create_deep_agent(
        model=make_model(),
        backend=backend,
        skills=["/skills/"],            # 路径相对 Backend 根 → ch07/skills/
    )
    r = agent.invoke({"messages": [{"role": "user", "content": (
        "请审查这段代码：\n```python\ndef div(a, b):\n    return a / b\n```"
    )}]})

    print("--- 工具调用序列（三级加载证据）---")
    for name, path in call_seq(r):
        level = "Level 2（读正文）" if path.endswith("SKILL.md") else \
                "Level 3（按需读资源）" if "/skills/" in path else ""
        print(f"  {name:<10} {path:<55} {level}")
    print("--- 回复是否遵循 Skill 模板 ---")
    reply = r["messages"][-1].content
    print(f"  以「# 代码审查报告」开头: {reply.lstrip().startswith('# 代码审查报告')}")
    print(f"  含四维评分表: {'正确性' in reply and '可维护性' in reply}")
    print(preview(reply, 150))


def part_b_description_quality():
    print()
    print("=" * 60)
    print("Part B: description 质量 —— 误触发与精准匹配")
    print("=" * 60)
    backend = FilesystemBackend(root_dir=str(ROOT), virtual_mode=True)

    # 实验1：模糊 description 的"乱触发"——只有它一个时，审查任务也会错误地用它
    only_bad = create_deep_agent(
        model=make_model(), backend=backend, skills=["/skills_bad/"],
    )
    r1 = only_bad.invoke({"messages": [{"role": "user", "content": (
        "请审查这段代码：```python\ndef div(a, b):\n    return a / b\n```"
    )}]})
    seq1 = call_seq(r1)
    print(f"  [实验1 模糊skill单独在场] 被误用于审查任务: "
          f"{any('vague-helper' in p for _, p in seq1)}（差 description 的问题是乱触发，不是不触发）")

    # 实验2：好差同场 —— 审查任务应选中 code-review 而不是 vague-helper
    both = create_deep_agent(
        model=make_model(), backend=backend,
        skills=["/skills/", "/skills_bad/"],
    )
    r2 = both.invoke({"messages": [{"role": "user", "content": (
        "请审查这段代码：```python\ndef div(a, b):\n    return a / b\n```"
    )}]})
    picked = [p for _, p in call_seq(r2) if p.endswith("SKILL.md")]
    print(f"  [实验2 好差同场] 审查任务选中: {picked}（期望 code-review）")

    # 实验3：无关问题 —— 好的 description 不应误触发
    r3 = both.invoke({"messages": [{"role": "user", "content": "1 加 1 等于几？直接回答。"}]})
    seq3 = call_seq(r3)
    print(f"  [实验3 无关问题] 未激活任何 Skill: {not any(p.endswith('SKILL.md') for _, p in seq3)}"
          f"（调用: {seq3 if seq3 else '无'}）")


if __name__ == "__main__":
    part_a_three_levels()
    part_b_description_quality()
