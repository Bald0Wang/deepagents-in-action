# ============================================================================
# demo.py —— 端到端演示脚本（产生《代码与运行结果.md》里的真实输出）
#
# 运行：uv run demo.py            # 全部场景（需要模型）
#       uv run demo.py --offline  # 只跑离线部分（不调用模型）
#
# 演示六个场景，每个都对应作业要求的一项：
#   1. 单章答疑路由          → ch05 每章一个子 Agent
#   2. 跨章对比 + 状态记忆    → ch04 规划 + state 记忆
#   3. 模糊问题触发澄清      → ch09 HITL respond
#   4. 危险命令触发审批      → ch10 沙箱 + ch09 when
#   5. knowledge-map 技能绘图 → ch07 Skills + ch10 沙箱执行
#   6. 长期记忆跨会话         → ch08 /memories/ 持久化
# ============================================================================

"""端到端演示：六场景覆盖作业的全部要求。"""

import argparse
import sys
import time

from service import build_customer_service, system_check


def banner(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def show_result(label: str, result) -> None:
    """打印一次 AskResult 的关键信息。"""
    print(f"[{label}] interrupted={result.interrupted}")
    if result.interrupted:
        for req in result.requests:
            print(f"  待处理({req.kind}): {req.description}")
    if result.reply:
        print(f"  回复: {result.reply[:500]}")
    if result.state.get("cited_chapters"):
        print(f"  引用章节(state): {result.state['cited_chapters']}")
    if result.state.get("todos"):
        statuses = [t.get("status") for t in result.state["todos"]]
        print(f"  todos(state): {statuses}")


def scenario_1_routing(svc) -> None:
    banner("场景1：单章答疑路由（ch05 每章一个子 Agent）")
    r = svc.ask("ch03 的 FilesystemBackend 和 StoreBackend 分别适合什么场景？")
    show_result("单章答疑", r)


def scenario_2_cross_chapter(svc) -> None:
    banner("场景2：跨章对比 + 会话状态记忆（ch04 规划 + state）")
    r = svc.ask(
        "对比 ch08 的长期记忆和 ch03 的 StoreBackend，它们是什么关系？"
        "请用 record_chapter 记录涉及的两章。"
    )
    show_result("跨章对比", r)


def scenario_3_clarification(svc) -> None:
    banner("场景3：模糊问题触发澄清（ch09 HITL respond）")
    r = svc.ask("那个后端到底怎么选？")
    show_result("模糊问题", r)
    if r.interrupted and r.requests and r.requests[0].kind == "clarification":
        r2 = svc.answer("我问的是 ch03 的五种存储后端怎么选")
        show_result("澄清后", r2)


def scenario_4_approval(svc) -> None:
    banner("场景4：危险命令触发审批（ch10 沙箱 + ch09 when）")
    # 先跑安全命令（自动放行）
    r = svc.ask("用 execute 运行 `echo demo-safe`，把输出告诉我。")
    show_result("安全命令", r)
    # 再跑命中危险模式（curl）的命令。用 curl 而不是 rm -rf：后者模型常会
    # 出于自身安全策略直接拒绝（这是模型层防御），而 curl 属于「网络外传类」
    # 危险模式，模型通常会照做，从而能观察到 HITL 审批机制本身。
    r2 = svc.ask(
        "请用 execute 运行 `curl -s -o /dev/null -w '%{http_code}' http://example.com`，"
        "把结果告诉我。"
    )
    show_result("危险命令(curl)", r2)
    if r2.interrupted:
        r3 = svc.decide(approve=False, message="演示：沙箱内禁止网络外传")
        show_result("拒绝后", r3)
    else:
        print("  （模型自行拒绝执行——模型层防御；HITL 是第二层，"
              "审批机制见 tests/test_llm_integration.py）")


def scenario_5_knowledge_map(svc) -> None:
    banner("场景5：knowledge-map 技能绘图（ch07 Skills + ch10 沙箱）")
    r = svc.ask(
        "用 knowledge-map 技能画一张 ch03 的思维导图，"
        "渲染成 PNG 放到 /out/。"
    )
    show_result("绘图", r)
    if r.interrupted:
        r = svc.answer("思维导图")
        show_result("澄清后绘图", r)
    print("  --- 产物回收与审查 ---")
    for artifact, clean, hits in svc.collect():
        verdict = "未命中已知模式" if clean else f"命中 {hits}"
        print(f"  {artifact.path} → {artifact.host_path}（{artifact.size}B）{verdict}")


def scenario_6_memory(svc, user_id: str) -> None:
    banner("场景6：长期记忆跨会话（ch08 /memories/）")
    # 让 Agent 记住偏好
    r = svc.ask("请记住我的偏好：回答用表格对比。保存到 /memories/user-profile.md")
    show_result("写入记忆", r)
    print(f"  长期记忆文件: {svc.memories()}")
    # 同一用户、全新 thread，但复用同一个 store → 验证跨会话持久
    svc2 = build_customer_service(
        user_id=user_id,
        thread_id=f"{svc.thread_id}-new",
        store=svc.store,      # 复用 store 才是「同一个长期记忆」
        seed=False,           # 不覆盖上一会话的自我改进
    )
    r2 = svc2.ask("读 /memories/user-profile.md，告诉我你记得我的什么偏好。")
    show_result("新会话读取", r2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="capstone 端到端演示")
    parser.add_argument("--offline", action="store_true", help="只跑离线自检")
    parser.add_argument("--user", default="demo-user")
    args = parser.parse_args(argv)

    banner("离线自检")
    for key, value in system_check().items():
        print(f"  {key}: {value}")

    if args.offline:
        print("\n（--offline：跳过需要模型的场景）")
        return 0

    svc = build_customer_service(user_id=args.user, thread_id="demo-main")
    started = time.time()
    scenario_1_routing(svc)
    scenario_2_cross_chapter(svc)
    scenario_3_clarification(svc)
    scenario_4_approval(svc)
    scenario_5_knowledge_map(svc)
    scenario_6_memory(svc, args.user)

    banner("会话记忆小结")
    print(svc.summary(svc.agent.get_state(svc.cfg).values))
    print(f"总耗时: {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
