"""充电动画冒烟测试：验证相位推进、只重画充电中的设备、图标像素确实在变。

不创建真实托盘图标（pystray 那层在测试里没意义），用假 icon 记录被赋值的图像。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btray.config import DEVICES, DEFAULTS  # noqa: E402
from btray.model import Reading  # noqa: E402
from btray.tray import TrayController  # noqa: E402


class StubService:
    def __init__(self):
        self._r = [
            Reading(key="sony_h9", name="索尼", percent=49, charging=False, status="ok", short="H9"),
            Reading(key="razer_dav3", name="雷蛇", percent=100, charging=False, status="ok", short="DA"),
            Reading(key="aula_f87", name="狼蛛", percent=85, charging=True, status="ok", short="F8"),
        ]

    def snapshot(self):
        return self._r


class StubRoot:
    def after(self, _ms, _fn):
        return "job"

    def after_cancel(self, _job):
        pass


class StubIcon:
    def __init__(self):
        self.frames = []

    @property
    def icon(self):
        return None

    @icon.setter
    def icon(self, img):
        self.frames.append(img)


def main() -> int:
    ctrl = TrayController(StubService(), dict(DEFAULTS), panel=None, root=StubRoot())
    ctrl._icons = [StubIcon(), StubIcon(), StubIcon()]

    ctrl._paint_charging()
    time.sleep(1.0)
    ctrl._paint_charging()

    ok = True
    for i, (dev, icon) in enumerate(zip(DEVICES, ctrl._icons)):
        n = len(icon.frames)
        if dev["key"] == "aula_f87":
            same = n == 2 and icon.frames[0].tobytes() != icon.frames[1].tobytes()
            print(f"{dev['key']}: frames={n} 两帧不同={same}")
            ok &= same
        else:
            print(f"{dev['key']}: frames={n} 未被重画={n == 0}")
            ok &= n == 0

    p1 = ctrl._phase()
    time.sleep(0.6)
    p2 = ctrl._phase()
    print(f"phase {p1:.2f} -> {p2:.2f} 推进={p2 != p1}")
    ok &= p2 != p1
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
