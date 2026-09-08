# ============================================================================
# 04_local_lifecycle.py —— ch10 实验四：本地执行、传输与生命周期体验
#
# 补齐课程 §1（execute 返回值）、§6（文件两个平面）、§7（作用域与清理）
# 三块在远程 Provider 之外、也能本地亲手验证的内容。
#
# 运行：uv run 04_local_lifecycle.py
# 特点：无需模型、API Key、容器或远程账号——只用标准库 + 现有 Backend。
#
# 定位说明：
#   - 每段用 TemporaryDirectory 持有工作区，成功或异常退出都会清理自己的临时文件；
#   - 这里隔离的是【演示数据的存放位置】，不提供操作系统级进程/网络隔离
#     （真正的进程/网络隔离要靠 Daytona/Modal 等远程容器，见 01 脚本）。
# ============================================================================

import shlex          # 安全引用：把路径/源码包成 Shell 能正确解析的单个参数
import sys            # 取当前解释器绝对路径（避免依赖 PATH 里的 python 是谁）
import tempfile       # 临时目录上下文管理器：退出即递归清理
from pathlib import Path

from deepagents.backends import FilesystemBackend, LocalShellBackend


def local_shell(root: Path) -> LocalShellBackend:
    """统一构造最小环境的 Shell 后端。

    - root_dir：命令的 cwd 与文件工具的沙箱根（虚拟路径 / ↔ 该目录）
    - virtual_mode=True：文件工具做路径沙箱（拒绝 .. 穿越）
    - inherit_env=False：不继承宿主环境变量，只保留最小 PATH/HOME
      （顺带避免把宿主的 API Key 之类变量带进子进程）
    """
    return LocalShellBackend(root_dir=str(root), virtual_mode=True, inherit_env=False)


def part_a_execution_results():
    """课程 §1：execute() 的返回值不是只有输出文本，必须同时看 exit_code 与 truncated。"""
    print("\nPart A: 成功 / 失败 / 超时的结构化结果")
    # with TemporaryDirectory：本段所有命令与文件都落在临时目录，退出自动删除
    with tempfile.TemporaryDirectory(prefix="ch10_exec_") as directory:
        backend = local_shell(Path(directory))

        # 用当前解释器的绝对路径 + shlex.quote 保护路径和源码字符串：
        # 路径可能含空格、源码含引号，不 quote 会被 Shell 拆成多个参数而失败。
        # 前缀 "exec " 用 exec 替换掉 Shell 进程本身，让超时杀死的就是这个 Python
        # 进程，而不是留下一个孤儿 Shell（避免超时后仍有子进程在跑）。
        python = "exec " + shlex.quote(sys.executable)

        # 场景1 成功：正常打印并退出码 0
        success = backend.execute(python + " -c " + shlex.quote("print('ready')"))

        # 场景2 失败：写 stderr 并以退出码 7 结束
        # 注意：非零退出码是【返回结果】，不是 Python 异常——调用方要自己看 exit_code
        failure = backend.execute(python + " -c " + shlex.quote(
            "import sys; print('bad input', file=sys.stderr); sys.exit(7)"
        ))

        # 场景3 超时：睡 3 秒但只给 1 秒超时 → 退出码 124（约定的超时码）
        timeout = backend.execute(python + " -c " + shlex.quote(
            "import time; time.sleep(3)"
        ), timeout=1)

        # 断言三态：成功/失败/超时分别对应 0 / 7 / 124，且 stderr 被合并进 output
        assert success.exit_code == 0 and "ready" in success.output
        assert failure.exit_code == 7 and "bad input" in failure.output
        assert timeout.exit_code == 124

        for label, result in [("成功", success), ("失败", failure), ("超时", timeout)]:
            print(f"  {label}: exit={result.exit_code}, truncated={result.truncated}, "
                  f"output={result.output.strip()!r}")

        print("  应用：CI 看退出码判成败；耗时命令设置超时；不要只看是否打印了文字。")


