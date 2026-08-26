# ============================================================================
# conftest.py —— pytest 全局配置（每个测试进程启动时自动执行）
# 做两件事：
#   1. 把 ch03 目录加入 sys.path，让测试能 import common / custom_backends
#   2. 自动加载 ch03/.env，让 `uv run pytest` 无需 --env-file 也能读到 API Key
# ============================================================================

# 模块文档字符串：说明本配置的用途
"""pytest 配置：sys.path 注入 + 自动加载 ch03/.env。

让 `uv run pytest` 无需 --project 或 --env-file 即可：
  - import 到 common / custom_backends
  - 从 ch03/.env 读到 API Key（LLM 集成测试用）
"""

# os：写入环境变量
import os
# sys：修改模块搜索路径
import sys
# Path：拼接文件路径
from pathlib import Path

# CH03_DIR：本 conftest.py 的上上级目录（即 ch03 根目录）
CH03_DIR = Path(__file__).resolve().parent.parent
# 若 ch03 目录不在 sys.path 中，则插入到最前面，保证优先 import 到本地模块
if str(CH03_DIR) not in sys.path:
    sys.path.insert(0, str(CH03_DIR))


# ---------------------------------------------------------------------------
# _load_dotenv：极简 .env 解析（与 common.py 中同名函数逻辑一致）
# 作用：把 KEY=VALUE 注入环境变量，不覆盖已有值。
# ---------------------------------------------------------------------------
def _load_dotenv(path: Path) -> None:
    """极简 .env 解析：KEY=VALUE，支持 # 注释；不覆盖已有环境变量。"""
    # 文件不存在则直接返回
    if not path.exists():
        return
    # 逐行读取
    for raw in path.read_text().splitlines():
        # 去掉首尾空白
        line = raw.strip()
        # 跳过空行、注释行、无 "=" 的行
        if not line or line.startswith("#") or "=" not in line:
            continue
        # 切分 key/value
        key, _, value = line.partition("=")
        # 清理 key
        key = key.strip()
        # 清理 value 并剥掉引号
        value = value.strip().strip('"').strip("'")
        # 非空 key 才写入（setdefault 保证已有环境变量优先）
        if key:
            os.environ.setdefault(key, value)


# 模块导入时立即执行：加载 ch03/.env（pytest 收集测试前就绪）
_load_dotenv(CH03_DIR / ".env")
