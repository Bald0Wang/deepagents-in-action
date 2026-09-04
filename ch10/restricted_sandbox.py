# ============================================================================
# restricted_sandbox.py —— 自定义受限沙箱（ch10 共享，供脚本与测试复用）
#
# 实现 SandboxBackendProtocol 的本地教学版：
#   只需实现 4 个原语 —— execute() / upload_files() / download_files() / id
#   BaseSandbox 会自动把 ls/read/write/edit/glob/grep 等文件工具构建在
#   execute() 之上（课程：「提供商接入的核心通常就是可靠地实现 execute()」）
#
# 教学性安全策略（模拟真实沙箱 Provider 的能力）：
#   - 命令黑名单：rm -rf /、curl/wget/nc（模拟网络外传阻断）
#   - 输出上限：超过 MAX_OUTPUT_BYTES 截断并附提示（大输出不塞模型上下文）
#   - 路径沙箱：upload/download 拒绝 .. 穿越
# ============================================================================

import subprocess
from pathlib import Path

from deepagents.backends.sandbox import (
    MAX_OUTPUT_BYTES,
    TRUNCATION_MSG,
    BaseSandbox,
    FileDownloadResponse,
    FileUploadResponse,
)

BLOCKED_PATTERNS = ["rm -rf /", "curl ", "wget ", "nc ", "ssh "]   # 模拟危险/外传命令


class RestrictedSandbox(BaseSandbox):
    """本地受限沙箱：教学版 Provider（真实场景换成 Daytona/Modal 等远程容器）。"""

    def __init__(self, root: str | Path):
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self.commands_run: list[str] = []          # 审计日志：记录每条实际执行的命令

    # ---- 协议要求的 4 个原语 ------------------------------------------------
    @property
    def id(self) -> str:
        return f"restricted-sandbox:{self._root.name}"

    def execute(self, command: str, *, timeout: int | None = None):
        self.commands_run.append(command)          # 审计：无论成败都记录
        for bad in BLOCKED_PATTERNS:
            if bad in command:
                from deepagents.backends.protocol import ExecuteResponse
                return ExecuteResponse(
                    output=f"Error: command blocked by sandbox policy: '{bad.strip()}' is not allowed.",
                    exit_code=126, truncated=False,
                )
        try:
            proc = subprocess.run(
                command, shell=True, cwd=self._root,
                capture_output=True, timeout=timeout or 30,
                env={"PATH": "/usr/bin:/bin", "HOME": str(self._root)},
            )
            output = (proc.stdout + proc.stderr).decode("utf-8", "replace")
            truncated = False
            if len(output.encode()) > MAX_OUTPUT_BYTES:
                output = output[:MAX_OUTPUT_BYTES] + f"\n{TRUNCATION_MSG}"
                truncated = True
            from deepagents.backends.protocol import ExecuteResponse
            return ExecuteResponse(output=output, exit_code=proc.returncode, truncated=truncated)
        except subprocess.TimeoutExpired:
            from deepagents.backends.protocol import ExecuteResponse
            return ExecuteResponse(output=f"Error: command timed out after {timeout or 30}s",
                                   exit_code=124, truncated=False)

    def upload_files(self, files) -> list[FileUploadResponse]:
        results = []
        for path, content in files:
            target = (self._root / path.lstrip("/")).resolve()
            if not str(target).startswith(str(self._root)):      # 路径沙箱
                results.append(FileUploadResponse(path=path, error="path escapes sandbox root"))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else content.encode())
            results.append(FileUploadResponse(path=path, error=None))
        return results

    def download_files(self, paths) -> list[FileDownloadResponse]:
        results = []
        for path in paths:
            target = (self._root / path.lstrip("/")).resolve()
            if not str(target).startswith(str(self._root)):
                results.append(FileDownloadResponse(path=path, content=None, error="path escapes root"))
                continue
            if not target.exists():
                results.append(FileDownloadResponse(path=path, content=None, error="not found"))
                continue
            results.append(FileDownloadResponse(path=path, content=target.read_bytes(), error=None))
        return results
