"""托盘弹出面板（PIL 渲染 + Tk 显示）。

为什么不用 Tk 原生图形：Canvas 的 arc/oval/polygon 没有抗锯齿，圆角、开关、胶囊
在 100% DPI 下全是台阶。这里整块面板画在 2 倍画布上再 LANCZOS 缩到 1:1，
文字走雅黑（PIL 带 hinting），边缘和系统原生控件一致。

v1.3 布局：
- 一台设备一张卡片，左侧是「圆环包围设备图形」的电量环，右侧是名称/状态/大号百分比
- 右上齿轮 → 面板内设置页（显示 / 提醒 / 通用）
- 跟随系统深浅色
"""
from __future__ import annotations

import ctypes
import math
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageTk

from .config import DEVICES, THRESHOLD_CHOICES, VERSION
from .glyphs import draw_glyph
from .icons import GLYPH
from .theme import Palette, current as current_palette, device_tint, mix_hex

SS = 2                     # 超采样倍数
FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_INDEX = 1             # ttc 里的 Microsoft YaHei UI

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

SEL = {"light": ("#EAF1FE", "#B9D2F7", "#12325E"),
       "dark": ("#22314D", "#3E5C8C", "#A8CBF5")}

KIND = {d["key"]: d.get("kind", "") for d in DEVICES}


def hide_from_taskbar(win: tk.Misc, force: bool = False) -> None:
    """把 Tk 窗口标记为工具窗口：任务栏和 Alt+Tab 都不会再多出条目。"""
    try:
        user32 = ctypes.windll.user32
        win.update_idletasks()
        child = win.winfo_id()
        hwnd = user32.GetParent(child) or child
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        wanted = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        if style != wanted:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, wanted)
        if force:
            user32.ShowWindow(hwnd, 0)  # SW_HIDE
            user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
    except Exception:  # noqa: BLE001
        pass


class Pen:
    """在超采样画布上绘制：入参都是逻辑像素，内部统一乘 SS。"""

    def __init__(self, img: Image.Image, draw: ImageDraw.ImageDraw, pal: Palette):
        self.img = img
        self.d = draw
        self.pal = pal
        self._fonts: dict[tuple, ImageFont.FreeTypeFont] = {}

    def font(self, px: float, bold: bool = False) -> ImageFont.FreeTypeFont:
        key = (round(px), bold)
        hit = self._fonts.get(key)
        if hit is None:
            hit = ImageFont.truetype(FONT_BOLD if bold else FONT_REG,
                                     max(6, int(round(px * SS))), index=FONT_INDEX)
            self._fonts[key] = hit
        return hit

    def text(self, x: float, y: float, s: str, px: float, color: str,
             anchor: str = "lt", bold: bool = False) -> None:
        self.d.text((x * SS, y * SS), s, font=self.font(px, bold), fill=color, anchor=anchor)

    def width(self, s: str, px: float, bold: bool = False) -> float:
        return self.d.textlength(s, font=self.font(px, bold)) / SS

    def line(self, x1, y1, x2, y2, color: str, width: float = 1) -> None:
        self.d.line([x1 * SS, y1 * SS, x2 * SS, y2 * SS], fill=color,
                    width=max(1, int(round(width * SS))))

    def rr(self, x1, y1, x2, y2, r, fill=None, outline=None, width: float = 1) -> None:
        self.d.rounded_rectangle([x1 * SS, y1 * SS, x2 * SS, y2 * SS], radius=r * SS,
                                 fill=fill, outline=outline,
                                 width=max(1, int(round(width * SS))))

    def glyph(self, kind: str, color: str, cx: float, cy: float, size: float,
              stroke: float = 1.9) -> None:
        draw_glyph(self.d, kind, color, cx * SS, cy * SS, size * SS, stroke)

    RING_SS = 8            # 环的局部超采样倍数，主画布只有 2 倍，环的边缘要更细的过渡

    def ring(self, cx: float, cy: float, r: float, w: float, ratio: float,
             color: str, track: str) -> None:
        """电量环：外半径 r、线宽 w，圆头落在中线 r - w/2 上。

        PIL 的 arc(width=) 是「从外边界向内」描边的，弧线中线并不在 r 上；
        若圆头按 r 摆放就会比环宽出去半个线宽，两端各冒一个小凸点。
        这里改用局部 8 倍画布上的实心几何（外圆减内圆）构造环，再降采样合成。
        """
        pad = w / 2 + 1
        size = (r + pad) * 2
        n = max(8, int(round(size * self.RING_SS)))
        layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        k = n / size                      # 逻辑像素 → 局部像素
        c = n / 2
        ro, ri = r * k, (r - w) * k
        rc = (r - w / 2) * k              # 中线半径
        box_out = (c - ro, c - ro, c + ro, c + ro)
        box_in = (c - ri, c - ri, c + ri, c + ri)

        d.ellipse(box_out, fill=track)
        d.ellipse(box_in, fill=(0, 0, 0, 0))

        ratio = max(0.0, min(1.0, ratio))
        if ratio > 0.002:
            if ratio >= 0.998:
                d.ellipse(box_out, fill=color)
                d.ellipse(box_in, fill=(0, 0, 0, 0))
            else:
                end = -90 + 360 * ratio
                d.pieslice(box_out, -90, end, fill=color)
                d.ellipse(box_in, fill=(0, 0, 0, 0))
                hr = w / 2 * k
                for ang in (-90, end):
                    a = math.radians(ang)
                    px, py = c + rc * math.cos(a), c + rc * math.sin(a)
                    d.ellipse((px - hr, py - hr, px + hr, py + hr), fill=color)

        edge = int(round(size * SS))
        small = layer.resize((edge, edge), Image.LANCZOS)
        self.img.paste(small, (int(round((cx - r - pad) * SS)),
                               int(round((cy - r - pad) * SS))), small)


