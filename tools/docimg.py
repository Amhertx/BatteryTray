"""生成 README 用的配图，输出到 docs/。

全部用假数据（复用 uipreview 的 StubService），不碰真设备，可随时重跑：

    python tools/docimg.py

产物：
  docs/hero.png      浅色 + 深色 首页并排
  docs/settings.png  设置页（浅色）
  docs/charge.gif    充电动画（键盘 85%，其余两台静止）
"""
from __future__ import annotations

import ctypes
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from PIL import Image  # noqa: E402

from btray import theme  # noqa: E402
from btray.config import DEFAULTS, DEVICES  # noqa: E402
from btray.icons import device_canvas  # noqa: E402
from btray.panel import Panel  # noqa: E402
from uipreview import StubService  # noqa: E402

DOCS = os.path.join(os.path.dirname(HERE), "docs")
CELL = 96                   # 图标展示尺寸：用 64 空间画布放大（比放大 16px 干净）


def big_icon(key: str, pct, charging: bool = False, charge: float | None = None):
    return device_canvas(key, pct, charging=charging, charge=charge).resize(
        (CELL, CELL), Image.LANCZOS)


def panel_shots() -> tuple[Image.Image, Image.Image, Image.Image]:
    cfg = dict(DEFAULTS)
    cfg.update(display_mode="multi", low_battery_alert=True, low_battery_threshold=20)
    root = tk.Tk()
    root.withdraw()
    panel = Panel(root, StubService(), cfg)

    def shot(pal, view) -> Image.Image:
        panel.pal, panel.view = pal, view
        panel._draw()
        return panel._img.resize((panel.W, panel.H), Image.LANCZOS)

    light = shot(theme.LIGHT, "main")
    dark = shot(theme.DARK, "main")
    settings = shot(theme.LIGHT, "settings")
    panel.win.destroy()
    root.destroy()
    return light, dark, settings


def hero(light: Image.Image, dark: Image.Image) -> Image.Image:
    gap = 28
    out = Image.new("RGBA", (light.width * 2 + gap, light.height), (0, 0, 0, 0))
    out.paste(light.convert("RGBA"), (0, 0))
    out.paste(dark.convert("RGBA"), (light.width + gap, 0))
    return out


def charge_gif(path: str) -> None:
    """白底卡片里放三台设备，键盘那条电量条循环补满（40% → 85%）。"""
    gap, pad = 18, 14
    w = pad * 2 + CELL * len(DEVICES) + gap * (len(DEVICES) - 1)
    h = pad * 2 + CELL
    frames = []
    steps = 24
    for i in range(steps):
        frame = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        progress = i / (steps - 1)
        for j, dev in enumerate(DEVICES):
            if dev["key"] == "aula_f87":
                icon = big_icon("aula_f87", 85, True, progress)
            elif dev["key"] == "sony_h9":
                icon = big_icon("sony_h9", 49)
            else:
                icon = big_icon("razer_dav3", 100)
            frame.alpha_composite(icon, (pad + j * (CELL + gap), pad))
        frames.append(frame.convert("RGB"))
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=90, loop=0, optimize=False)


def main() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    os.makedirs(DOCS, exist_ok=True)

    light, dark, settings = panel_shots()
    hero(light, dark).save(os.path.join(DOCS, "hero.png"))
    settings.save(os.path.join(DOCS, "settings.png"))
    charge_gif(os.path.join(DOCS, "charge.gif"))
    print("docs/ 已更新：hero.png settings.png charge.gif")


if __name__ == "__main__":
    main()
