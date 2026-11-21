"""托盘控制器：单图标 / 多图标两种模式 + 右键菜单。"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk

import pystray
from pystray import Menu, MenuItem as Item

from .config import (ALERT_HYSTERESIS, APP_DIR, APP_NAME, DEVICES, THRESHOLD_CHOICES,
                     save)
from .icons import battery_icon, device_icon

AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _autostart_command() -> str:
    if getattr(sys, "frozen", False):  # 打包成 exe 后直接指向自身
        return f'"{sys.executable}"'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    entry = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run.pyw")
    return f'"{pyw}" "{entry}"'


def is_autostart() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except OSError:
                pass


class TrayController:
    def __init__(self, service, cfg: dict, panel, root: tk.Tk):
        self.service = service
        self.cfg = cfg
        self.panel = panel
        self.root = root
        self._icons: list[pystray.Icon] = []
        self._lock = threading.Lock()
        self._pending_refresh = False
        self._alerted: dict[str, bool] = {}

    # ---------- 生命周期 ----------
    def start(self) -> None:
        self._build()

    def _build(self) -> None:
        self._stop_icons()
        if self.mode == "multi":
            for dev in DEVICES:
                self._spawn(dev["key"])
        else:
            self._spawn(None)

    def _spawn(self, key: str | None) -> None:
        name = f"{APP_NAME}-{key}" if key else APP_NAME
        icon = pystray.Icon(
            name,
            icon=self._image(key),
            title=self._tooltip(key),
            menu=self._menu(key),
        )
        self._icons.append(icon)
        threading.Thread(target=icon.run, name=f"tray-{name}", daemon=True).start()

    def _stop_icons(self) -> None:
        with self._lock:
            icons, self._icons = self._icons, []
        for icon in icons:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass

    # ---------- 状态 ----------
    @property
    def mode(self) -> str:
        mode = self.cfg.get("display_mode", "single")
        return "multi" if mode == "multi" else "single"

    @property
    def alert_enabled(self) -> bool:
        return bool(self.cfg.get("low_battery_alert", True))

    @property
    def threshold(self) -> int:
        return int(self.cfg.get("low_battery_threshold", 20))

    def _readings(self) -> dict:
        return {r.key: r for r in self.service.snapshot()}

    def _worst(self, readings: dict):
        ok = [r for r in readings.values() if r.status == "ok" and r.percent is not None]
        return min(ok, key=lambda r: r.percent) if ok else None

    def _image(self, key: str | None):
        readings = self._readings()
        if key:
            r = readings.get(key)
            if r is None:
                return device_icon(key, None, "offline")
            return device_icon(key, r.percent if r.status == "ok" else None, r.status,
                               bool(r.charging))
        worst = self._worst(readings)
        if worst is None:
            return battery_icon(None, "pending")
        return battery_icon(worst.percent, worst.status, bool(worst.charging))

    def _tooltip(self, key: str | None) -> str:
        readings = self._readings()
        if key:
            r = readings.get(key)
            return r.one_line() if r else "未知设备"
        return "\n".join(r.one_line() for r in readings.values())

    def _menu(self, key: str | None) -> Menu:
        threshold_items = [
            Item(f"{t}%", self._act(lambda t=t: self._set_alert(True, t)),
                 checked=(lambda _i, t=t: self.alert_enabled and self.threshold == t),
                 radio=True)
            for t in THRESHOLD_CHOICES
        ]
        return Menu(
            Item("打开面板", self._act(self._open_panel), default=True),
            Item("立即刷新", self._act(self._refresh)),
            Menu.SEPARATOR,
            Item("显示方式", Menu(
                Item("单图标（全部设备）", self._act(lambda: self._set_mode("single")),
                     checked=lambda _i: self.mode == "single", radio=True),
                Item("三个独立图标", self._act(lambda: self._set_mode("multi")),
                     checked=lambda _i: self.mode == "multi", radio=True),
            )),
            Item("低电量提醒", Menu(
                Item("关闭", self._act(lambda: self._set_alert(False)),
                     checked=lambda _i: not self.alert_enabled, radio=True),
                *threshold_items,
            )),
            Item("开机自启", self._act(self._toggle_autostart),
                 checked=lambda _i: is_autostart()),
            Menu.SEPARATOR,
            Item("打开日志目录", self._act(self._open_logs)),
            Item("退出", self._act(self._quit)),
        )

    # ---------- 动作（pystray 线程 → 交给 Tk 主线程） ----------
    @staticmethod
    def _act(fn):
        def wrapper(icon=None, item=None):
            fn()
        return wrapper

    def _on_ui(self, fn) -> None:
        try:
            self.root.after(0, fn)
        except Exception:  # noqa: BLE001
            pass

    def _open_panel(self) -> None:
        self._on_ui(self.panel.toggle)

    def _refresh(self) -> None:
        self.service.refresh_now()

    def _set_mode(self, mode: str) -> None:
        if self.cfg.get("display_mode") == mode:
            return
        self.cfg["display_mode"] = mode
        save(self.cfg)
        self._stop_icons()
        threading.Timer(0.3, self._build).start()

    def _set_alert(self, enabled: bool, threshold: int | None = None) -> None:
        self.cfg["low_battery_alert"] = enabled
        if threshold is not None:
            self.cfg["low_battery_threshold"] = threshold
        save(self.cfg)
        self._alerted.clear()   # 改设置后重新评估，别把新阈值挡住
        for icon in self._icons:
            try:
                icon.update_menu()
            except Exception:  # noqa: BLE001
                pass

    def _toggle_autostart(self) -> None:
        try:
            set_autostart(not is_autostart())
        except Exception:  # noqa: BLE001
            pass
        for icon in self._icons:
            try:
                icon.update_menu()
            except Exception:  # noqa: BLE001
                pass

    def _open_logs(self) -> None:
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["explorer", str(APP_DIR)])
        except Exception:  # noqa: BLE001
            pass

    def _quit(self) -> None:
        self._stop_icons()
        self.service.stop()
        self._on_ui(self.root.quit)

    # ---------- 低电量提醒 ----------
    def _notify(self, title: str, message: str) -> None:
        """走托盘图标的系统通知通道，即 Windows 右下角的标准弹窗。"""
        for icon in list(self._icons):
            try:
                icon.notify(message, title)
                return
            except Exception:  # noqa: BLE001
                continue

    def _check_low_battery(self, readings) -> None:
        if not self.alert_enabled:
            return
        th = self.threshold
        for r in readings:
            if r.status != "ok" or r.percent is None:
                self._alerted.pop(r.key, None)
                continue
            if r.charging:
                # 插上电就重新武装，避免拔掉后不提醒
                self._alerted.pop(r.key, None)
                continue
            if r.percent <= th:
                if not self._alerted.get(r.key):
                    self._alerted[r.key] = True
                    self._notify(f"{r.name} 电量偏低",
                                 f"剩余 {r.percent}%，建议尽快充电。")
            elif r.percent > th + ALERT_HYSTERESIS:
                # 回升到阈值以上一定幅度才重新武装，防止在临界点反复弹
                self._alerted.pop(r.key, None)

    # ---------- 供面板调用 ----------
    def autostart_enabled(self) -> bool:
        try:
            return is_autostart()
        except Exception:  # noqa: BLE001
            return False

    def set_display_mode(self, mode: str) -> None:
        self._set_mode(mode)

    def set_alert(self, enabled: bool, threshold: int | None = None) -> None:
        self._set_alert(enabled, threshold)

    def set_poll_interval(self, seconds: int) -> None:
        self.service.set_interval(seconds)
        save(self.cfg)

    def toggle_autostart(self) -> None:
        self._toggle_autostart()

    def open_logs(self) -> None:
        self._open_logs()

    def quit_app(self) -> None:
        self._quit()

    # ---------- 视觉刷新 ----------
    def refresh_visuals(self) -> None:
        if self._pending_refresh:
            return
        self._pending_refresh = True
        self._on_ui(self._do_refresh)

    def _do_refresh(self) -> None:
        self._pending_refresh = False
        if self.mode == "multi":
            keys = [d["key"] for d in DEVICES]
        else:
            keys = [None]
        for key, icon in zip(keys, self._icons):
            try:
                icon.icon = self._image(key)
                icon.title = self._tooltip(key)
                icon.update_menu()
            except Exception:  # noqa: BLE001
                pass
        self._check_low_battery(self.service.snapshot())
