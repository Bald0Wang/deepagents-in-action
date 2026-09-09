"""确定性测试：knowledge-map 渲染脚本（无 LLM、无 mmdc 依赖）。

覆盖：
  - Mermaid 子集解析（flowchart / mindmap）
  - 内置渲染器产出 PNG
  - 语法错误时如实失败（不假装成功）
  - 技能自带的两张示例图都能渲染
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

CAPSTONE = Path(__file__).resolve().parent.parent
SCRIPT = CAPSTONE / "skills" / "knowledge-map" / "scripts" / "render_mmd.py"
ASSETS = CAPSTONE / "skills" / "knowledge-map" / "assets"


def _load_render_module():
    """按路径加载渲染脚本模块（它不在包内）。"""
    spec = importlib.util.spec_from_file_location("render_mmd", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["render_mmd"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def render_mod():
    return _load_render_module()


def test_detect_kind(render_mod):
    assert render_mod.detect_kind("graph LR\n A-->B") == "flowchart"
    assert render_mod.detect_kind("flowchart TD\n A-->B") == "flowchart"
    assert render_mod.detect_kind("mindmap\n  root((x))") == "mindmap"
    assert render_mod.detect_kind("%% comment only") == "unknown"


def test_parse_flowchart(render_mod):
    g = render_mod.parse_flowchart("graph LR\n A[用户] -->|进入| B{路由}\n B --> C[后端]")
    assert set(g.nodes) == {"A", "B", "C"}
    assert g.nodes["A"].label == "用户"
    assert g.nodes["B"].shape == "diamond"
    assert len(g.edges) == 2
    assert g.edges[0].label == "进入"


def test_parse_mindmap(render_mod):
    text = "mindmap\n  root((主题))\n    分支一\n      子项\n    分支二\n"
    g = render_mod.parse_mindmap(text)
    assert g.root is not None
    assert len(g.nodes) == 4
    # 根有两个子节点
    assert len(g.edges) == 3


def test_builtin_render_produces_png(render_mod):
    """内置渲染器应产出非空 PNG（依赖 Chrome 或 qlmanage）。"""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.png"
        ok, info = render_mod.render_with_builtin(ASSETS / "knowledge-graph.mmd", out, scale=1)
        assert ok, info
        assert out.exists() and out.stat().st_size > 1000


def test_mindmap_asset_renders(render_mod):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "mind.png"
        ok, info = render_mod.render_with_builtin(ASSETS / "mindmap.mmd", out, scale=1)
        assert ok, info
        assert out.exists() and out.stat().st_size > 1000


def test_unknown_syntax_fails_honestly(render_mod):
    """无法识别的语法要如实失败，不能假装成功。"""
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.mmd"
        bad.write_text("sequenceDiagram\n  A->>B: hi\n", encoding="utf-8")
        out = Path(tmp) / "bad.png"
        ok, info = render_mod.render_with_builtin(bad, out, scale=1)
        assert not ok
        assert "无法识别" in info or "未解析到" in info


def test_missing_input_returns_error(render_mod):
    with tempfile.TemporaryDirectory() as tmp:
        rc = render_mod.main([str(Path(tmp) / "nope.mmd"), str(Path(tmp) / "o.png")])
        assert rc == 1


def test_cli_render_asset(render_mod):
    """通过 CLI 渲染示例图（builtin 引擎，避免依赖 mmdc）。"""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "cli.png"
        rc = render_mod.main([
            str(ASSETS / "knowledge-graph.mmd"), str(out), "--scale", "1", "--engine", "builtin",
        ])
        assert rc == 0
        assert out.exists() and out.stat().st_size > 1000
