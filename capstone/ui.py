# ============================================================================
# ui.py —— 简易测试用 Web UI（零额外依赖，仅标准库 + 现有 venv）
#
# 用途：把 CustomerService 包一层 JSON API，配一个单页前端，方便手动测试：
#   - 提问 / 看回复
#   - HITL 澄清：补充信息后继续
#   - HITL 审批：approve / reject 危险命令
#   - 实时查看会话 state（todos / cited_chapters / clarified_questions）
#   - 查看长期记忆、回收并查看 /out/ 产物
#   - 切换用户（测试记忆隔离）、重置会话
#
# 运行：
#   uv run ui.py                 # 默认 http://127.0.0.1:7860
#   uv run ui.py --port 8080     # 指定端口
#   uv run ui.py --offline       # 离线模式（不加载模型，仅用于验证 UI 骨架）
#
# 说明：这是**测试工具**，不是生产服务——单实例、无鉴权、串行处理请求。
# ============================================================================

"""测试用 Web UI：标准库 HTTP 服务 + JSON API + 单页前端。"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import OUT_DIR, SANDBOX_ROOT
from memory import read_memory
from service import CustomerService, build_customer_service, system_check

UI_DIR = Path(__file__).resolve().parent / "ui"

# 全局单实例（测试 UI 单用户；模型调用串行化，避免并发 invoke 同一 agent）
_LOCK = threading.Lock()
_SERVICE: CustomerService | None = None
_OFFLINE = False
_LAST_STATE: dict = {}


# ---------------------------------------------------------------------------
# 一、安全序列化
# ---------------------------------------------------------------------------
def json_safe(obj, depth: int = 0):
    """把任意对象转成可 JSON 序列化的结构（截断过深/过大的内容）。"""
    if depth > 6:
        return str(obj)[:200]
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, bytes):
        return f"<{len(obj)} bytes>"
    if isinstance(obj, dict):
        return {str(k): json_safe(v, depth + 1) for k, v in list(obj.items())[:50]}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v, depth + 1) for v in obj[:50]]
    # LangChain 消息对象：只取类型与内容
    if hasattr(obj, "content"):
        return {"type": getattr(obj, "type", "?"), "content": json_safe(obj.content, depth + 1)}
    return str(obj)[:300]


def _state_view(svc: CustomerService) -> dict:
    """从 agent state 里提取 UI 需要的安全字段。"""
    try:
        values = svc.agent.get_state(svc.cfg).values or {}
    except Exception:  # noqa: BLE001 - 状态读取失败不应让接口 500
        values = {}
    return {
        "thread_id": svc.thread_id,
        "user_id": svc.user_id,
        "cited_chapters": list(values.get("cited_chapters") or []),
        "clarified_questions": list(values.get("clarified_questions") or []),
        "todos": [
            {"content": str(t.get("content", "")), "status": str(t.get("status", ""))}
            for t in (values.get("todos") or [])
        ],
        "files": sorted((values.get("files") or {}).keys()),
    }


def _memory_view(svc: CustomerService) -> list[dict]:
    """列出该用户的长期记忆文件及内容预览。"""
    out = []
    for key in svc.memories():
        content = read_memory(svc.store, svc.user_id, key) or ""
        out.append({"key": key, "content": content, "size": len(content)})
    return out


def _artifact_view(svc: CustomerService) -> list[dict]:
    """回收 /out/ 产物并返回 UI 需要的元数据。"""
    items = []
    for artifact, clean, hits in svc.collect():
        suffix = Path(artifact.path).suffix.lower()
        items.append({
            "path": artifact.path,
            "host_path": str(artifact.host_path),
            "size": artifact.size,
            "clean": clean,
            "hits": hits,
            "is_image": suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"),
            "url": f"/api/artifact?path={artifact.path}",
        })
    return items


def _ask_result_view(result) -> dict:
    """把 AskResult 转成 UI 的 JSON。"""
    return {
        "interrupted": result.interrupted,
        "requests": [
            {"kind": r.kind, "tool_name": r.tool_name, "description": r.description,
             "args": json_safe(r.args)}
            for r in result.requests
        ],
        "reply": result.reply,
        "state": json_safe({
            "cited_chapters": result.state.get("cited_chapters"),
            "clarified_questions": result.state.get("clarified_questions"),
            "todos": result.state.get("todos"),
        }),
    }


# ---------------------------------------------------------------------------
# 二、服务实例管理
# ---------------------------------------------------------------------------
def ensure_service(user_id: str = "local-user", thread_id: str | None = None,
                   force: bool = False) -> CustomerService:
    """获取（或重建）全局服务实例。"""
    global _SERVICE
    if _SERVICE is None or force or _SERVICE.user_id != user_id or (
        thread_id is not None and _SERVICE.thread_id != thread_id
    ):
        if _OFFLINE:
            _SERVICE = _build_offline_stub(user_id, thread_id)
        else:
            _SERVICE = build_customer_service(user_id=user_id, thread_id=thread_id)
    return _SERVICE


class _OfflineStub:
    """离线占位服务：不加载模型，仅用于验证 UI 骨架与接口连通性。

    它模拟 state 与 HITL 分支，让前端在无 API Key 的环境下也能完整走通。
    """

    def __init__(self, user_id: str, thread_id: str | None):
        self.user_id = user_id
        self.thread_id = thread_id or "offline-thread"
        self.store = None
        self.sandbox_root = SANDBOX_ROOT
        self.cfg = {"configurable": {"thread_id": self.thread_id}}
        self._values: dict = {"cited_chapters": [], "clarified_questions": [], "todos": []}

    # 模拟 agent.get_state(...).values，供 _state_view 读取
    class _Snapshot:
        def __init__(self, values):
            self.values = values

    class _Agent:
        def __init__(self, owner):
            self._owner = owner

        def get_state(self, _cfg):
            return _OfflineStub._Snapshot(self._owner._values)

    @property
    def agent(self):
        return _OfflineStub._Agent(self)

    def ask(self, question: str):
        from hitl import PendingRequest
        from service import AskResult
        # 用「后端」触发澄清分支、用 curl/rm 触发审批分支，方便离线点按 UI
        if "后端" in question and "ch" not in question:
            return AskResult(
                interrupted=True,
                requests=[PendingRequest("clarification", "ask_clarification",
                                         {"question": "你问的是哪一章的后端？"},
                                         "你问的是哪一章的后端？")],
                reply="",
            )
        if "curl" in question or "rm " in question:
            return AskResult(
                interrupted=True,
                requests=[PendingRequest("approval", "execute",
                                         {"command": question}, f"请求执行命令：{question}")],
                reply="",
            )
        if "ch" in question:
            chapter = question[question.find("ch"):question.find("ch") + 4]
            self._values["cited_chapters"] = sorted(set(self._values["cited_chapters"] + [chapter]))
        return AskResult(interrupted=False, requests=[],
                         reply=f"[离线模式] 收到问题：{question}\n（未加载模型，仅验证 UI 流程）")

    def answer(self, message: str):
        from service import AskResult
        self._values["clarified_questions"] = self._values["clarified_questions"] + [message]
        return AskResult(interrupted=False, requests=[],
                         reply=f"[离线模式] 已收到补充：{message}")

    def decide(self, *, approve: bool, message: str = ""):
        from service import AskResult
        verdict = "已批准" if approve else "已拒绝"
        return AskResult(interrupted=False, requests=[],
                         reply=f"[离线模式] 审批结果：{verdict} {message}")

    def collect(self):
        return []

    def memories(self):
        return []

    def summary(self, state=None):
        s = state or self._values
        cited = "、".join(s.get("cited_chapters") or []) or "（无）"
        clar = "；".join(s.get("clarified_questions") or []) or "（无）"
        return f"# 本次答疑小结（离线）\n\n## 涉及章节\n- {cited}\n\n## 已澄清的问题\n- {clar}"


def _build_offline_stub(user_id: str, thread_id: str | None):
    return _OfflineStub(user_id, thread_id)


# ---------------------------------------------------------------------------
# 三、HTTP 处理器
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    """极简 JSON API + 静态文件服务。"""

    server_version = "CapstoneUI/0.1"

    # -- 工具方法 --
    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(json_safe(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"error": "文件不存在"}, 404)
            return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def log_message(self, fmt, *args):  # noqa: A002 - 覆盖父类签名
        # 静音默认访问日志，避免刷屏；需要时取消注释
        # print(f"[ui] {self.address_string()} {fmt % args}")
        pass

    # -- 路由 --
    def do_GET(self) -> None:  # noqa: N802 - http.server 约定
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._send_file(UI_DIR / "index.html")
            return
        if path == "/favicon.ico":
            # 内联一个极简 SVG favicon，避免浏览器 404
            svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                '<rect width="32" height="32" rx="7" fill="#2563eb"/>'
                '<text x="16" y="22" font-size="17" text-anchor="middle" fill="#fff" '
                'font-family="sans-serif" font-weight="700">C</text></svg>'
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(svg)))
            self.end_headers()
            self.wfile.write(svg)
            return
        if path.startswith("/ui/"):
            # 只服务 ui/ 目录内的静态文件（防穿越）
            rel = path[len("/ui/"):]
            target = (UI_DIR / rel).resolve()
            try:
                target.relative_to(UI_DIR.resolve())
            except ValueError:
                self._send_json({"error": "非法路径"}, 403)
                return
            self._send_file(target)
            return
        if path == "/api/health":
            self._send_json({"ok": True, "offline": _OFFLINE,
                             "service": _SERVICE is not None})
            return
        if path == "/api/state":
            if _SERVICE is None:
                self._send_json({"error": "服务未初始化"}, 409)
                return
            self._send_json({
                "state": _state_view(_SERVICE),
                "memories": _memory_view(_SERVICE),
                "artifacts": _artifact_view(_SERVICE),
            })
            return
        if path == "/api/artifact":
            self._serve_artifact(parsed.query)
            return
        if path == "/api/check":
            self._send_json(system_check())
            return

        self._send_json({"error": f"未知路径 {path}"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        payload = self._read_json()

        try:
            if path == "/api/reset":
                user_id = str(payload.get("user_id") or "local-user")
                thread_id = payload.get("thread_id") or None
                with _LOCK:
                    svc = ensure_service(user_id=user_id, thread_id=thread_id, force=True)
                self._send_json({"ok": True, "state": _state_view(svc)})
                return

            if path == "/api/ask":
                question = str(payload.get("question") or "").strip()
                if not question:
                    self._send_json({"error": "问题为空"}, 400)
                    return
                with _LOCK:
                    svc = ensure_service(user_id=str(payload.get("user_id") or "local-user"))
                    result = svc.ask(question)
                self._send_json(_ask_result_view(result))
                return

            if path == "/api/answer":
                message = str(payload.get("message") or "").strip()
                if not message:
                    self._send_json({"error": "补充内容为空"}, 400)
                    return
                with _LOCK:
                    svc = ensure_service()
                    result = svc.answer(message)
                self._send_json(_ask_result_view(result))
                return

            if path == "/api/decide":
                with _LOCK:
                    svc = ensure_service()
                    result = svc.decide(
                        approve=bool(payload.get("approve")),
                        message=str(payload.get("message") or ""),
                    )
                self._send_json(_ask_result_view(result))
                return

            if path == "/api/summary":
                with _LOCK:
                    svc = ensure_service()
                    state = svc.agent.get_state(svc.cfg).values if hasattr(svc, "agent") else {}
                    text = svc.summary(state)
                self._send_json({"summary": text})
                return

        except Exception as exc:  # noqa: BLE001 - UI 需要把错误显示出来而不是断开
            traceback.print_exc()
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return

        self._send_json({"error": f"未知路径 {path}"}, 404)

    def _serve_artifact(self, query: str) -> None:
        """只允许读取沙箱 /out/ 下的产物，防止路径穿越。"""
        params = parse_qs(query)
        rel = (params.get("path") or [""])[0]
        if not rel.startswith("/out/"):
            self._send_json({"error": "只允许读取 /out/ 下的产物"}, 403)
            return
        # 先按字面路径拼接，再 resolve 掉 .. 与符号链接，最后确认仍落在 /out/ 内。
        # 不能只判断「在 SANDBOX_ROOT 内」——/out/../knowledge/x 也满足那一条。
        out_root = (SANDBOX_ROOT / "out").resolve()
        target = (SANDBOX_ROOT / rel.lstrip("/")).resolve()
        try:
            target.relative_to(out_root)
        except ValueError:
            self._send_json({"error": "非法路径"}, 403)
            return
        self._send_file(target)


# ---------------------------------------------------------------------------
# 四、入口
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    global _OFFLINE
    parser = argparse.ArgumentParser(description="capstone 测试用 Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--offline", action="store_true", help="离线模式：不加载模型")
    parser.add_argument("--user", default="local-user", help="初始用户身份")
    args = parser.parse_args(argv)

    _OFFLINE = args.offline
    if not _OFFLINE:
        print("正在初始化客服系统（首次需加载模型与沙箱）……", flush=True)
    # 两种模式都在启动时初始化，这样打开页面就能看到 state/记忆/产物面板
    ensure_service(user_id=args.user, force=True)
    if not _OFFLINE:
        print("初始化完成。")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    mode = "离线模式" if _OFFLINE else "在线模式"
    url = f"http://{args.host}:{args.port}"
    print(f"\n  capstone 测试 UI（{mode}）已启动：{url}\n")
    print("  Ctrl+C 停止\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
