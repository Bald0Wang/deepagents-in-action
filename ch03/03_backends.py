# ============================================================================
# 03_backends.py —— ch03 段3：可插拔的存储后端（五种）
# 五个测试函数各自验证一种后端：
#   test_state_backend()       —— StateBackend（临时，同线程可见/换线程丢失）
#   test_filesystem_backend()  —— FilesystemBackend（本地磁盘 + 路径沙箱）
#   test_local_shell_backend() —— LocalShellBackend（文件工具 + execute）
#   test_store_backend()       —— StoreBackend（跨线程持久 + namespace 隔离）
#   test_composite_backend()   —— CompositeBackend（/memories/ -> Store，其余 -> State）
# ============================================================================

# 模块文档字符串：列出五种后端及其特性
"""ch03 段3：可插拔的存储后端（五种）—— 确定性验证 + Deep Agent 端到端。

覆盖课程五种后端：
  - StateBackend      : 临时存储（同线程内持久，换线程即丢）
  - FilesystemBackend : 本地磁盘 + virtual_mode 路径沙箱
  - LocalShellBackend : 文件工具 + execute（本地 Shell，无沙箱）
  - StoreBackend      : 跨线程持久化（namespace 按用户隔离）
  - CompositeBackend  : 混合路由（/memories/ -> Store，其余 -> State）
"""

# shutil：递归删除测试临时目录
import shutil
# Path：拼接本地目录路径
from pathlib import Path

# 从 common 导入公共工具
from common import make_model, preview

# create_deep_agent：创建 Agent 入口
from deepagents import create_deep_agent
# 一次性导入五种后端
from deepagents.backends import (
    CompositeBackend,     # 混合路由后端
    FilesystemBackend,    # 本地磁盘后端
    LocalShellBackend,    # 本地 Shell 后端（含 execute）
    StateBackend,         # 临时存储后端
    StoreBackend,         # 跨会话持久化后端
)
# MemorySaver：内存 checkpointer（多线程隔离/总结事件持久化需要）
from langgraph.checkpoint.memory import MemorySaver
# InMemoryStore：内存 store（StoreBackend 的持久化存储载体）
from langgraph.store.memory import InMemoryStore

# ROOT：FilesystemBackend / LocalShellBackend 使用的本地根目录
ROOT = Path(__file__).parent / ".backend_root"


# ---------------------------------------------------------------------------
# _files_of：从 invoke 结果里提取「路径 -> 文本内容」的简化字典
# （0.7.6 中 state.files 的值是 dict，含 content/encoding/modified_at）
# ---------------------------------------------------------------------------
def _files_of(result):
    out = {}                                    # 结果容器
    for path, meta in (result.get("files") or {}).items():  # 遍历 files
        # meta 是 dict 则取 content，否则直接当文本（向后兼容）
        out[path] = meta["content"] if isinstance(meta, dict) else meta
    return out                                  # 返回简化字典


# ---------------------------------------------------------------------------
# 1. StateBackend：临时存储（同线程可见、换线程丢失）
# ---------------------------------------------------------------------------
def test_state_backend():
    # 打印标题
    print("=" * 60)
    print("[StateBackend] 临时存储：同线程可见、换线程丢失")
    print("=" * 60)
    # 创建 Agent（默认 StateBackend），加 MemorySaver 支持多线程
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是文件助手，少说废话。",
        checkpointer=MemorySaver(),
    )
    # 线程 A 与线程 B 的配置（不同 thread_id = 不同对话线程）
    t1 = {"configurable": {"thread_id": "state-A"}}
    t2 = {"configurable": {"thread_id": "state-B"}}
    # 线程 A 写入文件
    r1 = agent.invoke(
        {"messages": [{"role": "user", "content": "write_file /workspace/x.md 内容为 '线程A独有'，完成后回我一句。"}]},
        config=t1,
    )
    # 同线程再次读取（StateBackend 同线程内持久，应该能读到）
    r1b = agent.invoke(
        {"messages": [{"role": "user", "content": "read_file /workspace/x.md，把内容原样告诉我。"}]}, config=t1
    )
    # 打印线程 A 写入的文件内容 + 再读到的内容
    print(f"  线程A 写入: {_files_of(r1).get('/workspace/x.md')}")
    print(f"  线程A 再读: {preview(r1b['messages'][-1].content, 60)}")
    # 换线程 B 读取（StateBackend 跨线程丢失，应该读不到）
    r2 = agent.invoke(
        {"messages": [{"role": "user", "content": "read_file /workspace/x.md，如果不存在就告诉我 '不存在'。"}]}, config=t2
    )
    # 打印线程 B 的读取结果（期望：不存在/为空）
    print(f"  线程B 读取: {preview(r2['messages'][-1].content, 60)}  （期望：不存在/为空）")


