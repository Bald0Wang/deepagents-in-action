# ============================================================================
# sandbox.py —— 沙箱层（对应 ch10，并整合 ch03/ch07 的只读与权限）
#
# 职责：
#   1. seed_sandbox()        —— 宿主平面：把知识库与技能包播种进沙箱（学习内容存储）
#   2. make_sandbox_backend() —— 构建带执行能力的沙箱 Backend（LocalShellBackend）
#   3. build_backend()        —— 组合后端：沙箱默认 + /memories/ 路由到 Store（ch08）
#   4. sandbox_permissions()  —— 只读规则：/knowledge/ 与 /skills/ 禁止写入（ch03/ch07）
#   5. dangerous_command()    —— HITL when 谓词：危险命令才中断审批（ch09）
#   6. collect_artifacts()    —— 宿主平面：取回 /out/ 产物并审查（ch10 两平面闭环）
#
# 边界说明（务必牢记，来自 ch10 的实测结论）：
#   - LocalShellBackend 的命令仍在本机执行，**不提供容器级隔离**；
#   - virtual_mode 只约束文件工具，不能限制 Shell 的绝对路径；
#   - 危险命令黑名单只是字符串匹配，不是真正的安全边界；
#   - 真正的隔离要靠远程容器 Provider（Daytona/Modal/E2B…）。
# 本模块的价值是把「沙箱作为 Backend 的接口、两平面、权限、审批、产物审查」
# 这五件事跑通，而不是声称本地进程等于沙箱。
# ============================================================================

