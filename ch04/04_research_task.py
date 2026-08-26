# ============================================================================
# 04_research_task.py —— ch04 段4：代码实战 —— 让 Agent 规划并执行研究任务
#
# 完整流程（课程示例的 DeepSeek 版）：
#   1. write_todos 制定研究计划（搜索→对比→写报告）
#   2. 逐步执行，实时更新任务状态
#   3. write_file 把搜索结果整理进虚拟文件系统
#   4. 综合输出研究报告
#
# 说明：
#   - 搜索工具用 Tavily（.env 里已配 Key）；想免 Key 可换成 ch02 的 DDG 版工具
#   - 0.7.6 需显式加 TodoListMiddleware（见 01 脚本头部的版本差异说明）
#   - 任务控制在「简要分析」级别以控制 token 成本
# ============================================================================

import os

from tavily import TavilyClient

from common import make_model, preview

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware

# 初始化 Tavily 搜索客户端（Key 从 .env 加载）
tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])


def internet_search(query: str, max_results: int = 3) -> dict:
    """搜索互联网获取最新信息。

    Args:
        query: 搜索关键词。
        max_results: 返回结果数量，默认 3（控制上下文体积）。
    """
    return tavily_client.search(query, max_results=max_results)


def main():
    # 创建研究 Agent：write_todos（显式注入）+ 7 个文件工具（自动）+ 搜索工具（自定义）
    agent = create_deep_agent(
        model=make_model(),
        tools=[internet_search],
        middleware=[TodoListMiddleware()],
        system_prompt="""你是一位专业的技术研究员。
面对复杂研究任务时，你会：
1. 先用 write_todos 制定研究计划
2. 逐步执行每个步骤，及时更新进度
3. 将搜索结果写入文件系统整理
4. 最终输出完整的研究报告
""",
    )

    # 发起需要规划的复杂研究任务（课程原文任务，保持「简要」以控制成本）
    result = agent.invoke({
        "messages": [{
            "role": "user",
            "content": "请调研 Agent 开发领域的三大 Harness 框架（Deep Agents、Claude Agent SDK、Codex SDK），"
                       "对比它们的核心能力差异，写一份简要分析报告。"
        }]
    })

    # 打印任务清单最终状态（应全部 completed）
    print("=" * 60)
    print("最终任务清单")
    print("=" * 60)
    for t in (result.get("todos") or []):
        print(f"  [{t['status']:^11}] {t['content']}")

    # 打印 Agent 整理出的文件（搜索中间结果应写入虚拟文件系统）
    print("=" * 60)
    print("虚拟文件系统（搜索结果整理）")
    print("=" * 60)
    for path, meta in (result.get("files") or {}).items():
        content = meta["content"] if isinstance(meta, dict) else meta
        print(f"  {path}  ({len(content)} chars)  preview: {preview(content, 60)}")

    # 打印最终报告
    print("=" * 60)
    print("研究报告")
    print("=" * 60)
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
