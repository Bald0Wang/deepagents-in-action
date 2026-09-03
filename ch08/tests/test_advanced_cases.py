"""高级用法确定性测试：情景检索工具 / 并发写入与缓解 / 多 Agent 隔离 / 升级路径。"""

from langgraph.store.memory import InMemoryStore

from deepagents.backends import StoreBackend
from deepagents.backends.utils import create_file_data

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _tool_helpers import make_search_episodes_tool, seed_episode  # noqa: E402


def test_episode_search_finds_and_misses():
    store = InMemoryStore()
    ns = ("u",)
    seed_episode(store, ns, "e001", "2026-09-01", "用户问 GIL，建议 IO 密集用 threading。")
    seed_episode(store, ns, "e002", "2026-09-02", "用户偏好 sorted() 不改原列表。")
    search = make_search_episodes_tool(store, ns)
    hit = search("GIL")
    assert "threading" in hit and "e001" in hit
    miss = search("不存在的关键词xyz")
    assert "没有找到" in miss


def test_last_write_wins_conflict():
    store = InMemoryStore()
    b = StoreBackend(namespace=lambda _rt: ("u",), store=store)
    b.write("/preferences.md", "线程1的内容")
    b.write("/preferences.md", "线程2的内容")
    assert b.read("/preferences.md").file_data["content"] == "线程2的内容"   # 先写丢失


def test_topic_split_avoids_conflict():
    store = InMemoryStore()
    b = StoreBackend(namespace=lambda _rt: ("u",), store=store)
    b.write("/coding_style.md", "注释用中文")
    b.write("/theme.md", "主题色暗色")
    assert b.read("/coding_style.md").file_data["content"] == "注释用中文"
    assert b.read("/theme.md").file_data["content"] == "主题色暗色"        # 双双存活


def test_append_only_event_logs_coexist():
    store = InMemoryStore()
    b = StoreBackend(namespace=lambda _rt: ("u",), store=store)
    b.write("/events/t001.md", "学到A")
    b.write("/events/t002.md", "学到B")
    keys = {i.key for i in store.search(("u",))}
    assert keys == {"/events/t001.md", "/events/t002.md"}                  # 零覆盖


def test_multi_agent_namespace_isolation():
    store = InMemoryStore()
    a = StoreBackend(namespace=lambda _rt: ("assistant-a", "user-42"), store=store)
    b = StoreBackend(namespace=lambda _rt: ("assistant-b", "user-42"), store=store)
    a.write("/AGENTS.md", "Agent A：LangGraph")
    b.write("/AGENTS.md", "Agent B：数据分析")
    assert "LangGraph" in a.read("/AGENTS.md").file_data["content"]
    assert "数据分析" in b.read("/AGENTS.md").file_data["content"]
    ns = {i.namespace for probe in ("assistant-a", "assistant-b")
          for i in store.search((probe,))}
    assert ns == {("assistant-a", "user-42"), ("assistant-b", "user-42")}
