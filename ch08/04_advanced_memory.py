# ============================================================================
# 04_advanced_memory.py —— ch08 段4：高级用法（本地可完整验证的部分）
#
#   Part A: 外部预填 —— 应用代码 store.put + create_file_data 预填
#           Agent 级记忆（AGENTS.md）和 Skill，Agent 启动即用
#   Part B: 组织级只读 —— /policies/ 路由 org namespace + deny 写权限
#           Agent 读得到、写不进（应用代码写入的合规策略）
#   Part C: 存储格式 —— 打印 store 条目验证 v2 格式
#           （content 完整字符串 + encoding + created_at/modified_at）
#
# 说明：情景记忆（搜索过去对话）、后台整合（Cron + 整合 Agent）需要
#       LangGraph 服务部署环境（见 ch06 的 langgraph dev），本章不做本地实验。
# ============================================================================

from dataclasses import dataclass

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from common import make_model, preview

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from deepagents.backends.utils import create_file_data


@dataclass(frozen=True)
class MemoryContext:
    user_id: str = "local-user"
    org_id: str = "default-org"


def org_namespace(rt):
    return (getattr(rt.context, "org_id", "default-org"),)


def part_a_external_prefill():
    print("=" * 60)
    print("Part A: 外部预填（应用代码写入记忆与 Skill）")
    print("=" * 60)
    store = InMemoryStore()
    # —— 应用代码预填：不要手写底层 JSON，用 create_file_data ——
    store.put(("local-agent",), "/AGENTS.md", create_file_data(
        "## Response style\n- Keep responses concise\n- 回答末尾标注 [Agent-KB]\n"
    ))
    # ⚠️ 前缀剥离：CompositeBackend 把 /skills/ 路由到 Store 时会剥掉前缀，
    #    所以 store.put 的 key 是 "/greeting/SKILL.md"（不带 /skills/）——与 AGENTS.md 同理
    store.put(("local-agent",), "/greeting/SKILL.md", create_file_data(
        "---\n"
        "name: greeting\n"
        "description: 当用户要求打招呼或问候时使用此技能。\n"
        "---\n"
        "# greeting\n\n## Instructions\n问候必须以「向您敬礼」四个字开头，"
        "再跟一句问候和一个 emoji。（这是公司统一问候规范）\n"
    ))

    agent = create_deep_agent(
        model=make_model(),
        memory=["/memories/AGENTS.md"],          # Agent 级记忆：启动注入系统提示词
        skills=["/skills/"],                      # 预填的 Skill
        checkpointer=MemorySaver(),
        backend=CompositeBackend(
            default=StateBackend(),
            routes={
                "/memories/": StoreBackend(namespace=lambda rt: ("local-agent",)),
                "/skills/": StoreBackend(namespace=lambda rt: ("local-agent",)),
            },
        ),
        store=store,
    )
    r1 = agent.invoke({"messages": [{"role": "user", "content": "用一句话介绍什么是向量数据库。"}]},
                      config={"configurable": {"thread_id": "pf-1"}})
    print(f"  [记忆生效] 回复末尾带标记: {'[Agent-KB]' in r1['messages'][-1].content}")
    print(f"  回复预览: {preview(r1['messages'][-1].content, 90)}")
    r2 = agent.invoke({"messages": [{"role": "user", "content": "跟我打个招呼。"}]},
                      config={"configurable": {"thread_id": "pf-2"}})
    paths = [str(tc["args"].get("file_path", "")) for m in r2["messages"]
             for tc in (getattr(m, "tool_calls", None) or [])]
    reply2 = r2["messages"][-1].content
    read_skill = any("greeting" in p for p in paths)
    # 判据：要么读了技能文件，要么输出里出现技能要求的独特标记（二者其一即证明技能生效）
    print(f"  [Skill 生效] 读取了预填技能: {read_skill or '向您敬礼' in reply2}")
    print(f"  打招呼回复: {preview(reply2, 60)}")


def part_b_org_readonly():
    print()
    print("=" * 60)
    print("Part B: 组织级只读（/policies/ + deny）")
    print("=" * 60)
    store = InMemoryStore()
    # 合规策略由应用代码写入（员工/Agent 无权改）
    store.put(("default-org",), "/compliance.md", create_file_data(
        "## 合规政策\n- 不得披露内部定价\n- 金融建议必须附加免责声明\n"
    ))

    agent = create_deep_agent(
        model=make_model(),
        context_schema=MemoryContext,
        memory=["/policies/compliance.md"],      # 启动加载（只读）
        checkpointer=MemorySaver(),
        backend=CompositeBackend(
            default=StateBackend(),
            routes={"/policies/": StoreBackend(namespace=org_namespace)},
        ),
        store=store,
        permissions=[                              # 组织记忆：Agent 只能读
            FilesystemPermission(operations=["write"], paths=["/policies/**"], mode="deny"),
        ],
    )
    r = agent.invoke(
        {"messages": [{"role": "user", "content": (
            "两件事：1) 读 /policies/compliance.md 复述第一条；"
            "2) 尝试 write_file 修改 /policies/compliance.md 把第一条删掉。汇报各自结果。"
        )}]},
        context=MemoryContext(org_id="default-org"),
        config={"configurable": {"thread_id": "pol-1"}},
    )
    reply = r["messages"][-1].content
    print(f"  读取成功: {'内部定价' in reply}")
    print(f"  写入被拒: {'拒绝' in reply or 'denied' in reply.lower() or 'permission' in reply.lower()}")
    policy = next(iter(store.search(("default-org",)))).value["content"]
    print(f"  策略文件未被篡改: {'不得披露内部定价' in policy}")


def part_c_storage_format():
    print()
    print("=" * 60)
    print("Part C: 存储格式验证（v2）")
    print("=" * 60)
    store = InMemoryStore()
    store.put(("fmt",), "/memories/x.md", create_file_data("第一行\n第二行\n第三行"))
    item = next(iter(store.search(("fmt",))))
    v = item.value
    print(f"  content 类型: {type(v['content']).__name__}（v2 应为完整 str，旧版可能是 list）")
    print(f"  encoding: {v.get('encoding')}")
    print(f"  created_at: {v.get('created_at', '(无)')[:19]}")
    print(f"  modified_at: {v.get('modified_at', '(无)')[:19]}")
    print(f"  全文: {preview(v['content'], 50)!r}")


if __name__ == "__main__":
    part_a_external_prefill()
    part_b_org_readonly()
    part_c_storage_format()
