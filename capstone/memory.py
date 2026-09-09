# ============================================================================
# memory.py —— 记忆管理层（对应 ch08，兼顾「state 做记忆管理」的作业要求）
#
# 作业要求里的「用 state 做记忆管理」在本项目分两层落地：
#
#   1. 会话内状态（LangGraph State）
#      - messages / todos / files 由 DeepAgentState 承载，靠 checkpointer 跨轮次保留；
#      - 本模块的 SessionState（TypedDict）额外挂上「已澄清的问题」「已引用章节」，
#        让 HITL 的追问结果、路由决策都进入 state，成为可恢复、可审计的记忆。
#
#   2. 跨会话长期记忆（Store + /memories/ 路由）
#      - 用户偏好、答疑沉淀写入 /memories/，由 CompositeBackend 路由到 StoreBackend；
#      - 换 thread 依然可读（对应 ch08 的短期 vs 长期对照）。
#
# 关键 API 事实（ch08 实测）：
#   - StateBackend 的文件是短期的，换 thread 消失；
#   - /memories/ 路由到 Store 才是长期；
#   - store key 会剥掉 /memories/ 前缀（/memories/prefs.md → /prefs.md）；
#   - memory=["/memories/AGENTS.md"] 会在启动时注入系统提示词的 <agent_memory> 段。
# ============================================================================

"""记忆管理：会话内 state 扩展 + 跨会话 /memories/ 长期记忆。"""

from typing import Annotated, NotRequired

from langgraph.store.memory import InMemoryStore

from deepagents import DeepAgentState
from deepagents.backends.utils import create_file_data

from config import CHAPTERS, TaContext


# ---------------------------------------------------------------------------
# 一、会话内状态扩展（对应 ch04 的 todos + ch09 的澄清结果）
# ---------------------------------------------------------------------------
def _merge_unique(left: list[str] | None, right: list[str] | None) -> list[str]:
    """列表合并去重（保留出现顺序），用作 state 字段的 reducer。"""
    out: list[str] = []
    for item in (left or []) + (right or []):
        if item not in out:
            out.append(item)
    return out


class SessionState(DeepAgentState):
    """客服会话的扩展状态。

    继承 ``DeepAgentState``（含 messages/todos/files）；这里追加答疑场景需要的字段：
    - clarified_questions：已经向用户澄清过的问题（避免重复追问，HITL 记忆）
    - cited_chapters：本次会话引用过的章节（供最后做学习小结/知识图谱）
    """

    # 已澄清问题：使用 reducer 去重合并，多个节点写入不冲突
    clarified_questions: NotRequired[Annotated[list[str], _merge_unique]]
    # 已引用章节：同上
    cited_chapters: NotRequired[Annotated[list[str], _merge_unique]]


# ---------------------------------------------------------------------------
# 二、长期记忆：Store 与预填
# ---------------------------------------------------------------------------
def make_store() -> InMemoryStore:
    """创建长期记忆的 Store（开发用内存版；生产可换持久化实现）。"""
    return InMemoryStore()


def memory_paths() -> list[str]:
    """需要启动时注入系统提示词的记忆文件（对应 ch08 的 memory= 参数）。

    这两个文件都在 ``/memories/`` 路由下，namespace 由运行时 ``TaContext.user_id`` 决定，
    因此每个用户有自己的一份（可被自我改进）。
    """
    return ["/memories/AGENTS.md", "/memories/user-profile.md"]


# 组织级知识：所有用户共享、Agent 只读（对应 ch08 的组织级只读 + ch03 deny）
ORG_NAMESPACE = ("deepagents-course",)
POLICY_PATH = "/policies/teaching-policy.md"


def _store_key(key: str) -> str:
    """把虚拟路径归一化成 store key。

    对应 ch08 的实测细节：CompositeBackend 路由会剥掉前缀
    （``/memories/x.md`` → ``/x.md``、``/policies/x.md`` → ``/x.md``）。
    这里对宿主侧辅助函数做同样归一化，避免调用方记混。
    """
    for prefix in ("/memories/", "/policies/"):
        if key.startswith(prefix):
            return "/" + key[len(prefix):]
    return key


