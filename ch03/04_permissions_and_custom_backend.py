# ============================================================================
# 04_permissions_and_custom_backend.py —— ch03 段4：权限控制 + 自定义后端
# 四个演示函数：
#   part_a_declarative_permission() —— FilesystemPermission（声明式 deny）
#   part_b_guarded_backend()        —— GuardedBackend（继承式拦截）
#   part_c_policy_wrapper()         —— PolicyWrapper（通用包装器）
#   part_d_s3_backend()             —— S3Backend（实现 BackendProtocol 六方法）
# 三个自定义后端定义在 custom_backends.py，供脚本与测试共用。
# ============================================================================

# 模块文档字符串：说明四部分内容
"""ch03 段4：权限控制 + 自定义后端。

  Part A: FilesystemPermission（声明式）—— deny /policies/** 的写入，端到端验证
  Part B: GuardedBackend（继承 FilesystemBackend，拦截 deny_prefixes）
  Part C: PolicyWrapper（通用包装器，适用于任何后端）
  Part D: 自定义 S3Backend（实现 BackendProtocol 6 个方法，内存 dict 模拟 S3）

三类自定义后端定义在 custom_backends.py，供脚本与测试共用。
"""

# 从 common 导入公共工具
from common import make_model, preview

# 从 custom_backends 导入三个自定义后端类（与测试共用同一份实现）
from custom_backends import GuardedBackend, PolicyWrapper, S3Backend

# create_deep_agent：创建 Agent 入口
from deepagents import create_deep_agent
# FilesystemBackend：作为 PolicyWrapper 的内层后端（Part C）
from deepagents.backends import FilesystemBackend
# FilesystemPermission：声明式权限规则（Part A）
from deepagents.middleware import FilesystemPermission


# ---------------------------------------------------------------------------
# Part A：FilesystemPermission 声明式权限（deny /policies/** 写入）
# 通过 create_deep_agent 的 permissions 参数声明「禁止写 /policies/**」，
# 让 Agent 端到端尝试写入普通路径与受保护路径，观察后者被拒。
# ---------------------------------------------------------------------------
def part_a_declarative_permission():
    # 打印标题
    print("=" * 60)
    print("Part A: FilesystemPermission 声明式权限（deny /policies/** 写入）")
    print("=" * 60)
    # 创建 Agent，注入一条 deny 规则：禁止对 /policies/** 的 write 操作
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是文件助手，严格按指令操作并汇报每一步是否成功。",
        permissions=[
            FilesystemPermission(operations=["write"], paths=["/policies/**"], mode="deny"),
        ],
    )
    # 让 Agent 依次尝试写普通路径与受保护路径
    r = agent.invoke(
        {"messages": [{"role": "user", "content": (
            "请依次尝试并汇报结果："
            "1) write_file /workspace/note.md 内容 '普通笔记'；"
            "2) write_file /policies/rule.md 内容 '机密政策'；"
            "最后说明哪一步成功、哪一步被拒绝。"
        )}]}
    )
    # 打印 Agent 汇报
    print("--- Agent 汇报 ---")
    print(result_report(r))


# ---------------------------------------------------------------------------
# Part B：GuardedBackend（继承 FilesystemBackend，拦截 /policies/）
# 后端层面重写 write/edit，直接拒绝 deny_prefixes 命中的路径。
# ---------------------------------------------------------------------------
def part_b_guarded_backend():
    # 打印标题
    print()
    print("=" * 60)
    print("Part B: GuardedBackend（继承 FilesystemBackend，拦截 /policies/）")
    print("=" * 60)
    # 局部导入（仅本函数用到）
    import shutil                      # 递归删除临时目录
    from pathlib import Path           # 拼接路径
    # 本地临时根目录
    root = Path(__file__).parent / ".guard_root"
    # 清空并重建
    shutil.rmtree(root, ignore_errors=True)
    # 创建 GuardedBackend，禁止 /policies 前缀
    b = GuardedBackend(deny_prefixes=["/policies"], root_dir=str(root), virtual_mode=True)
    # 写普通路径：应成功（error=None）
    print("  write /workspace/ok.md :", b.write("/workspace/ok.md", "ok").error)
    # 写受保护路径：应被拒绝（error 非 None）
    print("  write /policies/x.md   :", b.write("/policies/x.md", "no").error)


