"""上次读数缓存：跨重启保留每台设备最后一次真正读到的电量。

为什么需要：开机自启时设备往往还没醒 —— 键鼠休眠、耳机没开机，HID 一条也读不到。
内存里的「上次 xx%」随进程一起消失，面板就只剩一片「离线」。这里把成功读到的值落盘，
启动时先顶上，并明确标注是「多久前的读数」。

缓存只用于展示，**不参与低电量告警**（否则关一晚机、开机就误报）。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .config import APP_DIR

CACHE_PATH = APP_DIR / "last_readings.json"
MAX_AGE = 30 * 24 * 3600   # 超过 30 天的记录直接丢弃：多半换过设备，留着只会误导


class LastSeen:
    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path else CACHE_PATH
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        now = time.time()
        for key, item in raw.items():
            if not isinstance(item, dict):
                continue
            pct, ts = item.get("percent"), item.get("ts")
            if not isinstance(pct, (int, float)) or not isinstance(ts, (int, float)):
                continue
            if not 0 <= pct <= 100 or ts <= 0 or now - ts > MAX_AGE:
                continue
            self._data[str(key)] = {"percent": int(pct),
                                    "charging": bool(item.get("charging")),
                                    "ts": float(ts)}

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8")
        except OSError:
            pass   # 只读盘 / 无权限：降级为纯内存，不影响主流程

    # ---------- 对外 ----------
    def remember(self, key: str, percent: int | None, charging: bool | None,
                 ts: float | None = None) -> None:
        """记下这次真正读到的值。值没变、记录还不满 10 分钟就不重复落盘。"""
        if percent is None:
            return
        now = float(ts or time.time())
        with self._lock:
            prev = self._data.get(key)
            if (prev and prev["percent"] == int(percent)
                    and prev["charging"] == bool(charging) and now - prev["ts"] < 600):
                return
            self._data[key] = {"percent": int(percent), "charging": bool(charging), "ts": now}
            self._write()

    def get(self, key: str) -> dict | None:
        with self._lock:
            item = self._data.get(key)
            return dict(item) if item else None


seen = LastSeen()