def seed_memory(store: InMemoryStore, *, user_id: str = "local-user") -> None:
    """应用代码预填长期记忆（不要手写底层 JSON，用 create_file_data）。

    对应 ch08「外部预填」：用户级行为准则 + 用户画像 + 组织级只读政策。
    注意：CompositeBackend 路由会剥掉 /memories/ 前缀，所以 store key 不带前缀。
    """
    # 用户级：答疑行为准则（每个用户一份，可自我改进）
    store.put(
        (user_id,),
        "/AGENTS.md",
        create_file_data(
            "# 客服答疑行为准则\n"
            "- 先判断问题属于哪一章，再依据 /knowledge/<chapter>.md 回答。\n"
            "- 引用课程代码时给出文件名，不要编造不存在的 API。\n"
            "- 问题不清晰时，先用 ask_clarification 追问，不要臆测。\n"
            "- 涉及执行 Shell 或修改文件时，说明会被人工审批。\n"
            "- 回答末尾标注来源章节（如 [ch03]）。\n"
        ),
    )
    # 用户级：默认画像（用户后续可让 Agent 更新）
    store.put(
        (user_id,),
        "/user-profile.md",
        create_file_data(
            "# 用户画像\n"
            "- 身份：本课程学员\n"
            "- 偏好：中文回答、代码示例完整可运行、先结论后细节\n"
            "- 已学章节：ch02-ch10\n"
        ),
    )
    # 组织级：教学政策（Agent 只能读，改不了——配合 /policies/ 路由 + deny 权限）
    store.put(
        ORG_NAMESPACE,
        "/teaching-policy.md",
        create_file_data(
            "# 教学政策（组织级，只读）\n"
            "- 答疑必须基于课程仓库 ch02-ch10 的真实代码，不臆造 API。\n"
            "- 涉及版本差异时，明确标注实测版本（如 deepagents 0.7.13）。\n"
            "- 不提供绕过沙箱或权限的「技巧」。\n"
        ),
    )


# ---------------------------------------------------------------------------
# 三、长期记忆的读写辅助（宿主平面，用于测试与演示）
# ---------------------------------------------------------------------------
def read_memory(store: InMemoryStore, user_id: str, key: str) -> str | None:
    """读取某个长期记忆文件。

    ``key`` 可以是虚拟路径（``/memories/x.md``）或已剥掉前缀的 store key（``/x.md``）。
    """
    item = store.get((user_id,), _store_key(key))
    return None if item is None else item.value.get("content")


def write_memory(store: InMemoryStore, user_id: str, key: str, content: str) -> None:
    """写入某个长期记忆文件（key 接受虚拟路径或 store key）。"""
    store.put((user_id,), _store_key(key), create_file_data(content))


def list_memories(store: InMemoryStore, user_id: str) -> list[str]:
    """列出某个用户命名空间下的记忆文件 key。"""
    return sorted(item.key for item in store.search((user_id,)))


# ---------------------------------------------------------------------------
# 四、会话记忆小结（把 state 里的引用章节整理成学习脉络）
# ---------------------------------------------------------------------------
def summarize_session(
    *,
    cited_chapters: list[str] | None,
    clarified_questions: list[str] | None,
) -> str:
    """把一次会话的状态整理成可读小结（供知识图谱技能与最终交付使用）。"""
    cited = cited_chapters or []
    clarified = clarified_questions or []

    lines = ["# 本次答疑小结", ""]
    if cited:
        lines.append("## 涉及章节")
        for key in cited:
            chapter = next((c for c in CHAPTERS if c.key == key), None)
            lines.append(f"- {key}：{chapter.title if chapter else '（未知章节）'}")
    else:
        lines.append("## 涉及章节\n- （本次未引用具体章节）")

    lines += ["", "## 已澄清的问题"]
    lines += [f"- {q}" for q in clarified] or ["- （无）"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 五、离线演示（无需模型）
# ---------------------------------------------------------------------------
def demo_offline() -> None:
    """离线演示记忆分层：同一 store 预填 → 读回 → 会话小结。"""
    print("=" * 60)
    print("记忆离线演示：预填 → 读回 → 会话小结")
    print("=" * 60)
    store = make_store()
    seed_memory(store, user_id="alice")
    print(f"  alice 的记忆文件: {list_memories(store, 'alice')}")
    print(f"  alice 的画像预览: {(read_memory(store, 'alice', '/user-profile.md') or '')[:40]!r}")

    # 模拟 Agent 更新用户偏好（长期记忆自我改进）
    write_memory(store, "alice", "/user-profile.md",
                 "# 用户画像\n- 偏好：用表格对比、给出最小可运行示例\n")
    print(f"  更新后画像: {(read_memory(store, 'alice', '/user-profile.md') or '')[:40]!r}")

    # bob 与 alice 隔离
    print(f"  bob 的记忆文件: {list_memories(store, 'bob')}（应为空，namespace 隔离）")

    print()
    print(summarize_session(cited_chapters=["ch03", "ch08"], clarified_questions=["你想问的是 StateBackend 还是 StoreBackend？"]))


if __name__ == "__main__":
    demo_offline()
