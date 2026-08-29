# ============================================================================
# bench_sync_vs_async.py —— 实验一：同步 task() vs 异步 start_async_task 计时对比
#
# 前置：server A 已启动（uv run langgraph dev --n-jobs-per-worker 8 --port 2024）
# 任务规格：3 个主题 × 每个子任务固定 5 秒
#
#   同步组（sync_supervisor）  ：模型逐个调 research_topic（time.sleep(5)），
#                                主对话从头阻塞到尾 → 用户等待 ≈ 15s + LLM 开销
#   异步组（async_supervisor） ：3 个 start_async_task 立即返回 → 首答耗时 ≈ 数秒；
#                                3 个 timed_researcher 在后台并行 → 全部完成 ≈ 5s + 开销
#
# 度量：
#   t_sync_total       同步组用户拿到最终答案的总耗时（全程阻塞）
#   t_async_first      异步组用户拿到 task_id 的耗时（主对话不阻塞的关键指标）
#   t_async_total      异步组所有后台任务完成的总耗时
# 运行：uv run bench_sync_vs_async.py
# ============================================================================

import asyncio
import time

from langgraph_sdk import get_client

client = get_client(url="http://127.0.0.1:2024")

TASK = "请分别调研这三个主题：LangGraph 架构、Temporal 工作流、Prefect 数据管道。"


async def timed_run(assistant: str):
    """在全新 thread 上跑一轮，返回 (总耗时, 输出 state)。"""
    thread = await client.threads.create()
    t0 = time.perf_counter()
    out = await client.runs.wait(
        thread["thread_id"],
        assistant,
        input={"messages": [{"role": "user", "content": TASK}]},
    )
    return time.perf_counter() - t0, thread["thread_id"], out


async def collect_async_tasks(thread_id: str):
    """从 supervisor thread state 的 async_tasks 通道取任务元数据。

    这本身就是课程强调的设计：任务元数据独立于消息历史存放，
    上下文被压缩也不会丢 task_id。实测字段：task_id/agent_name/thread_id/
    run_id/status/created_at/last_checked_at/last_updated_at。"""
    state = await client.threads.get_state(thread_id)
    tasks = (state.get("values") or {}).get("async_tasks") or {}
    # 统一成 list[meta]（meta 里 task_id == 子 Agent 的 thread_id）
    return list(tasks.values()) if isinstance(tasks, dict) else list(tasks)


async def wait_all_tasks(metas: list[dict], t0: float):
    """并行 join 所有后台任务（thread_id + run_id），返回 (全部完成耗时, 各任务耗时)。"""
    async def join_one(meta):
        await client.runs.join(meta["thread_id"], meta["run_id"])
        return time.perf_counter() - t0

    times = await asyncio.gather(*[join_one(m) for m in metas])
    return max(times), {m["task_id"]: round(x, 1) for m, x in zip(metas, times)}


async def main():
    print("=" * 64)
    print("实验一：同步 task() vs 异步 start_async_task（3 主题 × 5 秒）")
    print("=" * 64)

    # ── 同步组 ──
    print("\n[同步组] 用户发出请求，主 Agent 逐个阻塞调用（预计 ≥15s）……")
    t_sync, _, out_sync = await timed_run("sync_supervisor")
    n_sleep = sum(
        1 for m in out_sync.get("messages", [])
        if m.get("type") == "tool" and "sync research done" in str(m.get("content"))
    )
    print(f"  用户拿到最终答案耗时: {t_sync:.1f}s（全程阻塞）")
    print(f"  同步工具调用次数: {n_sleep} × 5s = {n_sleep * 5}s 纯阻塞")

    # ── 异步组 ──（注意：后台任务在首轮 run 期间就已启动，因此计时统一从「用户发起」开始）
    print("\n[异步组] 用户发出请求，主 Agent 并发启动 3 个后台任务……")
    t_start = time.perf_counter()
    t_first, sup_thread, out_async = await timed_run("async_supervisor")
    print(f"  用户拿到 task_id 的耗时（首答，不阻塞）: {t_first:.1f}s")

    tasks = await collect_async_tasks(sup_thread)
    print(f"  async_tasks 通道中的任务数: {len(tasks)}")
    for meta in tasks:
        tid = meta.get("task_id", "?")
        print(f"    - agent={meta.get('agent_name','?'):<12} "
              f"task={tid[:8]}…{tid[-6:]} status={meta.get('status','?')}")

    if not tasks:
        print("  ⚠ 未取到任务列表（检查 async_tasks 通道字段结构）")
        return

    t_all, each = await wait_all_tasks(tasks, t_start)   # 统一基准：用户发起时刻
    print(f"  3 个后台任务全部完成（自用户发起计）: {t_all:.1f}s（并行 5s 起步）")
    for tid, sec in each.items():
        print(f"    - {tid[:8]}…{tid[-6:]} 完成于第 {sec}s")

    # ── 结论 ──
    print("\n" + "=" * 64)
    print("对比结论")
    print("=" * 64)
    print(f"  用户首答等待 : 同步 {t_sync:.1f}s（全程阻塞） vs 异步 {t_first:.1f}s（拿到ID即可继续聊）")
    print(f"  全部完成耗时 : 同步 {t_sync:.1f}s（串行 15s 起步） vs 异步 {t_all:.1f}s（并行 5s 起步）")
    print(f"  总加速比     : {t_sync / t_all:.1f}x")


if __name__ == "__main__":
    asyncio.run(main())
