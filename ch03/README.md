# 第 3 章 · 虚拟文件系统 — 代码逐段实现

沿用 ch02 环境（uv + DeepSeek 官方接口 + `deepseek-v4-flash`），对照课程 ch03 逐段落地并实测。

## 环境

ch03 有独立 `.venv`（依赖与 ch02 一致），`.env` 已从 ch02 复制过来，且 `common.py` / `tests/conftest.py` 会在 import 时自动加载 `.env`。因此直接在 ch03 目录下运行即可，无需任何 `--project` / `--env-file` 参数：

```bash
cd ch03
uv sync                 # 首次：用 uv 缓存秒建 .venv（无需重新下载）
uv run <脚本>.py
```

## 文件

| 脚本 | 对应课程段落 | 内容 |
|---|---|---|
| `common.py` | — | 公共模型配置（DeepSeek）+ `preview()` 预览工具 |
| `01_builtin_file_tools.py` | 内置文件系统工具 | 7 工具 + `read_file` 分片读取 + `grep` 三模式 + 路径沙箱。Part A 后端直调（确定性），Part B Deep Agent 端到端 |
| `02_context_auto_management.py` | 上下文自动管理 | Part A 大结果自动卸载（`tool_token_limit_before_evict` 降到 300）；Part B 对话历史自动总结（`SummarizationMiddleware`，加 `MemorySaver` 让事件可观测） |
| `03_backends.py` | 可插拔存储后端 | 五种后端：State / Filesystem / LocalShell / Store / Composite，各自验证核心特性 |
| `04_permissions_and_custom_backend.py` | 权限与自定义后端 | Part A `FilesystemPermission`(deny) 端到端；Part B `GuardedBackend`；Part C `PolicyWrapper`；Part D 自定义 `S3Backend`（实现 `BackendProtocol` 六方法） |

## 实测结论

- **大结果卸载**：tool 消息只留「路径引用 + 预览」，完整内容卸到 `/large_tool_results/`。
- **对话总结**：0.7.6 把总结事件存私有状态 `_summarization_event`（不直接改 `messages`），完整历史存档到 `/conversation_history/session_<uuid>.md`；模型实际拿到的是 `[summary, ...recent]`。
- **后端路由**：`CompositeBackend` 下 `/workspace/` 走 StateBackend（进 `state.files`）、`/memories/` 走 StoreBackend（跨线程持久）。
- **自定义后端**：实现 `BackendProtocol` 的 `ls/read/write/edit/grep/glob` 六方法即可被 Deep Agent 直接驱动。

## 测试

pytest 已装到 ch02 环境（dev 依赖）。分两层：

```bash
cd ch03

# 确定性单测（无 LLM，毫秒级）—— 默认
uv run pytest -q

# 全量（含 LLM 集成测试，走真实 DeepSeek，约 30s）
RUN_LLM_TESTS=1 uv run pytest -q
```

| 测试文件 | 覆盖 |
|---|---|
| `tests/test_filesystem_backend.py` | 分片读取、glob、grep、edit、delete、路径沙箱 |
| `tests/test_backends.py` | LocalShellBackend 执行命令、StoreBackend 读写/隔离、CompositeBackend 路由 |
| `tests/test_custom_backends.py` | S3Backend 六方法、GuardedBackend、PolicyWrapper |
| `tests/test_llm_integration.py` | Deep Agent 端到端：文件工具、大结果卸载、权限 deny、自定义后端、历史总结（`RUN_LLM_TESTS=1` 开启） |

## 说明

- `StateBackend` / `StoreBackend` 的 `namespace` 本地兜底用 `("local-user",)`（`rt.server_info` 在本地为 None）。
- `StateBackend` 必须在 graph 内运行（不能脱离 agent 直接调用），故其行为走 LLM 集成测试。
- `LocalShellBackend` 无沙箱，仅本地演示使用。
