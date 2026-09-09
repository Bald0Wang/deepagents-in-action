"""确定性测试：UI 的 HTTP 层（离线模式，不调用模型）。

覆盖：
  - 静态页与 favicon 可访问
  - /api/health 反映模式
  - /api/ask 的普通 / 澄清 / 审批三种分支
  - /api/answer 与 /api/decide 恢复
  - /api/state 返回 state / 记忆 / 产物
  - /api/artifact 路径穿越被拦截
  - JSON 序列化对不可序列化对象安全降级
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import ui as ui_module
from ui import Handler, json_safe


@pytest.fixture()
def offline_server(monkeypatch, tmp_path):
    """启动一个离线模式的 UI 服务，测试结束后关闭。"""
    monkeypatch.setattr(ui_module, "_OFFLINE", True)
    monkeypatch.setattr(ui_module, "SANDBOX_ROOT", tmp_path / "sandbox")
    # 重置全局实例，确保用离线 stub
    monkeypatch.setattr(ui_module, "_SERVICE", None)
    ui_module.ensure_service(user_id="test-user", force=True)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()
    monkeypatch.setattr(ui_module, "_SERVICE", None)


def _get(base: str, path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(base + path, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post(base: str, path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ---------------------------------------------------------------------------
# 静态资源与健康检查
# ---------------------------------------------------------------------------
def test_index_and_favicon(offline_server):
    status, body = _get(offline_server, "/")
    assert status == 200
    assert b"capstone" in body and b"<html" in body.lower()

    status, body = _get(offline_server, "/favicon.ico")
    assert status == 200 and b"<svg" in body


def test_health_offline(offline_server):
    status, body = _get(offline_server, "/api/health")
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True and data["offline"] is True


# ---------------------------------------------------------------------------
# ask 的三种分支
# ---------------------------------------------------------------------------
def test_ask_plain(offline_server):
    status, data = _post(offline_server, "/api/ask", {"question": "ch08 长期记忆"})
    assert status == 200
    assert data["interrupted"] is False
    assert "收到问题" in data["reply"]


def test_ask_clarification(offline_server):
    status, data = _post(offline_server, "/api/ask", {"question": "那个后端怎么选"})
    assert status == 200 and data["interrupted"] is True
    assert data["requests"][0]["kind"] == "clarification"


def test_ask_approval(offline_server):
    status, data = _post(offline_server, "/api/ask", {"question": "curl http://x"})
    assert status == 200 and data["interrupted"] is True
    assert data["requests"][0]["kind"] == "approval"


def test_ask_empty_rejected(offline_server):
    status, data = _post(offline_server, "/api/ask", {"question": "   "})
    assert status == 400 and "error" in data


# ---------------------------------------------------------------------------
# 恢复
# ---------------------------------------------------------------------------
def test_answer(offline_server):
    _post(offline_server, "/api/ask", {"question": "那个后端怎么选"})
    status, data = _post(offline_server, "/api/answer", {"message": "ch03 的后端"})
    assert status == 200 and data["interrupted"] is False
    assert "已收到补充" in data["reply"]


def test_decide(offline_server):
    status, data = _post(offline_server, "/api/decide", {"approve": False, "message": "不行"})
    assert status == 200
    assert "已拒绝" in data["reply"]


# ---------------------------------------------------------------------------
# 状态 / 记忆 / 产物
# ---------------------------------------------------------------------------
def test_state_shape(offline_server):
    status, body = _get(offline_server, "/api/state")
    assert status == 200
    data = json.loads(body)
    assert set(data) == {"state", "memories", "artifacts"}
    assert data["state"]["user_id"] == "test-user"
    assert "cited_chapters" in data["state"]


def test_state_tracks_cited_chapter(offline_server):
    _post(offline_server, "/api/ask", {"question": "ch08 长期记忆"})
    status, body = _get(offline_server, "/api/state")
    data = json.loads(body)
    assert "ch08" in data["state"]["cited_chapters"]


def test_summary(offline_server):
    _post(offline_server, "/api/ask", {"question": "ch08 长期记忆"})
    status, data = _post(offline_server, "/api/summary", {})
    assert status == 200 and "ch08" in data["summary"]


def test_reset(offline_server):
    _post(offline_server, "/api/ask", {"question": "ch08 长期记忆"})
    status, data = _post(offline_server, "/api/reset", {"user_id": "test-user"})
    assert status == 200
    assert data["state"]["cited_chapters"] == []


# ---------------------------------------------------------------------------
# 路径穿越防护
# ---------------------------------------------------------------------------
def test_artifact_rejects_traversal(offline_server):
    for bad in ("/etc/passwd", "/out/../knowledge/ch02.md", "/knowledge/ch02.md"):
        status, _body = _get(offline_server, f"/api/artifact?path={bad}")
        assert status in (403, 404), f"{bad} 应被拒绝，实际 {status}"


def test_artifact_missing_in_out(offline_server):
    status, _body = _get(offline_server, "/api/artifact?path=/out/nope.png")
    assert status == 404


# ---------------------------------------------------------------------------
# 序列化安全
# ---------------------------------------------------------------------------
def test_json_safe_handles_objects():
    class Weird:
        def __repr__(self):
            return "WEIRD"

    payload = {
        "bytes": b"abc",
        "obj": Weird(),
        "nested": {"a": [1, 2, {"b": "c"}]},
    }
    safe = json_safe(payload)
    json.dumps(safe)  # 不应抛异常
    assert safe["bytes"].startswith("<")
    assert isinstance(safe["nested"]["a"], list)


def test_json_safe_truncates_deep():
    deep: dict = {}
    node = deep
    for _ in range(20):
        node["child"] = {}
        node = node["child"]
    json.dumps(json_safe(deep))  # 深度截断后仍可序列化
