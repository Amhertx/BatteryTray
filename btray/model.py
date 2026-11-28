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
    charged_days: int | None = None   # 距上次观察到「正在充电」的整数天数
    seen_at: float = 0.0              # 最后一次真正读到电量的时间（0 = 从没读到过）

    @property
    def online(self) -> bool:
        return self.status in ("ok", "sleep", "pending")

    @property
    def is_cached(self) -> bool:
        """显示的是「上次读到的值」而不是本次实时读数（开机后设备还没醒时就是它）。"""
        return self.status != "ok" and self.percent is not None and self.seen_at > 0

    @property
    def age_text(self) -> str:
        """距上次真正读到电量多久：刚刚 / 12 分钟前 / 8 小时前 / 3 天前。"""
        if self.seen_at <= 0:
            return ""
        sec = max(0.0, time.time() - self.seen_at)
        if sec < 60:
            return "刚刚"
        if sec < 3600:
            return f"{int(sec // 60)} 分钟前"
        if sec < 86400:
            return f"{int(sec // 3600)} 小时前"
        return f"{int(sec // 86400)} 天前"

    @property
    def charge_note(self) -> str:
        """「今天充过 / 3 天前充过」；没有充电记录时为空串。"""
        if self.charged_days is None:
            return ""
        if self.charged_days <= 0:
            return "今天充过"
        return f"{self.charged_days} 天前充过"

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
        if self.is_cached:
            status = STATUS_LABEL.get(self.status, self.status)
            line = (f"{self.name}  {status} · {int(self.percent)}%"
                    f"（{self.age_text}读数）")
        else:
            tail = ""
            if self.status != "ok" and self.detail:
                tail = f"（{self.detail}）"
            line = f"{self.name}  {self.label}{tail}"
        # 正在充电时「今天充过」是废话，只在没在充的时候补天数
        if self.charge_note and not (self.status == "ok" and self.charging):
            line += f"  ·  {self.charge_note}"
        elif self.status == "ok" and self.charged_days is None:
            line += "  ·  尚无充电记录"
        return line
