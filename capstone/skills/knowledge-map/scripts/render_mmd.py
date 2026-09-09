#!/usr/bin/env python3
# ============================================================================
# render_mmd.py —— knowledge-map 技能的渲染脚本
#
# 职责：把 Mermaid 源文件（.mmd）渲染成 PNG。
#
# 两级引擎（自动降级，失败会如实报错，不假装成功）：
#   1. mmdc（@mermaid-js/mermaid-cli）：功能最全，需要 Node + Chrome。
#   2. 内置渲染器：纯 Python 解析 Mermaid 子集（flowchart / mindmap），
#      生成 SVG 后交给 Chrome headless 或 macOS qlmanage 转 PNG。
#
# 用法：
#   python3 render_mmd.py <input.mmd> <output.png> [--scale 3] [--theme light|dark]
#
# 退出码：0 成功；1 参数/文件错误；2 两种引擎都失败。
#
# 设计说明（对应 ch10）：
#   - 本脚本在沙箱内执行，cwd 是沙箱根，所以路径用相对路径；
#   - 输出写到 /out/（虚拟路径）→ 宿主侧相对路径 out/；
#   - 不访问网络、不安装依赖、不修改知识库。
# ============================================================================

"""把 Mermaid 源文件渲染成 PNG（mmdc 优先，内置渲染器兜底）。"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

# 常见 Chrome/Chromium 可执行文件位置（用于 mmdc 与 SVG 转 PNG）
_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
    shutil.which("chrome") or "",
)


def find_chrome() -> str | None:
    """返回可用的 Chrome/Chromium 路径，找不到返回 None。"""
    for path in _CHROME_CANDIDATES:
        if path and Path(path).exists():
            return path
    return None


def strip_comments(text: str) -> str:
    """去掉 Mermaid 的 %% 注释行（保留空行结构）。"""
    return "\n".join(
        "" if line.strip().startswith("%%") else line for line in text.splitlines()
    )


def detect_kind(text: str) -> str:
    """检测图类型：flowchart / mindmap / unknown。"""
    for line in strip_comments(text).splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("mindmap"):
            return "mindmap"
        if re.match(r"^(graph|flowchart)\b", s):
            return "flowchart"
    return "unknown"


# ---------------------------------------------------------------------------
# 引擎一：mmdc（mermaid-cli）
# ---------------------------------------------------------------------------
def render_with_mmdc(src: Path, out: Path, *, scale: int) -> tuple[bool, str]:
    """尝试用 mmdc 渲染。返回 (是否成功, 信息)。"""
    npx = shutil.which("npx")
    if not npx:
        return False, "未找到 npx（需要 Node.js）"

    chrome = find_chrome()
    with tempfile.TemporaryDirectory(prefix="mmdc_") as tmp:
        cfg = Path(tmp) / "puppeteer.json"
        payload: dict = {"args": ["--no-sandbox", "--disable-gpu"]}
        if chrome:
            payload["executablePath"] = chrome
        cfg.write_text(json.dumps(payload), encoding="utf-8")

        cmd = [
            npx, "-y", "@mermaid-js/mermaid-cli@11",
            "-i", str(src), "-o", str(out),
            "-b", "white", "-s", str(scale), "-p", str(cfg),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return False, "mmdc 渲染超时（300s）"
        except OSError as exc:
            return False, f"mmdc 启动失败：{exc}"

    if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
        return True, "mmdc"
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, detail[-1] if detail else f"mmdc 退出码 {proc.returncode}"


# ---------------------------------------------------------------------------
# 引擎二：内置 Mermaid 子集渲染器
# ---------------------------------------------------------------------------
@dataclass
class _Node:
    """一个图节点。"""

    nid: str
    label: str
    shape: str = "rect"          # rect / diamond / round
    depth: int = 0               # 布局深度
    order: int = 0               # 同层顺序
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    parent: str | None = None    # mindmap 用


@dataclass
class _Edge:
    """一条有向边。"""

    src: str
    dst: str
    label: str = ""


@dataclass
class _Graph:
    """解析结果。"""

    kind: str = "flowchart"
    direction: str = "LR"
    nodes: dict[str, _Node] = field(default_factory=dict)
    edges: list[_Edge] = field(default_factory=list)
    root: str | None = None

    def node(self, nid: str, label: str | None = None, shape: str = "rect") -> _Node:
        """按需创建/更新节点。"""
        if nid not in self.nodes:
            self.nodes[nid] = _Node(nid=nid, label=label or nid, shape=shape)
        elif label:
            self.nodes[nid].label = label
            self.nodes[nid].shape = shape
        return self.nodes[nid]


# 匹配 `A[label]` / `A{label}` / `A(label)` / `A((label))`
_NODE_DEF = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*(\(\(|\[|\{|\()\s*(.*?)\s*(\)\)|\]|\}|\))\s*$")
# 匹配边两端的节点 token：`A` 或 `A[label]` 或 `A{label}`（用于从边里提取内联定义）
_ENDPOINT = re.compile(
    r"^\s*([A-Za-z_][\w-]*)\s*(?:(\(\(|\[|\{|\()\s*(.*?)\s*(?:\)\)|\]|\}|\)))?\s*$"
)
# 匹配 `A --> B` / `A -->|label| B` / `A --- B`（两端可带内联节点定义）
_EDGE = re.compile(
    r"^\s*([A-Za-z_][\w-]*(?:\s*(?:\(\(|\[|\{|\()[^\n]*?(?:\)\)|\]|\}|\)))?)"
    r"\s*(?:-->|---|==>|-\.->)\s*(?:\|([^|]*)\|\s*)?"
    r"([A-Za-z_][\w-]*(?:\s*(?:\(\(|\[|\{|\()[^\n]*?(?:\)\)|\]|\}|\)))?)\s*$"
)


def _shape_of(open_tok: str) -> str:
    return {"[": "rect", "{": "diamond", "(": "round", "((": "round"}[open_tok]


def _add_endpoint(g: _Graph, token: str) -> str:
    """从边的端点 token 提取节点并返回其 id（支持内联 `A[label]`）。"""
    token = token.strip()
    m = _ENDPOINT.match(token)
    if not m:
        # 兜底：取开头的合法 id
        bare = re.match(r"^([A-Za-z_][\w-]*)", token)
        nid = bare.group(1) if bare else token
        g.node(nid)
        return nid
    nid, open_tok, label = m.group(1), m.group(2), m.group(3)
    if open_tok:
        g.node(nid, (label or "").strip(), _shape_of(open_tok))
    else:
        g.node(nid)
    return nid


def parse_flowchart(text: str) -> _Graph:
    """解析 flowchart/graph 的节点与边。"""
    g = _Graph(kind="flowchart")
    for raw in strip_comments(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        m_dir = re.match(r"^(?:graph|flowchart)\s+(LR|RL|TD|TB|BT)?", line, re.IGNORECASE)
        if m_dir:
            g.direction = (m_dir.group(1) or "LR").upper()
            continue
        # 边优先（含 -->|label|）；两端可带内联节点定义
        m_edge = _EDGE.match(line)
        if m_edge:
            src = _add_endpoint(g, m_edge.group(1))
            label = (m_edge.group(2) or "").strip()
            dst = _add_endpoint(g, m_edge.group(3))
            g.edges.append(_Edge(src=src, dst=dst, label=label))
            continue
        # 节点定义（可能一行多个，用分号分隔）
        for part in [p.strip() for p in line.split(";") if p.strip()]:
            m_node = _NODE_DEF.match(part)
            if m_node:
                nid, open_tok, label, _close = m_node.groups()
                g.node(nid, label, _shape_of(open_tok))
            else:
                bare = re.match(r"^([A-Za-z_][\w-]*)$", part)
                if bare:
                    g.node(bare.group(1))
    return g


def parse_mindmap(text: str) -> _Graph:
    """解析 mindmap 的缩进层级树。"""
    g = _Graph(kind="mindmap")
    stack: list[tuple[int, str]] = []   # (indent, node_id)
    counter = 0

    for raw in strip_comments(text).splitlines():
        if not raw.strip():
            continue
        if raw.strip().lower().startswith("mindmap"):
            continue
        indent = len(raw) - len(raw.lstrip(" \t"))
        content = raw.strip()
        # 根节点 `((label))` 或 `root((label))`
        m_root = re.match(r"^(?:root\s*)?\(\((.*?)\)\)$", content)
        if m_root and g.root is None:
            counter += 1
            nid = f"M{counter}"
            g.node(nid, m_root.group(1).strip(), "round")
            g.root = nid
            stack = [(indent, nid)]
            continue
        # 普通分支：去掉可能的 id 前缀 `A[label]`
        m_node = _NODE_DEF.match(content)
        if m_node:
            label = m_node.group(3)
        else:
            label = content
        counter += 1
        nid = f"M{counter}"
        g.node(nid, label, "rect")
        # 找到最近的更浅层级作为父节点
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            g.nodes[nid].parent = stack[-1][1]
            g.edges.append(_Edge(src=stack[-1][1], dst=nid))
        elif g.root is None:
            g.root = nid
        stack.append((indent, nid))
    return g


# ---- 文本宽度估算（中文按 1.0 em，ASCII 按 0.58 em）-------------------------
def _text_width(text: str, font_size: float) -> float:
    width = 0.0
    for ch in text:
        width += font_size * (1.0 if ord(ch) > 0x2E80 else 0.58)
    return width


def _layout(g: _Graph, *, font_size: float = 16.0) -> None:
    """计算节点坐标与尺寸（分层布局）。"""
    pad_x, pad_y = 26.0, 16.0

    if g.kind == "mindmap":
        _layout_tree(g, font_size=font_size, pad_x=pad_x, pad_y=pad_y)
        return

    # flowchart：按 BFS 计算深度
    if not g.nodes:
        return
    adj: dict[str, list[str]] = {nid: [] for nid in g.nodes}
    indeg: dict[str, int] = {nid: 0 for nid in g.nodes}
    for e in g.edges:
        if e.src in adj and e.dst in g.nodes:
            adj[e.src].append(e.dst)
            indeg[e.dst] += 1
    roots = [n for n in g.nodes if indeg[n] == 0] or list(g.nodes)[:1]
    depth: dict[str, int] = {}
    queue = [(r, 0) for r in roots]
    while queue:
        nid, d = queue.pop(0)
        if nid in depth and depth[nid] <= d:
            continue
        depth[nid] = d
        for nxt in adj.get(nid, []):
            queue.append((nxt, d + 1))
    for nid in g.nodes:
        depth.setdefault(nid, 0)

    # 尺寸
    for n in g.nodes.values():
        n.w = max(90.0, _text_width(n.label, font_size) + pad_x * 2)
        n.h = font_size + pad_y * 2
        n.depth = depth[n.nid]

    layers: dict[int, list[_Node]] = {}
    for n in g.nodes.values():
        layers.setdefault(n.depth, []).append(n)
    for d, items in layers.items():
        items.sort(key=lambda n: n.nid)

    # 用 barycenter 启发式降低边交叉：迭代若干轮，按邻居平均位置重排同层节点
    _reduce_crossings(g, layers, iterations=6)

    for d, items in layers.items():
        for i, n in enumerate(items):
            n.order = i

    horizontal = g.direction in ("LR", "RL")
    gap_main, gap_cross = 70.0, 34.0
    # 每层主方向偏移
    layer_extent: dict[int, float] = {}
    for d, items in layers.items():
        if horizontal:
            layer_extent[d] = max(n.w for n in items)
        else:
            layer_extent[d] = max(n.h for n in items)

    main_cursor = 0.0
    layer_main: dict[int, float] = {}
    for d in sorted(layers):
        layer_main[d] = main_cursor
        main_cursor += layer_extent[d] + gap_main

    for d, items in layers.items():
        cross_cursor = 0.0
        total_cross = sum((n.h if horizontal else n.w) for n in items) + gap_cross * max(0, len(items) - 1)
        start = -total_cross / 2.0
        for n in items:
            if horizontal:
                n.x = layer_main[d]
                n.y = start + cross_cursor
                cross_cursor += n.h + gap_cross
            else:
                n.x = start + cross_cursor
                n.y = layer_main[d]
                cross_cursor += n.w + gap_cross

    # 平移为正值
    min_x = min((n.x for n in g.nodes.values()), default=0.0)
    min_y = min((n.y for n in g.nodes.values()), default=0.0)
    for n in g.nodes.values():
        n.x -= min_x - 40.0
        n.y -= min_y - 40.0


def _reduce_crossings(g: _Graph, layers: dict[int, list[_Node]], *, iterations: int = 6) -> None:
    """用 barycenter 启发式重排同层节点，降低边交叉。

    思路：每轮先自左向右按「前一层邻居的平均序位」排序，再自右向左按
    「后一层邻居的平均序位」排序；取序位平均值（barycenter）。这是分层图
    布局的标准降交叉启发式，实现简单且效果明显。
    """
    preds: dict[str, list[str]] = {nid: [] for nid in g.nodes}
    succs: dict[str, list[str]] = {nid: [] for nid in g.nodes}
    for e in g.edges:
        if e.src in g.nodes and e.dst in g.nodes:
            succs[e.src].append(e.dst)
            preds[e.dst].append(e.src)

    depths = sorted(layers)

    def order_index() -> dict[str, int]:
        return {n.nid: i for d in depths for i, n in enumerate(layers[d])}

    for _ in range(iterations):
        # 正向：按前驱平均位置排序
        idx = order_index()
        for d in depths[1:]:
            def key_fwd(n: _Node) -> tuple[float, int]:
                positions = [idx[p] for p in preds.get(n.nid, []) if p in idx]
                bary = sum(positions) / len(positions) if positions else float(idx.get(n.nid, 0))
                return (bary, idx.get(n.nid, 0))
            layers[d].sort(key=key_fwd)
            idx = order_index()
        # 反向：按后继平均位置排序
        for d in reversed(depths[:-1]):
            def key_bwd(n: _Node) -> tuple[float, int]:
                positions = [idx[s] for s in succs.get(n.nid, []) if s in idx]
                bary = sum(positions) / len(positions) if positions else float(idx.get(n.nid, 0))
                return (bary, idx.get(n.nid, 0))
            layers[d].sort(key=key_bwd)
            idx = order_index()


def _layout_tree(g: _Graph, *, font_size: float, pad_x: float, pad_y: float) -> None:
    """mindmap 的横向树布局：根在左，子树向右展开。"""
    for n in g.nodes.values():
        n.w = max(90.0, _text_width(n.label, font_size) + pad_x * 2)
        n.h = font_size + pad_y * 2

    children: dict[str, list[str]] = {nid: [] for nid in g.nodes}
    for e in g.edges:
        children.setdefault(e.src, []).append(e.dst)

    row_gap = 14.0
    col_gap = 64.0
    cursor = [0.0]

    def place(nid: str, depth: int) -> float:
        kids = children.get(nid, [])
        node = g.nodes[nid]
        node.depth = depth
        if not kids:
            node.y = cursor[0]
            cursor[0] += node.h + row_gap
        else:
            ys = [place(k, depth + 1) for k in kids]
            node.y = (ys[0] + ys[-1]) / 2.0
        return node.y

    root = g.root or next(iter(g.nodes), None)
    if root is None:
        return
    place(root, 0)

    # 主方向 x：按深度累加每层最大宽度
    depth_w: dict[int, float] = {}
    for n in g.nodes.values():
        depth_w[n.depth] = max(depth_w.get(n.depth, 0.0), n.w)
    depth_x: dict[int, float] = {}
    x = 40.0
    for d in sorted(depth_w):
        depth_x[d] = x
        x += depth_w[d] + col_gap
    for n in g.nodes.values():
        n.x = depth_x[n.depth]

    min_y = min((n.y for n in g.nodes.values()), default=0.0)
    for n in g.nodes.values():
        n.y = n.y - min_y + 40.0


def _svg_escape(text: str) -> str:
    return html.escape(text, quote=True)


def _svg_shape(n: _Node) -> str:
    """按节点形状生成 SVG 元素。"""
    x, y, w, h = n.x, n.y, n.w, n.h
    cx, cy = x + w / 2, y + h / 2
    label = _svg_escape(n.label)
    text_attrs = (
        f'x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle" dominant-baseline="central" '
        f'font-family="PingFang SC, Hiragino Sans GB, Microsoft YaHei, Helvetica, sans-serif" '
        f'font-size="16" fill="#0f172a"'
    )
    if n.shape == "diamond":
        pts = f"{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}"
        body = f'<polygon points="{pts}" fill="#fef3c7" stroke="#f59e0b" stroke-width="1.6"/>'
    elif n.shape == "round":
        body = (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{h / 2:.1f}" fill="#e0e7ff" stroke="#6366f1" stroke-width="1.6"/>'
        )
    else:
        body = (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8" '
            f'fill="#dbeafe" stroke="#3b82f6" stroke-width="1.6"/>'
        )
    return body + f"<text {text_attrs}>{label}</text>"


def _svg_edges(g: _Graph) -> str:
    """生成带箭头的边（含标签）。"""
    out: list[str] = []
    for e in g.edges:
        a, b = g.nodes.get(e.src), g.nodes.get(e.dst)
        if a is None or b is None:
            continue
        # 从 a 的右/下边缘到 b 的左/上边缘
        if g.kind == "mindmap" or g.direction in ("LR", "RL"):
            x1, y1 = a.x + a.w, a.y + a.h / 2
            x2, y2 = b.x, b.y + b.h / 2
            if x2 < x1:  # 反向，从左边缘出发
                x1, x2 = a.x, b.x + b.w
        else:
            x1, y1 = a.x + a.w / 2, a.y + a.h
            x2, y2 = b.x + b.w / 2, b.y
        out.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#64748b" stroke-width="1.6" marker-end="url(#arrow)"/>'
        )
        if e.label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            lw = _text_width(e.label, 12) + 12
            out.append(
                f'<rect x="{mx - lw / 2:.1f}" y="{my - 11:.1f}" width="{lw:.1f}" height="22" '
                f'rx="6" fill="#ffffff" stroke="#e2e8f0"/>'
                f'<text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" dominant-baseline="central" '
                f'font-family="PingFang SC, Hiragino Sans GB, Helvetica, sans-serif" '
                f'font-size="12" fill="#475569">{_svg_escape(e.label)}</text>'
            )
    return "".join(out)


def graph_to_svg(g: _Graph, *, title: str = "") -> str:
    """把解析后的图渲染成独立 SVG 字符串。"""
    _layout(g)
    nodes = list(g.nodes.values())
    width = max((n.x + n.w for n in nodes), default=200.0) + 40.0
    height = max((n.y + n.h for n in nodes), default=100.0) + 40.0

    body = "".join(_svg_shape(n) for n in nodes)
    edges = _svg_edges(g)
    header = ""
    if title:
        header = (
            f'<text x="20" y="26" font-family="PingFang SC, Helvetica, sans-serif" '
            f'font-size="15" fill="#334155">{_svg_escape(title)}</text>'
        )
        body = f'<g transform="translate(0,28)">{body}</g>'
        edges = f'<g transform="translate(0,28)">{edges}</g>'
        height += 28

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}">'
        f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b"/></marker></defs>'
        f'<rect width="{width:.0f}" height="{height:.0f}" fill="#ffffff"/>'
        f"{header}{edges}{body}</svg>"
    )


def svg_to_png(svg: str, out: Path, *, scale: int = 2, width: int, height: int) -> tuple[bool, str]:
    """把 SVG 转成 PNG：优先 Chrome headless，其次 macOS qlmanage。"""
    chrome = find_chrome()
    with tempfile.TemporaryDirectory(prefix="svg2png_") as tmp:
        svg_path = Path(tmp) / "diagram.svg"
        html_path = Path(tmp) / "diagram.html"
        svg_path.write_text(svg, encoding="utf-8")
        html_path.write_text(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>html,body{margin:0;padding:0;background:#fff}"
            "svg{display:block}</style></head><body>" + svg + "</body></html>",
            encoding="utf-8",
        )
        if chrome:
            cmd = [
                chrome, "--headless", "--disable-gpu", "--no-sandbox",
                "--hide-scrollbars", f"--force-device-scale-factor={scale}",
                f"--window-size={width},{height}",
                f"--screenshot={out}", str(html_path),
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            except (subprocess.TimeoutExpired, OSError) as exc:
                return False, f"Chrome 转 PNG 失败：{exc}"
            if out.exists() and out.stat().st_size > 0:
                return True, "chrome"
            return False, (proc.stderr or "").strip().splitlines()[-1:] and proc.stderr.strip().splitlines()[-1] or "Chrome 未产出 PNG"

        # 回退：macOS qlmanage
        ql = shutil.which("qlmanage")
        if ql:
            try:
                proc = subprocess.run(
                    [ql, "-t", "-s", str(max(width, height) * scale), "-o", tmp, str(svg_path)],
                    capture_output=True, text=True, timeout=120,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                return False, f"qlmanage 失败：{exc}"
            produced = Path(tmp) / (svg_path.name + ".png")
            if produced.exists():
                shutil.copyfile(produced, out)
                return True, "qlmanage"
            return False, "qlmanage 未产出 PNG"
    return False, "未找到 Chrome 或 qlmanage，无法把 SVG 转成 PNG"


def render_with_builtin(src: Path, out: Path, *, scale: int) -> tuple[bool, str]:
    """内置渲染器：解析 Mermaid 子集 → SVG → PNG。"""
    text = src.read_text(encoding="utf-8")
    kind = detect_kind(text)
    if kind == "unknown":
        return False, "内置渲染器无法识别图类型（只支持 flowchart/graph 与 mindmap）"
    g = parse_mindmap(text) if kind == "mindmap" else parse_flowchart(text)
    if not g.nodes:
        return False, "未解析到任何节点（检查语法与缩进）"

    svg = graph_to_svg(g, title=f"{kind} · {len(g.nodes)} nodes / {len(g.edges)} edges")
    # 从 SVG 头部读回画布尺寸
    m = re.search(r'width="(\d+)" height="(\d+)"', svg)
    width, height = (int(m.group(1)), int(m.group(2))) if m else (800, 600)
    ok, engine = svg_to_png(svg, out, scale=scale, width=width, height=height)
    if not ok:
        # 至少把 SVG 留下来，便于人工排查
        svg_out = out.with_suffix(".svg")
        svg_out.write_text(svg, encoding="utf-8")
        return False, f"{engine}；已保留 SVG：{svg_out}"
    return True, f"builtin({engine})"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def render(src: Path, out: Path, *, scale: int, engine: str = "auto") -> tuple[bool, str]:
    """按引擎策略渲染，返回 (是否成功, 引擎信息)。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    attempts: list[str] = []

    if engine in ("auto", "mmdc"):
        ok, info = render_with_mmdc(src, out, scale=scale)
        if ok:
            return True, info
        attempts.append(f"mmdc: {info}")
        if engine == "mmdc":
            return False, attempts[-1]

    if engine in ("auto", "builtin"):
        ok, info = render_with_builtin(src, out, scale=scale)
        if ok:
            return True, info
        attempts.append(f"builtin: {info}")

    return False, " | ".join(attempts) or "无可用渲染引擎"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 Mermaid 源文件渲染成 PNG")
    parser.add_argument("input", type=Path, help="输入 .mmd 文件")
    parser.add_argument("output", type=Path, help="输出 .png 文件")
    parser.add_argument("--scale", type=int, default=3, help="缩放倍数（默认 3）")
    parser.add_argument(
        "--engine", choices=("auto", "mmdc", "builtin"), default="auto",
        help="渲染引擎：auto 先 mmdc 后内置（默认）；也可强制指定",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"错误：输入文件不存在：{args.input}", file=sys.stderr)
        return 1
    if args.input.suffix.lower() not in (".mmd", ".mermaid"):
        print(f"错误：输入应为 .mmd 文件，得到 {args.input.suffix}", file=sys.stderr)
        return 1

    ok, info = render(args.input, args.output, scale=args.scale, engine=args.engine)
    if ok:
        size = args.output.stat().st_size if args.output.exists() else 0
        print(f"渲染成功（{info}）→ {args.output}（{size} 字节）")
        return 0
    print(f"渲染失败：{info}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
