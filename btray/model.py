"""统一设备读数模型。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

# status 语义
# ok      读到电量
# sleep   设备在系统里但无响应（键鼠休眠 / 耳机未开机）
# offline 设备不在（接收器未插 / 未连接）
# pending 设备在，但电量协议尚未打通
# error   读取异常

STATUS_LABEL = {
    "ok": "",
    "sleep": "休眠",
    "offline": "离线",
    "pending": "待探测",
    "error": "读取失败",
}


@dataclass
class Reading:
    key: str
    name: str
    short: str
    percent: int | None = None
    charging: bool | None = None
    status: str = "unknown"
    detail: str = ""
    verified: bool = True
    updated: float = field(default_factory=time.time)

    @property
    def online(self) -> bool:
        return self.status in ("ok", "sleep", "pending")

    @property
    def label(self) -> str:
        if self.status == "ok" and self.percent is not None:
            txt = f"{self.percent}%"
            if self.charging:
                txt += " ⚡"
            elif not self.verified:
                txt += " ?"
            return txt
        return STATUS_LABEL.get(self.status, self.status)

    def one_line(self) -> str:
        """托盘 tooltip 用"""
        tail = ""
        if self.status != "ok" and self.detail:
            tail = f"（{self.detail}）"
        return f"{self.name}  {self.label}{tail}"
