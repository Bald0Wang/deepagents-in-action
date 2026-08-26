# ============================================================================
# test_custom_backends.py —— 自定义后端确定性单测（无 LLM）
# 覆盖：S3Backend 六方法、GuardedBackend 拦截、PolicyWrapper 拦截 + 透传
# ============================================================================

# 模块文档字符串：说明覆盖的类
"""自定义后端确定性单测：S3Backend / GuardedBackend / PolicyWrapper。"""

# pytest：测试框架
import pytest

# FilesystemBackend：PolicyWrapper 的内层后端用
from deepagents.backends import FilesystemBackend

# 从 custom_backends 导入三个被测类（与主脚本共用同一份实现）
from custom_backends import GuardedBackend, PolicyWrapper, S3Backend


# ---------------------------------------------------------------------------
# _content：从 ReadResult 中取出纯文本内容
# ---------------------------------------------------------------------------
def _content(res):
    return res.file_data["content"] if isinstance(res.file_data, dict) else res.file_data


# ===========================================================================
# 一、S3Backend
# ===========================================================================
# fixture s3：创建 S3Backend 实例
@pytest.fixture()
def s3():
    return S3Backend(bucket="demo", prefix="agent/")


# 测试：写入后读取一致
def test_s3_write_read(s3):
    # 写入
    s3.write("/docs/a.md", "# A\nhello")
    # 断言读回一致
    assert _content(s3.read("/docs/a.md")) == "# A\nhello"


# 测试：读取不存在的文件返回错误
def test_s3_read_missing(s3):
    # 断言 error 非空
    assert s3.read("/docs/nope.md").error is not None


# 测试：ls 列出直接子条目
def test_s3_ls(s3):
    # 写两个文件
    s3.write("/docs/a.md", "x")
    s3.write("/docs/b.md", "x")
    # 列出 /docs，提取路径集合
    paths = {e["path"] for e in s3.ls("/docs").entries}
    # 断言包含两个文件
    assert paths == {"/docs/a.md", "/docs/b.md"}


# 测试：glob 只匹配 .md
def test_s3_glob(s3):
    # 写一个 .md 和一个 .txt
    s3.write("/docs/a.md", "x")
    s3.write("/docs/b.txt", "x")
    # glob **/*.md
    matches = [m["path"] for m in s3.glob("**/*.md").matches]
    # 断言只匹配到 a.md（带 agent/ 前缀）
    assert matches == ["/agent/docs/a.md"]


# 测试：grep 定位 TODO 行号
def test_s3_grep(s3):
    # 写含 TODO 的内容
    s3.write("/docs/a.md", "# A\n# TODO: review\nok")
    # grep TODO
    matches = s3.grep("TODO", glob="*.md").matches
    # 断言命中 1 处、在第 2 行
    assert len(matches) == 1
    assert matches[0]["line"] == 2


# 测试：edit 精确替换
def test_s3_edit(s3):
    # 写入
    s3.write("/docs/a.md", "hello world")
    # 替换
    res = s3.edit("/docs/a.md", "hello world", "hello s3")
    # 断言替换 1 次
    assert res.occurrences == 1
    # 断言读回为新值
    assert _content(s3.read("/docs/a.md")) == "hello s3"


# 测试：edit 遇到多处匹配且未 replace_all 时返回错误
def test_s3_edit_ambiguous(s3):
    # 写入两个相同单词
    s3.write("/docs/a.md", "dup dup")
    # 替换 "dup"，出现两次且未 replace_all
    res = s3.edit("/docs/a.md", "dup", "x")
    # 断言返回错误（避免误替换）
    assert res.error is not None


# ===========================================================================
# 二、GuardedBackend
# ===========================================================================
# fixture guarded：创建禁止 /policies 前缀的 GuardedBackend
@pytest.fixture()
def guarded(tmp_path):
    return GuardedBackend(deny_prefixes=["/policies"], root_dir=str(tmp_path), virtual_mode=True)


# 测试：普通路径写入放行
def test_guarded_allows_normal(guarded):
    assert guarded.write("/workspace/ok.md", "ok").error is None


# 测试：受保护路径写入被拒
def test_guarded_denies_write(guarded):
    assert guarded.write("/policies/x.md", "no").error is not None


# 测试：受保护路径编辑被拒、普通路径编辑放行
def test_guarded_denies_edit(guarded):
    # 先写一个普通文件（供后续正常编辑验证）
    guarded.write("/workspace/ok.md", "ok")
    # 编辑受保护路径：应被拒
    assert guarded.edit("/policies/x.md", "a", "b").error is not None
    # 编辑普通路径：应放行
    assert guarded.edit("/workspace/ok.md", "ok", "ok2").error is None


# ===========================================================================
# 三、PolicyWrapper
# ===========================================================================
# fixture wrapped：创建包住 FilesystemBackend 的 PolicyWrapper
@pytest.fixture()
def wrapped(tmp_path):
    # 内层后端
    inner = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)
    # 包装，禁止 /policies 前缀
    return PolicyWrapper(inner=inner, deny_prefixes=["/policies"])


# 测试：普通路径写入放行，读取正常
def test_wrapper_allows_normal(wrapped):
    # 写入普通路径：应成功
    assert wrapped.write("/workspace/ok.md", "ok").error is None
    # 读回应为原内容（验证 read 透传）
    assert _content(wrapped.read("/workspace/ok.md")) == "ok"


# 测试：受保护路径写入被拒
def test_wrapper_denies(wrapped):
    assert wrapped.write("/policies/x.md", "no").error is not None


# 测试：其余方法（glob）原样透传
def test_wrapper_passthrough_other_methods(wrapped):
    # 写入一个文件
    wrapped.write("/workspace/ok.md", "ok")
    # glob 应能匹配到（验证 glob 透传）
    matches = wrapped.glob("**/*.md").matches
    assert {m["path"] for m in matches} == {"/workspace/ok.md"}
