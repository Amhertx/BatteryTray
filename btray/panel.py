"""托盘弹出面板（Tkinter）。

- 现代圆角：Win11 走 DWM 原生圆角（带抗锯齿）；旧系统自动回退直角
- 弹出动画：从下方 10px 处向上滑入 + 透明度渐显（ease-out），关闭时反向渐隐
"""
from __future__ import annotations

import ctypes
import time
import tkinter as tk

from .icons import level_color

BG = "#FFFFFF"
FG = "#111827"
SUB = "#6B7280"
TRACK = "#EDEFF2"

FONT = "Microsoft YaHei UI"

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

# 让窗口不进任务栏、不进 Alt+Tab（TOOLWINDOW），并去掉强制显示在任务栏的标记
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000


def hide_from_taskbar(win: tk.Misc, force: bool = False) -> None:
    """把 Tk 窗口标记为工具窗口：任务栏和 Alt+Tab 都不会再多出一个条目。

    force=True 时（窗口已映射后）额外做一次 hide/show，逼任务栏重新评估归属，
    否则只改 exstyle 任务栏不一定立刻生效。
    """
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
            SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
            user32.ShowWindow(hwnd, SW_HIDE)
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    except Exception:  # noqa: BLE001
        pass


def _rr(canvas, x1, y1, x2, y2, r, **kw):
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


def _rgb(color):
    return "#%02X%02X%02X" % color


def _interval_text(sec: int) -> str:
    if sec >= 3600 and sec % 3600 == 0:
        return f"{sec // 3600} 小时"
    if sec >= 60:
        return f"{sec // 60} 分钟"
    return f"{sec} 秒"


class Panel:
    W, H = 310, 234
    ROW_H = 52
    TOP = 50
    SLIDE = 10
    FRAMES = 9
    FRAME_MS = 13

    def __init__(self, root: tk.Tk, service, cfg: dict, on_refresh=None):
        self.root = root
        self.service = service
        self.cfg = cfg
        self.on_refresh = on_refresh
        self._job = None
        self._anim_job = None
        self._hide_job = None

        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BG)

        self.canvas = tk.Canvas(self.win, width=self.W, height=self.H, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_click)

        self.win.bind("<Escape>", lambda _e: self.hide())
        self.win.bind("<FocusOut>", self._maybe_hide)

        # 关键：面板是 overrideredirect 弹出窗，默认会被任务栏当成一个应用窗口，
        # 于是单击托盘就多出一个任务栏图标。这里连同 root 一起标成工具窗口。
        hide_from_taskbar(self.win)
        hide_from_taskbar(root)

    # ---------- 圆角 ----------
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
        return sw - self.W - 12, sh - self.H - 60

    def show(self) -> None:
        self._cancel_anim()
        if self._hide_job:
            self.win.after_cancel(self._hide_job)
            self._hide_job = None

        x, y = self._target()
        self._draw()
        self.win.attributes("-alpha", 0.0)
        self.win.geometry(f"{self.W}x{self.H}+{x}+{y + self.SLIDE}")
        self.win.deiconify()
        # 必须在映射之后打标记：overrideredirect 的顶层窗口在首次显示前层级未定型
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

    def _on_click(self, event) -> None:
        if event.y > self.H - 30 and event.x > self.W - 70:
            if self.on_refresh:
                self.on_refresh()

    def _schedule_refresh(self) -> None:
        if self._job:
            self.win.after_cancel(self._job)
        if not self.visible:
            return
        self._draw()
        self._job = self.win.after(3000, self._schedule_refresh)

    # ---------- 绘制 ----------
    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        readings = self.service.snapshot()

        c.create_text(16, 24, text="设备电量", anchor="w", fill=FG, font=(FONT, 11, "bold"))
        stamp = time.strftime("%H:%M:%S", time.localtime(self.service.last_update or time.time()))
        c.create_text(self.W - 16, 25, text=f"{stamp} 更新", anchor="e", fill=SUB, font=(FONT, 8))

        for idx, r in enumerate(readings):
            y0 = self.TOP + idx * self.ROW_H
            color = _rgb(level_color(r.percent, r.status))

            c.create_text(16, y0 + 6, text=r.name, anchor="w",
                          fill=FG if r.online else SUB, font=(FONT, 9))
            c.create_text(self.W - 16, y0 + 6, text=r.label, anchor="e",
                          fill=color if r.status == "ok" else SUB, font=(FONT, 9, "bold"))

            if r.status == "ok":
                hint = "充电中" if r.charging else ""
                if not r.verified:
                    hint = (hint + " · 字段待验证").strip(" ·")
            else:
                hint = r.detail or ""
                if r.percent is not None:
                    hint = f"{hint} · 上次 {r.percent}%" if hint else f"上次 {r.percent}%"
            if hint:
                c.create_text(16, y0 + 22, text=hint, anchor="w", fill=SUB, font=(FONT, 7))

            bar_y = y0 + 34
            _rr(c, 16, bar_y, self.W - 16, bar_y + 6, 3, fill=TRACK, outline=TRACK)
            if r.percent is not None and r.status == "ok":
                width = max(6, int((self.W - 32) * min(100, max(0, r.percent)) / 100))
                _rr(c, 16, bar_y, 16 + width, bar_y + 6, 3, fill=color, outline=color)

        c.create_line(16, self.H - 34, self.W - 16, self.H - 34, fill=TRACK)
        alert = "低电提醒关" if not self.cfg.get("low_battery_alert", True) \
            else f"低电 {int(self.cfg.get('low_battery_threshold', 20))}%"
        c.create_text(16, self.H - 17, anchor="w", fill=SUB, font=(FONT, 7),
                      text=f"每 {_interval_text(self.service.interval)}刷新 · {alert} · Esc 关闭")
        c.create_text(self.W - 16, self.H - 17, anchor="e", fill="#2563EB", font=(FONT, 7), text="刷新")
