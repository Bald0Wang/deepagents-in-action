# ============================================================================
# test_backends.py —— LocalShellBackend / StoreBackend / CompositeBackend 确定性单测（无 LLM）
# 覆盖：Shell 执行（成功/失败）、Store 读写/编辑/命名空间隔离、Composite 路由分流
# ============================================================================

# 模块文档字符串：说明覆盖的后端
"""LocalShellBackend / StoreBackend / CompositeBackend 确定性单测（无 LLM）。"""

# pytest：测试框架
import pytest

# 从 deepagents.backends 导入被测后端
from deepagents.backends import (
    CompositeBackend,     # 混合路由后端
    FilesystemBackend,    # 本地磁盘后端（Composite 的默认后端用）
    LocalShellBackend,    # 本地 Shell 后端
    StoreBackend,         # 跨会话持久化后端
)
# InMemoryStore：StoreBackend 的内存存储载体
from langgraph.store.memory import InMemoryStore


# ---------------------------------------------------------------------------
# _content：从 ReadResult 中取出纯文本内容（0.7.6 的 file_data 是 dict）
# ---------------------------------------------------------------------------
def _content(res):
    return res.file_data["content"] if isinstance(res.file_data, dict) else res.file_data


# ===========================================================================
# 一、LocalShellBackend
# ===========================================================================
# 测试：execute 执行成功（echo + python 求和）
def test_local_shell_execute_success(tmp_path):
    # 创建本地 Shell 后端（inherit_env=False 最小化环境）
    b = LocalShellBackend(root_dir=str(tmp_path), virtual_mode=True, inherit_env=False)
    # 执行命令
    resp = b.execute("echo shell-ok && python3 -c 'print(1+2)'")
    # 断言退出码 0、输出含 "shell-ok" 和 "3"
    assert resp.exit_code == 0
    assert "shell-ok" in resp.output
    assert "3" in resp.output


# 测试：execute 执行失败（返回非零退出码）
def test_local_shell_execute_failure(tmp_path):
    # 创建后端
    b = LocalShellBackend(root_dir=str(tmp_path), virtual_mode=True, inherit_env=False)
    # 执行 exit 7，让命令以退出码 7 结束
    resp = b.execute("exit 7")
    # 断言退出码为 7
    assert resp.exit_code == 7


# ===========================================================================
# 二、StoreBackend
# ===========================================================================
# fixture store_backend：创建共享的 store + StoreBackend，返回 (后端, store)
@pytest.fixture()
def store_backend():
    # 内存 store
    store = InMemoryStore()
    # namespace：本地 invoke 时 rt.server_info 为 None，兜底 local-user
    ns = lambda rt: (rt.server_info.user.identity,) if getattr(rt, "server_info", None) else ("local-user",)
    # 返回 StoreBackend 和 store（后者供隔离测试复用）
    return StoreBackend(namespace=ns, store=store), store


# 测试：Store 写入后读取内容一致
def test_store_write_read(store_backend):
    # 解构 fixture 返回值，只取后端
    b, _ = store_backend
    # 写入
    b.write("/mem/pref.txt", "偏好：简洁")
    # 断言读回一致
    assert _content(b.read("/mem/pref.txt")) == "偏好：简洁"


# 测试：Store edit 替换
def test_store_edit(store_backend):
    # 解构后端
    b, _ = store_backend
    # 写入旧值
    b.write("/mem/pref.txt", "旧值")
    # 替换
    res = b.edit("/mem/pref.txt", "旧值", "新值")
    # 断言无错误
    assert res.error is None
    # 断言读回为新值
    assert _content(b.read("/mem/pref.txt")) == "新值"


# 测试：namespace 隔离（另一用户读不到）
def test_store_namespace_isolation(store_backend):
    # 解构后端与 store
    b, store = store_backend
    # 写入私有内容
    b.write("/mem/private.txt", "secret")
    # 另一个 namespace（另一个用户）读不到同一份数据
    other = StoreBackend(namespace=lambda rt: ("other-user",), store=store)
    # 断言读不到（error 非空）
    assert other.read("/mem/private.txt").error is not None


# ===========================================================================
# 三、CompositeBackend：路由分流
# ===========================================================================
# fixture composite：创建 CompositeBackend（default=本地磁盘，/mem/=Store），返回 (后端, 临时目录, store)
@pytest.fixture()
def composite(tmp_path):
    # 内存 store
    store = InMemoryStore()
    # namespace 兜底
    ns = lambda rt: (rt.server_info.user.identity,) if getattr(rt, "server_info", None) else ("local-user",)
    # 组合后端：默认本地磁盘，/mem/ 前缀路由到 StoreBackend
    return CompositeBackend(
        default=FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True),
        routes={"/mem/": StoreBackend(namespace=ns, store=store)},
    ), tmp_path, store


# 测试：按前缀路由分流（普通路径落磁盘、/mem/ 前缀进 store）
def test_composite_routes_by_prefix(composite):
    # 解构返回值
    b, tmp_path, store = composite
    # 普通路径 -> default（本地磁盘）：断言真实落盘
    b.write("/workspace/draft.md", "草稿")
    assert (tmp_path / "workspace" / "draft.md").exists()
    # /mem/ 前缀 -> StoreBackend（内存 store，不落磁盘）：断言未落盘
    b.write("/mem/keep.txt", "持久")
    assert not (tmp_path / "mem").exists()
    # 断言 /mem/ 内容仍可读回（来自 store）
    assert _content(b.read("/mem/keep.txt")) == "持久"
