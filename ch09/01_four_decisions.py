# ============================================================================
# 01_four_decisions.py —— ch09 段1：interrupt_on 与四种决策类型
#
#   实验A approve：批准 → 用 Agent 原始参数执行
#   实验B edit   ：改参数后执行（收件人改掉，实际执行用的是新参数）
#   实验C reject ：跳过执行，原因反馈给 Agent（并观察 Agent 不再重试）
#   实验D respond：人的回答直接成为工具结果（ask_user 占位工具）
#
# 关键 API（0.7.13 实测）：
#   invoke(..., version="v2") → result.interrupts[0].value
#     = {"action_requests": [{name, args, description}...],
#        "review_configs":  [{action_name, allowed_decisions}...]}
#   恢复：agent.invoke(Command(resume={"decisions": [...]}), 同 config, version="v2")
#   决策数量/顺序必须与 action_requests 一一对应。
#   字段兼容：本版 action_requests 用 args；兼容代码读 arguments 再回退 args。
# ============================================================================

import uuid

from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from common import make_model, preview

from deepagents import create_deep_agent


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """发送邮件。"""
    return f"邮件已发送至 {to}（主题：{subject}）"


@tool
def ask_user(question: str) -> str:
    """向用户提问；真实回答由 HITL 的 respond 决策提供。"""
    return "等待用户回答"


def make_agent(interrupt_on):
    return create_deep_agent(
        model=make_model(),
        tools=[send_email, ask_user],
        interrupt_on=interrupt_on,
        checkpointer=MemorySaver(),
        system_prompt="严格按用户指令执行；审批结果就是最终事实，不要重复发起已被拒绝的操作。",
    )


def fresh_cfg():
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def get_args(action_request):
    """字段兼容：arguments（LangChain 标准）回退 args（本版实际字段）。"""
    return action_request.get("arguments") or action_request.get("args")


def experiment_a_approve():
    print("=" * 60)
    print("实验A: approve —— 批准原始参数")
    print("=" * 60)
    agent = make_agent({"send_email": {"allowed_decisions": ["approve", "edit", "reject"]}})
    cfg = fresh_cfg()
    r = agent.invoke({"messages": [{"role": "user", "content":
        "给 boss@corp.com 发邮件：主题'周报'，正文'本周完成 HITL 实验'。"}]},
        config=cfg, version="v2")
    ar = r.interrupts[0].value["action_requests"][0]
    print(f"  中断动作: {ar['name']} {get_args(ar)}")
    r2 = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=cfg, version="v2")
    tool_results = [m.content for m in r2.value["messages"] if m.type == "tool"]
    print(f"  实际执行: {tool_results[0][:60]}（原参数）")


def experiment_b_edit():
    print()
    print("=" * 60)
    print("实验B: edit —— 修改参数后执行")
    print("=" * 60)
    agent = make_agent({"send_email": {"allowed_decisions": ["approve", "edit", "reject"]}})
    cfg = fresh_cfg()
    r = agent.invoke({"messages": [{"role": "user", "content":
        "给 all@corp.com 发邮件：主题'通知'，正文'今晚维护'。"}]},
        config=cfg, version="v2")
    ar = r.interrupts[0].value["action_requests"][0]
    orig = get_args(ar)
    print(f"  原始参数: {orig}")
    # 审批人把收件人改成 team@corp.com，其余保持
    r2 = agent.invoke(Command(resume={"decisions": [{
        "type": "edit",
        "edited_action": {"name": ar["name"], "args": {**orig, "to": "team@corp.com"}},
    }]}), config=cfg, version="v2")
    tool_results = [m.content for m in r2.value["messages"] if m.type == "tool"]
    print(f"  实际执行: {tool_results[0][:60]}（已改为新收件人）")
    print("  提示：编辑尽量保守（只改必要参数），大幅改写可能让模型重新评估计划")


def experiment_c_reject():
    print()
    print("=" * 60)
    print("实验C: reject —— 拒绝并把原因反馈给 Agent")
    print("=" * 60)
    agent = make_agent({"send_email": {"allowed_decisions": ["approve", "reject"]}})
    cfg = fresh_cfg()
    r = agent.invoke({"messages": [{"role": "user", "content":
        "给 hr@corp.com 发邮件：主题'投诉'，正文'强烈不满'。"}]},
        config=cfg, version="v2")
    print(f"  已暂停待审批: {bool(r.interrupts)}")
    r2 = agent.invoke(Command(resume={"decisions": [{
        "type": "reject",
        "message": "用户拒绝发送。不要再次尝试发送，建议先与 HR 当面沟通。",
    }]}), config=cfg, version="v2")
    # 判据：整段历史里不应出现任何"成功发送"的工具结果（原始调用被跳过且未重试）
    never_sent = not any("邮件已发送" in str(m.content)
                         for m in r2.value["messages"] if m.type == "tool")
    print(f"  邮件从未实际发出: {never_sent}")
    print(f"  最终回复: {preview(r2.value['messages'][-1].content, 110)}")


def experiment_d_respond():
    print()
    print("=" * 60)
    print("实验D: respond —— 人的回答成为工具结果")
    print("=" * 60)
    agent = make_agent({"ask_user": {"allowed_decisions": ["respond"]}})
    cfg = fresh_cfg()
    r = agent.invoke({"messages": [{"role": "user", "content":
        "帮我生成季度报告。缺少口径信息时用 ask_user 问清楚再写。"}]},
        config=cfg, version="v2")
    print(f"  ask_user 暂停等待人工输入: {bool(r.interrupts)}")
    r2 = agent.invoke(Command(resume={"decisions": [{
        "type": "respond",
        "message": "使用季度维度，并排除测试数据。",
    }]}), config=cfg, version="v2")
    # respond 的 message 成为 ask_user 的成功 ToolMessage → Agent 据此写报告
    print(f"  Agent 拿到人工回答后的报告预览: {preview(r2.value['messages'][-1].content, 140)}")
    print("  规则回顾：拒绝副作用工具用 reject；ask_user 这类'问人'工具才用 respond")


if __name__ == "__main__":
    experiment_a_approve()
    experiment_b_edit()
    experiment_c_reject()
    experiment_d_respond()
