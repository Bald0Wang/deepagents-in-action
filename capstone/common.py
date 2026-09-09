# ============================================================================
# common.py —— 综合大作业公共工具
#
# 职责（沿用 ch02/ch03 的做法，避免各模块重复代码）：
#   1. _load_dotenv：极简 .env 解析器，import 时自动加载 capstone/.env
#   2. make_model：构建 DeepSeek（OpenAI 兼容接口）模型实例
#   3. preview：多行文本单行预览，方便打印与断言
# ============================================================================

"""公共工具：.env 自动加载 + DeepSeek 模型工厂 + 文本预览。"""

import os
from pathlib import Path

from langchain_openai import ChatOpenAI


# ---------------------------------------------------------------------------
# 一、.env 自动加载（ch02 直接读 os.environ；这里补一个极简解析器，免 export）
# ---------------------------------------------------------------------------
def _load_dotenv(path: Path) -> None:
    """极简 .env 解析：KEY=VALUE，支持 # 注释；不覆盖已有环境变量。"""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # setdefault：已有环境变量优先，不被 .env 覆盖
        if key:
            os.environ.setdefault(key, value)


# 模块导入时加载本目录 .env（含 DEEPSEEK_API_KEY / MODEL_NAME）
_load_dotenv(Path(__file__).resolve().parent / ".env")


# ---------------------------------------------------------------------------
# 二、模型工厂（ch02 的 ChatOpenAI + DeepSeek 官方兼容接口）
# ---------------------------------------------------------------------------
def make_model(**kwargs) -> ChatOpenAI:
    """按课程方式构建 DeepSeek 模型（OpenAI 兼容接口）。

    Args:
        **kwargs: 透传给 ChatOpenAI 的额外参数（如 timeout、max_retries）。

    Raises:
        KeyError: 未配置 DEEPSEEK_API_KEY 时抛出，便于尽早发现配置问题。
    """
    return ChatOpenAI(
        model=os.environ.get("MODEL_NAME", "deepseek-v4-flash"),
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com/v1",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 三、文本预览（与 ch03/ch04 的 preview 一致，兼容 dict 形态的 file_data）
# ---------------------------------------------------------------------------
def preview(text, n: int = 160) -> str:
    """把多行文本压成一行并截断，便于打印/断言。兼容 dict（取 content）。"""
    if isinstance(text, dict):
        text = text.get("content", "")
    return str(text).replace("\n", "\\n")[:n]
