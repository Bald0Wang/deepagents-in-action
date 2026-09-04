# 第 9 章 · Human-in-the-Loop — 学习代码

沿用 ch02 环境与模型配置（DeepSeek 官方接口），ch09 有独立 `.venv`，直接 `uv run`。deepagents 0.7.13。

## 运行

```bash
cd ch09
uv sync
uv run 01_four_decisions.py           # 四决策：approve/edit/reject/respond
uv run 02_when_and_batch.py           # when 条件中断 + 批量打包
uv run 03_subagent_and_permissions.py # 子 Agent 独立配置 + 权限中断合并
uv run 04_low_level_interrupt.py      # 底层 interrupt()：工具/审稿/输入验证/重放实证
uv run pytest -q                      # 2 例确定性
RUN_LLM_TESTS=1 uv run pytest -q      # +5 例 LLM 集成（7/7）
```

## 实测要点

- **四决策全验证**：approve 用原参数执行；edit 改参后执行（工具结果即新参数）；reject 跳过+原因反馈（Agent 不重试）；respond 让人的回答成为 ask_user 的成功结果。
- **when 谓词**：工作区内自动放行、工作区外才中断——审批界面零噪音。
- **批量打包**：多敏感调用合并一个批次，decisions 必须按 action_requests 动态构造（错配 ValueError）。
- **子 Agent 更严格**：主 Agent interrupt_on=False、子 Agent 独立覆盖为审批——委派即拦。
- **权限中断合并**：FilesystemPermission(mode="interrupt") 与 interrupt_on 同格式、可共存。
- **底层 interrupt()**：工具内自定义审批语义；after_model 审稿中间件（跨工具策略）；输入验证用「单次 interrupt + 条件边回路」；重放实证（恢复时节点从头跑，interrupt 前副作用执行 2 次）。

## ⚠️ 版本坑（0.7.13）

1. `version="v2"` + `result.interrupts` 可用；本版 action_requests 参数字段是 **args**（非 arguments），兼容读法 `ar.get("arguments") or ar.get("args")`；edit 的 `edited_action` 仍用 `args`。
2. 自定义工具**别与内置工具重名**（write_file 冲突会让模型走内置路径绕开 interrupt_on，实测踩坑）。
3. 模型可能自行拒绝敏感请求（不调工具→无中断）：测试时强制 system_prompt「必须走工具」或用中性路径。
4. 裸 CompiledStateGraph 的 invoke 返回 state 字典（无 `.values`）；deep agent v2 返回 `GraphOutput.value`。

完整代码与真实运行输出见《代码与运行结果.md》。
