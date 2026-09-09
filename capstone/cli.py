# ============================================================================
# cli.py —— 客服系统命令行入口
#
# 用法：
#   uv run cli.py                          # 交互式答疑
#   uv run cli.py --ask "ch03 的后端有哪些？"   # 单轮提问
#   uv run cli.py --demo                   # 离线自检（不调用模型）
#   uv run cli.py --render-assets          # 渲染技能自带的两张示例图
#
# 交互命令（对话中）：
#   /quit            退出
#   /summary         查看本次会话的 state 记忆小结
#   /memories        查看长期记忆文件
#   /collect         回收并审查 /out/ 产物
#   /approve         批准当前待审批的 execute 请求
#   /reject [原因]   拒绝当前待审批的 execute 请求
#   （其他输入 = 回答澄清问题 / 继续提问）
# ============================================================================

"""客服系统 CLI：交互答疑、HITL 审批、产物回收。"""

import argparse
import sys
from pathlib import Path

from config import SANDBOX_ROOT, SKILLS_SRC
from service import build_customer_service, system_check


def _print_requests(requests) -> None:
    """打印待处理的 HITL 请求。"""
    for i, req in enumerate(requests, 1):
        tag = "澄清" if req.kind == "clarification" else "审批"
        print(f"  [{tag} {i}] {req.description}")


def _print_artifacts(items) -> None:
    """打印产物回收结果。"""
    if not items:
        print("  （/out/ 下暂无产物）")
        return
    for artifact, clean, hits in items:
        verdict = "未命中已知模式（不代表安全）" if clean else f"⚠ 命中：{hits}"
        print(f"  {artifact.path} → {artifact.host_path}（{artifact.size}B）{verdict}")


def run_demo() -> int:
    """离线自检：不调用模型，验证各层组装。"""
    print("=" * 60)
    print("离线自检（不调用模型）")
    print("=" * 60)
    for key, value in system_check().items():
        print(f"  {key}: {value}")
    print()
    print("运行 `uv run cli.py` 进入交互答疑（需要 DEEPSEEK_API_KEY）。")
    return 0


def run_render_assets() -> int:
    """渲染技能自带的两张示例图（验证 knowledge-map 渲染链路）。"""
    import subprocess

    script = SKILLS_SRC / "knowledge-map" / "scripts" / "render_mmd.py"
    assets = SKILLS_SRC / "knowledge-map" / "assets"
    out_dir = SANDBOX_ROOT / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("渲染 knowledge-map 示例图")
    print("=" * 60)
    rc = 0
    for name in ("knowledge-graph", "mindmap"):
        src = assets / f"{name}.mmd"
        dst = out_dir / f"{name}.png"
        print(f"  {src.name} → {dst}")
        proc = subprocess.run([sys.executable, str(script), str(src), str(dst), "--scale", "3"])
        rc = rc or proc.returncode
    return rc


def interactive(svc) -> int:
    """交互式答疑循环，处理 HITL 中断。"""
    print("=" * 60)
    print("Deep Agents 课程客服（ch02-ch10）")
    print("输入问题开始；/quit 退出；/summary 看会话记忆；/collect 收产物")
    print("=" * 60)
    print(f"thread_id = {svc.thread_id} | user = {svc.user_id}")
    print()

    pending = None
    while True:
        try:
            raw = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not raw:
            continue

        # ---- 内置命令 ----
        if raw == "/quit":
            return 0
        if raw == "/summary":
            print(svc.summary(svc.agent.get_state(svc.cfg).values))
            continue
        if raw == "/memories":
            print(f"  长期记忆文件：{svc.memories()}")
            continue
        if raw == "/collect":
            _print_artifacts(svc.collect())
            continue
        if raw.startswith("/approve") or raw.startswith("/reject"):
            if not pending:
                print("  （当前没有待审批的请求）")
                continue
            approve = raw.startswith("/approve")
            reason = raw[len("/approve"):].strip() or raw[len("/reject"):].strip()
            result = svc.decide(approve=approve, message=reason)
            pending = result.requests or None
            if result.interrupted:
                print("还有待处理请求：")
                _print_requests(result.requests)
            else:
                print(f"客服> {result.reply}")
            continue

        # ---- 普通输入 ----
        # 若上一次是澄清中断，则把这次输入当作补充信息（respond）
        if pending and all(r.kind == "clarification" for r in pending):
            result = svc.answer(raw)
        else:
            result = svc.ask(raw)

        pending = result.requests or None
        if result.interrupted:
            print("需要你补充信息 / 审批：")
            _print_requests(result.requests)
            if pending and any(r.kind == "approval" for r in pending):
                print("  （用 /approve 或 /reject [原因] 处理审批）")
        else:
            print(f"客服> {result.reply}")
            _print_artifacts(svc.collect())
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deep Agents 课程客服（带沙箱）")
    parser.add_argument("--ask", help="单轮提问后退出")
    parser.add_argument("--user", default="local-user", help="用户身份（记忆隔离用）")
    parser.add_argument("--thread", help="会话 thread_id（默认自动生成）")
    parser.add_argument("--demo", action="store_true", help="离线自检，不调用模型")
    parser.add_argument("--render-assets", action="store_true", help="渲染技能示例图")
    args = parser.parse_args(argv)

    if args.demo:
        return run_demo()
    if args.render_assets:
        return run_render_assets()

    svc = build_customer_service(user_id=args.user, thread_id=args.thread)

    if args.ask:
        result = svc.ask(args.ask)
        if result.interrupted:
            print("需要补充信息 / 审批：")
            _print_requests(result.requests)
            return 0
        print(result.reply)
        _print_artifacts(svc.collect())
        return 0

    return interactive(svc)


if __name__ == "__main__":
    raise SystemExit(main())