"""沙箱层：学习内容存储 + 执行后端 + 只读权限 + 危险命令谓词 + 产物回收。"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from langchain.agents.middleware import ToolCallRequest

from deepagents.backends import (
    CompositeBackend,
    FilesystemBackend,
    LocalShellBackend,
    StateBackend,
    StoreBackend,
)
from deepagents.middleware import FilesystemPermission

from config import (
    DANGEROUS_COMMAND_PATTERNS,
    KNOWLEDGE_SRC,
    OUTPUT_PREFIX,
    OUT_DIR,
    READONLY_PREFIXES,
    SANDBOX_ROOT,
    SKILLS_SRC,
    WORKSPACE_PREFIX,
)


# ---------------------------------------------------------------------------
# 一、宿主平面：把「学习内容」播种进沙箱
# ---------------------------------------------------------------------------
def seed_sandbox(
    dest: Path | None = None,
    *,
    knowledge_src: Path | None = None,
    skills_src: Path | None = None,
    reset: bool = True,
) -> Path:
    """把知识库与技能包复制进沙箱根，并准备可写工作区。

    对应 ch10「宿主平面」：运行前由应用代码准备输入，模型不需要知道源文件在哪。
    对应 ch03：知识库与技能包是只读事实来源，工作区与产物区才可写。

    Args:
        dest: 沙箱根目录，默认 ``SANDBOX_ROOT``（capstone/.sandbox）。
        knowledge_src: 知识库源目录，默认 ``KNOWLEDGE_SRC``（capstone/knowledge）。
        skills_src: 技能包源目录，默认 ``SKILLS_SRC``（capstone/skills）。
        reset: True 时先清空目标目录（保证每次启动干净）。

    Returns:
        实际使用的沙箱根目录。
    """
    dest = Path(dest or SANDBOX_ROOT).resolve()
    knowledge_src = Path(knowledge_src or KNOWLEDGE_SRC)
    skills_src = Path(skills_src or SKILLS_SRC)

    # 清空重建：沙箱是「运行时工作区」，不承载持久状态（持久状态在 /memories/ → Store）
    if reset:
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    # ── 只读区：知识库 ──
    if knowledge_src.exists():
        shutil.copytree(knowledge_src, dest / "knowledge")
    else:
        (dest / "knowledge").mkdir(parents=True, exist_ok=True)

    # ── 只读区：技能包（含本作业新建的 knowledge-map）──
    if skills_src.exists():
        shutil.copytree(skills_src, dest / "skills")
    else:
        (dest / "skills").mkdir(parents=True, exist_ok=True)

    # ── 可写区：工作区与产物区 ──
    (dest / "workspace").mkdir(parents=True, exist_ok=True)
    (dest / "out").mkdir(parents=True, exist_ok=True)

    # ── 写入索引与说明（让 Agent 一进来就知道有什么、能写哪）──
    (dest / "knowledge" / "INDEX.md").write_text(_knowledge_index(), encoding="utf-8")
    (dest / "workspace" / "README.md").write_text(_workspace_readme(), encoding="utf-8")

    return dest


def _knowledge_index() -> str:
    """生成知识库索引：章节 → 文件路径（Agent 据此定位答疑依据）。"""
    from config import CHAPTERS

    lines = ["# 课程知识库索引", "", "| 章节 | 标题 | 文件 |", "|---|---|---|"]
    lines += [f"| {c.key} | {c.title} | `{c.knowledge}` |" for c in CHAPTERS]
    lines += [
        "",
        "## 使用说明",
        "- 每个文件包含该章的核心概念、关键代码事实、易错点与版本提示。",
        "- 本目录是**只读**事实来源；需要记录内容请写到 `/workspace/`。",
        "- 需要长期记住的用户偏好请写到 `/memories/`。",
    ]
    return "\n".join(lines) + "\n"


def _workspace_readme() -> str:
    """生成工作区说明：告诉 Agent 哪些路径可写、产物放哪。"""
    return (
        "# 沙箱工作区\n\n"
        "这是你的可写工作区（沙箱根下的 `workspace/`，虚拟路径 `/workspace/`）。\n\n"
        "| 路径 | 读写 | 用途 |\n"
        "|---|---|---|\n"
        "| `/knowledge/` | 只读 | 课程答疑知识库（事实来源） |\n"
        "| `/skills/` | 只读 | 技能包（含 knowledge-map 绘图技能） |\n"
        "| `/workspace/` | 可写 | 你的草稿、分析、临时文件 |\n"
        "| `/out/` | 可写 | 交付产物（会被宿主回收并审查） |\n"
        "| `/memories/` | 可写 | 长期记忆（跨会话持久，路由到 Store） |\n\n"
        "执行 Shell 时注意：`execute` 的 cwd 就是沙箱根，"
        "文件工具用虚拟路径（`/out/x.png`），Shell 用相对路径（`out/x.png`）。\n"
    )


# ---------------------------------------------------------------------------
# 二、沙箱 Backend：带执行能力的默认后端
# ---------------------------------------------------------------------------
def make_sandbox_backend(root: Path | str | None = None, **kwargs) -> LocalShellBackend:
    """构建沙箱执行后端（LocalShellBackend，实现 SandboxBackendProtocol）。

    对应 ch10：实现协议后模型才看得到 `execute` 工具。

    Args:
        root: 沙箱根目录，默认 ``SANDBOX_ROOT``。
        **kwargs: 透传额外参数（如 timeout、max_output_bytes）。

    Returns:
        配置好的 ``LocalShellBackend``。
    """
    root = Path(root or SANDBOX_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    # inherit_env=False：不把宿主环境变量（含 API Key）带进子进程。
    # 注意：这降低泄漏面，但不是隔离保证（见模块头部的边界说明）。
    return LocalShellBackend(
        root_dir=str(root),
        virtual_mode=True,
        inherit_env=False,
        timeout=int(os.environ.get("SANDBOX_TIMEOUT", "30")),
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(root)},
        **kwargs,
    )


def build_backend(
    *,
    root: Path | str | None = None,
    store=None,
    namespace=None,
    org_namespace=None,
    include_memory: bool = True,
) -> CompositeBackend:
    """组合后端：沙箱默认 + 只读区 + ``/memories/`` 与 ``/policies/`` 路由到 Store。

    对应 ch08 的 CompositeBackend 路径路由 + ch10 的执行能力：
    - 未匹配路径 → 沙箱（文件工具 + execute）
    - ``/knowledge/``、``/skills/`` → 只读 FilesystemBackend（无 execute）
    - ``/memories/`` → StoreBackend（用户级长期记忆，跨会话持久）
    - ``/policies/`` → StoreBackend（组织级只读政策，全用户共享）

    **为什么要给只读区单独路由？**
    deepagents 0.7.13 的 ``FilesystemMiddleware`` 不允许「执行型后端 + 非路由内权限」
    共存（见其 ``NotImplementedError``）。把只读区路由到**无 execute 能力**的
    ``FilesystemBackend``，既能用声明式 ``deny`` 权限保护它们，又保留默认后端的
    ``execute``——正好对应 ch03「按路径路由到不同后端」的设计。

    ``CompositeBackend.execute`` 会委托给 default，所以 execute 仍然可用。

    Args:
        root: 沙箱根目录。
        store: LangGraph Store 实例（``/memories/``、``/policies/`` 需要）。
        namespace: 用户级记忆的 namespace 工厂；None 时用 ``TaContext.user_id``。
        org_namespace: 组织级政策的 namespace 工厂；None 时用固定组织标识。
        include_memory: False 时只挂只读区路由（不挂 Store）。

    Returns:
        配置好的 ``CompositeBackend``。
    """
    root = Path(root or SANDBOX_ROOT)
    sandbox = make_sandbox_backend(root)
    routes: dict = {
        # 只读区：独立 FilesystemBackend（无 execute）→ 可安全叠加 deny 权限
        "/knowledge/": FilesystemBackend(root_dir=str(root / "knowledge"), virtual_mode=True),
        "/skills/": FilesystemBackend(root_dir=str(root / "skills"), virtual_mode=True),
    }
    if include_memory:
        if namespace is None:
            namespace = _default_memory_namespace
        if org_namespace is None:
            org_namespace = _default_org_namespace
        routes["/memories/"] = StoreBackend(namespace=namespace, store=store)
        routes["/policies/"] = StoreBackend(namespace=org_namespace, store=store)
    return CompositeBackend(default=sandbox, routes=routes)


def _default_memory_namespace(rt):
    """默认记忆命名空间：优先运行时身份，本地兜底 local-user。"""
    if getattr(rt, "server_info", None) and getattr(rt.server_info, "user", None):
        return (rt.server_info.user.identity,)
    return (getattr(rt.context, "user_id", "local-user"),)


def _default_org_namespace(rt):
    """默认组织命名空间：读取 ``TaContext.org_id``，本地兜底课程组织标识。"""
    return (getattr(rt.context, "org_id", "deepagents-course"),)


# ---------------------------------------------------------------------------
# 三、只读权限：知识库、技能包与组织政策禁止写入（ch03 声明式权限 + ch07 Skill 只读）
# ---------------------------------------------------------------------------
def sandbox_permissions() -> list[FilesystemPermission]:
    """返回沙箱的只读规则：``/knowledge/``、``/skills/``、``/policies/`` 禁止写入。

    对应 ch03 的 ``FilesystemPermission(operations=["write"], mode="deny")``：
    Agent 读得到课程内容与组织政策，但改不了（事实来源不可篡改）。
    """
    readonly = (*READONLY_PREFIXES, "/policies/")
    return [
        FilesystemPermission(operations=["write"], paths=[f"{prefix}**"], mode="deny")
        for prefix in readonly
    ]


# ---------------------------------------------------------------------------
# 四、危险命令谓词：只对真正危险的 execute 触发审批（ch09 when）
# ---------------------------------------------------------------------------
def dangerous_command(request: ToolCallRequest) -> bool:
    """HITL ``when`` 谓词：命令命中危险模式时返回 True（触发审批）。

    对应 ch09 的 ``when``：安全命令自动放行，危险命令才暂停，避免审批噪音。

    注意：这是**教学用的字符串匹配**，不是安全边界；绕过方式很多
    （变量拼接、脚本文件、编码等）。真正的隔离由容器 Provider 提供。
    """
    command = str(request.tool_call["args"].get("command", ""))
    lowered = command.lower()
    return any(pattern in lowered for pattern in DANGEROUS_COMMAND_PATTERNS)


def execute_interrupt_config() -> dict:
    """构造 ``execute`` 的 HITL 配置（配合 ``dangerous_command`` 使用）。"""
    return {
        "execute": {
            "allowed_decisions": ["approve", "reject"],
            "when": dangerous_command,
        }
    }


# ---------------------------------------------------------------------------
# 五、宿主平面：沙箱状态与产物回收
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Artifact:
    """一次产物回收的结果。"""

    path: str            # 沙箱内虚拟路径
    host_path: Path      # 落盘到宿主后的真实路径
    size: int            # 字节数
    content: bytes       # 原始字节（供审查）


def list_sandbox(root: Path | str | None = None, sub: str = "") -> list[str]:
    """列出沙箱内的文件（宿主平面视角，便于演示与测试）。"""
    base = Path(root or SANDBOX_ROOT)
    target = base / sub
    if not target.exists():
        return []
    return sorted(str(p.relative_to(base)) for p in target.rglob("*") if p.is_file())


def collect_artifacts(
    root: Path | str | None = None,
    *,
    out_dir: Path | str | None = None,
    remote_prefix: str = OUTPUT_PREFIX,
) -> list[Artifact]:
    """宿主平面回收 ``/out/`` 产物到宿主 ``out/`` 目录。

    对应 ch10「两个平面」：Agent 在沙箱内写产物，宿主在运行后取回。
    产物默认不可信，调用方应再做审查（见 ``review_artifact``）。

    Args:
        root: 沙箱根目录。
        out_dir: 宿主落盘目录，默认 ``OUT_DIR``。
        remote_prefix: 沙箱内产物前缀，默认 ``/out/``。

    Returns:
        回收到的产物列表（已复制到宿主）。
    """
    base = Path(root or SANDBOX_ROOT)
    src = base / remote_prefix.strip("/")
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[Artifact] = []
    if not src.exists():
        return artifacts
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        data = dest.read_bytes()
        artifacts.append(
            Artifact(
                path=f"{remote_prefix}{rel.as_posix()}",
                host_path=dest,
                size=len(data),
                content=data,
            )
        )
    return artifacts


# 产物审查：命中即视为不可信，需人工确认后再采用（ch10 安全闭环第三层）
UNTRUSTED_PATTERNS: tuple[str, ...] = (
    "ignore previous instructions",
    "disregard above",
    "rm -rf",
    "curl http",
    "wget http",
    "api_key",
    "sk-",
)


def review_artifact(content: bytes | str) -> tuple[bool, list[str]]:
    """审查产物是否命中已知危险模式。

    Returns:
        ``(is_clean, hits)``。``is_clean=True`` 只代表**未命中已知模式**，
        不代表产物已经安全（关键词过滤的固有限制，见 ch10）。
    """
    text = content.decode("utf-8", "ignore") if isinstance(content, bytes) else str(content)
    lowered = text.lower()
    hits = [p for p in UNTRUSTED_PATTERNS if p in lowered]
    return (not hits), hits


def sandbox_summary(root: Path | str | None = None) -> str:
    """打印沙箱目录结构摘要（宿主平面自检用）。"""
    base = Path(root or SANDBOX_ROOT)
    lines = [f"沙箱根: {base}"]
    for sub in ("knowledge", "skills", "workspace", "out"):
        files = list_sandbox(base, sub)
        lines.append(f"  /{sub}/: {len(files)} 个文件")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 六、确定性演示入口（无需模型：播种 → 执行 → 回收 → 审查）
# ---------------------------------------------------------------------------
def demo_offline() -> None:
    """离线演示沙箱闭环：播种 → 直接 execute → 写产物 → 回收 → 审查。"""
    import tempfile

    print("=" * 60)
    print("沙箱离线闭环：播种 → 执行 → 产物 → 回收 → 审查")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="capstone_sbx_") as tmp:
        root = Path(tmp) / "sandbox"
        # 1) 播种：知识库 + 技能包 + 可写区
        seed_sandbox(root)
        print(sandbox_summary(root))

        # 2) 直接执行（绕过模型，验证接口）
        backend = make_sandbox_backend(root)
        r = backend.execute("echo sandbox-ready && python3 -c 'print(6*7)'")
        print(f"  execute: exit={r.exit_code} output={r.output.strip()!r}")

        # 3) 越界写入被拦截（virtual_mode 路径沙箱）
        try:
            backend.write("../../escape.txt", "x")
            print("  越界写入: 未拦截（异常！）")
        except ValueError as exc:
            print(f"  越界写入: 拦截成功 ({exc})")

        # 4) Agent 平面写产物 → 宿主回收
        backend.write("/out/answer.txt", "sum=42\n")
        arts = collect_artifacts(root, out_dir=Path(tmp) / "host_out")
        for a in arts:
            clean, hits = review_artifact(a.content)
            print(f"  产物 {a.path} → {a.host_path.name} ({a.size}B) 审查: "
                  f"{'未命中已知模式' if clean else f'命中 {hits}'}")


if __name__ == "__main__":
    demo_offline()
