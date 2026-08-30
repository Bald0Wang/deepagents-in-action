# ============================================================================
# 03_subagent_inheritance.py —— ch07 段3：Skills 与子 Agent 的继承规则
#
#   实验A: general-purpose 子 Agent —— 自动继承主 Agent 的 Skills
#   实验B: 自定义子 Agent 不声明 skills —— 没有 Skills 系统（不继承）
#   实验C: 自定义子 Agent 显式声明 skills —— 有自己的 Skills 系统
#
# ⚠️ 判据说明（重要）：Skills 的"继承"指【系统提示词中的技能列表】是否注入，
#    不是文件能否读取——子 Agent 总有内置文件工具，能读到 backend 里的文件。
#    因此让子 Agent 自报"你的系统提示词里有没有 Skills 列表"，这才是准确判据。
# ============================================================================

from pathlib import Path

from common import make_model, preview

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

ROOT = Path(__file__).parent.resolve()
CODE = "```python\ndef div(a, b):\n    return a / b\n```"

# 主 Agent 的委派话术：只转述审查任务，绝不提示 /skills/ 路径（避免污染判据）
DELEGATE_TASK = (
    f"把这个任务委派完成：{CODE}\n"
    "先审查代码给出简短结论。另外请子 Agent 在汇报第一行明确回答："
    "「我的系统提示词里有 Skills 列表：有/无（有的话列出技能名）」。"
)

# 子 Agent 的自报规则（写进其 system_prompt）
REPORT_RULE = (
    "你的汇报第一行必须是：【技能列表自报】有/无。"
    "判断标准：你的系统提示词中是否出现了 Skills System / Available Skills 字样；"
    "注意：能用 read_file 读到某个文件不算有技能列表，只看系统提示词。"
)


def make_agent(subagents):
    return create_deep_agent(
        model=make_model(),
        backend=FilesystemBackend(root_dir=str(ROOT), virtual_mode=True),
        skills=["/skills/"],                 # 主 Agent 的 Skills
        subagents=subagents,
    )


def sub_reply(r):
    """提取 task 工具返回的子 Agent 汇报文本。"""
    for m in r["messages"]:
        if m.type == "tool":
            return str(m.content)
    return ""


def part_a_gp_inherits():
    print("=" * 60)
    print("实验A: general-purpose 子 Agent（期望：自动继承 → 有列表）")
    print("=" * 60)
    agent = make_agent(subagents=None)     # GP 默认可用
    r = agent.invoke({"messages": [{"role": "user", "content":
        "请把以下任务委派给 general-purpose 子 Agent 完成。\n" + DELEGATE_TASK}]})
    print(f"  子 Agent 自报: {preview(sub_reply(r), 120)}")


def part_b_custom_no_skills():
    print()
    print("=" * 60)
    print("实验B: 自定义子 Agent 未声明 skills（期望：无列表）")
    print("=" * 60)
    reviewer = {
        "name": "bare-reviewer",
        "description": "未配置任何 skills 的代码审查员",
        "system_prompt": "你是代码审查员。" + REPORT_RULE,
    }
    agent = make_agent(subagents=[reviewer])
    r = agent.invoke({"messages": [{"role": "user", "content":
        "请把以下任务委派给 bare-reviewer 完成。\n" + DELEGATE_TASK}]})
    print(f"  子 Agent 自报: {preview(sub_reply(r), 120)}")


def part_c_custom_own_skills():
    print()
    print("=" * 60)
    print("实验C: 自定义子 Agent 显式声明 skills（期望：有列表）")
    print("=" * 60)
    researcher = {
        "name": "skilled-reviewer",
        "description": "带专属技能的代码审查员",
        "system_prompt": "你是代码审查员。" + REPORT_RULE,
        "skills": ["/skills/"],              # 显式声明 → 独立 SkillsMiddleware
    }
    agent = make_agent(subagents=[researcher])
    r = agent.invoke({"messages": [{"role": "user", "content":
        "请把以下任务委派给 skilled-reviewer 完成。\n" + DELEGATE_TASK}]})
    print(f"  子 Agent 自报: {preview(sub_reply(r), 120)}")


if __name__ == "__main__":
    part_a_gp_inherits()
    part_b_custom_no_skills()
    part_c_custom_own_skills()
