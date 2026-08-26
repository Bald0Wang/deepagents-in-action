# ============================================================================
# 01_builtin_file_tools.py —— ch03 段1：七个内置文件系统工具 + 分片读取 + grep 三模式
# 结构分两部分：
#   part_a_backend_direct()   —— 无 LLM，FilesystemBackend 直接调用，确定性验证
#   part_b_agent_end_to_end() —— DeepSeek 端到端，让 Agent 走一遍全部文件工具
# ============================================================================

# 模块文档字符串：说明本脚本覆盖的内容
"""ch03 段1：七个内置文件系统工具 + read_file 分片读取 + grep 三种输出模式。

Part A（无 LLM）：FilesystemBackend 直接调用，确定性验证分片读取、glob、edit、delete、路径沙箱。
Part B（DeepSeek）：Deep Agent 端到端，走一遍 write/ls/read/grep(三模式)/edit/delete。
"""

# Path：拼接本地沙箱目录路径
from pathlib import Path

# 从 common 导入两个公共工具：make_model（构建模型）、preview（文本预览）
from common import make_model, preview

# create_deep_agent：创建 Deep Agent 的核心入口
from deepagents import create_deep_agent
# FilesystemBackend：本地磁盘后端（Part A 直接用，Part B 用默认 StateBackend）
from deepagents.backends import FilesystemBackend

# SANDBOX：Part A 本地后端使用的沙箱目录（本脚本同级目录下的 .sandbox）
SANDBOX = Path(__file__).parent / ".sandbox"


# ---------------------------------------------------------------------------
# Part A：FilesystemBackend 直接调用（确定性，无 LLM）
# 直接调用后端方法，逐一验证分片读取、glob、grep、edit、delete、路径沙箱。
# ---------------------------------------------------------------------------
def part_a_backend_direct():
    # 打印分隔线 + 标题，标识 Part A 开始
    print("=" * 60)
    print("Part A: FilesystemBackend 直接调用（确定性，无 LLM）")
    print("=" * 60)
    # 创建本地磁盘后端：根目录为 SANDBOX，开启 virtual_mode 路径沙箱
    backend = FilesystemBackend(root_dir=str(SANDBOX), virtual_mode=True)

    # 构造一个 160 行的文件内容，用于后续分片读取测试
    lines = []                       # 累积每一行的容器
    for i in range(1, 161):          # 生成第 1~160 行
        if i in (30, 80, 120):       # 第 30/80/120 行埋入 "TODO" 关键字（供 grep 测试）
            lines.append(f"Line {i}: TODO: fix this section")
        elif i == 55:                # 第 55 行埋入函数定义（供 grep 定位）
            lines.append("Line 55: def create_agent(model, tools):")
        else:                        # 其余行是普通内容
            lines.append(f"Line {i}: routine content of the report")
    # 用换行符把所有行拼成一个完整文本
    content = "\n".join(lines)
    # 写入虚拟文件系统（也真实落盘到 SANDBOX）
    w = backend.write("/workspace/report.md", content)
    # 断言写入无错误（失败会抛出 AssertionError，带上错误信息）
    assert not w.error, w.error
    # 打印写入成功 + 返回的逻辑路径
    print(f"[write] ok -> {w.path}")
    # 打印该文件是否真的落到了本地磁盘（验证 FilesystemBackend 真实落盘）
    print(f"[disk ] 真实落盘: {(SANDBOX / 'workspace' / 'report.md').exists()}")

    # --- read_file 特性一：分片读取 -------------------------------------
    # 默认读取（不传 offset/limit）：读整份文件
    r1 = backend.read("/workspace/report.md")
    # 打印默认读取返回的行范围、总行数、下一页偏移
    print(f"[read ] 默认: lines {r1.start_line}-{r1.end_line}, total={r1.total_lines}, next_offset={r1.next_offset}")
    # 分片读取：从第 100 行起，读 50 行（即第 101~150 行）
    r2 = backend.read("/workspace/report.md", offset=100, limit=50)
    # 打印分片读取返回的行范围与偏移
    print(f"[read ] offset=100 limit=50: lines {r2.start_line}-{r2.end_line}, next_offset={r2.next_offset}")
    # 断言分片边界正确：起始 101、结束 150、下一页偏移 150
    assert r2.start_line == 101 and r2.end_line == 150 and r2.next_offset == 150

    # --- glob 模式匹配 ----------------------------------------------------
    # 查找所有 .md 文件（** 表示递归匹配任意层级）
    g = backend.glob("**/*.md", path="/")
    # 打印匹配结果（0.7.6 中 glob.matches 是 dict 列表，用 hasattr 兜底兼容 FileInfo）
    print(f"[glob ] **/*.md -> {[m.path if hasattr(m, 'path') else m for m in g.matches]}")

    # --- grep（后端层：内容检索）-----------------------------------------
    # 在所有 .md 文件中检索 "TODO"
    gr = backend.grep("TODO", glob="**/*.md")
    # 取出命中列表（可能为 None，兜底为空列表）
    matches = gr.matches or []
    # 打印命中总数与前 3 条
    print(f"[grep ] 'TODO' 命中 {len(matches)} 处: {matches[:3]}")

    # --- edit_file 精确替换 ----------------------------------------------
    # 把第 30 行的 "TODO..." 精确替换为 "DONE"
    e = backend.edit("/workspace/report.md", "Line 30: TODO: fix this section", "Line 30: DONE")
    # 打印替换次数与错误
    print(f"[edit ] occurrences={e.occurrences}, error={e.error}")
    # 再次 grep "TODO"，验证替换后只剩 2 处（原 3 处 - 1）
    gr2 = backend.grep("TODO", glob="**/*.md")
    print(f"[grep ] 替换后 'TODO' 命中 {len(gr2.matches or [])} 处（应为 2）")

    # --- delete -----------------------------------------------------------
    # 先写一个临时文件
    backend.write("/workspace/tmp.txt", "temporary")
    # 删除它
    d = backend.delete("/workspace/tmp.txt")
    # 打印删除结果 + 本地是否已不存在
    print(f"[del  ] error={d.error}; 文件还在吗: {(SANDBOX / 'workspace' / 'tmp.txt').exists()}")

    # --- 路径沙箱（virtual_mode=True）------------------------------------
    # 绝对路径被当作沙箱内的虚拟路径（落在 root_dir 下），不会碰到真实 /etc
    esc1 = backend.write("/etc/evil.txt", "x")
    # 计算该绝对路径实际落盘的沙箱内位置
    landed = SANDBOX / "etc" / "evil.txt"
    # 打印验证：真实 /etc 未被触碰，而是写进了沙箱
    print(f"[sandbox] /etc/evil.txt -> 实际落在沙箱内: {landed.exists()}（真实 /etc 未被触碰）")
    # ".." 穿越会被直接拒绝（抛出 ValueError）
    try:
        backend.write("../../evil.txt", "x")                     # 尝试越界写入
        print("[sandbox] ../../evil.txt -> 未拦截（异常！）")      # 若未抛异常说明沙箱失效
    except ValueError as exc:                                    # 捕获 ValueError
        print(f"[sandbox] ../../evil.txt -> 拦截成功: {exc}")     # 打印拦截成功


