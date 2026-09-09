# ============================================================================
# service.py —— 客服 Agent 系统总装（把 ch02-ch10 的能力装成一个可运行系统）
#
# 组装清单（每一行都对应一个章节）：
#   ch02  模型：common.make_model（DeepSeek OpenAI 兼容接口）
#   ch03  虚拟文件系统 + 后端：sandbox.build_backend（沙箱默认 + /memories/ 路由）
#   ch04  任务规划：TodoListMiddleware（答疑多步时先列清单）
#   ch05  子 Agent：subagents.build_all_subagents（ch02-ch10 每章一个）
#   ch07  Skills：skills=["/skills/"]（含本作业新建的 knowledge-map）
#   ch08  长期记忆：memory 参数 + CompositeBackend 的 /memories/ 与 /policies/ 路由
#   ch09  HITL：hitl.hitl_config（澄清追问 + 危险命令审批）
#   ch10  沙箱：LocalShellBackend（execute）+ 只读权限 + 产物回收审查
#
# 对外接口：
#   build_customer_service() -> CustomerService（封装 agent + store + 配置）
#   CustomerService.ask()         单轮提问（返回是否中断 + 待处理请求）
#   CustomerService.answer()      回答澄清问题并恢复
#   CustomerService.decide()      审批执行请求并恢复
#   CustomerService.collect()     回收并审查 /out/ 产物
#   CustomerService.summary()     输出会话记忆小结
# ============================================================================

"""客服 Agent 系统总装：Supervisor + 9 个章节子 Agent + 沙箱 + 记忆 + HITL。"""

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from langchain.agents.middleware import TodoListMiddleware
from langgraph.checkpoint.memory import MemorySaver

from deepagents import create_deep_agent

from common import make_model
from config import CHAPTERS, SANDBOX_ROOT, TaContext
from hitl import (
    PendingRequest,
    ask_clarification,
    hitl_config,
    parse_interrupts,
    resume_batch,
    resume_with_answer,
)
from memory import (
    SessionState,
    list_memories,
    make_store,
    memory_paths,
    seed_memory,
    summarize_session,
)
from sandbox import (
    Artifact,
    build_backend,
    collect_artifacts,
    review_artifact,
    sandbox_permissions,
    seed_sandbox,
)
from subagents import build_all_subagents, routing_prompt
from tools import state_memory_tools


# ---------------------------------------------------------------------------
# 一、Supervisor 系统提示词
# ---------------------------------------------------------------------------
def supervisor_prompt() -> str:
    """客服主管的系统提示词：路由 + 澄清 + 沙箱 + 记忆 + 技能。"""
    return f"""你是《Deep Agents 实战》课程的客服主管，负责解答学员关于 ch02-ch10 的代码问题。

## 你的工作方式
1. **判断问题属于哪一章**，用 task 工具委派给对应的章节答疑子 Agent（见下方路由表）。
2. **问题不清晰时不要猜**：先用 ask_clarification 追问最关键的 1 个信息
   （例如：问的是哪一章？哪种后端？具体报错是什么？），拿到补充后用
   record_clarification 把这个问题记进会话状态，再委派。
3. 每次依据某章回答后，用 record_chapter 记录该章节（写入会话状态，便于小结）。
4. 多个章节的对比问题：可以依次委派多个子 Agent，最后自己整合对比结论。
5. 涉及沙箱执行、绘图等操作：在沙箱内完成，产物写到 `/out/`。
6. 回答学员时：先给结论，再给依据；引用课程代码时给出文件名；标注来源章节。

## 能力边界
- 你只能依据 `/knowledge/` 下的课程知识库回答；知识库没有的，明确说「知识库未覆盖」。
- 沙箱执行 Shell 命令会经过人工审批；危险命令会被拦截。
- 学习内容（`/knowledge/`、`/skills/`）是只读的，不要尝试修改。

## 绘图能力
学员要求画知识图谱/思维导图时，读取并遵循 `/skills/knowledge-map/SKILL.md`：
写 `.mmd` 到 `/workspace/`，用
`python3 skills/knowledge-map/scripts/render_mmd.py workspace/x.mmd out/x.png --scale 3`
渲染，产物在 `/out/`。

{routing_prompt()}
"""


