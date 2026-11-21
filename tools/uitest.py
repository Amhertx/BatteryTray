"""UI 预览：渲染面板并截图，用于检查排版。"""
from __future__ import annotations

import os
import sys

# 允许从 tools/ 目录直接运行：把项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ctypes
import tkinter as tk

from PIL import ImageGrab

from btray.config import load
from btray.panel import Panel
from btray.service import BatteryService


def main() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass

    cfg = load()
    service = BatteryService(cfg)
    service.poll_once()

    root = tk.Tk()
    root.withdraw()
    panel = Panel(root, service, cfg)
    panel.show()

    def grab() -> None:
        panel.win.update_idletasks()
        x, y = panel.win.winfo_rootx(), panel.win.winfo_rooty()
        w, h = panel.win.winfo_width(), panel.win.winfo_height()
        img = ImageGrab.grab(bbox=(x - 10, y - 10, x + w + 10, y + h + 10))
        img.save("panel_preview.png")
        root.quit()

    root.after(1500, grab)
    root.mainloop()


if __name__ == "__main__":
    main()
