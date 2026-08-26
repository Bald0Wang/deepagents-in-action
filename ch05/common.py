# ============================================================================
# common.py —— ch05 公共配置模块
# 职责：统一提供 DeepSeek 模型实例 + 文本预览工具 + .env 自动加载。
# 所有主脚本（01~04）与测试都 import 本模块，避免重复代码。
# ============================================================================

# 模块级文档字符串：说明本文件用途与运行方式
"""ch05 公共配置：DeepSeek 官方接口 + deepseek-v4-flash。

ch05 有独立 .venv（依赖与 ch02 一致），并在 import 时自动加载 ch05/.env，
因此直接在 ch05/ 目录下 `uv run <脚本>.py` 即可，无需 --project / --env-file。
"""

# os：读取/写入进程环境变量（读取 API Key、模型名）
import os
# Path：拼接文件路径（定位本目录下的 .env 文件）
from pathlib import Path

# ChatOpenAI：LangChain 的 OpenAI 兼容接口模型类，用于接入 DeepSeek
from langchain_openai import ChatOpenAI


# ---------------------------------------------------------------------------
# 私有函数 _load_dotenv：极简 .env 解析器
# 作用：把 ch05/.env 里的 KEY=VALUE 注入进程环境变量，使脚本无需手动 export。
# ---------------------------------------------------------------------------
def _load_dotenv(path: Path) -> None:
    """极简 .env 解析：KEY=VALUE，支持 # 注释；不覆盖已有环境变量。"""
    # 如果 .env 文件不存在，直接返回（容错，不报错）
    if not path.exists():
        return
    # 逐行读取文件内容（splitlines 去掉换行符）
    for raw in path.read_text().splitlines():
        # 去掉行首尾空白
        line = raw.strip()
        # 跳过空行、注释行、以及不含 "=" 的无效行
        if not line or line.startswith("#") or "=" not in line:
            continue
        # 以第一个 "=" 切分，得到 key 和 value
        key, _, value = line.partition("=")
        # 去掉 key 两端空白
        key = key.strip()
        # 去掉 value 两端空白，并剥掉可能包裹的单/双引号
        value = value.strip().strip('"').strip("'")
        # key 非空才写入；setdefault 保证「已有环境变量优先，不被 .env 覆盖」
        if key:
            os.environ.setdefault(key, value)


# 模块导入时立即执行：加载本目录下的 .env（模块级副作用，只需一次）
_load_dotenv(Path(__file__).resolve().parent / ".env")


# ---------------------------------------------------------------------------
# 公共函数 make_model：构建 DeepSeek 模型实例
# 作用：所有脚本都用它拿模型，统一改 .env 里的 MODEL_NAME 即可全局切换模型。
# ---------------------------------------------------------------------------
def make_model(**kwargs) -> ChatOpenAI:
    """按课程「OpenAI 兼容接口」方式构建 DeepSeek 模型。"""
    return ChatOpenAI(
        # 模型名：优先读环境变量 MODEL_NAME，缺省用 deepseek-v4-flash
        model=os.environ.get("MODEL_NAME", "deepseek-v4-flash"),
        # API Key：从环境变量 DEEPSEEK_API_KEY 读取（.env 已加载）
        api_key=os.environ["DEEPSEEK_API_KEY"],
        # base_url：DeepSeek 官方 OpenAI 兼容端点（换平台只需改这里 + Key）
        base_url="https://api.deepseek.com/v1",
        # 透传额外参数（如 temperature、timeout 等），保持调用方灵活
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 公共函数 preview：多行文本单行预览
# 作用：把多行文本压成一行（\n -> \\n）并截断，方便打印/断言时肉眼核对。
# ---------------------------------------------------------------------------
def preview(text, n: int = 160) -> str:
    """多行文本单行预览，方便断言输出。

    兼容 str 或 ReadResult.file_data 这类 dict（取 content 字段）。
    """
    # 如果传入的是 dict（0.7.6 的 file_data 就是 dict），只取其中的 content 文本
    if isinstance(text, dict):
        text = text.get("content", "")
    # 统一转成字符串（兜底非字符串输入）
    text = str(text)
    # 把换行符替换为字面量 \\n，再截取前 n 个字符
    return text.replace("\n", "\\n")[:n]
