"""上次读数缓存 + 多设备低电量通知的自检。

覆盖三件事：
1. 缓存落盘 → 新进程（新实例）能读回来；过期 / 非法记录会被丢掉
2. 服务启动时用缓存顶上，标成「上次读数」而不是实时值
3. 多台同时低电量时，每台都通过各自的托盘图标弹通知；单图标模式并成一条
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btray import service as service_mod  # noqa: E402
from btray.cache import LastSeen  # noqa: E402
from btray.config import DEFAULTS, DEVICES  # noqa: E402
from btray.model import Reading  # noqa: E402
from btray.service import BatteryService  # noqa: E402
from btray.tray import TrayController  # noqa: E402

fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    if not cond:
        fails.append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))


class StubRoot:
    """Tk root 替身：after 立即执行，方便同步断言。"""

    def after(self, _ms, fn, *a):
        fn(*a)
        return "job"

    def after_cancel(self, _job):
        pass


class StubIcon:
    def __init__(self, key):
        self.key = key
        self.sent: list[str] = []

    def notify(self, message, title=None):
        self.sent.append(f"{title}｜{message}")


def test_cache_file() -> None:
    print("\n[1] 缓存落盘与读取")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "last_readings.json")
        a = LastSeen(path)
        now = time.time()
        a.remember("aula_f87", 85, False, now)
        check("写入后可读", a.get("aula_f87")["percent"] == 85)

        b = LastSeen(path)          # 模拟重启：新实例从磁盘读
        got = b.get("aula_f87")
        check("新实例能读回上次电量", got is not None and got["percent"] == 85)
        check("时间戳一并保留", got is not None and abs(got["ts"] - now) < 1)

        # 过期 / 非法数据不进内存
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"sony_h9": {"percent": 49, "ts": 1},'
                     ' "razer_dav3": {"percent": 999, "ts": %d},'
                     ' "x": {"percent": "abc", "ts": %d}}' % (now, now))
        c = LastSeen(path)
        check("30 天前的记录被丢弃", c.get("sony_h9") is None)
        check("越界电量被丢弃", c.get("razer_dav3") is None)
        check("非数字字段被丢弃", c.get("x") is None)

        # 值没变且 10 分钟内不重复落盘（用文件 mtime 判断）
        d = LastSeen(path)
        d.remember("aula_f87", 85, False, now)
        before = os.path.getmtime(path)
        d.remember("aula_f87", 85, False, now + 60)
        check("同值 1 分钟内不重写文件", os.path.getmtime(path) == before)
        d.remember("aula_f87", 60, False, now + 120)
        check("值变化后立刻落盘", LastSeen(path).get("aula_f87")["percent"] == 60)


def test_seed() -> None:
    print("\n[2] 启动时用上次读数顶上")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "last_readings.json")
        store = LastSeen(path)
        ts = time.time() - 3 * 3600
        store.remember("sony_h9", 49, True, ts)      # 关机前在充电

        origin = service_mod.seen
        service_mod.seen = store                    # 只替换服务看到的缓存实例
        try:
            svc = BatteryService(dict(DEFAULTS))
            r = {x.key: x for x in svc.snapshot()}["sony_h9"]
        finally:
            service_mod.seen = origin

        check("电量取自缓存", r.percent == 49, f"percent={r.percent}")
        check("状态是「还没有实时读数」", r.status == "offline", f"status={r.status}")
        check("标记为缓存值", r.is_cached is True)
        check("不沿用旧的充电状态", r.charging is None, f"charging={r.charging}")
        check("能说出多久之前", r.age_text == "3 小时前", f"age={r.age_text!r}")
        check("tooltip 说明是旧值", "读数" in r.one_line(), r.one_line())

        fresh = {x.key: x for x in svc.snapshot()}["razer_dav3"]
        check("没缓存过就不编造数值", fresh.percent is None and not fresh.is_cached)


def test_alert_fanout() -> None:
    print("\n[3] 多台同时低电量的通知")
    cfg = dict(DEFAULTS)
    cfg.update(display_mode="multi", low_battery_alert=True, low_battery_threshold=20)
    ctrl = TrayController(service=None, cfg=cfg, panel=None, root=StubRoot())
    keys = [d["key"] for d in DEVICES]
    ctrl._icons = [StubIcon(k) for k in keys]

    low = [Reading(key=k, name=DEVICES[i]["name"], short=DEVICES[i]["short"],
                   percent=p, charging=False, status="ok", seen_at=time.time())
           for i, (k, p) in enumerate(zip(keys, (10, 12, 15)))]
    ctrl._check_low_battery(low)
    sent = {icon.key: len(icon.sent) for icon in ctrl._icons}
    check("三台各弹一条、走各自的图标", sent == {k: 1 for k in keys}, str(sent))
    check("标题带设备名", "狼蛛" in ctrl._icons[2].sent[0], ctrl._icons[2].sent[0])

    # 再来一轮：同一批设备不该重复骚扰
    ctrl._check_low_battery(low)
    check("同一批不重复弹", sum(len(i.sent) for i in ctrl._icons) == 3)

    # 插上电 → 重新武装
    charged = [Reading(key=k, name="x", short="x", percent=10, charging=True,
                       status="ok", seen_at=time.time()) for k in keys]
    ctrl._check_low_battery(charged)
    ctrl._check_low_battery(low)
    check("拔掉电源后能再提醒", sum(len(i.sent) for i in ctrl._icons) == 6)

    # 单图标模式：只有一个通知通道，多台并成一条
    cfg["display_mode"] = "single"
    ctrl._icons = [StubIcon("single")]
    ctrl._alerted.clear()
    ctrl._check_low_battery(low)
    check("单图标模式只弹一条汇总", len(ctrl._icons[0].sent) == 1,
          ctrl._icons[0].sent[0] if ctrl._icons[0].sent else "")
    check("汇总里三台都列出来",
          all(d["name"] in ctrl._icons[0].sent[0] for d in DEVICES))

    # 缓存值不参与告警（避免关机一晚开机误报）
    cfg["display_mode"] = "multi"
    ctrl._icons = [StubIcon(k) for k in keys]
    ctrl._alerted.clear()
    cached = [Reading(key=k, name="x", short="x", percent=5, status="offline",
                      seen_at=time.time() - 8 * 3600) for k in keys]
    ctrl._check_low_battery(cached)
    check("缓存值不触发低电提醒", sum(len(i.sent) for i in ctrl._icons) == 0)


def main() -> None:
    test_cache_file()
    test_seed()
    test_alert_fanout()
    print("\n结果：" + ("全部通过" if not fails else f"{len(fails)} 项失败 -> {fails}"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
