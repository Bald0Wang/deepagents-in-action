# ============================================================================
# test_filesystem_backend.py —— FilesystemBackend 确定性单测（无 LLM）
# 覆盖：写入/读取往返、分片读取、缺失文件、glob 匹配、grep 检索、
#       edit 替换、delete 删除、路径沙箱（父级穿越 + 绝对路径收容）
# ============================================================================

# 模块文档字符串：列出覆盖的测试点
"""FilesystemBackend 确定性单测：分片读取 / glob / grep / edit / delete / 路径沙箱。"""

# pytest：测试框架（fixture、raises 等）
import pytest

# FilesystemBackend：被测后端
from deepagents.backends import FilesystemBackend


# ---------------------------------------------------------------------------
# fixture backend：为每个测试创建一个干净的本地磁盘后端（根目录用 pytest 临时目录）
# ---------------------------------------------------------------------------
@pytest.fixture()
def backend(tmp_path):
    # tmp_path 是 pytest 内置的「每个测试独立的临时目录」
    # 开启 virtual_mode 路径沙箱，与课程推荐一致
    return FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)


# ---------------------------------------------------------------------------
# _content：从 ReadResult 中取出纯文本内容（0.7.6 的 file_data 是 dict）
# ---------------------------------------------------------------------------
def _content(res):
    """从 ReadResult 中取文本内容（0.7.6 file_data 是 dict）。"""
    # file_data 是 dict 则取 content 字段，否则直接返回（向后兼容旧版）
    return res.file_data["content"] if isinstance(res.file_data, dict) else res.file_data


# 测试：写入后读取应得到原内容（往返一致）
def test_write_and_read_roundtrip(backend):
    # 写入三行文本
    backend.write("/workspace/notes.md", "line1\nline2\nline3")
    # 读回
    res = backend.read("/workspace/notes.md")
    # 断言无错误
    assert res.error is None
    # 断言内容一致
    assert _content(res) == "line1\nline2\nline3"


# 测试：分片读取的 offset/limit 边界
def test_read_slicing_offset_limit(backend):
    # 构造 10 行文件（L1~L10）
    backend.write("/big.txt", "\n".join(f"L{i}" for i in range(1, 11)))
    # 从第 5 行起读 3 行
    res = backend.read("/big.txt", offset=5, limit=3)
    # 断言起始行号=6（第 5 行之后）、结束行号=8、下一页偏移=8
    assert res.start_line == 6
    assert res.end_line == 8
    assert res.next_offset == 8
    # 断言读到的行（splitlines 忽略末尾换行差异）
    assert _content(res).splitlines() == ["L6", "L7", "L8"]


# 测试：读取不存在的文件应返回错误
def test_read_missing_file_returns_error(backend):
    # 读一个不存在的文件
    res = backend.read("/nope.md")
    # 断言 error 非空
    assert res.error is not None


# 测试：glob 只匹配 .md 文件
def test_glob_pattern_match(backend):
    # 写两个 .md 和一个 .txt
    backend.write("/a.md", "x")
    backend.write("/b.md", "x")
    backend.write("/c.txt", "x")
    # glob 匹配 **/*.md
    matches = backend.glob("**/*.md", path="/").matches
    # 提取路径集合
    paths = {m["path"] for m in matches}
    # 断言只包含两个 .md（不含 c.txt）
    assert paths == {"/a.md", "/b.md"}


# 测试：grep 命中行号正确
def test_grep_content(backend):
    # 写一个含两处 TODO 的文件
    backend.write("/src/app.py", "# TODO: fix\nok line\n# TODO: again")
    # grep 检索 TODO
    matches = backend.grep("TODO", glob="**/*.py").matches
    # 断言命中行号为 [1, 3]
    assert [m["line"] for m in matches] == [1, 3]
    # 断言所有命中都在 /src/app.py
    assert all(m["path"] == "/src/app.py" for m in matches)


# 测试：edit 精确替换
def test_edit_exact_replace(backend):
    # 写入两行
    backend.write("/src/app.py", "old_value = 1\nkeep = 2")
    # 精确替换第一行
    res = backend.edit("/src/app.py", "old_value = 1", "old_value = 2")
    # 断言无错误、替换 1 次
    assert res.error is None
    assert res.occurrences == 1
    # 断言替换后的内容
    assert _content(backend.read("/src/app.py")) == "old_value = 2\nkeep = 2"


# 测试：delete 删除文件
def test_delete(backend):
    # 先写一个文件
    backend.write("/tmp.txt", "gone")
    # 删除
    res = backend.delete("/tmp.txt")
    # 断言删除无错误
    assert res.error is None
    # 断言再读时已不存在（error 非空）
    assert backend.read("/tmp.txt").error is not None


# 测试：路径沙箱拦截父级穿越（..）
def test_sandbox_blocks_parent_traversal(backend):
    # 尝试写 ../../escape.txt，应抛出 ValueError
    with pytest.raises(ValueError):
        backend.write("../../escape.txt", "x")


# 测试：绝对路径被收容到沙箱根目录内（不触碰真实 /etc）
def test_sandbox_scopes_absolute_path_inside_root(backend, tmp_path):
    # 绝对路径被当作沙箱内虚拟路径，落到 root_dir 下，不触碰真实 /etc
    backend.write("/etc/evil.txt", "x")
    # 断言实际落盘在临时目录的 etc/evil.txt
    assert (tmp_path / "etc" / "evil.txt").exists()
