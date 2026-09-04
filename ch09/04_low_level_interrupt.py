# ============================================================================
# 04_low_level_interrupt.py —— ch09 段4：揭开引擎盖 —— LangGraph 的 interrupt()
#
#   Part A: 工具内 interrupt() —— request_approval 自定义审批（任意业务语义）
#   Part B: DraftApprovalMiddleware —— after_model 审稿（跨工具策略，interrupt_on 做不到）
#   Part C: 输入验证模式 —— 每节点只 interrupt 一次 + 条件边回路（避免 while True 重放坑）
#   Part D: 重放机制实证 —— 恢复时节点从头重放：interrupt() 之前的副作用会再跑一次
#           （计数器打印两次 —— 这就是"副作用必须幂等/放在 interrupt 之后"的原因）
# ============================================================================

import uuid
from typing import Any, TypedDict

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.messages import AIMessage
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from common import make_model, preview

from deepagents import create_deep_agent


def fresh_cfg():
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def part_a_tool_interrupt():
    print("=" * 60)
    print("Part A: 工具内 interrupt() —— 自定义审批语义")
    print("=" * 60)

    @tool
    def request_approval(action_description: str) -> str:
        """请求人工审批。"""
        # interrupt() 暂停执行；返回值 = Command(resume=...) 传入的数据
        approval = interrupt({
            "type": "approval_request",
            "action": action_description,
            "message": f"请审批：{action_description}",
        })
        if approval.get("approved"):
            return f"操作 '{action_description}' 已获批准。"
        return f"操作 '{action_description}' 被拒绝，原因：{approval.get('reason', '未提供')}"

    agent = create_deep_agent(model=make_model(), tools=[request_approval],
                              checkpointer=MemorySaver())
    cfg = fresh_cfg()
    r = agent.invoke({"messages": [{"role": "user", "content":
        "我想重启生产数据库，先走审批。"}]}, config=cfg, version="v2")
    print(f"  审批请求触发: {bool(r.interrupts)} | {str(r.interrupts[0].value)[:70]}")
    r2 = agent.invoke(Command(resume={"approved": False, "reason": "高峰期，延后到 22:00"}),
                      config=cfg, version="v2")
    print(f"  拒绝后回复: {preview(r2.value['messages'][-1].content, 90)}")


def part_b_draft_middleware():
    print()
    print("=" * 60)
    print("Part B: DraftApprovalMiddleware —— 发布前统一审稿")
    print("=" * 60)

    class DraftApprovalMiddleware(AgentMiddleware):
        def after_model(self, state: AgentState, runtime) -> dict[str, Any] | None:
            last = state["messages"][-1]
            # 有工具调用时让 Agent 继续；只审查最终草稿（无工具调用的 AIMessage）
            if not isinstance(last, AIMessage) or last.tool_calls:
                return None
            decision = interrupt({
                "type": "draft_review",
                "draft": str(last.content)[:80],
                "message": "是否批准向用户发布这份草稿？",
            })
            if decision.get("approved"):
                return None
            return {"messages": [AIMessage(
                content=f"草稿未发布：{decision.get('reason', '审批未通过')}")]}

    agent = create_deep_agent(model=make_model(),
                              middleware=[DraftApprovalMiddleware()],
                              checkpointer=MemorySaver())
    cfg = fresh_cfg()
    r = agent.invoke({"messages": [{"role": "user", "content": "用一句话写一条上线公告。"}]},
                     config=cfg, version="v2")
    print(f"  审稿中断触发: {bool(r.interrupts)}")
    if r.interrupts:
        print(f"  草稿内容: {preview(str(r.interrupts[0].value), 90)}")
        # 拒绝 → 草稿被替换
        r2 = agent.invoke(Command(resume={"approved": False, "reason": "语气太随意"}),
                          config=cfg, version="v2")
        print(f"  拒绝后用户看到: {r2.value['messages'][-1].content[:50]}")
    print("  要点：Node-style Hook（after_model 等）才是推荐的审批位置；")
    print("        Wrap-style 在节点内部，恢复时会连 handler 一起重放，不适合做中断边界")


def part_c_input_validation():
    print()
    print("=" * 60)
    print("Part C: 输入验证 —— 单次 interrupt + 条件边回路")
    print("=" * 60)

    class FormState(TypedDict):
        age: int | None
        pending_question: str | None

    def collect_age(state: FormState):
        question = state.get("pending_question") or "请输入你的年龄："
        answer = interrupt(question)          # 每次节点执行只暂停一次
        if isinstance(answer, int) and answer > 0:
            return {"age": answer, "pending_question": None}
        return {"pending_question": f"'{answer}' 不是有效年龄，请输入正整数。"}

    def route(state: FormState):
        return END if state.get("age") is not None else "collect_age"

    builder = StateGraph(FormState)
    builder.add_node("collect_age", collect_age)
    builder.add_edge(START, "collect_age")
    builder.add_conditional_edges("collect_age", route)
    graph = builder.compile(checkpointer=MemorySaver())

    cfg = fresh_cfg()
    # 裸 CompiledStateGraph 的 invoke 直接返回 state 字典（中断时返回暂停前的部分状态）
    r1 = graph.invoke({"age": None, "pending_question": None}, config=cfg)
    print(f"  第1问: {r1.get('pending_question') or '请输入你的年龄：'}")
    # 故意给无效输入 → 条件边回到节点重新问
    r2 = graph.invoke(Command(resume="abc"), config=cfg)
    print(f"  输入 'abc' 后: {r2['pending_question'][:40]}")
    r3 = graph.invoke(Command(resume=28), config=cfg)
    print(f"  输入 28 后: age={r3['age']}，流程结束（next={graph.get_state(cfg).next or 'END'}）")
    print("  要点：不要在节点里 while True 反复 interrupt（重放会连前几轮一起重跑）；")
    print("        把下一问写回 state，用条件边决定是否回到同一节点")


def part_d_replay_proof():
    print()
    print("=" * 60)
    print("Part D: 重放机制实证（interrupt 前的代码会再跑一次）")
    print("=" * 60)
    runs = []          # 记录节点执行次数（模拟非幂等副作用）

    class S(TypedDict):
        approved: bool | None

    def node(state: S):
        runs.append(1)                        # interrupt 之前的"副作用"
        decision = interrupt("请审批")        # 暂停点
        return {"approved": decision.get("approved")}

    g = StateGraph(S)
    g.add_node("node", node)
    g.add_edge(START, "node")
    g.add_edge("node", END)
    graph = g.compile(checkpointer=MemorySaver())

    cfg = fresh_cfg()
    graph.invoke({"approved": None}, config=cfg)                     # 第1次：跑到 interrupt 暂停
    graph.invoke(Command(resume={"approved": True}), config=cfg)     # 恢复：节点从头重放
    print(f"  节点执行次数: {len(runs)}（恢复不是从 interrupt 下一行继续，而是节点重放）")
    print(f"  approved: {graph.get_state(cfg).values['approved']}")
    print("  结论：副作用要么放 interrupt 之后，要么做成幂等（upsert）")


if __name__ == "__main__":
    part_a_tool_interrupt()
    part_b_draft_middleware()
    part_c_input_validation()
    part_d_replay_proof()
