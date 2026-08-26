# 第 5 章 · 子 Agent 与上下文隔离 — 学习代码

沿用 ch02 环境与配置（DeepSeek 官方接口），ch05 有独立 `.venv`（依赖与 ch02 一致），`common.py` 自动加载 `.env`，直接 `uv run` 即可。

## 运行

```bash
cd ch05
uv sync                 # 首次建 .venv（走 uv 缓存）
uv run 01_context_quarantine.py
uv run 02_dict_subagents.py
uv run 03_multi_collab.py
uv run 04_compiled_structured.py
```

所有工具均为本地模拟（`fetch_stats` / `web_search` / `collect_data` 等），保证流水线确定性、低成本。

## 文件

| 脚本 | 对应课程段落 | 内容 |
|---|---|---|
| `common.py` | — | 公共模型配置（DeepSeek）+ `.env` 自动加载 |
| `01_context_quarantine.py` | 为什么需要子 Agent | 对照实验：主 Agent 自己做（原始数据全进上下文） vs 委派给 general-purpose（只剩 task + 摘要）。实测 5396 → 3015 字符（1.8x），主上下文零原始数据行 |
| `02_dict_subagents.py` | 字典方式定义 + 最佳实践 | Part A：`tools` 继承语义（不指定=继承全部；指定=完全替换不合并，且只替换自定义工具，内置文件工具仍在）；Part B：description 路由（「只要一个日期」→ quick-lookup，「综合分析」→ deep-researcher，全部正确） |
| `03_multi_collab.py` | 多子 Agent 协作模式 | 协调者模式：write_todos 规划 → task 依次委派 data-collector / data-analyzer / report-writer → 整合输出。主上下文只有 write_todos + task（4082 字符），中间工具细节全部隔离 |
| `04_compiled_structured.py` | CompiledSubAgent + 结构化输出 | Part A：`create_agent()` 图包装成 `CompiledSubAgent`（21×2+100=142，主 Agent 仅 4 条消息）；Part B：`response_format` 返回 JSON 并通过 Pydantic 校验 |

## 实测结论

- **task 工具默认可用**（0.7.6）：`create_deep_agent()` 自带 general-purpose 子 Agent 和 `task` 工具——与 ch04 的 `TodoListMiddleware` 不同，**无需显式声明**（但 TodoList 仍需 `middleware=[TodoListMiddleware()]`）。
- **Context Quarantine 量化**：委派后主 Agent 的工具调用从「原始数据×3」变为「task 摘要×3」，主上下文 1.8x 压缩；多 Agent 流水线场景下从 18381 → 4082 字符（4.5x）。
- **工具替换语义**：`tools` 显式指定后完全替换的是**自定义工具集**；`grep`/`glob` 等内置文件工具由 FilesystemMiddleware 注入，不受影响。
- **description 是路由开关**：具体、行为导向的描述让主 Agent 的委派决策 100% 正确。
- **返回精简很重要**：子 Agent 提示词不加字数限制时，一次协作把主上下文撑到 18k 字符；加上「50/100/150 字以内」后降到 4k——印证课程最佳实践第 5 条。

## ⚠️ 版本坑（DeepSeek + response_format）

`response_format`（结构化输出）内部强制 `tool_choice`，而 **`deepseek-v4-flash` 默认思考模式不支持 tool_choice**（400 报错 `Thinking mode does not support this tool_choice`）。

解法：给该子 Agent 单独指定非思考模式别名 `deepseek-chat`（同一平台、同一能力底座）：

```python
"model": ChatOpenAI(
    model="deepseek-chat",          # 非思考模式，支持强制 tool_choice
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com/v1",
),
"response_format": ResearchFindings,
```

主 Agent 仍可用 `deepseek-v4-flash`（MODEL_NAME 控制），只有需要结构化输出的子 Agent 换模型。
