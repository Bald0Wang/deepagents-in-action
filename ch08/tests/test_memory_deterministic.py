"""确定性单测（无 LLM）：存储格式 / namespace 隔离 / Composite 路由与前缀剥离。"""

from pathlib import Path
import tempfile

from langgraph.store.memory import InMemoryStore

from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend, StoreBackend
from deepagents.backends.utils import create_file_data


def make_store_backend(store, namespace):
    return StoreBackend(namespace=lambda _rt: namespace, store=store)


def test_create_file_data_is_v2_format():
    data = create_file_data("第一行\n第二行")
    assert isinstance(data["content"], str)          # v2：content 是完整字符串
    assert data.get("encoding") == "utf-8"


def test_store_roundtrip_with_created_modified():
    store = InMemoryStore()
    store.put(("u",), "/AGENTS.md", create_file_data("hello"))
    backend = make_store_backend(store, ("u",))
    res = backend.read("/AGENTS.md")
    assert res.error is None
    assert res.file_data["content"] == "hello"
    item = next(iter(store.search(("u",))))
    assert "created_at" in item.value            # v2 元数据字段
    assert "modified_at" in item.value


def test_namespace_isolation():
    """不同 namespace 同 key 互不可见（用户隔离的基础）。"""
    store = InMemoryStore()
    store.put(("user-A",), "/preferences.md", create_file_data("A 的偏好"))
    backend_b = make_store_backend(store, ("user-B",))
    assert backend_b.read("/preferences.md").error is not None   # B 读不到 A 的
    backend_a = make_store_backend(store, ("user-A",))
    assert backend_a.read("/preferences.md").file_data["content"] == "A 的偏好"


def test_composite_routes_and_prefix_strip():
    """/memories/ 路由到 Store（key 剥前缀），其余走 default。"""
    store = InMemoryStore()
    with tempfile.TemporaryDirectory() as d:
        default = FilesystemBackend(root_dir=d, virtual_mode=True)
        comp = CompositeBackend(
            default=default,
            routes={"/memories/": make_store_backend(store, ("u",))},
        )
        # /memories/ 路径 → store，key 剥掉前缀
        comp.write("/memories/prefs.md", "长期")
        assert [i.key for i in store.search(("u",))] == ["/prefs.md"]
        # 非 /memories/ 路径 → default 落盘
        comp.write("/workspace/draft.md", "临时")
        assert (Path(d) / "workspace" / "draft.md").exists()
        assert not list(store.search(("u",))) or all(
            i.key == "/prefs.md" for i in store.search(("u",))
        )
        # 路由读回：带前缀路径能读回 store 里的内容
        res = comp.read("/memories/prefs.md")
        assert res.file_data["content"] == "长期"


def test_prefill_key_must_strip_route_prefix():
    """外部预填的坑：put 的 key 必须是剥前缀形式，否则 Agent 侧读不到。"""
    store = InMemoryStore()
    store.put(("u",), "/wrong/SKILL.md", create_file_data("放错位置的 key"))
    comp = CompositeBackend(
        default=StateBackend(),
        routes={"/skills/": make_store_backend(store, ("u",))},
    )
    # Agent 视角的路径 /skills/wrong/SKILL.md → 映射到 store key /wrong/SKILL.md ✅
    res = comp.read("/skills/wrong/SKILL.md")
    assert res.error is None
    # 但如果把带前缀的 key 直接 put 进去（"/skills/wrong/SKILL.md"），就映射不上
    store.put(("u",), "/skills/greeting/SKILL.md", create_file_data("错误示范"))
    assert comp.read("/skills/greeting/SKILL.md").error is not None
