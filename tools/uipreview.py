"""UI 本地预览：用假数据渲染面板，输出明暗两套主题的首页/设置页截图。

不碰真设备（StubService 只返回构造好的 Reading），用于检查排版和对齐。
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from btray.config import DEVICES, DEFAULTS  # noqa: E402
from btray.model import Reading  # noqa: E402
from btray.panel import Panel  # noqa: E402
from btray import theme  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "preview")


class StubService:
    interval = 1800
    last_update = time.time()

    def __init__(self):
        self._r = [
            Reading(key="sony_h9", name=DEVICES[0]["name"], short="H9", percent=49,
                    charging=False, status="ok", updated=time.time() - 7200, charged_days=12),
            Reading(key="razer_dav3", name=DEVICES[1]["name"], short="DA", percent=100,
                    charging=False, status="ok", updated=time.time() - 7200, charged_days=3),
            Reading(key="aula_f87", name=DEVICES[2]["name"], short="F8", percent=85,
                    charging=True, status="ok", updated=time.time() - 120, charged_days=0),
        ]

    def snapshot(self):
        return self._r

    def refresh_now(self):
        pass

    def refresh_device(self, key):
        pass


def main() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    os.makedirs(OUT, exist_ok=True)

    cfg = dict(DEFAULTS)
    cfg.update(display_mode="multi", low_battery_alert=True, low_battery_threshold=20)

    root = tk.Tk()
    root.withdraw()
    panel = Panel(root, StubService(), cfg)
    panel.show()
    panel.win.attributes("-alpha", 1.0)
    panel.win.geometry(f"{panel.W}x{panel.H}+{panel._target()[0]}+{panel._target()[1]}")

    def shot(name: str) -> None:
        panel.win.update()
        panel._draw()
        # 直接存 2 倍渲染位图，避免抓屏受窗口位置 / DPI 影响
        panel._img.save(os.path.join(OUT, name))

    steps = [
        lambda: (setattr(panel, "pal", theme.LIGHT), setattr(panel, "view", "main"),
                 panel._draw(), shot("light_main.png")),
        lambda: (setattr(panel, "pal", theme.DARK), panel._draw(), shot("dark_main.png")),
        lambda: (setattr(panel, "pal", theme.LIGHT), setattr(panel, "view", "settings"),
                 panel._draw(), shot("light_settings.png")),
        lambda: (setattr(panel, "pal", theme.DARK), panel._draw(), shot("dark_settings.png")),
        root.quit,
    ]

    def run(i: int = 0) -> None:
        if i >= len(steps):
            return
        steps[i]()
        root.after(260, lambda: run(i + 1))

    root.after(500, run)
    root.mainloop()


if __name__ == "__main__":
    main()
