# ============================================================================
# 04_compiled_structured.py —— ch05 段4：CompiledSubAgent + 结构化输出
#
#   Part A: CompiledSubAgent —— 把 create_agent() 编译的 LangGraph 图包装成子 Agent
#           （适合多步骤、有分支逻辑的工作流；图的 State 必须含 "messages" 键）
#   Part B: response_format —— 子 Agent 返回 Pydantic schema 的 JSON，
#           主 Agent 的 ToolMessage 直接拿到结构化数据
#
# ⚠️ 版本坑（DeepSeek 实测）：response_format 内部会强制 tool_choice，
#    deepseek-v4-flash 默认思考模式不支持 tool_choice（400 报错）。
#    解法：给该子 Agent 单独指定非思考模式模型 "deepseek-chat"（同一平台别名）。
# ============================================================================

import os

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from common import make_model, preview

from deepagents import CompiledSubAgent, create_deep_agent


def part_a_compiled_subagent():
    print("=" * 60)
    print("Part A: CompiledSubAgent（LangGraph 图作为子 Agent）")
    print("=" * 60)

    def double_number(x: float) -> float:
        """把数字翻倍。"""
        return x * 2

    def add_hundred(x: float) -> float:
        """给数字加一百。"""
        return x + 100

    # 先用 LangChain 组装一个多工具计算图（复杂工作流可用 LangGraph 图 API 写分支/循环）
    custom_graph = create_agent(
        model=make_model(),
        tools=[double_number, add_hundred],
        system_prompt="你是计算专家。按用户要求依次使用工具计算，直接给出最终数字。",
    )
    # 包装为 CompiledSubAgent（要求：图的 State 必须包含 "messages" 键）
    calc_worker = CompiledSubAgent(
        name="calc-worker",
        description="执行数字计算任务（翻倍、加百等多步骤运算）",
        runnable=custom_graph,        # 传入编译好的图
    )
    agent = create_deep_agent(model=make_model(), subagents=[calc_worker])

    r = agent.invoke({"messages": [{"role": "user", "content": (
        "委派给 calc-worker：先算 21 的翻倍，再给结果加一百，告诉我最终数字。"
    )}]})
    calls = [tc["name"] for m in r["messages"] for tc in (getattr(m, "tool_calls", None) or [])]
    print(f"  主 Agent 调用: {calls}（只有 task，double/add 都在子 Agent 内部）")
    print(f"  消息数: {len(r['messages'])}")
    print(f"  回复: {preview(r['messages'][-1].content, 100)}（期望 142）")


def part_b_structured_output():
    print()
    print("=" * 60)
    print("Part B: response_format 结构化输出（子 Agent 返回 JSON）")
    print("=" * 60)

    def lookup_info(topic: str) -> str:
        """查询某个主题的资料（本地模拟工具）。"""
        return f"关于 {topic} 的三条模拟资料：A=42, B=7, C=99"

    # Pydantic schema：主 Agent 收到的就是符合这个结构的 JSON
    class ResearchFindings(BaseModel):
        summary: str = Field(description="研究摘要")
        confidence: float = Field(description="置信度 0-1")
        sources: list[str] = Field(description="信息来源列表")

    researcher = {
        "name": "researcher",
        "description": "研究特定主题并返回结构化发现",
        "system_prompt": "深入研究给定主题，用 lookup_info 查询后总结。",
        "tools": [lookup_info],
        # ⚠️ 思考模式（deepseek-v4-flash 默认）不支持强制 tool_choice，换非思考别名
        "model": ChatOpenAI(
            model="deepseek-chat",
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com/v1",
        ),
        "response_format": ResearchFindings,   # deepagents>=0.5.3
    }
    agent = create_deep_agent(model=make_model(), subagents=[researcher])

    r = agent.invoke({"messages": [{"role": "user", "content": (
        "委派给 researcher 研究'量子计算进展'，把它返回的 JSON 原样转述给我。"
    )}]})
    # 主 Agent 的 ToolMessage 收到的就是 JSON（可 json.loads 直接用）
    import json
    for m in r["messages"]:
        if m.type == "tool":
            raw = str(m.content)
            print(f"  task 返回原文: {preview(raw, 150)}")
            try:
                data = ResearchFindings.model_validate(json.loads(raw))
                print(f"  ✅ 校验通过: confidence={data.confidence}, {len(data.sources)} 个来源")
            except Exception as e:
                print(f"  校验失败: {e}")
            break


if __name__ == "__main__":
    part_a_compiled_subagent()
    part_b_structured_output()
