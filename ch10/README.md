# 第 10 章 · 沙箱执行 — 学习代码

沿用 ch02 环境与模型配置（DeepSeek 官方接口），ch10 有独立 `.venv`，直接 `uv run`。deepagents 0.7.13。

> 远程 Provider（LangSmith/Daytona/Modal/E2B…）需要各平台账号，本章做**本地等价验证**：
> Agent 级实验用 `LocalShellBackend`（实现了 SandboxBackendProtocol、自带虚拟路径映射）作沙箱替身；
> `restricted_sandbox.py` 自定义受限沙箱演示「Provider 接入的核心 = 实现 execute() 等 4 个原语」。

## 运行

```bash
cd ch10
uv sync
uv run 01_sandbox_nature.py     # 协议检测→execute 可见性 + 自定义受限沙箱
uv run 02_two_planes.py        # 两平面闭环 + 大输出截断/落盘分页
uv run 03_security_closure.py  # 宿主凭证 / execute+HITL / 产物审查
uv run pytest -q               # 7 例确定性
RUN_LLM_TESTS=1 uv run pytest -q  # +3 例 LLM 集成（10/10）
```

## 实测要点

- **沙箱的本质是 Backend**：普通 Backend 只实现文件读写；实现 `SandboxBackendProtocol`（核心 `execute()`）后模型才能看到 `execute` 工具——StateBackend vs LocalShellBackend 对照实证。
- **Provider 接入核心 = 4 个原语**：`execute/upload_files/download_files/id`（BaseSandbox 自动在其上构建全部文件工具）；RestrictedSandbox 附带命令黑名单（模拟网络阻断）、路径沙箱、审计日志。
- **两平面**：宿主 `upload_files` 播种输入 → Agent 沙箱内工作 → 宿主 `download_files` 取回产物（实测 sum=150 闭环）。
- **大输出**：直接打印被截断（truncated 标记）；推荐落盘 + `read_file` 分页——上下文只进预览。
- **安全闭环三层**：凭证留在宿主（模型与沙箱 FS 双重核验无泄漏）；`execute` 挂 HITL（reject 后副作用不发生）；产物默认不可信（宿主扫描器全量 REDACT 危险模式后才采用）。

## ⚠️ 本地 vs 远程的关键差异（教学发现）

1. **BaseSandbox 的文件辅助方法用绝对路径**——本地进程无法把沙箱根虚拟成 `/`；**这正是真实沙箱用容器的原因**（容器里的 `/` 就是沙箱根）。
2. **execute 的 cwd 是沙箱根**：命令用相对路径（`python3 src/app.py`），虚拟路径 `/big/` ↔ 根下 `big/`。
3. 截断有两层：LocalShell 的 `max_output_bytes`（100KB 默认）先于 sandbox 模块 `MAX_OUTPUT_BYTES`（500KB）。
4. **dcode CLI / LangSmith Sandboxes 未本地运行**（需账号）：Provider 列表、`--sandbox-id/--sandbox-setup`、快照/Auth Proxy 见课程 §8-§9。

完整代码与真实运行输出见《代码与运行结果.md》。
