"""面板内的矢量图形，直接画进 PIL 图像（配合超采样抗锯齿）。

坐标按 24×24 的设计网格书写，由 ox/oy/k 映射到实际像素，
这样同一份路径既能画 22px 的卡片图标，也能画 14px 的按钮图标。
"""
from __future__ import annotations

import math

from PIL import ImageDraw


def _p(ox: float, oy: float, k: float, *v: float) -> list[float]:
    """把 24 网格坐标映射到画布坐标（v 为 x,y 交替）。"""
    out: list[float] = []
    for i, val in enumerate(v):
        out.append(ox + val * k if i % 2 == 0 else oy + val * k)
    return out


def _headset(d, k, color, w, ox, oy):
    d.arc(_p(ox, oy, k, 3.5, 3.5, 20.5, 20.5), 180, 360, fill=color, width=w)
    d.rounded_rectangle(_p(ox, oy, k, 2.6, 12.5, 7.2, 21), radius=2.2 * k, fill=color)
    d.rounded_rectangle(_p(ox, oy, k, 16.8, 12.5, 21.4, 21), radius=2.2 * k, fill=color)


def _mouse(d, k, color, w, ox, oy):
    """实心机身 + 镂空分缝，小尺寸下比描边轮廓更立得住。"""
    d.rounded_rectangle(_p(ox, oy, k, 6.9, 2.6, 17.1, 21.4), radius=4.9 * k, fill=color)
    d.rectangle(_p(ox, oy, k, 11.1, 2.6, 12.9, 10.0), fill=(0, 0, 0, 0))
    d.rectangle(_p(ox, oy, k, 6.9, 9.7, 17.1, 11.3), fill=(0, 0, 0, 0))


def _keyboard(d, k, color, w, ox, oy):
    d.rounded_rectangle(_p(ox, oy, k, 1.8, 6.4, 22.2, 17.6), radius=2.4 * k,
                        outline=color, width=w)
    r = max(1, 0.9 * k)
    for x in (5.2, 8.9, 12.6, 16.3, 18.8):
        d.rounded_rectangle(_p(ox, oy, k, x - 0.6, 9.0, x + 0.6, 10.2), radius=r, fill=color)
    d.rounded_rectangle(_p(ox, oy, k, 7.6, 13.2, 16.4, 14.4), radius=r, fill=color)


def _gear(d, k, color, w, ox, oy):
    """实心齿轮：齿是外圈上的小圆，齿体是一道厚环。

    旧版是「小环 + 8 根细辐条」，14px 上辐条糊成一圈尖刺，看着像亮度/太阳图标。
    齿轮真正好认的特征是「厚齿体 + 中心孔」，所以齿做短、齿体加厚、孔缩小。
    """
    cx, cy = ox + 12 * k, oy + 12 * k
    tr, tooth = 9.2 * k, 2.5 * k
    for i in range(8):
        a = math.pi / 4 * i
        px, py = cx + tr * math.cos(a), cy + tr * math.sin(a)
        d.ellipse((px - tooth, py - tooth, px + tooth, py + tooth), fill=color)
    body = 7.0 * k
    d.ellipse((cx - body, cy - body, cx + body, cy + body),
              outline=color, width=max(2, int(round(4.0 * k))))


def _back(d, k, color, w, ox, oy):
    d.line(_p(ox, oy, k, 15, 4.5, 8, 12, 15, 19.5), fill=color, width=w, joint="curve")


def _chevron(d, k, color, w, ox, oy):
    d.line(_p(ox, oy, k, 9.5, 4, 15.5, 12, 9.5, 20), fill=color, width=w, joint="curve")


def _bell(d, k, color, w, ox, oy):
    d.arc(_p(ox, oy, k, 4.4, 1.6, 19.6, 16.8), 180, 360, fill=color, width=w)
    d.line(_p(ox, oy, k, 4.4, 9.2, 4.4, 15), fill=color, width=w)
    d.line(_p(ox, oy, k, 19.6, 9.2, 19.6, 15), fill=color, width=w)
    d.line(_p(ox, oy, k, 2.8, 15, 21.2, 15), fill=color, width=w)
    d.arc(_p(ox, oy, k, 9.6, 14.4, 14.4, 19.6), 0, 180, fill=color, width=w)


def _close(d, k, color, w, ox, oy):
    d.line(_p(ox, oy, k, 5.8, 5.8, 18.2, 18.2), fill=color, width=w)
    d.line(_p(ox, oy, k, 18.2, 5.8, 5.8, 18.2), fill=color, width=w)


def _bolt(d, k, color, w, ox, oy):
    d.polygon([_p(ox, oy, k, 13.4, 1.8), _p(ox, oy, k, 4.6, 13.4),
               _p(ox, oy, k, 11.2, 13.4), _p(ox, oy, k, 10.2, 22.2),
               _p(ox, oy, k, 19.0, 10.6), _p(ox, oy, k, 12.4, 10.6)],
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
    "close": _close,
}


def draw_glyph(d: ImageDraw.ImageDraw, kind: str, color: str, cx: float, cy: float,
               size: float, stroke: float = 2.0) -> None:
    """在 (cx, cy) 居中画一个 size 见方的图形；坐标已是目标像素。"""
    k = size / 24.0
    _GLYPHS[kind](d, k, color, max(2, int(round(stroke * k))),
                  cx - size / 2, cy - size / 2)
