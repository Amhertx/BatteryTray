"""截任务栏右侧，用于确认托盘图标是否在场。

屏幕休眠/锁屏时抓屏会得到全黑，所以连抓几次取最亮的一张。
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

from PIL import Image, ImageGrab

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "preview")


def grab_band(width: int = 700, height: int = 168) -> Image.Image | None:
    u = ctypes.windll.user32
    u.SetProcessDPIAware()
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    best = None
    best_bright = -1
    for _ in range(6):
        img = ImageGrab.grab(bbox=(sw - width, sh - height, sw, sh), all_screens=True)
        bright = sum(img.convert("L").resize((32, 8)).getdata())
        if bright > best_bright:
            best, best_bright = img, bright
        if best_bright > 120 * 32 * 8:      # 足够亮，不用再等
            break
        time.sleep(0.4)
    return best


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    img = grab_band()
    if img is None:
        print("grab failed")
        return
    path = os.path.join(OUT, "tray_band.png")
    img.resize((img.width * 2, img.height * 2), Image.LANCZOS).save(path)
    print("saved", path, img.size)


if __name__ == "__main__":
    sys.exit(main())
