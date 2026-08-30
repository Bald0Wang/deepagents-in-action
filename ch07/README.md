# 第 7 章 · Skills（可复用能力包）— 学习代码

沿用 ch02 环境与模型配置（DeepSeek 官方接口），ch07 有独立 `.venv`，`common.py` 自动加载 `.env`，直接 `uv run`。本次解析到 **deepagents 0.7.11**。

## 运行

```bash
cd ch07
uv sync
uv run 01_progressive_disclosure.py      # 三级加载 + description 质量
uv run 02_backends_and_priority.py       # 三种后端 + last-wins
uv run 03_subagent_inheritance.py        # 子 Agent 继承
uv run 04_permissions.py                 # deny 只读 + interrupt 审批
uv run pytest -q                         # 7 例确定性测试
RUN_LLM_TESTS=1 uv run pytest -q         # +6 例 LLM 集成（约 65s）
```

## 本地 Skills 资产（实验素材）

| 目录 | 用途 |
|---|---|
| `skills/code-review/` | 完整三级结构（SKILL.md + references/checklist + assets/template），渐进式加载实验主角 |
| `skills/team-report/` | 后端实验用（State/Store 注入、权限实验的目标文件） |
| `skills_bad/vague-helper/` | 差 description 样本（「帮助处理各种任务」） |
| `skills_shared/code-review/`、`skills_project/code-review/` | 同名双源，last-wins 判定（SHARED/PROJECT-VERSION 标记） |

## 实测要点

- **三级渐进式加载可见**：工具调用序列 = Level 2 `read SKILL.md` → Level 3 `read references/… + assets/…`；报告严格按模板。
- **description 的真实风险是「乱触发」**：模糊 skill 单独在场时被误用于审查任务；好差同场时精准选 code-review；无关问题零触发。
- **三后端全通**：Filesystem 直读 / State 经 `files` 参数 + `create_file_data` 注入 / Store `put` 一次跨线程共享。
- **last-wins 验证**：`skills=[shared, project]` 时 project 版生效。
- **继承判据**（0.7.11 关键发现）：子 Agent 总有内置文件工具能读到技能文件——「继承」的准确判据是**系统提示词里有没有技能列表**，用子 Agent 自报验证：GP=有 / 未声明=无 / 显式声明=有。
- **权限**：deny 读写分离（读得进、写被拒、磁盘未变）；interrupt 完整审批流（approve 落盘 / reject 不动），resume 格式 `Command(resume={"decisions": [{"type": "approve"}]})`。

## 测试

- `tests/test_skill_spec.py`（7 例，确定性）：Agent Skills 规范校验（frontmatter/name 一致/description 边界）、三级资源存在、双源标记、Filesystem/Store 后端往返、create_file_data 结构。
- `tests/test_llm_integration.py`（6 例，`RUN_LLM_TESTS=1`）：三级加载、无关不触发、last-wins、deny、interrupt approve+reject、GP 继承。

完整代码与真实运行输出见《代码与运行结果.md》。