class Panel:
    W, H = 360, 372
    PAD = 12
    TOP = 58
    CARD_H = 78
    GAP = 8
    SLIDE = 10
    FRAMES = 9
    FRAME_MS = 13

    def __init__(self, root: tk.Tk, service, cfg: dict, on_refresh=None):
        self.root = root
        self.service = service
        self.cfg = cfg
        self.on_refresh = on_refresh
        self.ctrl = None
        self.pal: Palette = current_palette()
        self.view = "main"
        self._hot: list[tuple[float, float, float, float, object]] = []
        self._hover = -1
        self._photo = None
        self._img: Image.Image | None = None
        self._job = None
        self._anim_job = None
        self._hide_job = None

        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=self.pal.bg)

        self.canvas = tk.Canvas(self.win, width=self.W, height=self.H, bg=self.pal.bg,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)

        self.win.bind("<Escape>", self._on_escape)
        self.win.bind("<FocusOut>", self._maybe_hide)

        hide_from_taskbar(self.win)
        hide_from_taskbar(root)

    def attach(self, ctrl) -> None:
        self.ctrl = ctrl

    # ---------- 窗口 ----------
    def _apply_round_corners(self) -> None:
        try:
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            pref = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), ctypes.sizeof(pref)
            )
        except Exception:  # noqa: BLE001
            pass

    @property
    def visible(self) -> bool:
        return bool(self.win.winfo_ismapped())

    def toggle(self) -> None:
        self.hide() if self.visible else self.show()

    def _target(self) -> tuple[int, int]:
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        return sw - self.W - 12, sh - self.H - 56

    def show(self) -> None:
        self._cancel_anim()
        if self._hide_job:
            self.win.after_cancel(self._hide_job)
            self._hide_job = None

        self.pal = current_palette()
        self.win.configure(bg=self.pal.bg)
        self.canvas.configure(bg=self.pal.bg)
        self.view = "main"
        self._hover = -1

        x, y = self._target()
        self._draw()
        self.win.attributes("-alpha", 0.0)
        self.win.geometry(f"{self.W}x{self.H}+{x}+{y + self.SLIDE}")
        self.win.deiconify()
        hide_from_taskbar(self.win, force=True)
        self.win.lift()
        self.win.attributes("-topmost", True)
        self._apply_round_corners()
        try:
            self.win.focus_force()
        except tk.TclError:
            pass
        self._animate(1, x, y, 0)
        self._schedule_refresh()

    def hide(self) -> None:
        if self._job:
            self.win.after_cancel(self._job)
            self._job = None
        if not self.visible:
            return
        self._cancel_anim()
        x, y = self._target()
        self._animate(0, x, y, 0)

    def _cancel_anim(self) -> None:
        if self._anim_job:
            try:
                self.win.after_cancel(self._anim_job)
            except Exception:  # noqa: BLE001
                pass
            self._anim_job = None

    def _animate(self, direction: int, x: int, y: int, step: int) -> None:
        step += 1
        t = min(1.0, step / self.FRAMES)
        eased = 1 - (1 - t) ** 3 if direction else t * t
        alpha = eased if direction else 1 - eased
        offset = int(self.SLIDE * (1 - eased)) if direction else int(self.SLIDE * eased)
        try:
            self.win.attributes("-alpha", max(0.0, min(1.0, alpha)))
            self.win.geometry(f"+{x}+{y + offset}")
        except tk.TclError:
            return
        if step < self.FRAMES:
            self._anim_job = self.win.after(self.FRAME_MS, lambda: self._animate(direction, x, y, step))
        else:
            self._anim_job = None
            if not direction:
                self.win.withdraw()
                self.win.attributes("-alpha", 1.0)

    def _maybe_hide(self, _event=None) -> None:
        if self._hide_job:
            self.win.after_cancel(self._hide_job)
        self._hide_job = self.win.after(260, self._hide_if_outside)

    def _hide_if_outside(self) -> None:
        self._hide_job = None
        if not self.visible:
            return
        px, py = self.win.winfo_pointerxy()
        try:
            widget = self.win.winfo_containing(px, py)
        except (KeyError, tk.TclError):
            widget = None
        if widget is None:
            self.hide()

    def _on_escape(self, _event=None) -> None:
        if self.view == "settings":
            self._goto_main()
        else:
            self.hide()

    # ---------- 交互 ----------
    def _on_click(self, event) -> None:
        for x1, y1, x2, y2, cb in reversed(self._hot):
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                try:
                    cb()
                except Exception:  # noqa: BLE001
                    pass
                return

    def _on_motion(self, event) -> None:
        idx = -1
        if self.view == "main":
            for i in range(len(DEVICES)):
                y0 = self.TOP + i * (self.CARD_H + self.GAP)
                if y0 <= event.y <= y0 + self.CARD_H:
                    idx = i
                    break
        clickable = any(x1 <= event.x <= x2 and y1 <= event.y <= y2
                        for x1, y1, x2, y2, _ in self._hot)
        self.canvas.configure(cursor="hand2" if clickable else "arrow")
        if idx != self._hover:
            self._hover = idx
            self._draw()

    def _schedule_refresh(self) -> None:
        if self._job:
            self.win.after_cancel(self._job)
        if not self.visible:
            return
        self._draw()
        self._job = self.win.after(2500, self._schedule_refresh)

    def _hit(self, x1, y1, x2, y2, cb) -> None:
        self._hot.append((x1, y1, x2, y2, cb))

    # ---------- 绘制入口 ----------
    def _draw(self) -> None:
        p = self.pal
        self._hot = []
        img = Image.new("RGB", (self.W * SS, self.H * SS), p.bg)
        pen = Pen(img, ImageDraw.Draw(img), p)
        pen.rr(0.5, 0.5, self.W - 0.5, self.H - 0.5, 8, fill=p.bg, outline=p.border)

        if self.view == "settings":
            self._draw_settings(pen)
        else:
            self._draw_main(pen)

        self._img = img
        self._photo = ImageTk.PhotoImage(img.resize((self.W, self.H), Image.LANCZOS))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

    # ---------- 主页 ----------
    def _draw_main(self, pen: Pen) -> None:
        p = self.pal
        readings = self.service.snapshot()
        online = sum(1 for r in readings if r.status == "ok")
        charging = sum(1 for r in readings if r.status == "ok" and r.charging)

        pen.text(16, 13, "设备电量", 14, p.text, bold=True)
        head = (f"{len(readings)} 台已连接" if online == len(readings)
                else f"{online}/{len(readings)} 台在线")
        if charging:
            head += f" · {charging} 台充电中"
        stamp = time.strftime("%H:%M", time.localtime(self.service.last_update or time.time()))
        pen.text(16, 32, f"{head} · {stamp} 更新", 11, p.sub)

        gx, gy = self.W - 14 - 26, 12
        pen.rr(gx, gy, gx + 26, gy + 26, 8, fill=p.chip)
        pen.glyph("gear", p.sub, gx + 13, gy + 13, 14, 2.0)
        self._hit(gx - 2, gy - 2, gx + 28, gy + 28, self._goto_settings)

        for idx, r in enumerate(readings):
            self._draw_card(pen, idx, r)
        self._draw_footer(pen)

    def _draw_card(self, pen: Pen, idx: int, r) -> None:
        p = self.pal
        x1, x2 = self.PAD, self.W - self.PAD
        y0 = self.TOP + idx * (self.CARD_H + self.GAP)
        y1 = y0 + self.CARD_H
        hovered = idx == self._hover
        is_ok = r.status == "ok" and r.percent is not None
        lit = bool(is_ok and r.charging)

        pen.rr(x1, y0, x2, y1, 11, fill=p.card_hover if hovered else p.card,
               outline=p.info if lit else p.border)

        fg, chip_bg = device_tint(r.key, p)
        if r.status == "offline":
            fg = p.faint
        cx, cy = x1 + 41, y0 + self.CARD_H / 2
        pen.rr(cx - 27, cy - 27, cx + 27, cy + 27, 27, fill=chip_bg)
        if is_ok:
            pct = max(0, min(100, int(r.percent)))
            color = p.ok if pct >= 60 else (p.warn if pct >= 30 else p.bad)
            pen.ring(cx, cy, 24, 4, pct / 100, color, mix_hex(color, chip_bg, 0.78))
        else:
            pen.ring(cx, cy, 24, 4, 0, p.track, p.chip)
        pen.glyph(GLYPH.get(r.key, "keyboard"), fg, cx, cy, 21, 1.9)

        # 文字列
        tx = x1 + 80
        pen.text(tx, y0 + 17, r.name, 12, p.text if r.status != "offline" else p.sub,
                 anchor="lm", bold=True)
        pen.text(tx, y0 + 40, self._meta(r), 11,
                 p.info_text if lit else p.sub, anchor="lm")

        # 右侧：百分比 / 状态胶囊
        xr = x2 - 14
        if is_ok:
            pct = max(0, min(100, int(r.percent)))
            color = p.ok_text if pct >= 60 else (p.warn_text if pct >= 30 else p.bad_text)
            sig_w = pen.width("%", 11, True)
            pen.text(xr, y0 + 48, "%", 11, color, anchor="rs", bold=True)
            num = str(pct)
            pen.text(xr - sig_w - 1, y0 + 48, num, 24, color, anchor="rs", bold=True)
            if r.charging:
                num_w = pen.width(num, 24, True)
                pen.glyph("bolt", p.info_text, xr - sig_w - num_w - 10, y0 + 36, 12, 1.6)
        else:
            label = {"sleep": "休眠", "offline": "离线", "pending": "待探测"}.get(r.status, "读取失败")
            w = max(46, pen.width(label, 11) + 20)
            pen.rr(xr - w, y0 + 28, xr, y0 + 50, 11, fill=p.chip)
            pen.text(xr - w / 2, y0 + 39, label, 11, p.faint, anchor="mm")

        self._hit(x1, y0, x2, y1, lambda k=r.key: self._refresh_one(k))

    def _meta(self, r) -> str:
        """状态词由右侧胶囊表达，这里补「设备类型 + 状态 + 距上次充电几天」。"""
        kind = KIND.get(r.key, "")
        parts = [kind]
        if r.status == "ok":
            parts.append("正在充电" if r.charging else "使用电池")
            # 正在充电时「今天充过」没有信息量，省掉
            if not r.charging:
                parts.append(r.charge_note)
        elif r.percent is not None:
            parts.append(f"上次 {r.percent}%")
            parts.append(r.charge_note)
        else:
            parts.append(r.charge_note)
        return " · ".join(x for x in parts if x)

    def _draw_footer(self, pen: Pen) -> None:
        p = self.pal
        y = 318
        pen.line(self.PAD, y, self.W - self.PAD, y, p.divider)
        on = bool(self.cfg.get("low_battery_alert", True))
        th = int(self.cfg.get("low_battery_threshold", 20))
        color = p.sub if on else p.faint
        pen.glyph("bell", color, self.PAD + 7, y + 21, 12, 1.6)
        pen.text(self.PAD + 17, y + 21, f"低电提醒 {th}%" if on else "低电提醒已关闭",
                 11, color, anchor="lm")

        self._hit(self.W - self.PAD - 62, y + 6, self.W - self.PAD, y + 36, self._refresh_all)
        pen.text(self.W - self.PAD, y + 21, "立即刷新", 11, p.accent, anchor="rm", bold=True)

    # ---------- 设置页 ----------
    def _draw_settings(self, pen: Pen) -> None:
        p = self.pal
        pen.rr(self.PAD, 12, self.PAD + 26, 38, 8, fill=p.chip)
        pen.glyph("back", p.sub, self.PAD + 13, 25, 13, 2.1)
        self._hit(self.PAD - 2, 10, self.PAD + 30, 40, self._goto_main)
        pen.text(self.PAD + 38, 25, "设置", 14, p.text, anchor="lm", bold=True)

        # 显示
        pen.text(self.PAD + 4, 58, "显示", 11, p.faint, anchor="lm")
        pen.rr(self.PAD, 68, self.W - self.PAD, 146, 11, fill=p.card, outline=p.border)
        pen.text(self.PAD + 16, 87, "任务栏图标", 12, p.text, anchor="lm")
        mode = "multi" if self.cfg.get("display_mode") == "multi" else "single"
        self._seg(pen, self.W - self.PAD - 12, 87, [
            ("单个", mode == "single", lambda: self._set_mode("single")),
            ("三个", mode == "multi", lambda: self._set_mode("multi")),
        ], 42)
        pen.line(self.PAD + 16, 107, self.W - self.PAD - 16, 107, p.divider)
        pen.text(self.PAD + 16, 127, "刷新间隔", 12, p.text, anchor="lm")
        iv = int(self.service.interval)
        self._seg(pen, self.W - self.PAD - 12, 127, [
            ("15 分", iv <= 900, lambda: self._set_interval(900)),
            ("30 分", 900 < iv <= 1800, lambda: self._set_interval(1800)),
            ("60 分", iv > 1800, lambda: self._set_interval(3600)),
        ], 44)

        # 提醒
        pen.text(self.PAD + 4, 161, "提醒", 11, p.faint, anchor="lm")
        pen.rr(self.PAD, 170, self.W - self.PAD, 248, 11, fill=p.card, outline=p.border)
        on = bool(self.cfg.get("low_battery_alert", True))
        pen.text(self.PAD + 16, 183, "低电量通知", 12, p.text, anchor="lm")
        pen.text(self.PAD + 16, 199, "低于阈值时在右下角弹出", 10, p.faint, anchor="lm")
        self._toggle(pen, self.W - self.PAD - 14, 189, on, lambda: self._set_alert(not on))
        pen.line(self.PAD + 16, 209, self.W - self.PAD - 16, 209, p.divider)
        pen.text(self.PAD + 16, 229, "提醒阈值", 12, p.text if on else p.faint, anchor="lm")
        th = int(self.cfg.get("low_battery_threshold", 20))
        cxx = self.W - self.PAD - 12 - 38 * 4 - 6 * 3
        for t in THRESHOLD_CHOICES:
            sel = th == t
            fill, line, fg = self._sel_colors() if sel else (p.chip, p.chip, p.sub)
            pen.rr(cxx, 218, cxx + 38, 240, 7, fill=fill, outline=line)
            pen.text(cxx + 19, 229, f"{t}%", 11, fg, anchor="mm", bold=sel)
            self._hit(cxx, 216, cxx + 38, 242, lambda t=t: self._set_threshold(t))
            cxx += 44

        # 通用
        pen.text(self.PAD + 4, 263, "通用", 11, p.faint, anchor="lm")
        pen.rr(self.PAD, 272, self.W - self.PAD, 368, 11, fill=p.card, outline=p.border)
        auto = bool(self.ctrl and self.ctrl.autostart_enabled())
        pen.text(self.PAD + 16, 288, "开机自动启动", 12, p.text, anchor="lm")
        self._toggle(pen, self.W - self.PAD - 14, 288, auto, self._toggle_autostart)
        pen.line(self.PAD + 16, 304, self.W - self.PAD - 16, 304, p.divider)
        pen.text(self.PAD + 16, 320, "打开数据目录", 12, p.text, anchor="lm")
        pen.glyph("chevron", p.faint, self.W - self.PAD - 18, 320, 12, 2.0)
        self._hit(self.PAD, 304, self.W - self.PAD, 336, self._open_logs)
        pen.line(self.PAD + 16, 336, self.W - self.PAD - 16, 336, p.divider)
        pen.text(self.PAD + 16, 352, "退出程序", 12, p.bad_text, anchor="lm")
        pen.text(self.W - self.PAD - 16, 352, f"BatteryTray v{VERSION}", 10, p.faint, anchor="rm")
        self._hit(self.PAD, 336, self.W - self.PAD, 368, self._quit)

    def _sel_colors(self) -> tuple[str, str, str]:
        return SEL["dark"] if self.pal.dark else SEL["light"]

    def _seg(self, pen: Pen, x_right: float, cy: float, items, w_each: float) -> None:
        p = self.pal
        total = w_each * len(items) + 4
        x1 = x_right - total
        pen.rr(x1, cy - 13, x_right, cy + 13, 8, fill=p.chip)
        for i, (label, selected, cb) in enumerate(items):
            ix1 = x1 + 2 + i * w_each
            if selected:
                pen.rr(ix1, cy - 11, ix1 + w_each, cy + 11, 6, fill=p.card, outline=p.border)
            pen.text(ix1 + w_each / 2, cy + 0.5, label, 11,
                     p.accent if selected else p.sub, anchor="mm", bold=selected)
            self._hit(ix1, cy - 13, ix1 + w_each, cy + 13, cb)

    def _toggle(self, pen: Pen, x_right: float, cy: float, on: bool, cb) -> None:
        p = self.pal
        w, h = 34, 19
        x1 = x_right - w
        pen.rr(x1, cy - h / 2, x_right, cy + h / 2, h / 2,
               fill=p.accent if on else p.toggle_off)
        kx = x_right - 2 - 7.5 if on else x1 + 2 + 7.5
        pen.d.ellipse([(kx - 6.5) * SS, (cy - 6.5) * SS, (kx + 6.5) * SS, (cy + 6.5) * SS],
                      fill="#FFFFFF")
        self._hit(x1 - 4, cy - 12, x_right + 4, cy + 12, cb)

    # ---------- 动作 ----------
    def _goto_settings(self) -> None:
        self.view = "settings"
        self._hover = -1
        self._draw()

    def _goto_main(self) -> None:
        self.view = "main"
        self._draw()

    def _refresh_one(self, key: str) -> None:
        try:
            self.service.refresh_device(key)
        except Exception:  # noqa: BLE001
            pass

    def _refresh_all(self) -> None:
        if self.on_refresh:
            self.on_refresh()

    def _set_mode(self, mode: str) -> None:
        if self.ctrl:
            self.ctrl.set_display_mode(mode)
        self._draw()

    def _set_interval(self, sec: int) -> None:
        if self.ctrl:
            self.ctrl.set_poll_interval(sec)
        self._draw()

    def _set_alert(self, enabled: bool) -> None:
        if self.ctrl:
            self.ctrl.set_alert(enabled)
        self._draw()

    def _set_threshold(self, th: int) -> None:
        if self.ctrl:
            self.ctrl.set_alert(True, th)
        self._draw()

    def _toggle_autostart(self) -> None:
        if self.ctrl:
            self.ctrl.toggle_autostart()
        self._draw()

    def _open_logs(self) -> None:
        if self.ctrl:
            self.ctrl.open_logs()

    def _quit(self) -> None:
        if self.ctrl:
            self.ctrl.quit_app()
