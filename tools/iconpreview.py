"""托盘图标预览：把 16px 图标按真实像素放大，检查充电动画各帧。

输出 preview/icon_phases.png：每行一台设备，每列一个充电进度（10%→100%），
分别贴在浅色、深色任务栏底色上，看颜色对比够不够。
"""
from __future__ import annotations

import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btray.icons import BASE, device_icon  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "preview")
ZOOM = 8
PHASES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
CASES = [
    ("aula_f87", 99, True),
    ("sony_h9", 49, True),
    ("razer_dav3", 22, True),
    ("aula_f87", 100, True),
]
BG_LIGHT = (243, 243, 243)
BG_DARK = (32, 32, 32)


def strip(bg) -> Image.Image:
    pad = 6
    cell = BASE * ZOOM
    w = pad + len(PHASES) * (cell + pad)
    h = pad + len(CASES) * (cell + pad) * 2
    out = Image.new("RGB", (w, h), bg)
    y = pad
    for key, pct, charging in CASES:
        for bg2 in (BG_LIGHT, BG_DARK):
            band = Image.new("RGB", (w, cell + pad), bg2)
            out.paste(band, (0, y - pad // 2))
            for i, ph in enumerate(PHASES):
                icon = device_icon(key, pct, "ok", charging, ph)
                big = icon.resize((cell, cell), Image.NEAREST)
                out.paste(big, (pad + i * (cell + pad), y), big)
            y += cell + pad
    return out


def actual_size() -> Image.Image:
    """1x 实际大小，贴在两种任务栏底色上，用来判断真机观感。"""
    keys = [("aula_f87", 99), ("sony_h9", 49), ("razer_dav3", 22), ("aula_f87", 100)]
    pad = 8
    w = pad * 2 + len(keys) * (BASE + pad)
    out = Image.new("RGB", (w, BASE * 2 + pad * 3), BG_LIGHT)
    for row, bg in enumerate((BG_LIGHT, BG_DARK)):
        out.paste(Image.new("RGB", (w, BASE + pad), bg), (0, pad // 2 + row * (BASE + pad * 2)))
        for i, (key, pct) in enumerate(keys):
            icon = device_icon(key, pct, "ok", True, 0.55)
            out.paste(icon, (pad + i * (BASE + pad), pad + row * (BASE + pad * 2)), icon)
    return out.resize((w * 4, (BASE * 2 + pad * 3) * 4), Image.NEAREST)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    img = strip(BG_LIGHT)
    path = os.path.join(OUT, "icon_phases.png")
    img.save(path)
    print("saved", path, img.size)
    p2 = os.path.join(OUT, "icon_actual.png")
    actual_size().save(p2)
    print("saved", p2)


if __name__ == "__main__":
    sys.exit(main())
