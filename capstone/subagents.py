# ============================================================================
# subagents.py —— 子 Agent 层（对应 ch05 的「每章一个子 Agent」+ ch05/ch07 的路由规则）
#
# 作业要求「subagent 可以用于不同章节，每个章节配一个 subagent」。
# 本模块为 ch02-ch10 各定义一个答疑子 Agent：
#
#   - name        : ch02-ta … ch10-ta（task 工具用这个名字路由）
#   - description : 具体、含章节号与关键词（ch05：description 决定路由，要具体）
#   - system_prompt: 只依据 /knowledge/<chapter>.md 回答，不臆造 API，标注来源
#   - tools       : 不给（继承主 Agent 的文件工具，可读知识库；见 ch05 继承语义）
#
# 路由策略（两层，互补）：
#   1. 主 Agent 的 system_prompt 给出「问题 → 章节」的映射表，主动选对子 Agent；
#   2. 每个子 Agent 的 description 里带章节号与核心关键词，兜底路由。
#
# 为什么不用 general-purpose 一个子 Agent 干全部？
#   ch05 的 Context Quarantine：每章独立上下文，主 Agent 只收到精炼答案，
#   避免 9 章知识全堆进一个上下文。同时 description 精准路由减少误派。
# ============================================================================

"""子 Agent 定义：ch02-ch10 每章一个答疑专家。"""

from config import CHAPTERS, Chapter
from hitl import hitl_config

# 子 Agent 的通用系统提示模板（强调「依据知识库、不臆造、标来源」）
_TA_TEMPLATE = """你是《Deep Agents 实战》课程 {key} 章节的答疑助教。

## 你的唯一知识来源
先用 read_file 读取 `{knowledge}`，再回答。该文件包含本章的核心概念、
关键代码事实、易错点与版本提示。

## 回答规则
1. **只依据知识库内容回答**；知识库没有的细节，明确说「知识库未覆盖」，
   不要编造 API、参数或行为。
2. 引用课程代码时给出**文件名**（本章对应源码：{sources}）。
3. 涉及版本差异时，标注实测版本（deepagents 0.7.13）。
4. 先给结论，再给依据；代码示例要完整可运行。
5. 回答末尾标注来源，格式：`来源：{knowledge}`。

## 本章一句话
{summary}
"""


def _sources_text(chapter: Chapter) -> str:
    """把章节目录下的源码文件名拼成可读字符串。"""
    return "、".join(chapter.sources)


def build_chapter_subagent(chapter: Chapter, *, hitl: bool = True) -> dict:
    """把一个 ``Chapter`` 元数据转成 Deep Agents 的字典式子 Agent 定义。

    Args:
        chapter: 章节元数据。
        hitl: 是否给子 Agent 挂 HITL 配置。子 Agent 的 ``interrupt_on`` 不继承
            主 Agent（见 ch09 的子 Agent 独立审批），所以危险 execute 需要单独配。
    """
    spec: dict = {
        "name": f"{chapter.key}-ta",
        # description 是路由锚点：章节号 + 标题 + 能力摘要（越具体越不容易误派）
        "description": (
            f"{chapter.key} 章节答疑专家。处理关于「{chapter.title}」的问题，"
            f"覆盖：{chapter.summary}。当用户问题涉及这些主题时委派给本子 Agent。"
        ),
        "system_prompt": _TA_TEMPLATE.format(
            key=chapter.key,
            knowledge=chapter.knowledge,
            sources=_sources_text(chapter),
            summary=chapter.summary,
        ),
        # 不指定 tools → 继承主 Agent 的工具（含文件工具），可读 /knowledge/
    }
    if hitl:
        # 子 Agent 独立 HITL：澄清追问 + 危险 execute 审批
        spec["interrupt_on"] = hitl_config()
    return spec


def build_all_subagents(*, hitl: bool = True) -> list[dict]:
    """构建全部 9 个章节答疑子 Agent（ch02-ch10）。"""
    return [build_chapter_subagent(c, hitl=hitl) for c in CHAPTERS]


# ---------------------------------------------------------------------------
# 主 Agent 的路由提示词：显式「问题 → 章节」映射，降低误派率
# ---------------------------------------------------------------------------
def routing_prompt() -> str:
    """生成主 Agent 的章节路由表（写进 supervisor 的 system_prompt）。"""
    lines = ["## 章节路由表（据此选择子 Agent）", ""]
    for c in CHAPTERS:
        lines.append(f"- **{c.key}**（{c.title}）→ 子 Agent `{c.key}-ta`：{c.summary}")
    return "\n".join(lines)
