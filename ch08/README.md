# 第 8 章 · 长期记忆 — 学习代码

沿用 ch02 环境与模型配置（DeepSeek 官方接口），ch08 有独立 `.venv`，`common.py` 自动加载 `.env`，直接 `uv run`。本次解析到 **deepagents 0.7.13**。

## 运行

```bash
cd ch08
uv sync
uv run 01_two_memories.py        # 短期 vs 长期对照
uv run 02_memory_scopes.py       # 用户级/Agent级/路径路由
uv run 03_memory_scenarios.py    # 偏好跨对话/自我改进/知识累积
uv run 04_advanced_memory.py     # 外部预填/组织只读/v2格式
uv run 05_episodic_and_consolidation.py  # 情景记忆 + 后台整合
uv run 06_concurrency_and_isolation.py   # 并发写入 + 多Agent隔离 + 升级路径
uv run pytest -q                 # 10 例确定性测试
RUN_LLM_TESTS=1 uv run pytest -q # +6 例 LLM 集成（约 47s，共 16 例）
```

## 实测要点

- **两种记忆对照**：Checkpointer 对话历史与 StateBackend 文件都是短期（换 thread 即丢）；`/memories/` 路由 StoreBackend 后跨 thread 持久。
- **三种作用域**：用户级 `(user_id,)` A/B 隔离；Agent 级 `(assistant_id,)` 全员共享；组织级 `(org_id,)` 配 deny 实现只读策略。
- **memory= 参数**：声明路径启动即以 `<agent_memory>` 注入系统提示词（附带"何时该更新记忆"的完整指导），Agent 用 `edit_file` 落盘新知识。
- **三场景验证**：偏好跨对话自动应用（中文注释英文变量名）；自我改进（纠错→AGENTS.md 更新→新对话遵循）；知识累积（三次对话追加，最终 React+FastAPI 都在）。
- **外部预填**：`store.put` + `create_file_data` 预填记忆与 Skill，Agent 启动即用。

## 高级用法补全（05 / 06 脚本）

| 主题 | 实现 | 实测结果 |
|---|---|---|
| **情景记忆** | 对话结束追加 `/memories/episodes/<id>.md`（保留完整经历），自定义 `search_episodes` 检索工具交给 Agent | Agent 主动调工具，还原上次 GIL 咨询时"先结论后解释+threading/multiprocessing 建议"的全过程 |
| **后台整合** | 热路径写唯一命名事件日志 → 独立整合 Agent 去重合并成 `preferences.md` → 新对话 `memory=` 加载遵循 | 两份事件零冲突；整合后两条偏好都在；去重函数"不改原列表"符合整合记忆 |
| **并发写入** | 同文件 last-write-wins 冲突现场 + 两种缓解（主题拆分 / 追加式 `events/<thread>.md`） | 冲突复现（线程1 丢失）；两种缓解均零丢失 |
| **多 Agent 隔离** | namespace 用 `(assistant_id, user_id)` 二元组 | 同一 user-42 在 assistant-a/b 间记忆互不干扰，store 按二元组分仓 |
| **升级路径** | InMemoryStore → PostgresStore | 代码就绪；无 `DATABASE_URL` 时优雅跳过并打印生产写法 |

> 情景记忆/后台整合的课程版走部署端 `threads.search`/`crons`（需 LangGraph 服务，见 ch06）；本地用「文件式情景日志 + 整合 Agent」实现同一语义——这本身就是课程推荐的"追加式记录，再后台合并"模式。

## ⚠️ 关键版本发现（0.7.13）：store key 剥离路由前缀

CompositeBackend 写 Store 时 key 会**剥掉路由前缀**：`/memories/prefs.md` → `/prefs.md`，`/skills/greeting/SKILL.md` → `/greeting/SKILL.md`。

两个直接影响：
1. **外部预填必须用剥前缀的 key**——实测把 Skill put 成 `/skills/greeting/SKILL.md` 会导致 Agent 侧读不到（技能列表里根本没有它）；改成 `/greeting/SKILL.md` 才被激活。
2. **排查数据时别找不到**——`store.search()` 里看到的 key 都没有 `/memories/` 前缀。

## 测试

- `tests/test_memory_deterministic.py`（5 例）：v2 格式、Store 往返、namespace 隔离、Composite 路由与前缀剥离、预填 key 陷阱（正反两例）。
- `tests/test_advanced_cases.py`（5 例）：情景检索命中/未命中、last-write-wins、主题拆分、追加式共存、多 Agent 隔离。
- `tests/test_llm_integration.py`（6 例）：短期记忆线程作用域、跨对话长期记忆、用户隔离、Agent 级共享、memory= 启动加载、组织只读。

完整代码与真实运行输出见《代码与运行结果.md》。
