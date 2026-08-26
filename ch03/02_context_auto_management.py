# ============================================================================
# 02_context_auto_management.py —— ch03 段2：上下文自动管理
# 演示 Deep Agents 的两道「上下文防线」：
#   Part A: 大结果自动卸载 —— 工具输出过大时写入文件系统，对话里只留引用+预览
#   Part B: 对话历史自动总结 —— 消息数超过阈值时，早期历史压缩为摘要并存档
# ============================================================================

# 模块文档字符串：说明两部分的触发条件与效果
"""ch03 段2：上下文自动管理 —— 大结果自动卸载 + 对话历史自动总结。

Part A：tool_token_limit_before_evict 低于工具输出 token 数时，
        工具结果自动写入虚拟文件系统，对话历史只留「路径引用 + 前 10 行预览」。
Part B：SummarizationMiddleware 用 trigger={"messages": N} 低成本触发，
        完整历史写入文件存档，对话历史替换为结构化摘要。
"""

# 从 common 导入公共工具
from common import make_model, preview

# create_deep_agent：创建 Agent 入口
from deepagents import create_deep_agent
# StateBackend：临时存储后端（文件存入 Agent State）
from deepagents.backends import StateBackend
# FilesystemMiddleware：控制「大结果卸载」阈值；SummarizationMiddleware：控制「历史总结」
from deepagents.middleware import FilesystemMiddleware, SummarizationMiddleware

# LONG_TEXT：构造一段很长的文本（约 4000 tokens），用于触发 Part A 的大结果卸载
LONG_TEXT = "\n".join(
    # 生成 60 个小节，每节一行标题 + 一句重复长句，把体积撑大
    f"# Section {i}\n" + "The quick brown fox jumps over the lazy dog. " * 12 + "\n"
    for i in range(1, 61)
)  # 约 4000 tokens，远超下面设定的 300 阈值


# ---------------------------------------------------------------------------
# dump_messages：打印对话历史中每条消息的类型与内容预览（便于观察上下文变化）
# ---------------------------------------------------------------------------
def dump_messages(result, tail: int | None = None):
    # tail 指定只看末尾 N 条；None 表示看全部
    msgs = result["messages"] if tail is None else result["messages"][-tail:]
    # 遍历消息
    for m in msgs:
        # 消息内容可能是 str 或 list（多模态块），统一转成 str 便于预览
        content = m.content if isinstance(m.content, str) else str(m.content)
        # 打印：居中的消息类型 + 单行预览（截 110 字符）
        print(f"  [{m.type:^9}] {preview(content, 110)}")


# ---------------------------------------------------------------------------
# Part A：大结果自动卸载
# 关键：把 FilesystemMiddleware 的 tool_token_limit_before_evict 降到 300，
#       让「远超 300 tokens」的工具输出被自动卸到文件系统。
# ---------------------------------------------------------------------------
def part_a_tool_result_eviction():
    # 打印标题
    print("=" * 60)
    print("Part A: 大结果自动卸载（阈值降到 300 tokens 便于演示）")
    print("=" * 60)

    # 定义一个会返回超长结果的工具（供 Agent 调用）
    def fetch_big_report(topic: str) -> str:
        """Fetch a very long research report about the topic."""
        return LONG_TEXT      # 固定返回上面构造的长文本

    # 创建 Agent；自定义 FilesystemMiddleware 会按名字合并、覆盖核心栈里的默认实例
    agent = create_deep_agent(
        model=make_model(),                     # DeepSeek 模型
        tools=[fetch_big_report],               # 注册超长结果工具
        middleware=[
            FilesystemMiddleware(
                backend=StateBackend(),         # 卸载目标后端（临时存储）
                tool_token_limit_before_evict=300,  # 阈值降到 300，便于演示触发
            )
        ],
    )
    # 调用 Agent：让它查询并只报告第一节标题（逼它调用超长工具）
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "调用 fetch_big_report 查询 LangGraph，然后只告诉我报告第一节的标题。"}]}
    )

    # 打印对话历史，观察 tool 消息是否已被替换为「引用 + 预览」
    print("--- 对话历史（关注 tool 消息：应只有预览，没有全文）---")
    dump_messages(result)
    # 打印被卸载到虚拟文件系统的文件（应出现 /large_tool_results/...）
    print("--- 卸载到虚拟文件系统的文件 ---")
    for path, meta in (result.get("files") or {}).items():
        content = meta["content"] if isinstance(meta, dict) else meta
        print(f"  {path}  ({len(content)} chars)")
    # 打印 Agent 的最终回答（验证它仍能从预览/文件里读到第一节标题）
    print("--- Agent 回答 ---")
    print(preview(result["messages"][-1].content, 200))


