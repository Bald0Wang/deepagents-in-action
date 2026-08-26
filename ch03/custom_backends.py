# ============================================================================
# custom_backends.py —— ch03 段4 的自定义后端集合（供脚本与测试共用）
# 三个类演示了自定义后端 / 安全策略的三种写法：
#   GuardedBackend —— 继承现有后端（课程「方式一」）
#   PolicyWrapper  —— 通用包装器（课程「方式二」，适用于任何后端）
#   S3Backend      —— 从头实现 BackendProtocol 六方法（内存 dict 模拟对象存储）
# ============================================================================

# 模块文档字符串：说明本文件包含的三类后端
"""ch03 段4 的自定义后端集合（供脚本与测试共用）。

包含课程对应的三类：
  - GuardedBackend : 继承 FilesystemBackend，拦截 deny_prefixes
  - PolicyWrapper  : 通用包装器，适用于任何后端
  - S3Backend      : 实现 BackendProtocol 六方法（内存 dict 模拟对象存储）
"""

# fnmatch：Unix 风格通配符匹配（S3Backend 的 grep/glob 用它做文件名匹配）
import fnmatch

# FilesystemBackend：作为 GuardedBackend 的父类（本地磁盘后端）
from deepagents.backends import FilesystemBackend
# 从协议模块导入后端接口与各类结果对象（返回值类型标注用）
from deepagents.backends.protocol import (
    BackendProtocol,   # 后端协议：要求实现 ls/read/write/edit/grep/glob
    EditResult,        # edit 操作结果
    GlobResult,        # glob 操作结果
    GrepResult,        # grep 操作结果
    LsResult,          # ls 操作结果
    ReadResult,        # read 操作结果
    WriteResult,       # write 操作结果
)


# ============================================================================
# 一、GuardedBackend —— 继承现有后端（课程「方式一」）
# 思路：在 FilesystemBackend 基础上，重写 write/edit，对敏感前缀直接拒绝。
# ============================================================================
class GuardedBackend(FilesystemBackend):
    def __init__(self, *, deny_prefixes: list[str], **kwargs):
        # 调用父类初始化，处理 root_dir / virtual_mode 等参数
        super().__init__(**kwargs)
        # 归一化前缀列表：确保每个前缀都以 "/" 结尾，避免误匹配（如 /policy 匹配到 /policies）
        self.deny_prefixes = [p if p.endswith("/") else p + "/" for p in deny_prefixes]

    def _denied(self, file_path: str) -> bool:
        # 判断路径是否命中任一被禁止的前缀（startswith 前缀匹配）
        return any(file_path.startswith(p) for p in self.deny_prefixes)

    def write(self, file_path: str, content: str) -> WriteResult:
        # 命中禁用前缀：不执行写入，直接返回带错误信息的 WriteResult
        if self._denied(file_path):
            return WriteResult(error=f"写入被拒绝：{file_path}")
        # 未命中：交给父类正常写入
        return super().write(file_path, content)

    def edit(self, file_path: str, old_string: str, new_string: str,
             replace_all: bool = False) -> EditResult:
        # 命中禁用前缀：不执行编辑，直接返回带错误信息的 EditResult
        if self._denied(file_path):
            return EditResult(error=f"编辑被拒绝：{file_path}")
        # 未命中：交给父类正常编辑
        return super().edit(file_path, old_string, new_string, replace_all)


# ============================================================================
# 二、PolicyWrapper —— 通用包装器（课程「方式二」）
# 思路：不继承具体后端，而是「包住」任意一个 BackendProtocol 实例，
#       只拦截 write/edit，其余方法原样透传给内层后端。
# ============================================================================
class PolicyWrapper(BackendProtocol):
    def __init__(self, inner: BackendProtocol, deny_prefixes: list[str]):
        # 保存被包装的内层后端（任何实现了 BackendProtocol 的对象）
        self.inner = inner
        # 归一化前缀列表（同 GuardedBackend）
        self.deny_prefixes = [p if p.endswith("/") else p + "/" for p in deny_prefixes]

    def _deny(self, path: str) -> bool:
        # 判断路径是否命中禁用前缀
        return any(path.startswith(p) for p in self.deny_prefixes)

    # 以下四个只读方法：原样透传给内层后端，不做任何拦截
    def ls(self, path): return self.inner.ls(path)
    def read(self, file_path, offset=0, limit=2000): return self.inner.read(file_path, offset=offset, limit=limit)
    def grep(self, pattern, path=None, glob=None): return self.inner.grep(pattern, path, glob)
    def glob(self, pattern, path="/"): return self.inner.glob(pattern, path)

    def write(self, file_path: str, content: str) -> WriteResult:
        # 命中禁用前缀：拒绝写入
        if self._deny(file_path):
            return WriteResult(error=f"写入被拒绝：{file_path}")
        # 未命中：透传给内层后端
        return self.inner.write(file_path, content)

    def edit(self, file_path: str, old_string: str, new_string: str,
             replace_all: bool = False) -> EditResult:
        # 命中禁用前缀：拒绝编辑
        if self._deny(file_path):
            return EditResult(error=f"编辑被拒绝：{file_path}")
        # 未命中：透传给内层后端
        return self.inner.edit(file_path, old_string, new_string, replace_all)


