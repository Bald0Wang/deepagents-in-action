# ============================================================================
# 06_concurrency_and_isolation.py —— ch08 高级用法补全（二）
#
#   Part A: 并发写入冲突 —— 同一文件 last-write-wins（后写覆盖先写）
#           + 两种缓解：按主题拆文件 / 追加式唯一命名日志（都不丢数据）
#   Part B: 多 Agent 部署隔离 —— namespace 用 (assistant_id, user_id) 二元组，
#           同一用户在不同 Agent 间记忆互不干扰
#   Part C: Store 升级路径 —— InMemoryStore → PostgresStore（代码就绪，
#           未配置 DATABASE_URL 时演示跳过逻辑）
# ============================================================================

import os

from langgraph.store.memory import InMemoryStore

from common import preview

from deepagents.backends import StoreBackend
from deepagents.backends.utils import create_file_data


def part_a_write_conflicts():
    print("=" * 60)
    print("Part A: 并发写入 —— last-write-wins 与两种缓解")
    print("=" * 60)

    def store_backend(store):
        return StoreBackend(namespace=lambda _rt: ("u1",), store=store)

    # ── 冲突现场：两个"线程"先后写同一个 preferences.md ──
    store = InMemoryStore()
    b = store_backend(store)
    b.write("/preferences.md", "# 偏好\n- 线程1写入：注释用中文")        # 线程1
    b.write("/preferences.md", "# 偏好\n- 线程2写入：主题色用暗色")        # 线程2（后写）
    final = b.read("/preferences.md").file_data["content"]
    print(f"  [冲突] 同文件后写覆盖先写: {'线程2' in final and '线程1' not in final}")
    print(f"         最终内容: {preview(final, 50)!r}（线程1 的偏好丢了）")

    # ── 缓解1：按主题拆文件（两个 key 并存）──
    store2 = InMemoryStore()
    b2 = store_backend(store2)
    b2.write("/coding_style.md", "- 注释用中文")
    b2.write("/theme.md", "- 主题色用暗色")
    keys = sorted(i.key for i in store2.search(("u1",)))
    print(f"  [缓解1 按主题拆分] 两个主题文件并存: {keys}（零丢失）")

    # ── 缓解2：追加式唯一命名日志（课程推荐：events/<thread>.md）──
    store3 = InMemoryStore()
    b3 = store_backend(store3)
    b3.write("/events/2026-09-03-t001.md", "- 学到：注释用中文")
    b3.write("/events/2026-09-03-t002.md", "- 学到：主题色用暗色")
    events = sorted(i.key for i in store3.search(("u1",)))
    print(f"  [缓解2 追加式日志] 每线程一个文件: {events}（零丢失，后台再合并）")


def part_b_multi_agent_isolation():
    print()
    print("=" * 60)
    print("Part B: 多 Agent 部署隔离（namespace = (assistant_id, user_id)）")
    print("=" * 60)
    store = InMemoryStore()

    # 图内（create_deep_agent 运行时）推荐写法：
    #   lambda rt: (rt.server_info.assistant_id, getattr(rt.context, "user_id", "local-user"))
    # 本脚本在图外直接调用 backend，Runtime 不可用，用常量元组等价演示隔离语义
    def agent_ns(aid, uid="user-42"):
        return lambda _rt: (aid, uid)

    # 同一个用户 user-42 同时使用两个不同的 Agent（assistant-a / assistant-b）
    backend_a = StoreBackend(namespace=agent_ns("assistant-a"), store=store)
    backend_b = StoreBackend(namespace=agent_ns("assistant-b"), store=store)

    backend_a.write("/AGENTS.md", "Agent A 的知识：专精 LangGraph")
    backend_b.write("/AGENTS.md", "Agent B 的知识：专精 数据分析")

    content_a = backend_a.read("/AGENTS.md").file_data["content"]
    content_b = backend_b.read("/AGENTS.md").file_data["content"]
    print(f"  assistant-a 读到: {content_a!r}")
    print(f"  assistant-b 读到: {content_b!r}")
    print(f"  互不干扰: {'LangGraph' in content_a and '数据分析' in content_b and content_a != content_b}")
    namespaces = sorted({i.namespace for i in store.search(())} | set())
    all_ns = set()
    for probe in ("assistant-a", "assistant-b"):
        all_ns |= {i.namespace for i in store.search((probe,))}
    print(f"  store 中的 namespace: {sorted(all_ns)}（按 agent 分仓）")


def part_c_store_upgrade_path():
    print()
    print("=" * 60)
    print("Part C: Store 升级路径（InMemory → Postgres）")
    print("=" * 60)
    print("  开发阶段: InMemoryStore()（本章全部实验在用，重启丢失）")
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("  生产阶段: 未检测到 DATABASE_URL，PostgresStore 演示跳过。生产代码如下：")
        print("""
            from langgraph.store.postgres import PostgresStore

            with PostgresStore.from_conn_string(os.environ["DATABASE_URL"]) as store:
                store.setup()                     # 首次建表
                agent = create_deep_agent(
                    model=model,
                    memory=["/memories/AGENTS.md"],
                    store=store,                  # 其余配置与 InMemory 完全一致
                    backend=CompositeBackend(
                        default=StateBackend(),
                        routes={"/memories/": StoreBackend(namespace=assistant_namespace)},
                    ),
                )
            # LangSmith 部署：省略 store 参数，平台自动提供
        """)
        return
    # 配置了数据库则真连（保真演示升级路径）
    from langgraph.store.postgres import PostgresStore
    with PostgresStore.from_conn_string(db_url) as store:
        store.setup()
        store.put(("upgrade-demo",), "/AGENTS.md", create_file_data("来自 PostgresStore 的记忆"))
        item = next(iter(store.search(("upgrade-demo",))))
        print(f"  ✅ PostgresStore 写入并读回: {item.value['content']!r}")


if __name__ == "__main__":
    part_a_write_conflicts()
    part_b_multi_agent_isolation()
    part_c_store_upgrade_path()
