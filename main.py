#!/usr/bin/env python3
"""LTspice 离线模型导入工具入口。

用法:
  python main.py              # 启动图形界面
  python main.py gui
  python main.py import ...
  python main.py parse ...
  python main.py detect
  python main.py --cli import --help
"""

from __future__ import annotations

import sys
from pathlib import Path

# 保证以脚本方式运行时可找到包
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ltspice_importer.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
