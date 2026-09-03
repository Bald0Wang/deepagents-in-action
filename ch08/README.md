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
uv run pytest -q                 # 5 例确定性测试
RUN_LLM_TESTS=1 uv run pytest -q # +6 例 LLM 集成（约 45s）
```

## 实测要点

- **两种记忆对照**：Checkpointer 对话历史与 StateBackend 文件都是短期（换 thread 即丢）；`/memories/` 路由 StoreBackend 后跨 thread 持久。
- **三种作用域**：用户级 `(user_id,)` A/B 隔离；Agent 级 `(assistant_id,)` 全员共享；组织级 `(org_id,)` 配 deny 实现只读策略。
- **memory= 参数**：声明路径启动即以 `<agent_memory>` 注入系统提示词（附带"何时该更新记忆"的完整指导），Agent 用 `edit_file` 落盘新知识。
- **三场景验证**：偏好跨对话自动应用（中文注释英文变量名）；自我改进（纠错→AGENTS.md 更新→新对话遵循）；知识累积（三次对话追加，最终 React+FastAPI 都在）。
- **外部预填**：`store.put` + `create_file_data` 预填记忆与 Skill，Agent 启动即用。

## ⚠️ 关键版本发现（0.7.13）：store key 剥离路由前缀

CompositeBackend 写 Store 时 key 会**剥掉路由前缀**：`/memories/prefs.md` → `/prefs.md`，`/skills/greeting/SKILL.md` → `/greeting/SKILL.md`。

两个直接影响：
1. **外部预填必须用剥前缀的 key**——实测把 Skill put 成 `/skills/greeting/SKILL.md` 会导致 Agent 侧读不到（技能列表里根本没有它）；改成 `/greeting/SKILL.md` 才被激活。
2. **排查数据时别找不到**——`store.search()` 里看到的 key 都没有 `/memories/` 前缀。

## 测试

- `tests/test_memory_deterministic.py`（5 例）：v2 格式、Store 往返、namespace 隔离、Composite 路由与前缀剥离、预填 key 陷阱（正反两例）。
- `tests/test_llm_integration.py`（6 例）：短期记忆线程作用域、跨对话长期记忆、用户隔离、Agent 级共享、memory= 启动加载、组织只读。

完整代码与真实运行输出见《代码与运行结果.md》。
