# ============================================================================
# 02_backends_and_priority.py —— ch07 段2：三种存储后端 + 多源 last-wins
#
#   Part A: FilesystemBackend —— 本地磁盘直读（本地开发/CLI 场景）
#   Part B: StateBackend —— 无磁盘环境，Skill 内容经 invoke 的 files 参数注入
#   Part C: StoreBackend —— store.put 写一次，跨线程共享
#   Part D: 多源优先级 —— 同名 Skill 后面的覆盖前面的（last wins）
# ============================================================================

from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from common import make_model, preview

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend, StateBackend, StoreBackend
from deepagents.backends.utils import create_file_data

ROOT = Path(__file__).parent.resolve()
SKILL_MD = Path("skills/team-report/SKILL.md").read_text()


def call_seq(r):
    return [(tc["name"], str(tc["args"].get("file_path", "")))
            for m in r["messages"] for tc in (getattr(m, "tool_calls", None) or [])]


def part_a_filesystem():
    print("=" * 60)
    print("Part A: FilesystemBackend（本地磁盘直读）")
    print("=" * 60)
    agent = create_deep_agent(
        model=make_model(),
        backend=FilesystemBackend(root_dir=str(ROOT), virtual_mode=True),
        skills=["/skills/"],
    )
    r = agent.invoke({"messages": [{"role": "user", "content": (
        "帮我生成周报：本周完成环境搭建，下周计划写测试，风险是无。"
    )}]})
    seq = call_seq(r)
    print(f"  激活: {[p for _, p in seq if p.endswith('SKILL.md')]}")
    print(f"  回复含固定小节: {all(s in r['messages'][-1].content for s in ['本周完成', '下周计划', '风险与阻塞'])}")


def part_b_state():
    print()
    print("=" * 60)
    print("Part B: StateBackend（files 参数动态注入）")
    print("=" * 60)
    # create_file_data：StateBackend 注入必须用这个格式，直接传 str 会报错
    skills_files = {"/skills/team-report/SKILL.md": create_file_data(SKILL_MD)}
    agent = create_deep_agent(
        model=make_model(),
        backend=StateBackend(),
        skills=["/skills/"],
        checkpointer=MemorySaver(),
    )
    r = agent.invoke(
        {"messages": [{"role": "user", "content": "帮我生成周报：本周上线支付模块，下周计划压测，风险是第三方接口不稳定。"}],
         "files": skills_files},                       # 每次调用都要传入
        config={"configurable": {"thread_id": "state-skills"}},
    )
    seq = call_seq(r)
    print(f"  激活: {[p for _, p in seq if p.endswith('SKILL.md')]}")
    print(f"  回复预览: {preview(r['messages'][-1].content, 100)}")


def part_c_store():
    print()
    print("=" * 60)
    print("Part C: StoreBackend（写入一次，跨线程共享）")
    print("=" * 60)
    store = InMemoryStore()
    # 文件通过 store.put 写入（不是 invoke 时传入）
    store.put(
        namespace=("filesystem",),
        key="/skills/team-report/SKILL.md",
        value=create_file_data(SKILL_MD),
    )
    agent = create_deep_agent(
        model=make_model(),
        backend=StoreBackend(namespace=lambda _rt: ("filesystem",)),
        store=store,
        skills=["/skills/"],
        checkpointer=MemorySaver(),
    )
    # 两个不同 thread 都能用到同一个 Skill（跨线程共享）
    for tid, done in [("thread-A", "本周完成订单重构"), ("thread-B", "本周完成灰度发布")]:
        r = agent.invoke(
            {"messages": [{"role": "user", "content": f"帮我生成周报：{done}，下周计划待定，风险无。"}]},
            config={"configurable": {"thread_id": tid}},
        )
        seq = call_seq(r)
        print(f"  {tid}: 激活 {[p for _, p in seq if p.endswith('SKILL.md')]}")


def part_d_last_wins():
    print()
    print("=" * 60)
    print("Part D: 多源同名 —— last wins（后声明的覆盖先声明的）")
    print("=" * 60)
    agent = create_deep_agent(
        model=make_model(),
        backend=FilesystemBackend(root_dir=str(ROOT), virtual_mode=True),
        skills=[
            "/skills_shared/",     # 共享版：结论含 SHARED-VERSION 标记
            "/skills_project/",    # 项目版：结论含 PROJECT-VERSION 标记（排在后面 → 生效）
        ],
    )
    r = agent.invoke({"messages": [{"role": "user", "content": (
        "请审查这段代码：```python\ndef f(xs):\n    s = ''\n    for x in xs:\n        s = s + str(x)\n    return s\n```"
    )}]})
    seq = call_seq(r)
    picked = [p for _, p in seq if p.endswith("SKILL.md")]
    reply = r["messages"][-1].content
    print(f"  实际加载的 Skill: {picked}")
    print(f"  结论标记: {'PROJECT-VERSION（项目版生效）' if 'PROJECT-VERSION' in reply else 'SHARED-VERSION（共享版生效）'}")


if __name__ == "__main__":
    part_a_filesystem()
    part_b_state()
    part_c_store()
    part_d_last_wins()
