"""充电历史：记录每台设备最近一次「观察到正在充电」的日期。

纯本地文件、跨重启保留，不参与任何 HID 交互（只在我们本来就有的只读采集里顺手记一笔）。

单位是天：按**本地日历日期**求差，所以昨天深夜充电、今天凌晨打开也是「1 天前」，
与日常口语一致；用 24 小时取整会出现「20 分钟前显示 1 天」这种怪读数。
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

from .config import APP_DIR

HISTORY_PATH = APP_DIR / "charge_history.json"


class ChargeHistory:
    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path else HISTORY_PATH
        self._lock = threading.Lock()
        self._days: dict[str, str] = {}   # key -> "YYYY-MM-DD"
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            self._days = {str(k): v for k, v in raw.items()
                          if isinstance(v, str) and _valid(v)}

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._days, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8")
        except OSError:
            pass   # 只读盘 / 无权限时不影响主流程

    # ---------- 对外 ----------
    def note_charging(self, key: str, today: dt.date | None = None) -> None:
        """记一笔「此刻正在充电」。同一天重复调用不会反复落盘。"""
        day = (today or dt.date.today()).isoformat()
        with self._lock:
            if self._days.get(key) == day:
                return
            self._days[key] = day
            self._write()

    def last_day(self, key: str) -> dt.date | None:
        with self._lock:
            raw = self._days.get(key)
        if not raw:
            return None
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            return None

    def days_since(self, key: str, today: dt.date | None = None) -> int | None:
        """距上次观察到充电过了几个整数天；没有记录返回 None。

        系统时间被往回调时可能算出负数，收敛到 0（「今天」）。
        """
        day = self.last_day(key)
        if day is None:
            return None
        return max(0, ((today or dt.date.today()) - day).days)


def _valid(s: str) -> bool:
    try:
        dt.date.fromisoformat(s)
        return True
    except ValueError:
        return False


history = ChargeHistory()
