# ============================================================================
# tools.py —— 会话状态记忆工具（把答疑过程写进 LangGraph State）
#
# 作业要求「使用 state 做记忆管理」。memory.py 定义了 SessionState 的两个字段，
# 本模块提供写入它们的工具：工具返回 ``Command(update=...)``，由 LangGraph 的
# reducer 合并进 state（对应 ch04 的 state 持久化 + ch09 的 Command 用法）。
#
# 为什么用工具而不是在节点里写？
#   - 让「记录引用章节 / 记录已澄清问题」成为模型可主动调用的能力，
#     写入内容进入对话历史，可审计、可恢复（checkpointer）。
#   - reducer（memory._merge_unique）保证多轮写入去重合并，不会互相覆盖。
#
# 实现要点（langgraph 1.x 实测）：
#   返回 ``Command`` 的工具必须同时返回一条匹配当前 tool_call_id 的 ToolMessage，
#   否则 ToolNode 会抛「Expected to have a matching ToolMessage」。
# ============================================================================

"""会话状态记忆工具：记录引用章节与已澄清问题。"""

from typing import Annotated

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from config import CHAPTER_BY_KEY


@tool
def record_chapter(chapter: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """记录本次答疑引用了哪个课程章节，写入会话状态。

    每次依据某章知识库回答后调用一次，让系统记住「本次会话涉及哪些章节」，
    便于最后生成学习小结或知识图谱。

    Args:
        chapter: 章节标识，必须是 ch02-ch10 之一（如 "ch03"）。
    """
    key = chapter.strip().lower()
    if key not in CHAPTER_BY_KEY:
        # 非法章节：不写 state，返回错误说明（不抛异常，避免打断执行流）
        return Command(update={"messages": [ToolMessage(
            content=f"未知章节 {chapter!r}；有效值：{', '.join(sorted(CHAPTER_BY_KEY))}",
            tool_call_id=tool_call_id,
        )]})
    title = CHAPTER_BY_KEY[key].title
    return Command(update={
        "cited_chapters": [key],
        "messages": [ToolMessage(content=f"已记录引用章节：{key}（{title}）", tool_call_id=tool_call_id)],
    })


@tool
def record_clarification(question: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """记录一个已经向用户澄清过的问题，写入会话状态，避免重复追问。

    在 ask_clarification 之后、拿到用户补充信息时调用。

    Args:
        question: 已经问过并得到回答的问题（一句话概括）。
    """
    return Command(update={
        "clarified_questions": [question],
        "messages": [ToolMessage(content=f"已记录澄清问题：{question}", tool_call_id=tool_call_id)],
    })


def state_memory_tools() -> list:
    """返回会话状态记忆工具（挂给主 Agent 与子 Agent）。"""
    return [record_chapter, record_clarification]
