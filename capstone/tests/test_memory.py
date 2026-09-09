"""确定性测试：记忆层（无 LLM）。

覆盖 ch08 的核心断言：
  - 用户级 namespace 隔离
  - 长期记忆预填与读回
  - SessionState 的 reducer 去重合并
  - 会话小结生成
"""

from memory import (
    ORG_NAMESPACE,
    POLICY_PATH,
    SessionState,
    list_memories,
    make_store,
    memory_paths,
    read_memory,
    seed_memory,
    summarize_session,
    write_memory,
)
from memory import _merge_unique


def test_seed_and_read_memory():
    store = make_store()
    seed_memory(store, user_id="alice")
    assert "/AGENTS.md" in list_memories(store, "alice")
    assert "/user-profile.md" in list_memories(store, "alice")
    profile = read_memory(store, "alice", "/user-profile.md")
    assert profile and "本课程学员" in profile


def test_user_namespace_isolation():
    store = make_store()
    seed_memory(store, user_id="alice")
    # bob 没有预填，读不到 alice 的记忆
    assert list_memories(store, "bob") == []
    assert read_memory(store, "bob", "/user-profile.md") is None


def test_org_policy_shared():
    store = make_store()
    seed_memory(store, user_id="alice")
    policy = read_memory(store, ORG_NAMESPACE[0], POLICY_PATH)
    assert policy and "只读" in policy


def test_memory_self_improvement():
    store = make_store()
    seed_memory(store, user_id="alice")
    write_memory(store, "alice", "/user-profile.md", "# 用户画像\n- 偏好：用表格\n")
    assert "用表格" in read_memory(store, "alice", "/user-profile.md")


def test_memory_paths_under_memories_route():
    assert all(p.startswith("/memories/") for p in memory_paths())


def test_merge_unique_reducer():
    assert _merge_unique(["ch03"], ["ch08"]) == ["ch03", "ch08"]
    assert _merge_unique(["ch03"], ["ch03", "ch08"]) == ["ch03", "ch08"]
    assert _merge_unique(None, ["ch05"]) == ["ch05"]


def test_session_state_extends_deep_agent_state():
    annotations = SessionState.__annotations__
    # 继承来的字段 + 本作业新增字段
    assert "messages" in annotations
    assert "clarified_questions" in annotations
    assert "cited_chapters" in annotations
    assert "cited_chapters" in SessionState.__optional_keys__


def test_summarize_session():
    text = summarize_session(
        cited_chapters=["ch03", "ch08"],
        clarified_questions=["问的是哪个后端？"],
    )
    assert "ch03" in text and "ch08" in text
    assert "问的是哪个后端？" in text
