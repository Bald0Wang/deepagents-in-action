# ============================================================================
# run_demo.py —— ch06：用 SDK 在同一 Thread 上验证异步子 Agent 行为
#
# 前置：已启动本地 Agent Server（另一终端）：
#     uv run langgraph dev --n-jobs-per-worker 4 --port 2024
#
# 验证四步（同一 thread 连续对话，观察主 Agent 是否阻塞、任务状态流转）：
#   第1轮 start ：委派后台研究 → 应【立即】返回 task_id（不等 researcher 的 8 秒）
#   第2轮 check ：立刻问进度   → 主线程不被阻塞；researcher 可能还在 running
#   第3轮 update：追加新约束   → 应更新已有任务，而不是重开一个
#   等待后 check：状态 running → success，拿到子 Agent 最终结果
#
# 运行：uv run run_demo.py
# ============================================================================

import asyncio
import json

from langgraph_sdk import get_client

client = get_client(url="http://127.0.0.1:2024")
ASSISTANT = "supervisor"           # langgraph.json 里注册的主 graph 名


def show(tag: str, out: dict) -> None:
    """打印一轮对话的关键信息：用过的遥控器工具 + AI 最终回复。"""
    msgs = out.get("messages", [])
    calls = [tc["name"] for m in msgs if m.get("type") == "ai"
             for tc in (m.get("tool_calls") or [])]
    print(f"\n=== {tag} ===")
    print("本轮工具调用:", calls if calls else "（无工具调用）")
    for m in reversed(msgs):
        if m.get("type") == "ai":
            content = m.get("content") or ""
            if isinstance(content, list):
                content = " ".join(str(c) for c in content)
            print(f"AI 回复: {content[:400]}")
            break


async def ask(prompt: str, thread_id: str) -> dict:
    """往同一 thread 追加一轮用户消息并等待 supervisor 回合结束。"""
    return await client.runs.wait(
        thread_id,
        ASSISTANT,
        input={"messages": [{"role": "user", "content": prompt}]},
    )


async def main():
    thread = await client.threads.create()
    thread_id = thread["thread_id"]
    print("thread_id =", thread_id)

    # ── 第1轮：委派后台任务（关键观察：是否立即返回 task_id）──
    out1 = await ask("请把这个任务交给 researcher 异步处理：用后台任务总结 async subagent 的关键行为。",
                     thread_id)
    show("[第1轮] start_async_task", out1)

    # ── 第2轮：立刻问进度（关键观察：主线程未被阻塞；任务可能仍 running）──
    out2 = await ask("刚才那个后台任务现在进展如何？", thread_id)
    show("[第2轮] check_async_task", out2)

    # ── 第3轮：中途追加约束（关键观察：update 而不是重开任务）──
    out3 = await ask("补充约束：完成时请把答案写成 3 条 bullet。", thread_id)
    show("[第3轮] update_async_task", out3)

    # ── 等 researcher 的 8 秒 sleep 结束，再查最终结果 ──
    print("\n（等待 12 秒让 researcher 后台跑完……）")
    await asyncio.sleep(12)
    out4 = await ask("现在任务应该完成了，告诉我最终结果和当前状态。", thread_id)
    show("[第4轮] check → success", out4)

    # 把整轮消息存档供笔记引用
    with open("/tmp/ch06_thread_messages.json", "w") as f:
        all_msgs = []
        for tag, out in [("[t1]", out1), ("[t2]", out2), ("[t3]", out3), ("[t4]", out4)]:
            for m in out.get("messages", []):
                keep = {k: m.get(k) for k in ("type", "name") if m.get(k)}
                content = m.get("content")
                keep["content"] = " ".join(str(c) for c in content) if isinstance(content, list) else content
                tcs = m.get("tool_calls")
                if tcs:
                    keep["tool_calls"] = [{"name": tc.get("name"), "args": tc.get("args")} for tc in tcs]
                all_msgs.append({"round": tag, **keep})
        json.dump(all_msgs, f, ensure_ascii=False, indent=1, default=str)
    print("\n消息序列已存档 -> /tmp/ch06_thread_messages.json")


if __name__ == "__main__":
    asyncio.run(main())