# ---------------------------------------------------------------------------
# Part B：Deep Agent 端到端（DeepSeek + StateBackend）
# 让 Agent 依次执行 7 个文件工具，验证工具能被模型正确调度与组合。
# ---------------------------------------------------------------------------
def part_b_agent_end_to_end():
    # 打印空行分隔 + 标题，标识 Part B 开始
    print()
    print("=" * 60)
    print("Part B: Deep Agent 端到端（DeepSeek + StateBackend）")
    print("=" * 60)
    # 创建 Deep Agent：默认 StateBackend（临时存储），只带系统提示词
    agent = create_deep_agent(
        model=make_model(),                                    # 用 common 构建的 DeepSeek 模型
        system_prompt="你是文件管理助手。严格按用户指令操作，最后用中文简短汇报。",  # 角色设定
    )

    # 任务描述：让 Agent 依次执行 6 步文件操作（覆盖 7 个工具）
    task = (
        "请依次完成并汇报每步结果：\n"
        "1. write_file 创建 /workspace/notes.md，内容为三行：'要点A：虚拟文件系统'、'要点B：分片读取'、'要点C：grep检索'\n"
        "2. ls 列出 /workspace\n"
        "3. read_file 读取 /workspace/notes.md\n"
        "4. grep 用三种模式各查一次关键词 '要点'：files_with_matches、content、count，汇报三种输出的区别\n"
        "5. edit_file 把 '要点C：grep检索' 改成 '要点C：grep三种模式'\n"
        "6. write_file 创建 /workspace/draft.txt（任意内容），然后 delete 它\n"
    )
    # 调用 Agent：输入标准消息格式，Agent 内部自动规划并多次调用工具
    result = agent.invoke({"messages": [{"role": "user", "content": task}]})

    # 打印最终虚拟文件系统内容（state.files）
    print("--- 最终虚拟文件系统（state.files）---")
    for path, meta in (result.get("files") or {}).items():
        # 0.7.6 中 files 的值是 {"content": ..., "encoding": ..., "modified_at": ...}
        content = meta["content"] if isinstance(meta, dict) else meta
        # 打印每个文件的路径、长度与内容预览
        print(f"  {path}  ({len(content)} chars)  preview: {preview(content, 60)}")
    # 打印 Agent 的最终汇报
    print("--- Agent 汇报 ---")
    print(result["messages"][-1].content)


# 脚本入口：作为主程序运行时依次执行 Part A 与 Part B
if __name__ == "__main__":
    part_a_backend_direct()       # 先跑确定性后端直调
    part_b_agent_end_to_end()     # 再跑 Deep Agent 端到端
