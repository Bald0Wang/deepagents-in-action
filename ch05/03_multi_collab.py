# ============================================================================
# 03_multi_collab.py —— ch05 段3：多子 Agent 协作模式（主 Agent 作协调者）
#
# 流水线：data-collector → data-analyzer → report-writer
#   主 Agent：write_todos 制定计划 + task() 逐步委派 + 整合输出
#   每个子 Agent 在独立上下文中工作，主 Agent 只收到精炼结果
#
# 版本提示（0.7.6）：TodoListMiddleware 需显式声明（ch04 的结论），
#                   task 工具则默认可用。
# 工具全部本地模拟，保证流水线确定性与低成本。
# ============================================================================

from langchain.agents.middleware import TodoListMiddleware

from common import make_model, preview

from deepagents import create_deep_agent


# ---------------------------- 本地模拟工具 ---------------------------------
def collect_data(source: str) -> dict:
    """从指定数据源收集原始数据（本地模拟）。"""
    rows = [
        {"framework": "DeepAgents", "stars": 9000 + i, "contrib": 120 + i}
        for i in range(5)
    ] + [
        {"framework": "LangGraph", "stars": 30000 + i * 3, "contrib": 400 + i}
        for i in range(5)
    ]
    return {"source": source, "rows": rows}


def statistical_analysis(dataset: str, metric: str = "mean") -> dict:
    """对数据集做统计分析（本地模拟，直接给结论）。"""
    return {
        "dataset": dataset, "metric": metric,
        "mean_stars": 19500.0, "max_stars": 30012, "min_stars": 9000,
        "insight": "LangGraph 星数约为 DeepAgents 的 3 倍，但两者增速都在加快",
    }


def format_document(title: str, body: str) -> str:
    """把内容排版成正式文档（本地模拟）。"""
    return f"# {title}\n\n{body}\n\n---\n*由 report-writer 排版生成*"


# ---------------------------- 三个专业子 Agent ------------------------------
subagents = [
    {
        "name": "data-collector",
        "description": "用 collect_data 工具从模拟数据源收集原始数据，返回简短数据概况",
        "system_prompt": "你是数据收集专家。只能用 collect_data 工具收集数据（这是模拟数据源，不要尝试真实网络请求）。"
                         "只返回 50 字以内的数据概况，禁止返回原始数据行。",
        "tools": [collect_data],
    },
    {
        "name": "data-analyzer",
        "description": "用 statistical_analysis 工具对数据进行统计分析，提取关键洞察",
        "system_prompt": "你是数据分析专家。只能用 statistical_analysis 工具分析数据。"
                         "提取 3 个关键发现，控制在 100 字以内，禁止贴原始表格。",
        "tools": [statistical_analysis],
    },
    {
        "name": "report-writer",
        "description": "用 format_document 工具把分析结果排版成专业报告",
        "system_prompt": "你是技术写作专家。只能用 format_document 工具排版。"
                         "输出 150 字以内的简报，禁止自行添加数据。",
        "tools": [format_document],
    },
]


def main():
    # 主 Agent = 协调者：规划 + 委派 + 整合
    agent = create_deep_agent(
        model=make_model(),
        subagents=subagents,
        middleware=[TodoListMiddleware()],   # 0.7.6 需显式声明（见 ch04 结论）
        system_prompt="""你是一位项目协调者。面对复杂任务时：
1. 先用 write_todos 制定计划
2. 将数据收集委派给 data-collector
3. 将分析工作委派给 data-analyzer
4. 将报告撰写委派给 report-writer
5. 整合各子 Agent 的输出，形成最终结果""",
    )

    result = agent.invoke({"messages": [{"role": "user", "content": (
        "请完成《Agent 框架热度对比》简报：用 data-collector 从模拟数据源收集数据，"
        "再用 data-analyzer 分析，最后让 report-writer 排版。严格走这条流水线，不要尝试真实网络。"
    )}]})

    # 1) 任务清单
    print("=" * 60)
    print("主 Agent 的任务清单（write_todos）")
    print("=" * 60)
    for t in (result.get("todos") or []):
        print(f"  [{t['status']:^11}] {t['content']}")

    # 2) 委派序列（主上下文里只有 task 调用 + 摘要，没有中间工具细节）
    print("=" * 60)
    print("主 Agent 的委派序列（task 调用）")
    print("=" * 60)
    for m in result["messages"]:
        for tc in (getattr(m, "tool_calls", None) or []):
            if tc["name"] == "task":
                args = tc["args"]
                who = args.get("name") or args.get("subagent_type", "?")
                what = preview(str(args.get("task", args.get("description", ""))), 60)
                print(f"  task → {who:<16} {what}")

    # 3) 主上下文规模（隔离效果）
    calls = [tc["name"] for m in result["messages"]
             for tc in (getattr(m, "tool_calls", None) or [])]
    chars = sum(len(str(m.content)) for m in result["messages"])
    print("=" * 60)
    print("主上下文规模（Context Quarantine）")
    print("=" * 60)
    print(f"  工具调用: {calls}   ← 全是 task，无 collect_data/statistical_analysis")
    print(f"  消息数: {len(result['messages'])}，总字符: {chars}")

    # 4) 最终整合输出
    print("=" * 60)
    print("主 Agent 整合的最终输出")
    print("=" * 60)
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
