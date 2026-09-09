# ============================================================================
# config.py —— 综合大作业公共配置
#
# 职责：集中定义目录、章节元数据、运行时上下文（TaContext）、沙箱策略常量。
# 设计对应关系（章节 → 本文件职责）：
#   ch02  模型与工具三要素      → common.py 的 make_model
#   ch03  虚拟文件系统与后端    → 本文件的 KNOWLEDGE/SKILLS/SANDBOX 目录 + sandbox.py
#   ch04  任务规划              → service.py 注入 TodoListMiddleware
#   ch05  子 Agent 与路由       → subagents.py 每章一个子 Agent
#   ch06  异步子 Agent          → README 说明（需 langgraph dev，不本地跑）
#   ch07  Skills                → skills/knowledge-map/ + sandbox.py 播种
#   ch08  长期记忆              → memory.py 的 /memories/ 路由 + TaContext
#   ch09  HITL                  → hitl.py 的澄清工具 + 审批配置
#   ch10  沙箱                  → sandbox.py 的 LocalShellBackend + 执行策略
# ============================================================================

"""综合大作业公共配置：目录、章节元数据、运行时上下文与沙箱策略。"""

from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# 一、目录布局
# ---------------------------------------------------------------------------
# ROOT：capstone 项目根目录（本文件所在目录）
ROOT = Path(__file__).resolve().parent

# KNOWLEDGE_SRC：学习内容「源」——版本控制里的章节答疑资料（宿主平面只读源）
KNOWLEDGE_SRC = ROOT / "knowledge"

# SKILLS_SRC：Skill 源——包含本作业新建的 knowledge-map 技能
SKILLS_SRC = ROOT / "skills"

# SANDBOX_ROOT：运行时沙箱根目录（每次启动由 sandbox.py 从上面两个源播种）
# 对应 ch10：沙箱是 Agent 的工作区，宿主平面负责准备输入与收取产物。
SANDBOX_ROOT = ROOT / ".sandbox"

# OUT_DIR：宿主平面产物目录（渲染出的 PNG、导出的 Markdown 等）
OUT_DIR = ROOT / "out"


# ---------------------------------------------------------------------------
# 二、章节元数据（子 Agent 路由与知识检索的唯一事实来源）
# ---------------------------------------------------------------------------
# 每章：编号、标题、一句话摘要、知识文件路径（沙箱内虚拟路径）、源文件名。
# subagents.py 用 description 做路由；knowledge 文件是子 Agent 的答疑依据。
@dataclass(frozen=True)
class Chapter:
    """一个课程章节的元数据。"""

    key: str          # 章节标识，如 "ch03"
    title: str        # 章节标题
    summary: str      # 一句话能力摘要（用于子 Agent description 的路由锚点）
    knowledge: str    # 沙箱内知识文件虚拟路径，如 "/knowledge/ch03.md"
    sources: tuple[str, ...]   # 对应章节目录里的源码文件名（答疑时引用）


