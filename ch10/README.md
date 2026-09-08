# 第 10 章 · 沙箱执行 — 学习代码

沿用 ch02 环境与模型配置（DeepSeek 官方接口），ch10 有独立 `.venv`，直接 `uv run`。deepagents 0.7.13。

> 本目录只做本地接口与工作流程演示，不需要远程沙箱账号。
> `LocalShellBackend` 实现执行协议，但命令仍在本机运行，不能等价验证容器隔离。
> 实验三 Part A 使用 `FilesystemBackend`；`RestrictedSandbox` 的黑名单也只是教学策略，不是真正断网。

## 运行

```bash
cd ch10
uv sync
uv run 01_sandbox_nature.py     # 协议检测→execute 可见性 + 自定义受限沙箱
uv run 02_two_planes.py        # 两平面闭环 + 大输出截断/落盘分页
uv run 03_security_closure.py  # 宿主凭证 / execute+HITL / 产物审查
uv run 04_local_lifecycle.py   # 无 LLM：失败/超时、部分下载失败、作用域和清理
uv run pytest -q               # 本地回归检查，LLM 用例默认跳过
RUN_LLM_TESTS=1 uv run pytest -q  # 另行启用真实模型集成
```

## 对照原文的阅读路线

每段代码的 docstring 说明它对应哪一节；段内注释解释调用方、路径、返回值和预期现象。

| 原文章节 | 本地实验 | 重点看什么 |
|---|---|---|
| §1、§10 执行协议 | 01 Part A/B | 协议检查与模型调用记录；四原语的上传—执行—下载 |
| §5–6 两种模式、两个平面 | 02 Part A | 宿主传入 bytes，模型操作工作区，宿主下载产物 |
| §1 大输出 | 02 Part B | 先截断，再将多行日志落盘，按 offset/limit 读两行 |
| §2、§11 凭证与审查 | 03 Part A/B/C | 模拟凭证不返回给模型、execute 审批恢复、产物检查 |
| §1 返回值与执行失败 | **04 Part A（新增）** | stdout/stderr、非零退出码、超时返回 124 |
| §6 逐文件处理传输结果 | **04 Part B（新增）** | 同批一项成功、一项缺失；检查 content is not None |
| §7 生命周期与作用域 | **04 Part C（新增）** | 应用维护目录映射，比较按线程隔离与按助手复用，异常后清理 |

原文 §3–4 的远程 Provider、§8 远程 dcode、§9 托管资源以及 §10 的 dcode Provider 注册不新增实验。
§7 只模拟工作区作用域和清理，不实现云端 TTL、快照或后台进程回收。

推荐先运行实验四（全程无需模型），再读 01 → 02 → 03。前三个脚本整段运行包含模型调用，
需要本地配置 `DEEPSEEK_API_KEY`；其中 01 Part B、02 Part B、03 Part C 可单独调用，无需模型请求。

注释修订同时纠正了一个分页演示问题：原 02 Part B 把 60 万字符写在同一行，
`limit=2` 仍可能读取整条长行；现在使用 6000 行日志，两行读取约 200 字符，下一页偏移为 2。

## 实测要点

### 实验三 Part A 停在标题处的修复

Part A 原来允许模型通过 `LocalShellBackend.execute` 自主搜索凭证文件。
`virtual_mode=True` 只约束文件工具，不限制 Shell；搜索可能越出临时目录，且
`invoke()` 完成前没有进度输出。现在 Part A 使用 `FilesystemBackend`，只检查
临时工作区，空目录即结束；模型请求设置 60 秒超时、不自动重试，图步数上限为 12，
并在调用前打印等待提示。Part B 仍用 LocalShell 演示命令审批。

修复后本地检查：8 passed、3 skipped（未调用真实模型）。
《代码与运行结果.md》中的实验三源码已同步；其中旧的模型回复是历史记录，
不代表本次修复后的重新实测结果。

- **沙箱的本质是 Backend**：普通 Backend 只实现文件读写；实现 `SandboxBackendProtocol`（核心 `execute()`）后模型才能看到 `execute` 工具——StateBackend vs LocalShellBackend 对照实证。
- **Provider 接入核心 = 4 个原语**：`execute/upload_files/download_files/id`（BaseSandbox 自动在其上构建全部文件工具）；RestrictedSandbox 附带命令黑名单（模拟网络阻断）、路径沙箱、审计日志。
- **两平面**：宿主 `upload_files` 播种输入 → Agent 沙箱内工作 → 宿主 `download_files` 取回产物（实测 sum=150 闭环）。
- **大输出**：直接打印被截断（truncated 标记）；推荐落盘 + `read_file` 分页——上下文只进预览。
- **安全闭环三层**：凭证由宿主工具持有；`execute` 挂 HITL；宿主检查下载产物。关键词扫描只识别已知模式，未命中不等于安全，命中后应停止采用并人工审查。

## ⚠️ 本地 vs 远程的关键差异（教学发现）

1. **BaseSandbox 的文件辅助方法用绝对路径**——本地进程无法把沙箱根虚拟成 `/`；**这正是真实沙箱用容器的原因**（容器里的 `/` 就是沙箱根）。
2. **execute 的 cwd 是沙箱根**：命令用相对路径（`python3 src/app.py`），虚拟路径 `/big/` ↔ 根下 `big/`。
3. 截断有两层：LocalShell 的 `max_output_bytes`（100KB 默认）先于 sandbox 模块 `MAX_OUTPUT_BYTES`（500KB）。
4. **dcode CLI / LangSmith Sandboxes 未本地运行**（需账号）：Provider 列表、`--sandbox-id/--sandbox-setup`、快照/Auth Proxy 见课程 §8-§9。

完整代码与真实运行输出见《代码与运行结果.md》。