# ---------------------------------------------------------------------------
# 2. FilesystemBackend：本地磁盘 + virtual_mode 路径沙箱
# ---------------------------------------------------------------------------
def test_filesystem_backend():
    # 打印标题
    print()
    print("=" * 60)
    print("[FilesystemBackend] 本地磁盘 + virtual_mode 路径沙箱")
    print("=" * 60)
    # 清理并重建本地根目录（保证每次干净运行）
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    # 创建本地磁盘后端，开启 virtual_mode
    backend = FilesystemBackend(root_dir=str(ROOT), virtual_mode=True)

    # 写入文件（真实落盘到 ROOT/workspace/code.py）
    w = backend.write("/workspace/code.py", "print('hello from agent')\n")
    # 打印写入错误（None 表示成功）
    print(f"  write: error={w.error}")
    # 打印真实落盘情况 + 读回的内容预览
    print(f"  真实落盘: {(ROOT / 'workspace' / 'code.py').exists()}，内容={preview(backend.read('/workspace/code.py').file_data, 40)!r}")

    # 精确替换：把 "hello from agent" 改成 "hello from FilesystemBackend"
    e = backend.edit("/workspace/code.py", "hello from agent", "hello from FilesystemBackend")
    # 打印替换次数
    print(f"  edit: occurrences={e.occurrences}")
    # 打印磁盘内容已更新
    print(f"  磁盘已更新: {preview(backend.read('/workspace/code.py').file_data, 50)!r}")

    # 路径沙箱：".." 穿越会被拒绝
    try:
        backend.write("../../escape.txt", "x")              # 尝试越界
        print("  越界写入: 未拦截（异常！）")                  # 未抛异常说明沙箱失效
    except ValueError as exc:                                # 捕获 ValueError
        print(f"  越界写入: 拦截成功 ({exc})")                # 打印拦截成功

    # Deep Agent 端到端读写真实磁盘
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是本地编程助手，按要求操作磁盘文件并汇报。",
        backend=FilesystemBackend(root_dir=str(ROOT), virtual_mode=True),  # Agent 使用本地磁盘后端
    )
    # 让 Agent 读取刚才写入的真实文件
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "读取 /workspace/code.py 并告诉我它打印什么。"}]}
    )
    # 打印 Agent 的读取结果
    print(f"  Agent 读取真实文件: {preview(r['messages'][-1].content, 70)}")


# ---------------------------------------------------------------------------
# 3. LocalShellBackend：文件工具 + execute（本地 Shell，无沙箱）
# ---------------------------------------------------------------------------
def test_local_shell_backend():
    # 打印标题
    print()
    print("=" * 60)
    print("[LocalShellBackend] 文件工具 + execute（本地 Shell，无沙箱）")
    print("=" * 60)
    # 清理并重建本地根目录
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    # 创建本地 Shell 后端：继承 FilesystemBackend，额外提供 execute
    backend = LocalShellBackend(root_dir=str(ROOT), virtual_mode=True, inherit_env=False)

    # 直接执行 Shell 命令（echo + python3 求和）
    exec_resp = backend.execute("echo shell-ok && python3 -c 'print(1+2)'")
    # 打印退出码与输出（0 表示成功）
    print(f"  execute: exit_code={exec_resp.exit_code}, output={preview(exec_resp.output, 60)!r}")

    # Deep Agent 用 execute 工具跑命令（同时兼具文件工具）
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是本地助手，可以用 execute 运行命令，操作完汇报。",
        backend=LocalShellBackend(root_dir=str(ROOT), virtual_mode=True, inherit_env=False),
    )
    # 让 Agent 用 execute 跑一条命令
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "用 execute 运行命令 `echo langchain-ch03`，把输出告诉我。"}]}
    )
    # 打印 Agent 的执行结果
    print(f"  Agent 执行结果: {preview(r['messages'][-1].content, 70)}")


