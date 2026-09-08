# ============================================================================
# 02_two_planes.py —— ch10 段2：文件的两个平面 + 大输出处理
#
#   Part A: 两平面闭环（LLM 参与）
#     宿主平面：upload_files 播种输入 → Agent 在沙箱内工作（读数据、跑
#     python、写结果）→ 宿主 download_files 取回产物。
#     Agent 平面：read_file/execute/write_file 完成任务。本地 Shell 能访问宿主 FS，
#     本例只模拟工具流向，不演示远程容器的隔离保证。
#   Part B: 大输出的两种处理（确定性）
#     ① 截断：execute 输出超过 MAX_OUTPUT_BYTES → truncated 标记 + 提示
#     ② 落盘分页（课程推荐）：大输出重定向到文件，read 分页查看，
#        模型上下文只进预览不进全文。
# ============================================================================

import tempfile
from pathlib import Path

from common import make_model, preview

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from deepagents.backends.sandbox import MAX_OUTPUT_BYTES


def part_a_two_planes():
    """对应原文 §5–6：宿主准备输入和收取结果，模型只编排工作区里的计算。"""
    print("=" * 60)
    print("Part A: 两平面闭环（upload → Agent 沙箱内工作 → download）")
    print("=" * 60)
    root = tempfile.mkdtemp(prefix="sbx_plane_")
    backend = LocalShellBackend(root_dir=root, virtual_mode=True, inherit_env=False)

    # ── 宿主平面：运行前播种输入（源码 + 数据）──
    # 这是普通 Python 调用，未经过模型。模型不需要知道宿主输入文件原来放在哪里。
    # 输入预先固定为 10+20+30+40+50，便于拿最终产物与 150 比对。
    backend.upload_files([
        ("/src/stats.py", b"import json\n"
                          b"data = json.load(open('data/nums.json'))\n"
                          b"print(sum(data['nums']))\n"),
        ("/data/nums.json", b'{"nums": [10, 20, 30, 40, 50]}'),
    ])
    print("  [宿主平面] 已播种 /src/stats.py + /data/nums.json")

    # ── Agent 平面：工作区内读数据 → 跑脚本 → 写报告 ──
    # 文件工具用虚拟路径 /data/nums.json；execute 用 cwd 下的 python3 src/stats.py。
    # 两者路径写法不同，却访问同一个工作区文件。
    print("  [Agent 平面] 等待模型完成计算并写报告…", flush=True)
    agent = create_deep_agent(
        model=make_model(),
        backend=backend,
        system_prompt="你是数据助手，在沙箱内工作：读数据、用 execute 运行 python3 src/stats.py，"
                      "把结果写入 /out/result.txt（格式：sum=<数值>）。",
    )
    r = agent.invoke({"messages": [{"role": "user", "content":
        "统计 /data/nums.json 的数值总和，并把结果文件写好。"}]})
    calls = [tc["name"] for m in r["messages"] for tc in (getattr(m, "tool_calls", None) or [])]
    print(f"  [Agent 平面] 使用工具: {sorted(set(calls))}")
    print(f"  Agent 回复: {preview(r['messages'][-1].content, 90)}")

    # ── 宿主平面：运行后取回产物 ──
    # 最终交付是下载得到的 bytes，不是模型口头说“文件已写好”。
    # content=None 时要读取 error；不能直接 decode。多文件部分失败见实验四 Part B。
    results = backend.download_files(["/out/result.txt"])
    if results[0].content is not None:
        print(f"  [宿主平面] 取回产物: {results[0].content.decode().strip()!r}")
    else:
        print(f"  下载失败: {results[0].error}")


def part_b_large_output():
    """对应原文 §1：截断丢失返回文本；主动落盘后按行读回，才能保留完整日志。"""
    print()
    print("=" * 60)
    print("Part B: 大输出 —— 截断 vs 落盘分页")
    print("=" * 60)
    root = tempfile.mkdtemp(prefix="sbx_big_")
    backend = LocalShellBackend(root_dir=root, virtual_mode=True, inherit_env=False)
    print(f"  BaseSandbox MAX_OUTPUT_BYTES = {MAX_OUTPUT_BYTES}（不是本例的配置值）")
    print("  本例 LocalShellBackend 默认先按 max_output_bytes=100000 截断")

    # ① 截断：直接打印 600KB
    big_cmd = "python3 -c \"print('x' * 600000)\""
    r = backend.execute(big_cmd)
    print(f"  ① 截断: exit={r.exit_code}, truncated={r.truncated}, "
          f"返回长度={len(r.output)}（原文 600KB）")

    # ② 落盘分页（推荐）：大输出重定向到文件，read 分页查看。
    # 关键是生成多行：limit 按“行数”限制，不按字符数限制。
    # 若把 600000 个字符写在一行，limit=2 仍可能返回整条巨长行！
    # 注意：execute 的 cwd 是沙箱根，命令里用相对路径（虚拟路径 /big/ ↔ 根下 big/）
    backend.execute("mkdir -p big && python3 -c \"[print('line', i, 'x' * 100) for i in range(6000)]\" > big/output.txt")
    info = backend.glob("**/output.txt", path="/")
    print(f"  ② 落盘: 文件存在={bool(info.matches)}")
    r2 = backend.read("/big/output.txt", offset=0, limit=2)
    content = r2.file_data["content"] if isinstance(r2.file_data, dict) else r2.file_data
    # 预期：总行数 6000，本页第 1–2 行、next_offset=2，读取内容只有约 200 字符。
    assert r2.total_lines == 6000 and r2.next_offset == 2
    assert len(content) < 1000
    print(f"     分页读取: lines {r2.start_line}-{r2.end_line}, total={r2.total_lines}, "
          f"next_offset={r2.next_offset}")
    print(f"     本页预览: {str(content)[:40]!r}...")
    print("  结论：大输出不塞上下文——编译日志/测试报告先落盘，模型按需 read_file 分页")


if __name__ == "__main__":
    part_a_two_planes()
    part_b_large_output()