# ---------------------------------------------------------------------------
# Part C：PolicyWrapper（包装任意后端，拦截 /policies/）
# 用 PolicyWrapper 包住一个 FilesystemBackend，只拦截 write/edit，其余透传。
# ---------------------------------------------------------------------------
def part_c_policy_wrapper():
    # 打印标题
    print()
    print("=" * 60)
    print("Part C: PolicyWrapper（包装任意后端，拦截 /policies/）")
    print("=" * 60)
    # 局部导入
    from pathlib import Path           # 拼接路径
    import shutil                      # 递归删除临时目录
    # 本地临时根目录
    root = Path(__file__).parent / ".wrap_root"
    # 清空并重建
    shutil.rmtree(root, ignore_errors=True)
    # 内层后端：本地磁盘后端
    inner = FilesystemBackend(root_dir=str(root), virtual_mode=True)
    # 用 PolicyWrapper 包装，禁止 /policies 前缀
    wrapped = PolicyWrapper(inner=inner, deny_prefixes=["/policies"])
    # 写普通路径：应成功
    print("  write /workspace/ok.md :", wrapped.write("/workspace/ok.md", "ok").error)
    # 写受保护路径：应被拒绝
    print("  write /policies/x.md   :", wrapped.write("/policies/x.md", "no").error)
    # 其余方法原样透传：验证 read 仍能正常工作
    print("  read  /workspace/ok.md :", preview(wrapped.read("/workspace/ok.md").file_data, 30))


# ---------------------------------------------------------------------------
# Part D：自定义 S3Backend（BackendProtocol 六方法，内存模拟）
# 先直接调用六方法做确定性验证，再把它交给 Deep Agent 端到端驱动。
# ---------------------------------------------------------------------------
def part_d_s3_backend():
    # 打印标题
    print()
    print("=" * 60)
    print("Part D: 自定义 S3Backend（BackendProtocol 六方法，内存模拟）")
    print("=" * 60)
    # 创建 S3 后端实例（内存 dict 模拟）
    s3 = S3Backend(bucket="demo", prefix="agent/")
    # write：写入两个文件
    print("  write /docs/a.md:", s3.write("/docs/a.md", "# A\n# TODO: review\nhello world").error)
    print("  write /docs/b.md:", s3.write("/docs/b.md", "# B\nnothing here").error)
    # ls：列出 /docs 下的条目
    print("  ls /docs       :", [e["path"] for e in s3.ls("/docs").entries])
    # glob：匹配所有 .md 文件
    print("  glob **/*.md   :", [m["path"] for m in s3.glob("**/*.md").matches])
    # grep：搜索 TODO
    print("  grep 'TODO'    :", s3.grep("TODO", glob="*.md").matches)
    # edit：精确替换
    e = s3.edit("/docs/a.md", "hello world", "hello s3")
    print(f"  edit a.md      : occurrences={e.occurrences}, error={e.error}")
    # read：读回验证
    print("  read a.md      :", preview(s3.read("/docs/a.md").file_data, 50))

    # 端到端：把自定义后端交给 Deep Agent，验证文件工具能被 Agent 正常驱动
    print("  --- 接入 Deep Agent（DeepSeek 驱动 read/grep）---")
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是对象存储助手，用文件工具查询 /docs 下的文件并汇报。",
        backend=s3,                         # 直接传自定义后端实例
    )
    # 让 Agent 用 grep 定位 TODO
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "用 grep 在 /docs 下搜索关键词 'TODO'，告诉我出现在哪个文件的第几行。"}]}
    )
    # 打印 Agent 回答
    print("  Agent 回答:", preview(r["messages"][-1].content, 160))


# ---------------------------------------------------------------------------
# result_report：从 invoke 结果中取最终回复的预览文本
# ---------------------------------------------------------------------------
def result_report(result) -> str:
    # 取最后一条消息的文本内容，做 400 字符预览
    return preview(result["messages"][-1].content, 400)


# 脚本入口：依次运行四个演示
if __name__ == "__main__":
    part_a_declarative_permission()  # 声明式权限
    part_b_guarded_backend()         # 继承式拦截
    part_c_policy_wrapper()          # 通用包装器
    part_d_s3_backend()              # 自定义 S3 后端