def part_b_partial_download():
    """课程 §6：同一批下载里一个文件缺失，不应丢弃其他成功的产物（逐项处理）。"""
    print("\nPart B: 批量下载，逐项处理成功与失败")
    with tempfile.TemporaryDirectory(prefix="ch10_transfer_") as directory:
        backend = local_shell(Path(directory))

        # 宿主平面写入：upload_files 接收 (虚拟路径, bytes) 列表
        # 这是"运行前播种输入"的宿主侧 API，与 Agent 的 write_file 是两条通道
        payload = "统计结果：150\n".encode("utf-8")
        uploads = backend.upload_files([("/out/result.txt", payload)])
        assert uploads[0].error is None, uploads[0].error

        # 宿主平面读取：故意混入一个不存在的文件，验证批量语义
        results = backend.download_files(["/out/result.txt", "/out/missing.txt"])

        for result in results:
            # 关键判据是 content is not None，而不是 if result.content：
            # b""（合法空文件）为假值，用真值判断会把空文件误判为失败。
            if result.content is not None:
                print(f"  成功 {result.path}: {result.content.decode('utf-8').strip()}")
            else:
                print(f"  失败 {result.path}: {result.error}")

        # 成功项内容与上传一致；失败项 content 为 None 且带 error 说明
        assert results[0].content == payload
        assert results[1].content is None and results[1].error
        print("  应用：报告成功、附件失败时分别反馈，避免对 None 调用 decode()。")


def part_c_scope_and_cleanup():
    """课程 §7：作用域由应用维护标识→工作区映射；thread_id 本身不会自动隔离磁盘。"""
    print("\nPart C: 按线程隔离 / 按助手复用 / 异常清理")
    with tempfile.TemporaryDirectory(prefix="ch10_scopes_") as directory:
        root = Path(directory)

        # ── Thread-scoped（按对话隔离）──
        # 用两个子目录模拟应用自己维护的 thread_id -> 工作区映射：
        # 沙箱/工作区不会因为换了 thread_id 自动隔离，是【应用把标识映射到不同目录】。
        thread_a = FilesystemBackend(root_dir=str(root / "thread-a"), virtual_mode=True)
        thread_b = FilesystemBackend(root_dir=str(root / "thread-b"), virtual_mode=True)
        assert thread_a.write("/note.txt", "A 的任务记录").error is None

        # 重建一个指向同一目录的 Backend = 同一线程的下一轮复用：
        # Backend 是"访问句柄"，重建它不会删磁盘文件，指向同目录即复用同一份数据。
        resumed_a = FilesystemBackend(root_dir=str(root / "thread-a"), virtual_mode=True)
        assert resumed_a.read("/note.txt").error is None
        # 另一个线程指向另一目录 → 读不到（隔离来自目录不同，而非框架强制）
        assert thread_b.read("/note.txt").error is not None
        print("  同线程复用目录：能读回；另一线程使用另一目录：读不到。")

        # ── Assistant-scoped（跨对话复用）──
        # 两个"会话"显式共用同一 assistant 目录：缓存/依赖/仓库得以跨对话保留。
        # 代价是也会残留上次任务的数据——不是多用户隔离方案，需要 TTL/快照/清理策略。
        session_1 = FilesystemBackend(root_dir=str(root / "assistant"), virtual_mode=True)
        session_2 = FilesystemBackend(root_dir=str(root / "assistant"), virtual_mode=True)
        assert session_1.write("/cache.txt", "依赖缓存标记").error is None
        assert session_2.read("/cache.txt").error is None
        print("  跨线程共用目录：新对话仍能读到缓存标记（模拟文件，不实际安装依赖）。")

        # ── 异常清理 ──
        # 模拟任务中途失败：即使抛异常，with 的上下文管理器仍会回收该任务目录。
        # 边界：这只清理文件；不会回收脱离当前进程的后台服务，也不是 TTL 实现
        # （真实 Provider 的自动回收靠 idle_ttl_seconds 等机制）。
        try:
            with tempfile.TemporaryDirectory(dir=root, prefix="failed_job_") as job:
                failed_root = Path(job)
                (failed_root / "partial.txt").write_text("未完成", encoding="utf-8")
                raise RuntimeError("模拟计算失败")
        except RuntimeError as exc:
            print(f"  捕获任务异常: {exc}")
        assert not failed_root.exists()
        print("  异常任务目录已清理: True")

    # 外层 TemporaryDirectory 退出：所有演示工作区一并消失
    assert not root.exists()
    print("  所有演示工作区已清理: True")


if __name__ == "__main__":
    part_a_execution_results()
    part_b_partial_download()
    part_c_scope_and_cleanup()
