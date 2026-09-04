"""确定性测试（无 LLM）：底层 interrupt() 的输入验证模式与重放机制。"""

import uuid
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


def cfg():
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def build_form_graph():
    class FormState(TypedDict):
        age: int | None
        pending_question: str | None

    def collect_age(state: FormState):
        question = state.get("pending_question") or "请输入你的年龄："
        answer = interrupt(question)
        if isinstance(answer, int) and answer > 0:
            return {"age": answer, "pending_question": None}
        return {"pending_question": f"'{answer}' 不是有效年龄，请输入正整数。"}

    def route(state: FormState):
        return END if state.get("age") is not None else "collect_age"

    builder = StateGraph(FormState)
    builder.add_node("collect_age", collect_age)
    builder.add_edge(START, "collect_age")
    builder.add_conditional_edges("collect_age", route)
    return builder.compile(checkpointer=MemorySaver())


def test_input_validation_invalid_then_valid():
    g = build_form_graph()
    c = cfg()
    g.invoke({"age": None, "pending_question": None}, config=c)
    r2 = g.invoke(Command(resume="abc"), config=c)          # 无效输入 → 回路重问
    assert "不是有效年龄" in r2["pending_question"]
    r3 = g.invoke(Command(resume=28), config=c)             # 有效输入 → 结束
    assert r3["age"] == 28
    assert g.get_state(c).next == ()


def test_replay_reruns_node_from_start():
    """恢复时节点从头重放：interrupt 之前的副作用会再执行一次。"""
    runs = []

    class S(TypedDict):
        approved: bool | None

    def node(state: S):
        runs.append(1)
        decision = interrupt("请审批")
        return {"approved": decision.get("approved")}

    b = StateGraph(S)
    b.add_node("node", node)
    b.add_edge(START, "node")
    b.add_edge("node", END)
    g = b.compile(checkpointer=MemorySaver())
    c = cfg()
    g.invoke({"approved": None}, config=c)
    g.invoke(Command(resume={"approved": True}), config=c)
    assert len(runs) == 2                        # 第2次=重放，副作用计数翻倍
    assert g.get_state(c).values["approved"] is True
