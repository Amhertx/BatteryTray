"""电量采集服务：后台轮询、失败退避、状态广播。"""
from __future__ import annotations

import threading
import time

from .cache import seen
from .config import DEVICES
from .history import history
from .model import Reading
from .providers import build_providers

# 休眠 / 待探测状态的固定重试间隔（秒）
SLEEP_RETRY = 300


class BatteryService:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._providers = build_providers(cfg)
        self._lock = threading.Lock()
        self._readings: dict[str, Reading] = {
            d["key"]: self._seed(d) for d in DEVICES
        }
        self._fails: dict[str, int] = {d["key"]: 0 for d in DEVICES}
        self._next_due: dict[str, float] = {d["key"]: 0.0 for d in DEVICES}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_update: float = 0.0
        self.on_update = None  # 由 UI 注入

    # ---------- 对外 ----------
    @property
    def interval(self) -> int:
        return max(30, int(self.cfg.get("poll_interval") or 60))

    def snapshot(self) -> list[Reading]:
        with self._lock:
            return [self._readings[d["key"]] for d in DEVICES]

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="battery-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def refresh_now(self) -> None:
        for key in self._next_due:
            self._next_due[key] = 0.0
        self._wake.set()

    def refresh_device(self, key: str) -> None:
        """只让某台设备立刻重读，其余保持原排程。"""
        if key in self._next_due:
            self._next_due[key] = 0.0
        self._wake.set()

    def set_interval(self, seconds: int) -> None:
        """改轮询间隔：已排到更远未来的设备提前到「现在」，立即按新节奏生效。"""
        self.cfg["poll_interval"] = max(30, int(seconds))
        now = time.time()
        for key, due in self._next_due.items():
            if due > now + self.interval:
                self._next_due[key] = now
        self._wake.set()


    # ---------- 内部 ----------
    @staticmethod
    def _seed(dev: dict) -> Reading:
        """启动时的初始读数：有缓存就先用上次读到的电量顶上。

        刚开机键鼠还在休眠、耳机没开机，一条也读不到；显示「上次读数 · N 小时前」
        比一片「离线」有用得多。charging 故意留空 —— 旧值不能当成现在还在充。
        """
        reading = Reading(key=dev["key"], name=dev["name"], short=dev["short"],
                          status="offline", detail="尚未读取",
                          charged_days=history.days_since(dev["key"]))
        cached = seen.get(dev["key"])
        if cached:
            reading.percent = cached["percent"]
            reading.seen_at = cached["ts"]
            reading.detail = "上次读数"
        return reading

    def _next_wait(self) -> float:
        """下一轮唤醒前要等多久：取最近到期设备的剩余时间，上限一个正常间隔。"""
        now = time.time()
        dues = [t - now for t in self._next_due.values() if t > now]
        if not dues:
            return float(self.interval)
        return max(1.0, min(float(self.interval), min(dues)))

    def _loop(self) -> None:
        self.poll_once()
        while not self._stop.is_set():
            self._wake.wait(self._next_wait())
            self._wake.clear()
            if self._stop.is_set():
                break
            self.poll_once()

    def poll_once(self) -> None:
        now = time.time()
        for provider in self._providers:
            key = provider.dev["key"]
            if self._next_due.get(key, 0) > now:
                continue
            try:
                reading = provider.poll()
            except Exception as exc:  # noqa: BLE001
                reading = Reading(
                    key=key,
                    name=provider.dev["name"],
                    short=provider.dev["short"],
                    status="error",
                    detail=str(exc)[:80],
                )

            if reading.status == "ok":
                self._fails[key] = 0
                self._next_due[key] = now + self.interval
            elif reading.status in ("sleep", "pending"):
                # 休眠（键鼠睡着）和待探测（耳机没开机）都是「临时不可读」，
                # 不能按故障做指数退避，否则会卡一小时不更新。固定短间隔重试即可，
                # 这类重试只是开一次共享句柄 + 一条查询帧，开销可忽略。
                self._fails[key] = 0
                self._next_due[key] = now + SLEEP_RETRY
            else:
                self._fails[key] = self._fails.get(key, 0) + 1
                # 真异常才指数退避，最多 3 倍间隔，避免对故障设备反复开句柄
                factor = min(2 ** min(self._fails[key] - 1, 2), 3)
                self._next_due[key] = now + self.interval * factor

            # 顺手记一笔充电日期，用于「N 天前充过」；同一天只落盘一次
            if reading.status == "ok" and reading.charging:
                history.note_charging(key)
            reading.charged_days = history.days_since(key)

            if reading.status == "ok":
                reading.seen_at = now
                seen.remember(key, reading.percent, reading.charging, now)

            with self._lock:
                prev = self._readings.get(key)
                # 休眠/离线时保留上次电量用于「上次 xx%」，但状态照实标注
                if reading.status != "ok" and prev is not None and prev.percent is not None:
                    reading.percent = prev.percent
                    reading.seen_at = prev.seen_at or prev.updated
                self._readings[key] = reading

            time.sleep(0.25)  # 设备之间错峰，避免同时打满 USB

        self.last_update = time.time()
        cb = self.on_update
        if cb:
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass
