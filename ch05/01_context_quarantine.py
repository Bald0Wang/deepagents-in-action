# ============================================================================
# 01_context_quarantine.py —— ch05 段1：为什么需要子 Agent —— Context Quarantine
#
# 对照实验（同一批资料查询任务）：
#   Part A: 主 Agent 自己做 —— 每个主题的完整检索过程全部堆进主上下文
#   Part B: 委派给 general-purpose 子 Agent —— 中间过程被隔离，主上下文只剩
#           task 调用 + 精炼结果
# 度量：主 Agent 的消息数 / 工具调用序列 / 上下文字符量
#
# 说明：用本地模拟工具 fetch_stats（返回 30 行数据）代替真实搜索，
#       保证实验确定性、低成本，同时让「中间过程膨胀」肉眼可见。
# ============================================================================

from common import make_model, preview

from deepagents import create_deep_agent

TOPICS = ["LangGraph", "Temporal", "Prefect"]     # 三个研究主题


def fetch_stats(topic: str) -> str:
    """查询某个主题的详细统计资料（本地模拟，返回 30 行数据）。"""
    return "\n".join(
        f"[{topic}] metric_{i}: value={i * 7 % 100}, note=模拟数据第{i}条，包含若干背景说明文字"
        for i in range(1, 31)
    )


def stats_of(r):
    """统计一次运行的主上下文规模：消息数、工具调用序列、总字符量。"""
    msgs = r["messages"]
    calls = [tc["name"] for m in msgs for tc in (getattr(m, "tool_calls", None) or [])]
    chars = sum(len(str(m.content)) for m in msgs)
    return len(msgs), calls, chars


def part_a_no_delegation():
    print("=" * 60)
    print("Part A: 主 Agent 自己做（所有中间过程进主上下文）")
    print("=" * 60)
    agent = create_deep_agent(
        model=make_model(),
        tools=[fetch_stats],
        system_prompt="你是研究助手，对每个主题调用 fetch_stats 后总结一句要点。",
    )
    task = "分别查询 " + "、".join(TOPICS) + " 三个主题的资料，每个都要调用 fetch_stats，最后各用一句话总结要点。"
    r = agent.invoke({"messages": [{"role": "user", "content": task}]})
    n, calls, chars = stats_of(r)
    print(f"主 Agent 消息数: {n}")
    print(f"主 Agent 工具调用: {calls}")
    print(f"主上下文总量: {chars} 字符")
    print(f"回复预览: {preview(r['messages'][-1].content, 120)}")
    return n, calls, chars


def part_b_with_delegation():
    print()
    print("=" * 60)
    print("Part B: 委派给 general-purpose 子 Agent（Context Quarantine）")
    print("=" * 60)
    # 不传 subagents：0.7.6 默认自带 general-purpose 子 Agent + task 工具
    agent = create_deep_agent(
        model=make_model(),
        tools=[fetch_stats],
        system_prompt=(
            "你是项目经理。对于每个主题的资料查询，必须用 task 工具委派给 "
            "general-purpose 子 Agent 完成，不要自己调用 fetch_stats。"
            "收到子 Agent 的摘要后再向用户汇总。"
        ),
    )
    task = "分别查询 " + "、".join(TOPICS) + " 三个主题的资料，最后各用一句话总结要点。"
    r = agent.invoke({"messages": [{"role": "user", "content": task}]})
    n, calls, chars = stats_of(r)
    print(f"主 Agent 消息数: {n}")
    print(f"主 Agent 工具调用: {calls}   ← 只有 task 委派，没有 fetch_stats")
    print(f"主上下文总量: {chars} 字符")
    # 展示主 Agent 收到的 task 结果（子 Agent 的精炼摘要）
    for m in r["messages"]:
        if m.type == "tool":
            print(f"  task 返回（摘要）: {preview(str(m.content), 90)}")
    print(f"回复预览: {preview(r['messages'][-1].content, 120)}")
    return n, calls, chars


if __name__ == "__main__":
    a = part_a_no_delegation()
    b = part_b_with_delegation()
    print()
    print("=" * 60)
    print("对比结论（Context Quarantine 效果）")
    print("=" * 60)
    print(f"  消息数   : 主 Agent 自己做 {a[0]} 条  ->  委派后 {b[0]} 条")
    print(f"  工具调用 : 自己做 {len(a[1])} 次（含全部检索细节） -> 委派后 {len(b[1])} 次（仅 task）")
    print(f"  上下文量 : {a[2]} 字符 -> {b[2]} 字符（压缩率 {a[2] / max(b[2], 1):.1f}x）")
