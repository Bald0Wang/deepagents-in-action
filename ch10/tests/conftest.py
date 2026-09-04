"""pytest 配置：sys.path 注入 + .env 加载（与 ch03 同款）。"""

import os
import sys
from pathlib import Path

CH10_DIR = Path(__file__).resolve().parent.parent
if str(CH10_DIR) not in sys.path:
    sys.path.insert(0, str(CH10_DIR))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv(CH10_DIR / ".env")
