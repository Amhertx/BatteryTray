"""面板交互冒烟测试：用假控制器验证设置页每个控件都真的调到了托盘动作。

不触碰真实设备，只验证「点哪儿 → 调什么」这条链路。
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btray.config import DEFAULTS, DEVICES  # noqa: E402
from btray.model import Reading  # noqa: E402
from btray.panel import Panel  # noqa: E402


class StubService:
    interval = 1800
    last_update = time.time()

    def __init__(self):
        self._r = [
            Reading(key=d["key"], name=d["name"], short=d["short"], percent=p,
                    charging=c, status="ok", updated=time.time() - 600)
            for d, p, c in zip(DEVICES, (49, 100, 85), (False, False, True))
        ]
        self.calls: list[tuple] = []

    def snapshot(self):
        return self._r

    def refresh_now(self):
        self.calls.append(("refresh_all",))

    def refresh_device(self, key):
        self.calls.append(("refresh", key))


class StubCtrl:
    def __init__(self, cfg):
        self.cfg = cfg
        self.calls: list[tuple] = []
        self.auto = False

    def autostart_enabled(self):
        return self.auto

    def set_display_mode(self, mode):
        self.cfg["display_mode"] = mode
        self.calls.append(("mode", mode))

    def set_poll_interval(self, sec):
        self.calls.append(("interval", sec))

    def set_alert(self, enabled, threshold=None):
        self.cfg["low_battery_alert"] = enabled
        if threshold is not None:
            self.cfg["low_battery_threshold"] = threshold
        self.calls.append(("alert", enabled, threshold))

    def toggle_autostart(self):
        self.auto = not self.auto
        self.calls.append(("autostart", self.auto))

    def open_logs(self):
        self.calls.append(("logs",))

    def quit_app(self):
        self.calls.append(("quit",))


class Ev:
    def __init__(self, x, y):
        self.x, self.y = x, y


def click(panel, x, y):
    panel._on_click(Ev(x, y))


def main() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass

    cfg = dict(DEFAULTS)
    cfg.update(display_mode="multi", low_battery_alert=True, low_battery_threshold=20)
    svc, ctrl = StubService(), StubCtrl(cfg)

    root = tk.Tk()
    root.withdraw()
    panel = Panel(root, svc, cfg, on_refresh=svc.refresh_now)
    panel.attach(ctrl)
    panel.show()
    panel.win.attributes("-alpha", 1.0)

    fails: list[str] = []

    def check(name, cond):
        if not cond:
            fails.append(name)
        print(("  ok   " if cond else "  FAIL ") + name)

    # 主界面：点第三张卡片应只刷新狼蛛
    panel._draw()
    click(panel, 180, panel.TOP + 2 * (panel.CARD_H + panel.GAP) + 30)
    check("点卡片只刷新那台设备", ("refresh", "aula_f87") in svc.calls)

    # 齿轮 → 设置页
    click(panel, panel.W - 26, 25)
    check("齿轮进入设置页", panel.view == "settings")

    # 显示方式：单个
    click(panel, panel.W - panel.PAD - 12 - 62, 87)
    check("切换单图标", ("mode", "single") in ctrl.calls)

    # 刷新间隔 15 分
    click(panel, panel.W - panel.PAD - 12 - 3 * 44 + 20, 127)
    check("刷新间隔 15 分", ("interval", 900) in ctrl.calls)

    # 关闭低电通知
    click(panel, panel.W - panel.PAD - 20, 189)
    check("关闭低电通知", ("alert", False, None) in ctrl.calls)

    # 阈值 30%
    click(panel, panel.W - panel.PAD - 12 - 38 // 2, 229)
    check("阈值 30%", ("alert", True, 30) in ctrl.calls)

    # 开机自启
    click(panel, panel.W - panel.PAD - 20, 288)
    check("开机自启开关", ("autostart", True) in ctrl.calls)

    # 打开数据目录
    click(panel, 120, 320)
    check("打开数据目录", ("logs",) in ctrl.calls)

    # 返回
    click(panel, panel.PAD + 10, 25)
    check("返回主界面", panel.view == "main")

    # 底部立即刷新
    click(panel, panel.W - 30, 340)
    check("立即刷新", ("refresh_all",) in svc.calls)

    root.after(200, root.quit)
    root.mainloop()
    print("\n结果：" + ("全部通过" if not fails else f"{len(fails)} 项失败 -> {fails}"))


if __name__ == "__main__":
    main()
