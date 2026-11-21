"""入口：单实例 + DPI + Tk 主循环。"""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk

from . import diag
from .config import load
from .panel import Panel
from .service import BatteryService
from .tray import TrayController

_MUTEX = None


def _acquire_single_instance() -> bool:
    """同名互斥体，防止多开抢设备。"""
    global _MUTEX
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _MUTEX = kernel32.CreateMutexW(None, False, "Local\\BatteryTray_SingleInstance")
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001
        return True


def _enable_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    diag.install()
    if not _acquire_single_instance():
        diag.note("skip: another instance is running")
        return 0

    _enable_dpi()
    cfg = load()

    service = BatteryService(cfg)
    root = tk.Tk()
    root.withdraw()
    root.title("BatteryTray")
    # 再上一道保险：root 本身不留边框、完全透明，避免它被任务栏当成一个应用窗口
    try:
        root.overrideredirect(True)
        root.attributes("-alpha", 0.0)
    except tk.TclError:
        pass

    panel = Panel(root, service, cfg, on_refresh=service.refresh_now)
    tray = TrayController(service, cfg, panel, root)
    panel.attach(tray)
    service.on_update = tray.refresh_visuals

    service.start()
    tray.start()
    diag.note(f"ready: {len(tray._icons)} tray icon(s), mode={tray.mode}")

    try:
        root.mainloop()
    finally:
        diag.note("mainloop returned")
        service.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
