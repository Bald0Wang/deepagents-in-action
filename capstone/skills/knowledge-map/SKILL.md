---
name: knowledge-map
description: 当用户要求绘制知识图谱、概念关系图、思维导图、学习脉络图，或把一章/多章内容整理成可视化结构时使用此技能。支持 Mermaid 图谱与 Markdown 大纲思维导图，并渲染成 PNG。
---

# knowledge-map

## Overview

把课程章节内容整理成两类可视化产物：

| 产物 | 语法 | 适用 |
|---|---|---|
| **知识图谱**（knowledge graph） | Mermaid `flowchart` | 概念之间的关系、依赖、层级 |
| **思维导图**（mind map） | Mermaid `mindmap` 或 Markdown 缩进大纲 | 单章知识点的发散式展开 |

本技能在沙箱内工作：源码写在 `/workspace/`，渲染产物写到 `/out/`。

## Instructions

### 1. 明确绘图对象与类型
- 用户说「知识图谱 / 关系图 / 依赖」→ 用 `flowchart`（`graph LR` / `graph TD`）。
- 用户说「思维导图 / 大纲 / 脉络」→ 用 `mindmap`（或 Markdown 缩进）。
- 用户没说 → 先问一句（或用 `ask_clarification`）：想要关系图谱还是思维导图？

### 2. 收集事实
用 `read_file` 读取相关章节的知识库文件（`/knowledge/ch0X.md`），
**只使用知识库里出现过的概念与关系**，不要凭印象补充节点。

### 3. 编写 Mermaid 源文件
- 知识图谱模板见 `/skills/knowledge-map/assets/knowledge-graph.mmd`。
- 思维导图模板见 `/skills/knowledge-map/assets/mindmap.mmd`。
- 节点文案控制在 **12 个汉字以内**；一张图不超过 **25 个节点**。
- 节点 id 用英文/数字（`A1`、`VFS`），显示文案用中文。
- 关系边的标签用动词（「路由到」「继承自」「保护」）。

### 4. 渲染成 PNG
把 `.mmd` 源文件写到 `/workspace/`，然后调用渲染脚本：

```bash
python3 skills/knowledge-map/scripts/render_mmd.py workspace/graph.mmd out/graph.png --scale 3
```

（注意：`execute` 的 cwd 是沙箱根，用相对路径；文件工具用虚拟路径 `/workspace/graph.mmd`。）

渲染脚本会优先用 `mmdc`（mermaid-cli），失败则回退到内置 SVG 渲染器。
**渲染失败时不要假装成功**：把错误原文返回，并给出「检查语法」的建议。

### 5. 交付
- 产物写到 `/out/`（会被宿主回收审查）。
- 回复里给出：① 产物路径；② 图的节点数/边数；③ 一句话说明图的结构。
- 同时把 Mermaid 源码块贴出来，方便用户在编辑器里继续改。

## 边界情况
- 用户要画的章节不在 `/knowledge/` 里 → 明确说没有该章知识库，不要编造。
- 节点超过 25 个 → 建议拆成多张图，或先做高层概览图。
- Mermaid 语法报错 → 返回原始错误，定位到具体行，不要反复盲改。
- 不要执行与渲染无关的 Shell 命令。

## 参考
- 图谱设计规范：`/skills/knowledge-map/references/graph-design.md`
- 渲染脚本：`/skills/knowledge-map/scripts/render_mmd.py`
