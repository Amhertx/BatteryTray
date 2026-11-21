"""面板内的矢量图形（PIL 4 倍超采样 → PhotoImage）。

Tk Canvas 自带的 arc/polygon 没有抗锯齿，19px 的耳机、鼠标图形会毛边；
这里统一先画 4 倍图再 LANCZOS 缩小，边缘和系统图标一致。
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageTk

_CACHE: dict[tuple, ImageTk.PhotoImage] = {}
S = 4  # 超采样倍数


def _canvas(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw, float]:
    n = size * S
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), n / 24.0


def _headset(d, k, color, w):
    def p(*v):
        return tuple(x * k for x in v)

    d.arc(p(3.5, 3.5, 20.5, 20.5), 180, 360, fill=color, width=w)
    d.rounded_rectangle(p(2.6, 12.5, 7.2, 21), radius=2.2 * k, fill=color)
    d.rounded_rectangle(p(16.8, 12.5, 21.4, 21), radius=2.2 * k, fill=color)


def _mouse(d, k, color, w):
    """实心机身 + 镂空分缝。19px 下描边太细看不出来，实心剪影更立得住。"""
    def p(*v):
        return tuple(x * k for x in v)

    d.rounded_rectangle(p(6.9, 2.6, 17.1, 21.4), radius=4.9 * k, fill=color)
    d.rectangle(p(11.1, 2.6, 12.9, 10.0), fill=(0, 0, 0, 0))
    d.rectangle(p(6.9, 9.7, 17.1, 11.3), fill=(0, 0, 0, 0))


def _keyboard(d, k, color, w):
    def p(*v):
        return tuple(x * k for x in v)

    d.rounded_rectangle(p(1.8, 6.4, 22.2, 17.6), radius=2.4 * k, outline=color, width=w)
    r = max(1, int(0.9 * k))
    for i, x in enumerate((5.2, 8.9, 12.6, 16.3, 18.8)):
        cy = 9.6 if i < 4 else 9.6
        d.rounded_rectangle(p(x - 0.55, cy - 0.55, x + 0.55, cy + 0.55), radius=r, fill=color)
    d.rounded_rectangle(p(7.6, 13.2, 16.4, 14.4), radius=r, fill=color)


def _gear(d, k, color, w):
    cx = cy = 12 * k
    for i in range(8):
        a = math.pi / 4 * i
        r1, r2 = 6.4 * k, 9.2 * k
        d.line((cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                cx + r2 * math.cos(a), cy + r2 * math.sin(a)),
               fill=color, width=int(w * 1.5))
    r = 5.0 * k
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=int(w * 1.1))


def _back(d, k, color, w):
    d.line((15 * k, 4.5 * k, 8 * k, 12 * k, 15 * k, 19.5 * k),
           fill=color, width=w, joint="curve")


def _chevron(d, k, color, w):
    d.line((9.5 * k, 4 * k, 15.5 * k, 12 * k, 9.5 * k, 20 * k),
           fill=color, width=w, joint="curve")


def _bell(d, k, color, w):
    d.arc((4.4 * k, 1.6 * k, 19.6 * k, 16.8 * k), 180, 360, fill=color, width=w)
    d.line((4.4 * k, 9.2 * k, 4.4 * k, 15 * k), fill=color, width=w)
    d.line((19.6 * k, 9.2 * k, 19.6 * k, 15 * k), fill=color, width=w)
    d.line((2.8 * k, 15 * k, 21.2 * k, 15 * k), fill=color, width=w)
    d.arc((9.6 * k, 14.4 * k, 14.4 * k, 19.6 * k), 0, 180, fill=color, width=w)


def _bolt(d, k, color, w):
    d.polygon([(13.4 * k, 1.8 * k), (4.6 * k, 13.4 * k), (11.2 * k, 13.4 * k),
               (10.2 * k, 22.2 * k), (19.0 * k, 10.6 * k), (12.4 * k, 10.6 * k)],
              fill=color)


_GLYPHS = {
    "headset": _headset,
    "mouse": _mouse,
    "keyboard": _keyboard,
    "gear": _gear,
    "back": _back,
    "chevron": _chevron,
    "bell": _bell,
    "bolt": _bolt,
}


def ui_icon(kind: str, color: str, size: int = 19, stroke: float = 1.9) -> ImageTk.PhotoImage:
    """返回可直接给 Canvas.create_image 的图形；同参数会命中缓存。"""
    key = (kind, color, size, round(stroke, 2))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit

    img, draw, k = _canvas(size)
    _GLYPHS[kind](draw, k, color, max(1, int(stroke * S)))
    img = img.resize((size, size), Image.LANCZOS)
    photo = ImageTk.PhotoImage(img)
    _CACHE[key] = photo
    return photo
