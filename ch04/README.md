# 第 4 章 · 任务规划与分解 — 学习代码

沿用 ch02 环境与配置（DeepSeek 官方接口 + `deepseek-v4-flash`），ch04 有独立 `.venv`（依赖与 ch02 一致），`common.py` 自动加载 `.env`，直接 `uv run` 即可。

## ⚠️ 重要版本差异（deepagents 0.7.6 实测）

课程说 `write_todos` 在 `create_deep_agent()` 时**自动注入**（TodoListMiddleware 属常驻层）。
但实测 **0.7.6 的默认中间件栈不包含 `TodoListMiddleware`**，需要显式加入：

```python
from langchain.agents.middleware import TodoListMiddleware

agent = create_deep_agent(
    model=model,
    middleware=[TodoListMiddleware()],   # 0.7.6 必须显式加，否则没有 write_todos
)
```

加入后行为与课程描述完全一致（`write_todos` 工具 + 规划提示词自动生效）。本目录所有脚本均已处理。

## 运行

```bash
cd ch04
uv sync                 # 首次建 .venv（走 uv 缓存）
uv run 01_write_todos_basics.py
uv run 02_langchain_middleware.py
uv run 03_todo_summarization_synergy.py
uv run 04_research_task.py        # 走真实 Tavily 搜索，较慢
```

## 文件

| 脚本 | 对应课程段落 | 内容 |
|---|---|---|
| `common.py` | — | 公共模型配置（DeepSeek）+ `.env` 自动加载 |
| `01_write_todos_basics.py` | `write_todos` 工具详解 | Part A：5 步任务的规划→执行→状态流转（4 次 write_todos 调用序列）；Part B：清单持久化（同 thread 跨轮保留 / 换 thread 隔离） |
| `02_langchain_middleware.py` | 揭开引擎盖：LangChain 中间件 | Part A：`create_agent()` 手动组装 `TodoListMiddleware` + `FilesystemMiddleware`（Framework 层 vs Harness 层对比）；Part B：`TodoListMiddleware(system_prompt=..., tool_description=...)` 自定义规划规范（实测首项文档、末项核对的团队规范被严格执行） |
| `03_todo_summarization_synergy.py` | 任务规划与上下文管理的协同 | 「北极星」验证：`trigger={"messages": 6}` 低成本触发总结 → 存档文件出现（总结已触发）且 `todos` 6 项完整、状态继续推进、Agent 不迷失方向 |
| `04_research_task.py` | 代码实战 | 三大 Harness 框架对比研究：5 步计划全部 completed、搜索结果整理进虚拟文件系统（7066 字符报告落盘）、输出完整对比报告 |

## 实测结论

- **状态流转**：Agent 对 5 步任务调了 4 次 `write_todos`（初规划 → 中途更新 → 收尾全 completed），`result["todos"]` 实时反映进度。
- **持久化**：同一 thread 跨 invoke 保留清单（上轮 pending 的任务下轮接着完成）；换 thread 清单为空，不串扰。
- **自定义规划**：`TodoListMiddleware(system_prompt=...)` 的团队规范（首项写文档、末项核对）被模型严格执行。
- **北极星**：总结触发后（`/conversation_history/` 存档出现），`todos` 依旧完整、Agent 汇总覆盖全部 6 步——清单不受对话压缩影响。
- **默认提示词的规划门槛**：内置 tool_description 要求「>=3 步才用 write_todos」，3 步以下模型会直接做完；demo 任务要设计成 5~6 步才能稳定触发规划。

## 依赖说明

`SummarizationMiddleware` 用 deepagents 版本（`backend=StateBackend()` 必填，完整历史存档到该后端）；`TodoListMiddleware` / `create_agent` 来自 langchain。
