"""托盘图标绘制。

单图标模式：电池图形（按最低电量填充）
多图标模式：设备图形（耳机 / 鼠标 / 键盘）+ 底部电量条，靠形状和颜色区分设备

绘制约定：画布固定 64x64（= 16px 的 4 倍超采样），所有坐标直接写 64 空间，
最后 LANCZOS 缩到 16x16。托盘在 100% DPI 下就是 16x16，这样边缘最干净。
"""
from __future__ import annotations

from PIL import Image, ImageDraw

BASE = 16   # 托盘实际像素
N = 64      # 超采样画布

GRAY = (148, 155, 164)
GREEN = (34, 197, 94)
AMBER = (245, 158, 11)
RED = (239, 68, 68)

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


# ---------------- 设备图形遮罩（64 空间） ----------------
def _mask_headset(d) -> None:
    d.arc((12, 4, 52, 44), 180, 360, fill=255, width=12)
    d.rounded_rectangle((4, 22, 20, 52), radius=8, fill=255)
    d.rounded_rectangle((44, 22, 60, 52), radius=8, fill=255)


def _mask_mouse(d) -> None:
    d.rounded_rectangle((18, 2, 46, 52), radius=14, fill=255)
    d.rectangle((30, 2, 34, 20), fill=0)      # 中缝
    d.rectangle((20, 22, 44, 25), fill=0)     # 左右键分隔


def _mask_keyboard(d) -> None:
    d.rounded_rectangle((2, 16, 62, 46), radius=8, fill=255)
    for row in range(2):
        y = 24 + row * 10
        for col in range(4):
            x = 9 + col * 13
            d.rectangle((x, y, x + 9, y + 5), fill=0)


_MASKS = {"headset": _mask_headset, "mouse": _mask_mouse, "keyboard": _mask_keyboard}


def _glyph_layer(kind: str, color: tuple[int, int, int]) -> Image.Image:
    mask = Image.new("L", (N, N), 0)
    _MASKS[kind](ImageDraw.Draw(mask))
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    layer.paste(Image.new("RGBA", (N, N), color + (255,)), (0, 0), mask)
    return layer


def _draw_bar(draw, percent: int | None, top: int = 54, bottom: int = 63) -> None:
    draw.rounded_rectangle((2, top, 62, bottom), radius=4, fill=(203, 208, 215, 255))
    if percent is not None:
        width = max(6, int(60 * min(100, max(0, percent)) / 100))
        draw.rounded_rectangle((2, top, 2 + width, bottom), radius=4, fill=level_color(percent))


def _draw_bolt(draw) -> None:
    """充电标记：右上角白色闪电。

    16px 托盘里没有空间放文字，闪电是唯一能同时表达「充电中」又不牺牲电量条比例的标记。
    先描一圈深色轮廓，保证在浅色任务栏上也能立住。
    """
    poly = [(57, 0), (46, 19), (54, 19), (48, 34), (63, 11), (55, 11), (61, 0)]
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        draw.polygon([(x + dx, y + dy) for x, y in poly], fill=(28, 32, 40, 255))
    draw.polygon(poly, fill=(255, 255, 255, 255))


# ---------------- 对外接口 ----------------
def device_icon(key: str, percent: int | None, status: str = "ok",
                charging: bool = False) -> Image.Image:
    """多图标模式：设备形状 + 底部电量条 + 充电闪电。"""
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    color = ACCENT.get(key, GRAY) if status != "offline" else GRAY
    img.alpha_composite(_glyph_layer(GLYPH.get(key, "keyboard"), color))
    d = ImageDraw.Draw(img)
    _draw_bar(d, percent if status == "ok" else None)
    if charging and status == "ok":
        _draw_bolt(d)
    return img.resize((BASE, BASE), Image.LANCZOS)


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

    return img.resize((BASE, BASE), Image.LANCZOS)


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
