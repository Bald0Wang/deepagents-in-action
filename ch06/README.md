# 第 6 章 · 异步子 Agent — 学习代码

> ⚠️ 本章运行模型与前几章不同：Async Subagent 是预览特性，**不能直接 `agent.invoke()`**，
> 必须跑在 LangGraph 服务（Agent Protocol）里，用 SDK 验证。

沿用 ch02 环境与模型配置（DeepSeek 官方接口 `deepseek-v4-flash`）。

## 运行（两个终端）

```bash
cd ch06
uv sync            # 依赖：deepagents + langchain-openai + langgraph-cli[inmem] + langgraph-sdk

# 终端 1：启动本地 Agent Server（实测无需 LangSmith Key）
uv run langgraph dev --n-jobs-per-worker 4 --port 2024
# 看到 "API: http://127.0.0.1:2024" 即成功；worker=4 至少容纳 1 主 + 1 子

# 终端 2：SDK 四轮验证
uv run run_demo.py
```

## 文件

| 文件 | 说明 |
|---|---|
| `langgraph.json` | 把 supervisor 与 researcher 注册到同一本地 Server（同部署 = ASGI 进程内传输的前提）；`env` 指向 ./.env |
| `graphs/researcher.py` | 故意 `sleep(8)` 的子 Agent 图——让"立即返回 / 后台运行 / running→success"稳定可观察 |
| `graphs/supervisor.py` | 主 Agent：`create_deep_agent` + `AsyncSubAgent(graph_id="researcher")`，不传 url 走 ASGI；system_prompt 写死四条遥控器行为规则 |
| `run_demo.py` | 同一 thread 连续四轮对话：start → check(running) → update 追加约束 → check(success) |
| `bench_sync_vs_async.py` | ⭐挑战实验一：同步 task() vs 异步 start_async_task 计时对比（33.4s 阻塞 vs 首答 6.7s/全部 11.5s，2.9x） |
| `bench_hybrid.py` | ⭐挑战实验二：混合拓扑——ASGI(同部署) + HTTP(远程 server B) 双传输并行，9.8s 完成 |
| `graphs/timed_researcher.py` / `sync_supervisor.py` / `async_supervisor.py` / `hybrid_supervisor.py` | 实验用 graphs（5 秒工作图 + 三种 supervisor） |
| `remote/langgraph.json` + `remote/graphs/remote_coder.py` | server B 独立部署（uv source 复用同一 venv；注意 source 模式下路径相对 ch06 根解析） |

实验详情与完整运行输出见《挑战实验-同步vs异步与混合拓扑.md》。

## 实测结论（详见《代码与运行结果.md》）

- **start 立即返回**：第 1 轮秒回完整 task_id（`01a040b1-…-401f0`），没有等 researcher 的 8 秒。
- **非阻塞验证**：立刻问进度时 `check_async_task` 返回 `running`——主对话与后台任务并行。
- **update 生效**：追加"答案写成 3 条 bullet"后 task_id 不变，且后台任务的最终产出真的变成了 3 条 bullet——中途注入指令直达子 Agent。
- **状态流转**：同一 task_id 上观察到 running → success；最终 result 原文就是 researcher 图里写的那段话。

## ⚠️ 版本差异与坑（0.7.9 实测）

1. **langgraph dev 本地不需要 LangSmith Key**：课程说需要，实测 `auth=noop` 直接跑通（in-memory runtime）。远端部署才需要。
2. **deepagents 已到 0.7.9**：`AsyncSubAgent` 是 TypedDict（name/description/graph_id 必填），用法与课程一致。
3. **`checkpointer` 不能传给 langgraph dev**：平台自带持久化，传入报 ValueError。只有裸 python 运行 supervisor 时才需要手动加 `InMemorySaver()`。
4. **本地 ASGI 只支持 async 入口**：经 SDK/Server 调用没问题；若绕过 server 直接进程内调用需注意。
5. Worker 槽位：每个活跃 run 占一个，槽位不足时 start 卡住或 check 无进展——并发多就调大 `--n-jobs-per-worker`。

## 五把"遥控器"实测映射

| 工具 | 本实验中的真实返回 |
|---|---|
| `start_async_task` | `Launched async subagent. task_id: 01a040b1-…` |
| `check_async_task`（进行中） | `{"status": "running", "thread_id": "…"}` |
| `update_async_task` | `Updated async subagent. task_id: …`（ID 不变） |
| `check_async_task`（完成） | `{"status": "success", "result": "[researcher finished after 8s]…"}` |
| `cancel_async_task` / `list_async_tasks` | 未触发（模型按规则只做必要操作）；可直接追问"取消它/列出所有任务"验证 |
