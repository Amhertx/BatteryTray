"""无控制台启动入口（配合 pythonw.exe 使用）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from btray.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