# ============================================================================
# 三、S3Backend —— 从头实现 BackendProtocol 六方法（内存 dict 模拟对象存储）
# 思路：用一个 Python dict 模拟 S3 的对象存储，key 是对象路径，value 是内容。
#       实现了协议要求的 ls/read/write/edit/grep/glob 六个方法。
# ============================================================================
class S3Backend(BackendProtocol):
    def __init__(self, bucket: str, prefix: str = ""):
        # bucket：模拟的 S3 桶名（本实现未实际使用，仅作语义标记）
        self.bucket = bucket
        # prefix：对象 key 的统一前缀（模拟 S3 的目录前缀），去掉末尾 "/"
        self.prefix = prefix.rstrip("/")
        # 核心存储：dict，key 为带前缀的对象路径，value 为文件内容
        self._objects: dict[str, str] = {}

    def _key(self, path: str) -> str:
        # 把逻辑路径转成实际存储 key：前缀 + 路径，再去掉开头多余的 "/"
        return (self.prefix + path).lstrip("/")

    # -- 六方法之一：ls（列出目录条目）---------------------------------------
    def ls(self, path: str) -> LsResult:
        # 目标目录对应的存储 key 前缀（去掉末尾 "/"）
        base = self._key(path).rstrip("/")
        # seen：去重集合，key 是条目名，value 是条目信息 dict（path + is_dir）
        seen: dict[str, dict] = {}
        # 遍历所有已存对象
        for key in self._objects:
            # 计算相对 base 的路径：命中前缀则去掉前缀，否则直接用完整 key
            rel = key[len(base):].lstrip("/") if base and key.startswith(base) else key
            # 相对路径为空说明就是 base 本身，跳过（不是子条目）
            if not rel:
                continue
            # 取第一段作为「直接子条目」的名字
            head = rel.split("/", 1)[0]
            # 记录条目：is_dir 通过是否还含 "/" 判断（含 "/" 说明下面还有层级）
            seen[head] = {"path": f"{path.rstrip('/')}/{head}", "is_dir": "/" in rel}
        # 返回去重后的条目列表
        return LsResult(entries=list(seen.values()))

    # -- 六方法之二：read（读取文件，支持分片）-------------------------------
    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        # 转成实际存储 key
        key = self._key(file_path)
        # 对象不存在则返回错误结果
        if key not in self._objects:
            return ReadResult(error=f"File not found: {file_path}")
        # 按行拆分内容
        lines = self._objects[key].splitlines()
        # 取 [offset, offset+limit) 的行片段（模拟分片读取）
        chunk = lines[offset:offset + limit]
        # 组装 ReadResult：内容、总行数、起始/结束行号、下一页偏移
        return ReadResult(
            file_data={"content": "\n".join(chunk), "encoding": "utf-8"},
            total_lines=len(lines),
            start_line=offset + 1 if chunk else None,          # 起始行号（1 起）
            end_line=offset + len(chunk) if chunk else None,   # 结束行号
            next_offset=offset + limit if (offset + limit) < len(lines) else None,  # 还有下一页才给 offset
        )

    # -- 六方法之三：write（写入文件）----------------------------------------
    def write(self, file_path: str, content: str) -> WriteResult:
        # 直接写入 dict（覆盖写）
        self._objects[self._key(file_path)] = content
        # 返回成功结果，带逻辑路径
        return WriteResult(path=file_path)

    # -- 六方法之四：edit（精确替换）-----------------------------------------
    def edit(self, file_path: str, old_string: str, new_string: str,
             replace_all: bool = False) -> EditResult:
        # 转成实际存储 key
        key = self._key(file_path)
        # 对象不存在则报错
        if key not in self._objects:
            return EditResult(error=f"File not found: {file_path}")
        # 统计旧字符串出现次数
        count = self._objects[key].count(old_string)
        # 找不到旧字符串则报错
        if count == 0:
            return EditResult(error=f"String not found in {file_path}")
        # 出现多次但未指定 replace_all，则拒绝（避免误替换），提示调用方
        if not replace_all and count > 1:
            return EditResult(error=f"String appears {count} times; pass replace_all=True or be more specific")
        # 执行替换：replace_all 用 -1（全部），否则只替换第一个
        self._objects[key] = self._objects[key].replace(old_string, new_string, -1 if replace_all else 1)
        # 返回成功结果，occurrences 记录替换次数
        return EditResult(path=file_path, occurrences=1 if not replace_all else count)

    # -- 六方法之五：grep（内容检索）-----------------------------------------
    def grep(self, pattern: str, path: str | None = None, glob: str | None = None):
        # 目标路径对应的 key 前缀（无 path 则为空串，表示全量搜索）
        base = self._key(path).rstrip("/") if path else ""
        # matches：命中结果列表，每项 {path, line, text}
        matches = []
        # 遍历所有已存对象
        for key, content in self._objects.items():
            # 指定了 base 且 key 不以 base 开头，则跳过（不在搜索范围内）
            if base and not key.startswith(base):
                continue
            # 取文件名（路径最后一段），用于 glob 过滤
            fname = key.rsplit("/", 1)[-1]
            # 指定了 glob 且文件名不匹配，则跳过
            if glob and not fnmatch.fnmatch(fname, glob):
                continue
            # 逐行扫描内容，命中 pattern 则记录（行号从 1 开始）
            for lineno, line in enumerate(content.splitlines(), 1):
                if pattern in line:
                    matches.append({"path": "/" + key.lstrip("/"), "line": lineno, "text": line})
        # 返回命中结果
        return GrepResult(matches=matches)

    # -- 六方法之六：glob（模式匹配文件路径）---------------------------------
    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        # 目标目录对应的 key 前缀
        base = self._key(path).rstrip("/")
        # out：匹配结果列表，每项 {path, is_dir}
        out = []
        # 遍历所有已存对象
        for key in self._objects:
            # 计算相对 base 的路径
            rel = key[len(base):].lstrip("/") if base and key.startswith(base) else key
            # 相对路径或绝对路径任一匹配模式，即命中
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch("/" + rel, pattern):
                out.append({"path": "/" + key.lstrip("/"), "is_dir": False})
        # 返回匹配结果
        return GlobResult(matches=out)