# ---------------------------------------------------------------------------
# 二、客服系统封装
# ---------------------------------------------------------------------------
@dataclass
class AskResult:
    """一次提问的结果。"""

    interrupted: bool                    # 是否触发 HITL 中断
    requests: list[PendingRequest]       # 待处理请求（澄清/审批）
    reply: str                          # Agent 的回复（未中断时）
    state: dict = field(default_factory=dict)   # 原始 state（含 todos/cited_chapters）


class CustomerService:
    """带沙箱的 Agent 客服系统。

    典型用法::

        svc = build_customer_service(user_id="alice")
        r = svc.ask("ch03 的 StateBackend 和 StoreBackend 有什么区别？")
        if r.interrupted:
            r = svc.answer("问的是换 thread 后文件还在不在")
        print(r.reply)
    """

    def __init__(self, agent, store, *, user_id: str, sandbox_root: Path, thread_id: str | None = None):
        self.agent = agent
        self.store = store
        self.user_id = user_id
        self.sandbox_root = Path(sandbox_root)
        self.thread_id = thread_id or f"cs-{uuid.uuid4().hex[:8]}"
        self.context = TaContext(user_id=user_id)
        self.cfg = {"configurable": {"thread_id": self.thread_id}}

    # -- 单轮提问 --
    def ask(self, question: str) -> AskResult:
        """向客服提问。若触发 HITL，返回待处理请求（不阻塞）。"""
        result = self.agent.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config=self.cfg,
            context=self.context,
            version="v2",
        )
        return self._to_ask_result(result)

    # -- 回答澄清问题（respond） --
    def answer(self, message: str) -> AskResult:
        """用户补充信息，恢复被 ask_clarification 暂停的执行流。"""
        result = resume_with_answer(self.agent, self.cfg, message)
        return self._to_ask_result(result)

    # -- 审批执行请求（approve/reject） --
    def decide(self, *, approve: bool, message: str = "") -> AskResult:
        """审批 execute 请求（危险命令触发的中断）。"""
        decision: dict = {"type": "approve"} if approve else {"type": "reject"}
        if message:
            decision["message"] = message
        result = resume_batch(self.agent, self.cfg, [decision])
        return self._to_ask_result(result)

    # -- 回收并审查产物 --
    def collect(self) -> list[tuple[Artifact, bool, list[str]]]:
        """回收 /out/ 产物并审查。返回 [(产物, 是否未命中已知模式, 命中项)]。"""
        out: list[tuple[Artifact, bool, list[str]]] = []
        for artifact in collect_artifacts(self.sandbox_root):
            clean, hits = review_artifact(artifact.content)
            out.append((artifact, clean, hits))
        return out

    # -- 会话记忆小结 --
    def summary(self, state: dict | None = None) -> str:
        """输出会话记忆小结（涉及章节 + 已澄清问题）。"""
        state = state or {}
        return summarize_session(
            cited_chapters=state.get("cited_chapters"),
            clarified_questions=state.get("clarified_questions"),
        )

    # -- 长期记忆查看（宿主平面） --
    def memories(self) -> list[str]:
        """列出该用户的长期记忆文件。"""
        return list_memories(self.store, self.user_id)

    # -- 内部：把 invoke 结果转成 AskResult --
    def _to_ask_result(self, result) -> AskResult:
        # version="v2" 时：中断在 result.interrupts，状态在 result.value
        interrupts = getattr(result, "interrupts", None) or []
        value = getattr(result, "value", None) or {}
        requests = parse_interrupts(result) if interrupts else []
        reply = ""
        messages = value.get("messages") or []
        if messages:
            reply = str(getattr(messages[-1], "content", ""))
        return AskResult(
            interrupted=bool(interrupts),
            requests=requests,
            reply=reply,
            state=value,
        )