CHAPTERS: tuple[Chapter, ...] = (
    Chapter(
        key="ch02",
        title="快速上手：第一个 Deep Agent",
        summary="create_deep_agent 三件套、自定义工具三要素、Tavily/DDG 搜索工具、DeepSeek 兼容接口接入",
        knowledge="/knowledge/ch02.md",
        sources=("01_hello_weather.py", "02_calculator.py", "03_research_assistant.py", "03b_research_assistant_ddg.py"),
    ),
    Chapter(
        key="ch03",
        title="虚拟文件系统与可插拔后端",
        summary="七种内置文件工具、五种存储后端、上下文自动管理、权限声明与自定义后端协议",
        knowledge="/knowledge/ch03.md",
        sources=("01_builtin_file_tools.py", "02_context_auto_management.py", "03_backends.py", "04_permissions_and_custom_backend.py", "custom_backends.py"),
    ),
    Chapter(
        key="ch04",
        title="任务规划与分解",
        summary="write_todos 任务清单、TodoListMiddleware 显式注入、中间件 Hook、规划与总结协同",
        knowledge="/knowledge/ch04.md",
        sources=("01_write_todos_basics.py", "02_langchain_middleware.py", "03_todo_summarization_synergy.py", "04_research_task.py"),
    ),
    Chapter(
        key="ch05",
        title="子 Agent 与上下文隔离",
        summary="task 委派、Context Quarantine、字典/CompiledSubAgent、tools 继承语义、description 路由、结构化输出",
        knowledge="/knowledge/ch05.md",
        sources=("01_context_quarantine.py", "02_dict_subagents.py", "03_multi_collab.py", "04_compiled_structured.py"),
    ),
    Chapter(
        key="ch06",
        title="异步子 Agent",
        summary="AsyncSubAgent、start/check/update/list_async_task、同步阻塞 vs 异步并行、ASGI 与 HTTP 混合拓扑",
        knowledge="/knowledge/ch06.md",
        sources=("graphs/async_supervisor.py", "graphs/sync_supervisor.py", "graphs/hybrid_supervisor.py", "run_demo.py"),
    ),
    Chapter(
        key="ch07",
        title="Skills 可复用能力包",
        summary="SKILL.md 规范、三级渐进式加载、description 质量与误触发、三种后端注入、last-wins、子 Agent 继承、deny/interrupt 权限",
        knowledge="/knowledge/ch07.md",
        sources=("01_progressive_disclosure.py", "02_backends_and_priority.py", "03_subagent_inheritance.py", "04_permissions.py"),
    ),
    Chapter(
        key="ch08",
        title="长期记忆",
        summary="短期 Checkpointer vs 长期 Store、CompositeBackend 路由、用户级/Agent 级/组织级作用域、memory 参数自动注入、自我改进",
        knowledge="/knowledge/ch08.md",
        sources=("01_two_memories.py", "02_memory_scopes.py", "03_memory_scenarios.py", "04_advanced_memory.py"),
    ),
    Chapter(
        key="ch09",
        title="Human-in-the-Loop",
        summary="interrupt_on 四种决策、when 谓词、批量中断、子 Agent 独立审批、低层 interrupt() 与重放机制",
        knowledge="/knowledge/ch09.md",
        sources=("01_four_decisions.py", "02_when_and_batch.py", "03_subagent_and_permissions.py", "04_low_level_interrupt.py"),
    ),
    Chapter(
        key="ch10",
        title="沙箱执行",
        summary="SandboxBackendProtocol 与 execute 可见性、四原语自定义沙箱、宿主/Agent 两平面、大输出落盘、凭证隔离与产物审查",
        knowledge="/knowledge/ch10.md",
        sources=("01_sandbox_nature.py", "02_two_planes.py", "03_security_closure.py", "04_local_lifecycle.py", "restricted_sandbox.py"),
    ),
)

# 便于按 key 快速查找章节
CHAPTER_BY_KEY: dict[str, Chapter] = {c.key: c for c in CHAPTERS}


# ---------------------------------------------------------------------------
# 三、运行时上下文（对应 ch08 的 context_schema + namespace 三件套）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TaContext:
    """一次客服会话的运行时身份。

    对应 ch08：namespace 工厂从 rt.context 读取 user_id/org_id，
    实现「用户级记忆隔离」与「组织级知识只读」。
    """

    user_id: str = "local-user"      # 用户身份：决定 /memories/ 的 namespace
    org_id: str = "deepagents-course"  # 组织身份：决定组织级知识共享
    chapter_hint: str | None = None  # 可选的章节提示，帮助路由（None 表示不指定）


# ---------------------------------------------------------------------------
# 四、沙箱策略常量（对应 ch09 的 when 谓词 + ch10 的安全闭环）
# ---------------------------------------------------------------------------
# 危险命令模式：命中即触发人工审批（不是直接拒绝——由人决定）。
# 注意：这是教学用的字符串匹配，不是真正的安全边界（见 ch10 的边界说明）。
DANGEROUS_COMMAND_PATTERNS: tuple[str, ...] = (
    "rm ", "rm -", "sudo", "curl ", "wget ", "nc ", "ssh ",
    "chmod ", "chown ", "dd if=", "> /etc", "mkfs", "shutdown", "reboot",
)

# 沙箱只读区：学习内容与技能包是「事实来源」，Agent 只能读、不能改。
# 对应 ch03 的 FilesystemPermission(mode="deny") 与 ch07 的 Skill 只读。
READONLY_PREFIXES: tuple[str, ...] = ("/knowledge/", "/skills/")

# 沙箱可写区：Agent 的工作区、产物区（对应 ch10 的两平面产物落盘）
WORKSPACE_PREFIX = "/workspace/"
OUTPUT_PREFIX = "/out/"
