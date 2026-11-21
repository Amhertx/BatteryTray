"""托盘图标绘制。

单图标模式：电池图形（按最低电量填充）
多图标模式：设备图形（耳机 / 鼠标 / 键盘）+ 底部电量条，靠形状和颜色区分设备

绘制约定：画布固定 64x64（= 16px 的 4 倍超采样），所有坐标直接写 64 空间，
最后 LANCZOS 缩到 16x16。托盘在 100% DPI 下就是 16x16，这样边缘最干净。
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

BASE = 16   # 托盘实际像素
N = 64      # 超采样画布

GRAY = (148, 155, 164)
GREEN = (34, 197, 94)
AMBER = (245, 158, 11)
RED = (239, 68, 68)
TRACK = (188, 194, 202)

ACCENT = {
    "sony_h9": (59, 130, 246),     # 蓝
    "razer_dav3": (139, 92, 246),  # 紫
    "aula_f87": (237, 108, 24),    # 橙
}

GLYPH = {
    "sony_h9": "headset",
    "razer_dav3": "mouse",
    "aula_f87": "keyboard",
}


def level_color(percent: int | None, status: str = "ok") -> tuple[int, int, int]:
    if percent is None or status != "ok":
        return GRAY
    if percent >= 60:
        return GREEN
    if percent >= 30:
        return AMBER
    return RED


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x * (1 - t) + y * t) for x, y in zip(a, b))


# ---------------- 设备图形遮罩（64 空间） ----------------
# 16px 下每个像素 = 4 个 64 空间单位，所以特征必须 ≥8 单位（2px）才立得住。
# 键盘原来 8 个小键（9×5）缩下去只有 2×1px，看起来是一排噪点；改成 3 大键 × 2 行。
def _mask_headset(d) -> None:
    d.arc((13, 1, 51, 41), 180, 360, fill=255, width=13)
    d.rounded_rectangle((1, 17, 18, 45), radius=7, fill=255)
    d.rounded_rectangle((46, 17, 63, 45), radius=7, fill=255)


def _mask_mouse(d) -> None:
    d.rounded_rectangle((16, 1, 48, 45), radius=14, fill=255)
    d.rectangle((30, 1, 34, 17), fill=0)       # 中缝
    d.rectangle((17, 19, 47, 23), fill=0)      # 左右键分隔


def _mask_keyboard(d) -> None:
    d.rounded_rectangle((2, 9, 62, 45), radius=7, fill=255)
    for row, y in enumerate((15, 28)):
        for col in range(3):
            x = 9 + col * 17
            d.rounded_rectangle((x, y, x + 12, y + 8), radius=2, fill=0)
    d.rounded_rectangle((9, 40, 55, 45), radius=2, fill=0)


_MASKS = {"headset": _mask_headset, "mouse": _mask_mouse, "keyboard": _mask_keyboard}


def _glyph_layer(kind: str, color: tuple[int, int, int]) -> Image.Image:
    mask = Image.new("L", (N, N), 0)
    _MASKS[kind](ImageDraw.Draw(mask))
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    layer.paste(Image.new("RGBA", (N, N), color + (255,)), (0, 0), mask)
    return layer


def _draw_bar(draw, percent: int | None, charge: float | None = None,
              left: int = 5, right: int = 59, top: int = 51, bottom: int = 62) -> None:
    """底部电量条（64 空间里 11 单位高 → 16px 下约 2.75px）。

    长度 = 电量，充电时整条在**同一种颜色**里呼吸（深 ↔ 浅，色相不变）。
    为什么不用「从当前电量补满」的涨条：电量到 99% 时只剩 0.15px 可涨，等于没有动画；
    呼吸与剩余空间无关，任何电量都看得见。
    """
    draw.rounded_rectangle((left, top, right, bottom), radius=5, fill=TRACK + (255,))
    if percent is None:
        return
    pct = min(100, max(0, percent))
    color = level_color(pct)
    if charge is not None:
        wave = 0.5 - 0.5 * math.cos(2 * math.pi * max(0.0, min(1.0, charge)))
        color = _mix(TRACK, color, 0.38 + 0.62 * wave)
    span = right - left
    width = max(5, int(span * pct / 100))
    draw.rounded_rectangle((left, top, left + width, bottom), radius=5, fill=color)


# ---------------- 对外接口 ----------------
def device_icon(key: str, percent: int | None, status: str = "ok",
                charging: bool = False, charge: float | None = None) -> Image.Image:
    """多图标模式：设备形状 + 底部电量条。

    充电时不再画闪电（16px 里和图形糊在一起），改成电量条从当前电量往 100% 涨：
    charge 传动画进度 0~1；不传则停在当前电量。
    """
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    color = ACCENT.get(key, GRAY) if status != "offline" else GRAY
    img.alpha_composite(_glyph_layer(GLYPH.get(key, "keyboard"), color))
    d = ImageDraw.Draw(img)
    live = status == "ok"
    _draw_bar(d, percent if live else None,
              (charge or 0.0) if (charging and live) else None)
    return img.resize((BASE, BASE), Image.BOX)


def battery_icon(percent: int | None, status: str = "ok", charging: bool = False) -> Image.Image:
    """单图标模式：电池图形，按最低电量填充。"""
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = level_color(percent, status)

    d.rounded_rectangle((2, 4, 54, 56), radius=10, outline=color, width=8)
    d.rounded_rectangle((55, 20, 62, 40), radius=3, fill=color)

    if percent is not None and status == "ok":
        inner_x1, inner_x2 = 10, 46
        inner_y2 = 48
        inner_h = 36
        ratio = max(0.0, min(1.0, percent / 100))
        fill_h = max(int(inner_h * ratio), 5) if ratio > 0 else 0
        if fill_h:
            d.rounded_rectangle((inner_x1, inner_y2 - fill_h, inner_x2, inner_y2),
                                radius=3, fill=color)

    if charging and status == "ok":
        # 电池内部右上角打闪电，比原来那圈白描边清楚得多
        poly = [(38, 12), (28, 30), (35, 30), (30, 44), (44, 24), (37, 24), (42, 12)]
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            d.polygon([(x + dx, y + dy) for x, y in poly], fill=(28, 32, 40, 255))
        d.polygon(poly, fill=(255, 255, 255, 255))

    return img.resize((BASE, BASE), Image.BOX)


def make_ico(path: str) -> None:
    """生成多尺寸 .ico，供 exe 使用。"""
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((8, 8, 248, 248), radius=56, fill=ACCENT["razer_dav3"])
    d.rounded_rectangle((60, 88, 180, 168), radius=18, outline=(255, 255, 255, 255), width=16)
    d.rounded_rectangle((184, 108, 200, 148), radius=6, fill=(255, 255, 255, 255))
    d.rounded_rectangle((78, 104, 150, 152), radius=10, fill=GREEN)
    base.save(path, format="ICO", sizes=[(s, s) for s in sizes])
