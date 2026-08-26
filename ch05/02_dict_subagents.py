# ============================================================================
# 02_dict_subagents.py —— ch05 段2：字典方式定义子 Agent + 继承语义 + description 路由
#
#   Part A: 工具继承语义 —— 不指定 tools 时继承主 Agent 工具；指定后完全替换
#   Part B: description 路由 —— 具体 vs 模糊描述，主 Agent 的委派决策对比
#
# 版本说明（0.7.6）：task 工具 + general-purpose 子 Agent 默认可用（与 ch04
# 的 TodoListMiddleware 不同，无需显式声明中间件）。
# ============================================================================

from common import make_model, preview

from deepagents import create_deep_agent


# 本地模拟工具（保证确定性、低成本）
def web_search(query: str) -> str:
    """搜索网络信息（本地模拟）。"""
    return f"[搜索结果] 关于 '{query}'：发布于 2026 年，要点 1/2/3 ……（约 500 字）"


def calculator(expression: str) -> float:
    """计算数学表达式。"""
    return eval(expression)


def translate(text: str, to: str = "en") -> str:
    """翻译文本（本地模拟）。"""
    return f"[翻译结果:{to}] {text}"


def part_a_tool_semantics():
    print("=" * 60)
    print("Part A: tools 继承语义（默认继承 / 指定后完全替换）")
    print("=" * 60)

    # 子 Agent A：不指定 tools —— 继承主 Agent 的全部工具
    inheritor = {
        "name": "all-tools-worker",
        "description": "演示继承：未指定 tools，继承主 Agent 全部工具",
        "system_prompt": "你是通用工人，按指令使用可用工具完成任务。",
    }
    # 子 Agent B：指定 tools=[calculator] —— 完全替换（拿不到 web_search）
    replacer = {
        "name": "calc-only-worker",
        "description": "演示替换：只指定了 calculator，其他工具不可用",
        "system_prompt": "你是计算工人，只能使用 calculator 工具。",
        "tools": [calculator],          # 显式指定 → 完全替换，不合并
    }

    agent = create_deep_agent(
        model=make_model(),
        tools=[web_search, calculator],   # 主 Agent 的工具集
        subagents=[inheritor, replacer],
        system_prompt="你是调度员，严格按用户指令委派。",
    )

    # 实验 1：让继承者搜索（应能拿到 web_search，因为它继承了主 Agent 工具）
    r1 = agent.invoke({"messages": [{"role": "user", "content": (
        "委派给 all-tools-worker 搜索 'LangGraph release notes'，完成后转述结果。"
    )}]})
    tool_contents = " ".join(str(m.content) for m in r1["messages"] if m.type == "tool")
    # 模拟工具的输出带特征标记「发布于 2026 年」；子 Agent 摘要引用了它即证明真的调到了 web_search
    # （不能靠「无法」等字样判断——子 Agent 常会如实吐槽模拟数据是占位符）
    ok1 = "2026" in tool_contents
    print(f"  继承者调用 web_search 成功: {ok1}（未指定 tools → 继承）")

    # 实验 2：让替换者搜索（它只有 calculator，应失败/说明没有该工具）
    r2 = agent.invoke({"messages": [{"role": "user", "content": (
        "委派给 calc-only-worker 搜索 'LangGraph release notes'。如果它没有搜索工具，"
        "请如实报告它有哪些工具、缺哪些工具。"
    )}]})
    print(f"  替换者搜索结果: {preview(r2['messages'][-1].content, 150)}")

    # 实验 3：让替换者计算（calculator 在它的替换工具集里，应成功）
    r3 = agent.invoke({"messages": [{"role": "user", "content": (
        "委派给 calc-only-worker 计算 (123 + 456) * 2，转述结果。"
    )}]})
    print(f"  替换者计算结果: {preview(r3['messages'][-1].content, 90)}（1158 才对）")


def part_b_description_routing():
    print()
    print("=" * 60)
    print("Part B: description 决定路由（具体 vs 模糊）")
    print("=" * 60)

    # ❌ 模糊描述 + ✅ 具体描述 并存，观察主 Agent 把「快速查事实」路由给谁
    subagents = [
        {
            "name": "deep-researcher",
            "description": "执行深度网络研究，需要多次搜索、信息交叉验证和综合分析时使用，适合生成全面报告",
            "system_prompt": "你是深度研究员，多次调用 web_search 后输出综合摘要（100 字内）。",
            "tools": [web_search],
        },
        {
            "name": "quick-lookup",
            "description": "用于简单、快速的查询，只需 1-2 次搜索，适合查找基本事实或定义",
            "system_prompt": "你是速查助手，调用一次 web_search 后直接给出简洁答案（30 字内）。",
            "tools": [web_search],
        },
    ]
    agent = create_deep_agent(
        model=make_model(),
        subagents=subagents,
        system_prompt="你是调度员。根据任务特点用 task 工具委派给最合适的子 Agent。",
    )

    # 问题 1：简单事实查询 → 期望路由到 quick-lookup
    r1 = agent.invoke({"messages": [{"role": "user", "content": "查一下 'Python 3.13 发布日期'，我只要一个日期。"}]})
    routed1 = [tc["args"].get("name") or tc["args"].get("subagent_type", "?")
               for m in r1["messages"] for tc in (getattr(m, "tool_calls", None) or []) if tc["name"] == "task"]
    print(f"  '只要一个日期'   → 路由到: {routed1}（期望 quick-lookup）")

    # 问题 2：综合研究 → 期望路由到 deep-researcher
    r2 = agent.invoke({"messages": [{"role": "user", "content": "深入研究 '2026 年 Agent 框架发展趋势'，需要多次搜索并交叉验证，给我综合分析。"}]})
    routed2 = [tc["args"].get("name") or tc["args"].get("subagent_type", "?")
               for m in r2["messages"] for tc in (getattr(m, "tool_calls", None) or []) if tc["name"] == "task"]
    print(f"  '综合分析'       → 路由到: {routed2}（期望 deep-researcher）")


if __name__ == "__main__":
    part_a_tool_semantics()
    part_b_description_routing()
