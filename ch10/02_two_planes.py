# ============================================================================
# 02_two_planes.py —— ch10 段2：文件的两个平面 + 大输出处理
#
#   Part A: 两平面闭环（LLM 参与）
#     宿主平面：upload_files 播种输入 → Agent 在沙箱内工作（读数据、跑
#     python、写结果）→ 宿主 download_files 取回产物。
#     Agent 平面：read_file/execute/write_file 全程在沙箱内，见不到宿主 FS。
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
    print("=" * 60)
    print("Part A: 两平面闭环（upload → Agent 沙箱内工作 → download）")
    print("=" * 60)
    root = tempfile.mkdtemp(prefix="sbx_plane_")
    backend = LocalShellBackend(root_dir=root, virtual_mode=True, inherit_env=False)

    # ── 宿主平面：运行前播种输入（源码 + 数据）──
    backend.upload_files([
        ("/src/stats.py", b"import json\n"
                          b"data = json.load(open('data/nums.json'))\n"
                          b"print(sum(data['nums']))\n"),
        ("/data/nums.json", b'{"nums": [10, 20, 30, 40, 50]}'),
    ])
    print("  [宿主平面] 已播种 /src/stats.py + /data/nums.json")

    # ── Agent 平面：沙箱内读数据 → 跑脚本 → 写报告 ──
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
    results = backend.download_files(["/out/result.txt"])
    if results[0].content is not None:
        print(f"  [宿主平面] 取回产物: {results[0].content.decode().strip()!r}")
    else:
        print(f"  下载失败: {results[0].error}")


def part_b_large_output():
    print()
    print("=" * 60)
    print("Part B: 大输出 —— 截断 vs 落盘分页")
    print("=" * 60)
    root = tempfile.mkdtemp(prefix="sbx_big_")
    backend = LocalShellBackend(root_dir=root, virtual_mode=True, inherit_env=False)
    print(f"  MAX_OUTPUT_BYTES = {MAX_OUTPUT_BYTES}（约 {MAX_OUTPUT_BYTES // 1024}KB）")

    # ① 截断：直接打印 600KB
    big_cmd = "python3 -c \"print('x' * 600000)\""
    r = backend.execute(big_cmd)
    print(f"  ① 截断: exit={r.exit_code}, truncated={r.truncated}, "
          f"返回长度={len(r.output)}（原文 600KB）")

    # ② 落盘分页（推荐）：大输出重定向到文件，read 分页查看
    # 注意：execute 的 cwd 是沙箱根，命令里用相对路径（虚拟路径 /big/ ↔ 根下 big/）
    backend.execute("mkdir -p big && python3 -c \"print('x' * 600000)\" > big/output.txt")
    info = backend.glob("**/output.txt", path="/")
    print(f"  ② 落盘: 文件存在={bool(info.matches)}")
    r2 = backend.read("/big/output.txt", offset=0, limit=2)
    content = r2.file_data["content"] if isinstance(r2.file_data, dict) else r2.file_data
    print(f"     分页读取: lines {r2.start_line}-{r2.end_line}, total={r2.total_lines}, "
          f"next_offset={r2.next_offset}")
    print(f"     本页预览: {str(content)[:40]!r}...")
    print("  结论：大输出不塞上下文——编译日志/测试报告先落盘，模型按需 read_file 分页")


if __name__ == "__main__":
    part_a_two_planes()
    part_b_large_output()