# ---------------------------------------------------------------------------
# 三、总装函数
# ---------------------------------------------------------------------------
def build_customer_service(
    *,
    user_id: str = "local-user",
    sandbox_root: Path | str | None = None,
    thread_id: str | None = None,
    model=None,
    with_skills: bool = True,
    store=None,
    seed: bool = True,
) -> CustomerService:
    """组装客服系统。

    Args:
        user_id: 用户身份（决定 /memories/ 的 namespace 隔离）。
        sandbox_root: 沙箱根目录，默认 ``SANDBOX_ROOT``。
        thread_id: 会话线程 id；None 时自动生成。
        model: 模型实例；None 时用 ``common.make_model()``。
        with_skills: 是否启用 skills（默认 True，含 knowledge-map）。
        store: 长期记忆 Store。**跨会话演示时必须复用同一个 store**；
            None 时新建内存 store（仅本进程内有效）。
        seed: 是否预填长期记忆。复用 store 做「新会话」时传 False，
            否则会用默认内容覆盖上一会话的自我改进结果。

    Returns:
        可用的 ``CustomerService``。
    """
    root = Path(sandbox_root or SANDBOX_ROOT)
    # ch10 宿主平面：播种学习内容与技能包（每次重建，保证干净）
    seed_sandbox(root)

    # ch08：Store + 预填长期记忆（复用 store 时不再覆盖）
    store = store if store is not None else make_store()
    if seed:
        seed_memory(store, user_id=user_id)

    # ch03/ch08：组合后端（沙箱 + /memories/ + /policies/ 路由）
    backend = build_backend(root=root, store=store)

    agent = create_deep_agent(
        model=model or make_model(),
        # ch09 澄清工具 + 会话状态记忆工具（记录引用章节/已澄清问题）
        tools=[ask_clarification, *state_memory_tools()],
        # ch05：每章一个子 Agent
        subagents=build_all_subagents(),
        # ch04：任务规划
        middleware=[TodoListMiddleware()],
        # ch07：技能包（含新建的 knowledge-map）
        skills=["/skills/"] if with_skills else None,
        # ch08：启动时注入长期记忆
        memory=memory_paths(),
        # ch03/ch07：学习内容与政策只读
        permissions=sandbox_permissions(),
        # ch09：澄清追问 + 危险命令审批
        interrupt_on=hitl_config(),
        # ch08：扩展 state（已澄清问题、引用章节）
        state_schema=SessionState,
        context_schema=TaContext,
        # ch08：短期记忆（对话历史）
        checkpointer=MemorySaver(),
        store=store,
        backend=backend,
        system_prompt=supervisor_prompt(),
    )
    return CustomerService(
        agent, store, user_id=user_id, sandbox_root=root, thread_id=thread_id
    )


# ---------------------------------------------------------------------------
# 四、系统自检（离线，不调用模型）
# ---------------------------------------------------------------------------
def system_check(*, sandbox_root: Path | str | None = None) -> dict:
    """离线自检：确认各层都装好了（不调用模型）。"""
    root = Path(sandbox_root or SANDBOX_ROOT)
    seed_sandbox(root)

    store = make_store()
    seed_memory(store, user_id="selfcheck")
    backend = build_backend(root=root, store=store)

    subs = build_all_subagents()
    checks = {
        "章节子 Agent 数量": len(subs),
        "子 Agent 名称": [s["name"] for s in subs],
        "沙箱知识库文件": len(list((root / "knowledge").glob("*.md"))),
        "沙箱技能包": sorted(p.name for p in (root / "skills").iterdir() if p.is_dir()),
        "只读权限规则": len(sandbox_permissions()),
        "长期记忆文件": list_memories(store, "selfcheck"),
        "沙箱 execute 可用": hasattr(backend, "execute"),
        "后端路由": sorted(backend.routes.keys()),
    }
    return checks


if __name__ == "__main__":
    import json

    print("=" * 60)
    print("客服系统离线自检")
    print("=" * 60)
    print(json.dumps(system_check(), ensure_ascii=False, indent=2))
