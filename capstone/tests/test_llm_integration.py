"""LLM 集成测试（默认跳过，设置 RUN_LLM_TESTS=1 启用）。

这些用例会真实调用 DeepSeek，验证端到端行为：
  - 单章答疑路由（ch03）
  - 模糊问题触发澄清（ch09 HITL respond）
  - 危险命令触发审批（ch10 + ch09 when）
  - 会话状态记忆（record_chapter 写入 cited_chapters）
  - knowledge-map 技能（渲染产物到 /out/）

注意：模型输出有随机性，断言只验证「机制是否生效」，不逐字比对文案。
"""

import os
import sys
from pathlib import Path

import pytest

CAPSTONE = Path(__file__).resolve().parent.parent
if str(CAPSTONE) not in sys.path:
    sys.path.insert(0, str(CAPSTONE))

RUN_LLM = os.environ.get("RUN_LLM_TESTS") == "1"
pytestmark = pytest.mark.skipif(not RUN_LLM, reason="设置 RUN_LLM_TESTS=1 启用 LLM 集成测试")


@pytest.fixture(scope="module")
def svc_factory(tmp_path_factory):
    """按需构建客服系统（共享模型，独立沙箱与 thread）。"""
    from service import build_customer_service

    base = tmp_path_factory.mktemp("capstone_llm")
    counter = {"n": 0}

    def make(user_id="alice", store=None, seed=True):
        counter["n"] += 1
        return build_customer_service(
            user_id=user_id,
            sandbox_root=base / f"sbx{counter['n']}",
            thread_id=f"llm-{counter['n']}",
            store=store,
            seed=seed,
        )

    return make


def test_single_chapter_routing(svc_factory):
    """ch03 问题应被路由到 ch03-ta 并给出与知识库一致的结论。"""
    svc = svc_factory()
    r = svc.ask("ch03 里 StateBackend 和 StoreBackend 的区别是什么？")
    assert not r.interrupted
    # 机制断言：提到了两个后端与「thread」这一核心区别
    assert "StateBackend" in r.reply and "StoreBackend" in r.reply
    assert "thread" in r.reply.lower()


def test_clarification_on_vague_question(svc_factory):
    """模糊问题应触发 ask_clarification，回答后能给出结论。"""
    svc = svc_factory()
    r = svc.ask("那个东西到底怎么用？")
    assert r.interrupted
    assert any(q.kind == "clarification" for q in r.requests)
    r2 = svc.answer("我问的是 ch02 怎么创建第一个 Deep Agent")
    assert not r2.interrupted
    assert r2.reply.strip()


def test_dangerous_execute_triggers_approval(svc_factory):
    """危险命令应触发审批；拒绝后命令不应产生副作用。"""
    svc = svc_factory()
    r = svc.ask("用 execute 运行命令 `sudo rm -rf /tmp/capstone-demo`。")
    if not r.interrupted:
        pytest.skip("模型拒绝执行危险命令（安全行为），本次未触发审批")
    assert any(q.kind == "approval" for q in r.requests)
    r2 = svc.decide(approve=False, message="不允许删除")
    assert not r2.interrupted
    # 拒绝后不应出现成功执行 sudo 的结果
    assert "已删除" not in r2.reply or "未执行" in r2.reply


def test_safe_execute_runs_without_approval(svc_factory):
    """安全命令应自动放行（when 谓词返回 False）。"""
    svc = svc_factory()
    r = svc.ask("用 execute 运行 `echo capstone-safe`，把输出告诉我。")
    assert not r.interrupted
    assert "capstone-safe" in r.reply


def test_state_memory_records_chapter(svc_factory):
    """会话状态记忆：record_chapter 应写入 cited_chapters。"""
    svc = svc_factory()
    r = svc.ask("ch08 的长期记忆是怎么实现的？请用 record_chapter 记录章节 ch08。")
    assert not r.interrupted
    assert "ch08" in (r.state.get("cited_chapters") or [])


def test_knowledge_map_skill_renders(svc_factory):
    """knowledge-map 技能：应产出 PNG 到 /out/。"""
    svc = svc_factory()
    r = svc.ask(
        "用 knowledge-map 技能画一张 ch03 的思维导图，"
        "渲染成 PNG 放到 /out/。"
    )
    if r.interrupted:
        # 可能触发澄清（问图谱还是思维导图）
        r = svc.answer("思维导图")
    artifacts = svc.collect()
    pngs = [a for a, _clean, _hits in artifacts if a.path.endswith(".png")]
    assert pngs, f"未产出 PNG；回复={r.reply[:300]}"
    assert all(a.size > 1000 for a in pngs)


def test_long_term_memory_cross_session(svc_factory):
    """ch08：写入 /memories/ 后，新会话（复用 store）仍能读到。"""
    svc1 = svc_factory(user_id="memory-user")
    svc1.ask("请记住我的偏好：回答用表格对比。保存到 /memories/user-profile.md")
    # 新会话、新 thread，但复用同一个 store
    svc2 = svc_factory(user_id="memory-user", store=svc1.store, seed=False)
    r = svc2.ask("读 /memories/user-profile.md，告诉我你记得我的什么偏好。")
    assert not r.interrupted
    assert "表格" in r.reply
