# ============================================================================
# 02_langchain_middleware.py —— ch04 段2：揭开引擎盖 —— LangChain 中间件
# 内容：
#   Part A: 用更底层的 langchain.agents.create_agent() 手动组装
#           TodoListMiddleware + FilesystemMiddleware（课程「引擎盖」示例）
#   Part B: TodoListMiddleware 自定义配置（system_prompt / tool_description）
#
# 对比要点：
#   create_agent()      —— 手动选择和组合中间件（Framework 层）
#   create_deep_agent() —— 预设好一套最佳组合（Harness 层）
# 两类 Hook（理解中间件执行边界）：
#   Node-style: before_agent / before_model / after_model / after_agent（独立图节点）
#   Wrap-style: wrap_model_call / wrap_tool_call（包裹调用，可重试/缓存/降级）
# ============================================================================

from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware

from common import make_model

from deepagents.middleware import FilesystemMiddleware


def part_a_manual_assembly():
    print("=" * 60)
    print("Part A: create_agent() 手动组装 TodoList + Filesystem")
    print("=" * 60)
    # 课程「引擎盖」示例：在 LangChain 层手动组装规划 + 文件能力
    agent = create_agent(
        model=make_model(),
        tools=[],
        middleware=[
            TodoListMiddleware(),    # 注入 write_todos 工具 + 规划指导提示词
            FilesystemMiddleware(),  # 注入 read_file / write_file 等 7 个文件工具
        ],
    )
    # 一个需要规划的多步骤任务（在「裸」create_agent 上运行；默认提示词要求 >=3 步才规划，这里给 5 步）
    r = agent.invoke({"messages": [{"role": "user", "content": (
        "5 步任务：1) write_file /workspace/hello.md 内容 'from create_agent'；"
        "2) write_file /workspace/notes.md 内容 'manual assembly works'；"
        "3) read_file /workspace/hello.md；4) read_file /workspace/notes.md；"
        "5) 汇总两个文件的内容。请先规划再执行。"
    )}]})
    # 打印任务清单与文件系统状态
    print("--- todos（来自 TodoListMiddleware 注入的 write_todos）---")
    for t in (r.get("todos") or []):
        print(f"  [{t['status']:^11}] {t['content']}")
    print("--- files（来自 FilesystemMiddleware 注入的文件工具）---")
    for path, meta in (r.get("files") or {}).items():
        content = meta["content"] if isinstance(meta, dict) else meta
        print(f"  {path}: {content}")
    print("--- Agent 回复 ---")
    print(r["messages"][-1].content)


def part_b_custom_config():
    print()
    print("=" * 60)
    print("Part B: TodoListMiddleware 自定义配置")
    print("=" * 60)
    # 自定义规划指导提示词：引导特定工作流（如「先写测试再写代码」式的定向引导）
    agent = create_agent(
        model=make_model(),
        tools=[],
        middleware=[
            TodoListMiddleware(
                system_prompt=(
                    "## 任务规划规范（本团队约定）\n"
                    "1. 任何 >=2 步的任务都必须先 write_todos。\n"
                    "2. 计划的第一项永远是「撰写任务说明 documentation.md」。\n"
                    "3. 计划的最后一项永远是「核对清单 review」。\n"
                    "4. 每完成一步立即标记 completed。"
                ),
                tool_description="创建/更新任务清单（团队规范：首项写文档，末项做核对）。",
            ),
            FilesystemMiddleware(),
        ],
    )
    # 观察自定义提示词是否改变规划形态（首项文档 / 末项核对）
    r = agent.invoke({"messages": [{"role": "user", "content": (
        "2 步任务：write_file /workspace/demo.md 内容 'demo'，然后读回确认。按团队规范规划执行。"
    )}]})
    print("--- todos（观察首项=文档、末项=核对 的自定义形态）---")
    for t in (r.get("todos") or []):
        print(f"  [{t['status']:^11}] {t['content']}")


if __name__ == "__main__":
    part_a_manual_assembly()
    part_b_custom_config()
