"""pytest 配置：把 capstone 根目录加入 sys.path，让测试能直接 import 各模块。"""

import sys
from pathlib import Path

CAPSTONE = Path(__file__).resolve().parent.parent
if str(CAPSTONE) not in sys.path:
    sys.path.insert(0, str(CAPSTONE))