# ---------------------------------------------------------------------------
# 4. StoreBackend：跨线程持久化（namespace 按用户隔离）
# ---------------------------------------------------------------------------
def test_store_backend():
    # 打印标题
    print()
    print("=" * 60)
    print("[StoreBackend] 跨线程持久化（namespace 按用户隔离）")
    print("=" * 60)
    # InMemoryStore：开发用的内存 store（生产换 LangSmith 自动提供）
    store = InMemoryStore()
    # namespace：按用户身份隔离数据；本地 invoke 时 rt.server_info 为 None，兜底 local-user
    namespace = lambda rt: (rt.server_info.user.identity,) if getattr(rt, "server_info", None) else ("local-user",)

    # 创建 Agent，backend 用 StoreBackend，store 用 InMemoryStore
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是记忆助手，少说废话。",
        backend=StoreBackend(namespace=namespace),
        store=store,
        checkpointer=MemorySaver(),
    )
    # 线程 A / B 配置
    t1 = {"configurable": {"thread_id": "store-A"}}
    t2 = {"configurable": {"thread_id": "store-B"}}
    # 线程 A 写入 /memories/pref.txt
    agent.invoke(
        {"messages": [{"role": "user", "content": "write_file /memories/pref.txt 内容为 '用户偏好：简洁中文回答'，完成后回我一句。"}]},
        config=t1,
    )
    # 换一个全新线程 B，StoreBackend 仍能读到（跨线程持久化）
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "read_file /memories/pref.txt，把内容原样告诉我；若不存在就说 '不存在'。"}]},
        config=t2,
    )
    # 打印跨线程读取结果
    print(f"  跨线程读取: {preview(r['messages'][-1].content, 80)}")

    # 不同用户（不同 namespace）隔离：另建一个 Agent，namespace 换成 other-user
    agent_b = create_deep_agent(
        model=make_model(),
        system_prompt="你是记忆助手，少说废话。",
        backend=StoreBackend(namespace=lambda rt: ("other-user",)),  # 固定其它用户
        store=store,                                                 # 同一个 store
        checkpointer=MemorySaver(),
    )
    # 另一用户读取同一路径，应读不到（被 namespace 隔离）
    rb = agent_b.invoke(
        {"messages": [{"role": "user", "content": "read_file /memories/pref.txt，若不存在就说 '不存在'。"}]},
        config={"configurable": {"thread_id": "store-C"}},
    )
    # 打印另一用户的读取结果（期望：不存在）
    print(f"  另一用户读取: {preview(rb['messages'][-1].content, 80)}  （期望：不存在，被 namespace 隔离）")


# ---------------------------------------------------------------------------
# 5. CompositeBackend：混合路由（/memories/ -> Store，其余 -> State）
# ---------------------------------------------------------------------------
def test_composite_backend():
    # 打印标题
    print()
    print("=" * 60)
    print("[CompositeBackend] 混合路由：/memories/ -> Store，其余 -> State")
    print("=" * 60)
    # 内存 store + namespace 兜底
    store = InMemoryStore()
    namespace = lambda rt: (rt.server_info.user.identity,) if getattr(rt, "server_info", None) else ("local-user",)
    # 组合后端：默认 StateBackend，/memories/ 前缀路由到 StoreBackend
    backend = CompositeBackend(
        default=StateBackend(),
        routes={"/memories/": StoreBackend(namespace=namespace)},
    )
    # 创建 Agent，使用组合后端
    agent = create_deep_agent(
        model=make_model(),
        system_prompt="你是助手，少说废话。",
        backend=backend,
        store=store,
        checkpointer=MemorySaver(),
    )
    # 固定线程
    thread = {"configurable": {"thread_id": "composite-1"}}
    # 让 Agent 分别写入普通路径与 /memories/ 路径，并做 ls 与说明
    r = agent.invoke(
        {"messages": [{"role": "user", "content": (
            "依次完成：1) write_file /workspace/draft.md 内容 '临时草稿'；"
            "2) write_file /memories/keep.txt 内容 '要长期记住的内容'；"
            "3) ls / 列出顶层；4) 告诉我两个文件分别去了哪种存储（临时/持久）。"
        )}]},
        config=thread,
    )
    # 验证普通路径进了 state.files，而 /memories/ 路径进了 store（不在 state.files）
    for path in ("/workspace/draft.md", "/memories/keep.txt"):
        print(f"  state.files 含 {path}: {path in (r.get('files') or {})}")
    # 打印 Agent 的汇报
    print(f"  Agent 汇报: {preview(r['messages'][-1].content, 140)}")


# 脚本入口：依次运行五个后端测试
if __name__ == "__main__":
    test_state_backend()       # StateBackend
    test_filesystem_backend()  # FilesystemBackend
    test_local_shell_backend() # LocalShellBackend
    test_store_backend()       # StoreBackend
    test_composite_backend()   # CompositeBackend
