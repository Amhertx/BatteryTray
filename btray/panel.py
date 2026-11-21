"""托盘弹出面板（Tkinter 绘制）。

v1.1 设计稿：
- 360×372 圆角浮层，一台设备一张卡片（色块图形 + 名称 + 状态 + 大号百分比 + 电量条）
- 右上齿轮进入「设置」页，显示/提醒/通用三组，不必再翻右键菜单
- 跟随系统深浅色（读 AppsUseLightTheme）
- 弹出：下方 10px 上滑 + 渐显；关闭反向渐隐
- 点某张卡片只刷新那台设备
"""
from __future__ import annotations

import ctypes
import time
import tkinter as tk

from .config import DEVICES, THRESHOLD_CHOICES, VERSION
from .glyphs import ui_icon
from .icons import GLYPH
from .theme import Palette, current as current_palette, device_tint

FONT = "Microsoft YaHei UI"

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

# 选中态胶囊的等效色（浅色 / 深色）
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


def _ago(ts: float) -> str:
    if not ts:
        return ""
    delta = max(0, int(time.time() - ts))
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{delta // 60} 分钟前"
    if delta < 86400:
        return f"{delta // 3600} 小时前"
    return f"{delta // 86400} 天前"


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
        self._imgs: list = []
        self._hover = -1
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

    # ---------- 基础绘制 ----------
    def _round(self, x1, y1, x2, y2, r, fill, outline="", width=1):
        """精确圆角矩形：Tk 没有原生圆角，smooth-polygon 的拐角会塌成斜角，
        这里用「两块矩形 + 四个圆」填充，再用「四段圆弧 + 四条直边」描边。
        圆角半径可以等于高度一半，因此开关胶囊也是同一个函数画的。"""
        c = self.canvas
        r = max(1, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        d = 2 * r
        if fill:
            c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")
            c.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline="")
            for bx, by in ((x1, y1), (x2 - d, y1), (x1, y2 - d), (x2 - d, y2 - d)):
                c.create_oval(bx, by, bx + d, by + d, fill=fill, outline="")
        if outline:
            for bx, by, start in ((x1, y1, 90), (x2 - d, y1, 0),
                                  (x1, y2 - d, 180), (x2 - d, y2 - d, 270)):
                c.create_arc(bx, by, bx + d, by + d, start=start, extent=90,
                             style="arc", outline=outline, width=width)
            c.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=width)
            c.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=width)
            c.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=width)
            c.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=width)

    def _text(self, x, y, s, size, color, anchor="w", bold=False):
        font = (FONT, size, "bold") if bold else (FONT, size)
        return self.canvas.create_text(x, y, text=s, anchor=anchor, fill=color, font=font)

    def _icon(self, kind, color, x, y, size=19):
        photo = ui_icon(kind, color, size)
        self._imgs.append(photo)
        self.canvas.create_image(x, y, image=photo, anchor="center")

    def _hit(self, x1, y1, x2, y2, cb) -> None:
        self._hot.append((x1, y1, x2, y2, cb))

    # ---------- 绘制入口 ----------
    def _draw(self) -> None:
        self.canvas.delete("all")
        self._imgs = []
        self._hot = []
        p = self.pal
        self._round(0.5, 0.5, self.W - 0.5, self.H - 0.5, 12, p.bg, p.border)
        if self.view == "settings":
            self._draw_settings()
        else:
            self._draw_main()

    # ---------- 主页 ----------
    def _draw_main(self) -> None:
        p = self.pal
        readings = self.service.snapshot()
        online = sum(1 for r in readings if r.status == "ok")
        charging = sum(1 for r in readings if r.status == "ok" and r.charging)

        self._text(16, 15, "设备电量", 10, p.text, anchor="nw", bold=True)
        if online == len(readings):
            head = f"{len(readings)} 台已连接"
        else:
            head = f"{online}/{len(readings)} 台在线"
        if charging:
            head += f" · {charging} 台充电中"
        stamp = time.strftime("%H:%M", time.localtime(self.service.last_update or time.time()))
        self._text(16, 36, f"{head} · {stamp} 更新", 8, p.sub, anchor="nw")

        # 齿轮
        gx1, gy1 = self.W - 14 - 26, 12
        self._round(gx1, gy1, gx1 + 26, gy1 + 26, 8, p.chip)
        self._icon("gear", p.sub, gx1 + 13, gy1 + 13, 14)
        self._hit(gx1 - 2, gy1 - 2, gx1 + 28, gy1 + 28, self._goto_settings)

        for idx, r in enumerate(readings):
            self._draw_card(idx, r)
        self._draw_footer()

    def _draw_card(self, idx: int, r) -> None:
        p = self.pal
        x1, x2 = self.PAD, self.W - self.PAD
        y0 = self.TOP + idx * (self.CARD_H + self.GAP)
        y1 = y0 + self.CARD_H
        hovered = idx == self._hover
        is_ok = r.status == "ok" and r.percent is not None
        lit = is_ok and bool(r.charging)

        self._round(x1, y0, x2, y1, 11, p.card_hover if hovered else p.card,
                    p.info if lit else p.border)

        fg, chip_bg = device_tint(r.key, p)
        if r.status == "offline":
            fg = p.faint
        cxx, cyy = x1 + 12, y0 + 11
        self._round(cxx, cyy, cxx + 38, cyy + 38, 11, chip_bg)
        self._icon(GLYPH.get(r.key, "keyboard"), fg, cxx + 19, cyy + 19, 19)

        self._text(x1 + 60, y0 + 13, r.name, 9, p.text if r.status != "offline" else p.sub,
                   anchor="nw", bold=True)
        self._text(x1 + 60, y0 + 34, self._meta(r), 8,
                   p.info_text if lit else p.sub, anchor="nw")

        xr = x2 - 14
        if is_ok:
            pct = max(0, min(100, int(r.percent)))
            color = p.ok_text if pct >= 60 else (p.warn_text if pct >= 30 else p.bad_text)
            item = self._text(xr - 10, y0 + 12, str(pct), 14, color, anchor="ne", bold=True)
            self._text(xr, y0 + 17, "%", 8, color, anchor="ne")
            if r.charging:
                bb = self.canvas.bbox(item)
                if bb:
                    self._icon("bolt", p.info_text, bb[0] - 8, (bb[1] + bb[3]) / 2, 12)
        else:
            label = {"sleep": "休眠", "offline": "离线", "pending": "待探测"}.get(r.status, "读取失败")
            self._round(xr - 46, y0 + 14, xr, y0 + 34, 7, p.chip)
            self._text(xr - 23, y0 + 24, label, 8, p.faint, anchor="center")

        bx1, bx2, by = x1 + 60, xr - 2, y0 + 58
        self._round(bx1, by, bx2, by + 4, 2, p.track)
        if is_ok:
            ratio = max(0, min(100, int(r.percent))) / 100
            w = max(8, int((bx2 - bx1) * ratio))
            color = p.ok if r.percent >= 60 else (p.warn if r.percent >= 30 else p.bad)
            self._round(bx1, by, bx1 + w, by + 4, 2, color)

        self._hit(x1, y0, x2, y1, lambda k=r.key: self._refresh_one(k))

    def _meta(self, r) -> str:
        """状态词已经由右侧胶囊表达，这里只补「设备类型 + 时间/上次读数」。"""
        kind = KIND.get(r.key, "")
        if r.status == "ok":
            tail = f"正在充电 · {_ago(r.updated)}" if r.charging else _ago(r.updated)
        else:
            tail = f"上次 {r.percent}%" if r.percent is not None else "暂无读数"
        return " · ".join(x for x in (kind, tail) if x)

    def _draw_footer(self) -> None:
        p = self.pal
        y = 318
        self.canvas.create_line(self.PAD, y, self.W - self.PAD, y, fill=p.divider)
        on = bool(self.cfg.get("low_battery_alert", True))
        th = int(self.cfg.get("low_battery_threshold", 20))
        color = p.sub if on else p.faint
        self._icon("bell", color, self.PAD + 7, y + 22, 12)
        self._text(self.PAD + 18, y + 22, f"低电提醒 {th}%" if on else "低电提醒已关闭",
                   8, color, anchor="w")

        bw = 62
        self._hit(self.W - self.PAD - bw, y + 8, self.W - self.PAD, y + 36, self._refresh_all)
        self._text(self.W - self.PAD, y + 22, "立即刷新", 8, p.accent, anchor="e", bold=True)

    # ---------- 设置页 ----------
    def _draw_settings(self) -> None:
        p = self.pal
        self._round(self.PAD, 12, self.PAD + 26, 38, 8, p.chip)
        self._icon("back", p.sub, self.PAD + 13, 25, 13)
        self._hit(self.PAD - 2, 10, self.PAD + 30, 40, self._goto_main)
        self._text(self.PAD + 38, 25, "设置", 10, p.text, anchor="w", bold=True)

        # 显示
        self._text(self.PAD + 4, 58, "显示", 8, p.faint, anchor="w")
        self._round(self.PAD, 68, self.W - self.PAD, 146, 11, p.card, p.border)
        self._text(self.PAD + 16, 87, "任务栏图标", 9, p.text)
        seg_l, seg_r = self.W - self.PAD - 12, self.PAD + 16
        mode = "multi" if self.cfg.get("display_mode") == "multi" else "single"
        self._seg(self.W - self.PAD - 12, 87, [
            ("单个", mode == "single", lambda: self._set_mode("single")),
            ("三个", mode == "multi", lambda: self._set_mode("multi")),
        ], 42)
        self.canvas.create_line(seg_r, 107, seg_l, 107, fill=p.divider)
        self._text(self.PAD + 16, 127, "刷新间隔", 9, p.text)
        iv = int(self.service.interval)
        self._seg(self.W - self.PAD - 12, 127, [
            ("15 分", iv <= 900, lambda: self._set_interval(900)),
            ("30 分", 900 < iv <= 1800, lambda: self._set_interval(1800)),
            ("60 分", iv > 1800, lambda: self._set_interval(3600)),
        ], 44)

        # 提醒
        self._text(self.PAD + 4, 161, "提醒", 8, p.faint, anchor="w")
        self._round(self.PAD, 170, self.W - self.PAD, 248, 11, p.card, p.border)
        on = bool(self.cfg.get("low_battery_alert", True))
        self._text(self.PAD + 16, 182, "低电量通知", 9, p.text)
        self._text(self.PAD + 16, 198, "低于阈值时在右下角弹出", 8, p.faint)
        self._toggle(self.W - self.PAD - 14, 189, on, lambda: self._set_alert(not on))
        self.canvas.create_line(self.PAD + 16, 209, self.W - self.PAD - 16, 209, fill=p.divider)
        self._text(self.PAD + 16, 229, "提醒阈值", 9, p.text if on else p.faint)
        th = int(self.cfg.get("low_battery_threshold", 20))
        cx = self.W - self.PAD - 12 - 38 * 4 - 6 * 3
        for t in THRESHOLD_CHOICES:
            sel = th == t
            fill, line, fg = self._sel_colors() if sel else (p.chip, p.chip, p.sub)
            self._round(cx, 218, cx + 38, 240, 7, fill, line)
            self._text(cx + 19, 229, f"{t}%", 8, fg, anchor="center", bold=sel)
            self._hit(cx, 216, cx + 38, 242, lambda t=t: self._set_threshold(t))
            cx += 44

        # 通用
        self._text(self.PAD + 4, 263, "通用", 8, p.faint, anchor="w")
        self._round(self.PAD, 272, self.W - self.PAD, 368, 11, p.card, p.border)
        auto = bool(self.ctrl and self.ctrl.autostart_enabled())
        self._text(self.PAD + 16, 288, "开机自动启动", 9, p.text)
        self._toggle(self.W - self.PAD - 14, 288, auto, self._toggle_autostart)
        self.canvas.create_line(self.PAD + 16, 304, self.W - self.PAD - 16, 304, fill=p.divider)
        self._text(self.PAD + 16, 320, "打开数据目录", 9, p.text)
        self._icon("chevron", p.faint, self.W - self.PAD - 18, 320, 12)
        self._hit(self.PAD, 304, self.W - self.PAD, 336, self._open_logs)
        self.canvas.create_line(self.PAD + 16, 336, self.W - self.PAD - 16, 336, fill=p.divider)
        self._text(self.PAD + 16, 352, "退出程序", 9, p.bad_text)
        self._text(self.W - self.PAD - 16, 352, f"BatteryTray v{VERSION}", 7, p.faint, anchor="e")
        self._hit(self.PAD, 336, self.W - self.PAD, 368, self._quit)

    def _sel_colors(self) -> tuple[str, str, str]:
        return SEL["dark"] if self.pal.dark else SEL["light"]

    def _seg(self, x_right: float, cy: float, items, w_each: float) -> None:
        p = self.pal
        total = w_each * len(items) + 4
        x1 = x_right - total
        self._round(x1, cy - 13, x_right, cy + 13, 8, p.chip)
        for i, (label, selected, cb) in enumerate(items):
            ix1 = x1 + 2 + i * w_each
            if selected:
                self._round(ix1, cy - 11, ix1 + w_each, cy + 11, 6, p.card, p.border)
            self._text(ix1 + w_each / 2, cy, label, 8,
                       p.accent if selected else p.sub, anchor="center", bold=selected)
            self._hit(ix1, cy - 13, ix1 + w_each, cy + 13, cb)

    def _toggle(self, x_right: float, cy: float, on: bool, cb) -> None:
        p = self.pal
        w, h = 34, 19
        x1 = x_right - w
        self._round(x1, cy - h / 2, x_right, cy + h / 2, h / 2,
                    p.accent if on else p.toggle_off)
        kx = x_right - 2 - 7.5 if on else x1 + 2 + 7.5
        self.canvas.create_oval(kx - 6.5, cy - 6.5, kx + 6.5, cy + 6.5,
                                fill="#FFFFFF", outline="")
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
