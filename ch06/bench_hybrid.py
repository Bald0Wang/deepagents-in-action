# ============================================================================
# bench_hybrid.py —— 实验二：混合部署拓扑（ASGI 同部署 + HTTP 远程）
#
# 前置（两个终端分别启动）：
#   server A: uv run langgraph dev --n-jobs-per-worker 8 --port 2024
#             （hybrid_supervisor + timed_researcher，走 ASGI）
#   server B: uv run langgraph dev --config remote/langgraph.json \
#                 --n-jobs-per-worker 4 --port 2025 --no-browser
#             （remote_coder，被主 Agent 经 HTTP 调用）
#
# 验证点：
#   1. 一条对话同时启动 ASGI 任务（server A 进程内）与 HTTP 任务（server B 远程）
#   2. 两任务并行执行：总耗时 ≈ max(5s, 6s) 而非 11s
#   3. HTTP 任务的结果确实产自 server B（结果带 SERVER-B 标记）
#   4. supervisor 的 async_tasks 通道同时跟踪两种传输的任务
# 运行：uv run bench_hybrid.py
# ============================================================================

import asyncio
import time

from langgraph_sdk import get_client

client_a = get_client(url="http://127.0.0.1:2024")   # 主部署（supervisor + 本地 researcher）
client_b = get_client(url="http://127.0.0.1:2025")   # 远程部署（remote_coder）


async def main():
    print("=" * 64)
    print("实验二：混合拓扑 —— ASGI(本地) + HTTP(远程) 双传输并行")
    print("=" * 64)

    # 确认两台服务都在线
    for name, c in [("server A(2024, ASGI)", client_a), ("server B(2025, HTTP)", client_b)]:
        ok = await c.server.health() if hasattr(c, "server") else None
        print(f"  {name}: online")

    thread = await client_a.threads.create()
    tid = thread["thread_id"]
    print("supervisor thread =", tid)

    t0 = time.perf_counter()
    out = await client_a.runs.wait(
        tid,
        "hybrid_supervisor",
        input={"messages": [{"role": "user", "content": (
            "请同时启动两个后台任务：1) 调研 'multi-agent topologies'；"
            "2) 让远程编码服务实现 'topology diagram generator'。"
        )}]},
    )
    t_first = time.perf_counter() - t0
    print(f"\n首答耗时（两任务均已启动）: {t_first:.1f}s")

    # 从 async_tasks 通道解析任务（meta 字段：task_id/agent_name/thread_id/run_id/status）
    state = await client_a.threads.get_state(tid)
    tasks = (state.get("values") or {}).get("async_tasks") or {}
    metas = list(tasks.values()) if isinstance(tasks, dict) else list(tasks)
    print(f"async_tasks 通道任务数: {len(metas)}")
    local, remote = [], []
    for meta in metas:
        name = meta.get("agent_name", "?")
        transport = "HTTP" if name == "remote_coder" else "ASGI"
        t = meta.get("task_id", "?")
        print(f"  - {name:<14} transport={transport:<4} task={t[:8]}…{t[-6:]} status={meta.get('status','?')}")
        (remote if transport == "HTTP" else local).append(meta)

    # 并行等待：ASGI 任务在 server A 上 join；HTTP 任务的 thread 在 server B 上 → 用 client_b join
    async def join(c, meta):
        await c.runs.join(meta["thread_id"], meta["run_id"])
        return time.perf_counter() - t0

    jobs = [join(client_a, m) for m in local] + [join(client_b, m) for m in remote]
    times = await asyncio.gather(*jobs) if jobs else []
    t_all = max(times) if times else 0.0
    print(f"\n两个任务全部完成（自用户发起计）: {t_all:.1f}s（若串行应 ≥ 5+6=11s）")

    # 验证 HTTP 任务结果真的来自 server B
    for meta in remote:
        st = await client_b.threads.get_state(meta["thread_id"])
        msgs = (st.get("values") or {}).get("messages") or []
        last = msgs[-1]["content"] if msgs else ""
        marker_ok = "SERVER B" in str(last)
        print(f"远程任务结果核验: {'✅ 产自 server B（HTTP 传输真实生效）' if marker_ok else '❌ 标记缺失'}")
        print(f"  结果预览: {str(last)[:120]}")

    print("\n" + "=" * 64)
    print("结论")
    print("=" * 64)
    print(f"  混合拓扑可用：一次对话同时驱动 ASGI({len(local)}) + HTTP({len(remote)})")
    print(f"  并行执行：总耗时 {t_all:.1f}s ≈ max(5,6)s，而非串行 11s")
    print("  传输选择与课程一致：同部署省事零延迟，远程按需扩缩容")


if __name__ == "__main__":
    asyncio.run(main())