# ---------------------------------------------------------------------------
# Part B：对话历史自动总结
# 关键：SummarizationMiddleware 用 trigger={"messages": 6} 提前触发总结，
#       并加 MemorySaver + 固定 thread_id 让总结事件可跨轮持久化、可观测。
# ---------------------------------------------------------------------------
def part_b_history_summarization():
    # 打印标题
    print()
    print("=" * 60)
    print("Part B: 对话历史自动总结（trigger: messages>=6 提前触发）")
    print("=" * 60)
    # 加 checkpointer + 固定 thread_id，让总结事件可跨轮持久化、可观测（生产用法）
    from langgraph.checkpoint.memory import MemorySaver   # 内存 checkpointer

    # 创建 Agent，注入自定义 SummarizationMiddleware
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是文件助手，严格按指令操作，少说废话。",
        middleware=[
            SummarizationMiddleware(
                model=make_model(),            # 用于生成摘要的模型（可与主模型不同）
                backend=StateBackend(),        # 完整历史存档到该后端
                trigger={"messages": 6},       # 消息数 >= 6 即触发（课程默认 fraction 0.85）
                keep=("messages", 2),          # 摘要后保留最近 2 条消息
            )
        ],
        checkpointer=MemorySaver(),            # 持久化私有状态 _summarization_event
    )
    # 固定 thread_id：多轮 invoke 共享同一对话线程，state 才会累积
    thread = {"configurable": {"thread_id": "ch03-summary-demo"}}

    # 用多轮对话把消息数推过阈值；同一 thread 内 state 累积，总结才会真实触发
    turns = [
        "用 write_file 创建 /workspace/a.md，内容为 'A计划已启动'，完成后只回我一句收到。",
        "用 write_file 创建 /workspace/b.md，内容为 'B计划已暂停'，完成后只回我一句收到。",
        "用 write_file 创建 /workspace/c.md，内容为 'C计划已完成'，完成后只回我一句收到。",
        "请读取 /workspace/a.md 和 /workspace/b.md，然后回答：B计划当前的状态是什么？只回答状态。",
    ]

    # HumanMessage：构造单条用户消息（避免一次性塞入全部历史）
    from langchain_core.messages import HumanMessage
    # 逐轮 invoke，同一 thread 累积消息
    for i, t in enumerate(turns, 1):
        result = agent.invoke({"messages": [HumanMessage(content=t)]}, config=thread)

    # 取最终完整消息列表
    history = list(result["messages"])
    # 打印对话历史（原始 messages 仍完整保留；0.7.6 用私有状态记录总结事件）
    print("--- 对话历史（原始 messages 仍完整保留；0.7.6 用私有状态记录总结事件）---")
    for m in history:
        content = m.content if isinstance(m.content, str) else str(m.content)
        print(f"  [{m.type:^9}] {preview(content, 120)}")

    # 从 checkpoint 私有状态读出总结事件（0.7.6 把事件存在 _summarization_event）
    state = agent.get_state(thread)
    evt = (state.values or {}).get("_summarization_event")
    # 找出完整对话历史存档文件（/conversation_history/ 前缀）
    history_files = [p for p in (result.get("files") or {}) if "conversation_history" in p]
    # 打印是否触发总结
    print(f"[check] 是否触发总结: {bool(evt)}")
    if evt:
        # 打印总结事件的截止下标、存档路径、摘要预览
        print(f"        cutoff_index={evt['cutoff_index']}, 存档={evt.get('file_path')}")
        print(f"        summary 预览: {preview(str(evt['summary_message'].content), 200)}")
    # 打印完整对话存档文件列表
    print(f"[check] 完整对话存档文件: {history_files}")
    # 打印存档到文件系统的完整对话历史
    print("--- 存档到文件系统的完整对话历史 ---")
    for path, meta in (result.get("files") or {}).items():
        content = meta["content"] if isinstance(meta, dict) else meta
        print(f"  {path}  ({len(content)} chars)  preview: {preview(content, 80)}")
    # 打印 Agent 最终回答（验证摘要后仍记得 B 计划状态）
    print("--- Agent 回答（验证摘要后仍记得 B 计划状态）---")
    print(result["messages"][-1].content)


# 脚本入口：依次执行 Part A 与 Part B
if __name__ == "__main__":
    part_a_tool_result_eviction()   # 大结果卸载
    part_b_history_summarization()  # 历史总结
