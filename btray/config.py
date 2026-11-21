"""配置与审计日志。"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

APP_NAME = "BatteryTray"
VERSION = "1.4"
APP_DIR = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
CONFIG_PATH = APP_DIR / "config.json"
AUDIT_PATH = APP_DIR / "audit.log"

# 设备注册表：VID/PID 来自本机实测枚举结果
DEVICES = [
    {"key": "sony_h9", "name": "索尼 INZONE H9 二代", "kind": "耳机", "short": "H9", "vid": 0x054C, "pid": 0x0FA8, "provider": "sony"},
    {"key": "razer_dav3", "name": "雷蛇 炼狱蝰蛇 V3 Pro", "kind": "鼠标", "short": "DA", "vid": 0x1532, "pid": 0x00B7, "provider": "razer"},
    {"key": "aula_f87", "name": "狼蛛 F87 Pro", "kind": "键盘", "short": "F8", "vid": 0x3554, "pid": 0xFA09, "provider": "aula"},
]

DEFAULTS = {
    "display_mode": "multi",       # multi | single
    "poll_interval": 1800,         # 秒，默认 30 分钟，最小 30 秒
    "aula_verified": True,         # 狼蛛电量字段已实测确认
    "razer_level_byte": 10,        # 雷蛇电量字段在响应中的偏移
    "autostart": False,
    "low_battery_alert": True,     # 低电量是否弹系统通知
    "low_battery_threshold": 20,   # 低电量阈值（15/20/25/30）
    "start_hint_shown": False,     # 首次启动是否已提示过「图标在通知区」
}

THRESHOLD_CHOICES = (15, 20, 25, 30)
# 回差：电量为「阈值+5%」以上才重新武装提醒，避免在阈值附近反复弹
ALERT_HYSTERESIS = 5

MIN_POLL_INTERVAL = 30


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    cfg["poll_interval"] = max(MIN_POLL_INTERVAL, int(cfg.get("poll_interval") or DEFAULTS["poll_interval"]))
    th = int(cfg.get("low_battery_threshold") or DEFAULTS["low_battery_threshold"])
    cfg["low_battery_threshold"] = th if th in THRESHOLD_CHOICES else DEFAULTS["low_battery_threshold"]
    return cfg


def save(cfg: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    payload = {k: cfg[k] for k in DEFAULTS if k in cfg}
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class AuditLog:
    """记录所有 HID 访问，用于证明零写入。"""

    def __init__(self, path: Path = AUDIT_PATH, max_bytes: int = 1_000_000):
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass

    def write(self, kind: str, msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{kind:<7}] {msg}\n"
        with self._lock:
            try:
                if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                    self.path.write_text("", encoding="utf-8")
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
            except Exception:  # noqa: BLE001
                pass


AUDIT = AuditLog()
