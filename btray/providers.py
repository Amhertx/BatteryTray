"""各厂商电量 Provider。

所有 Provider 只做读取：
- 雷蛇：白名单内的两条只读查询（0x07/0x80 电量、0x07/0x81 充电状态）
- 狼蛛：白名单内的单条查询帧（0x13/0x4A 读电量 + 充电状态）
- 索尼：白名单内的只读查询帧（0x41/0x04 读电量 + 充电状态），与 INZONE Hub 共存
"""
from __future__ import annotations

import time

import hid

from .config import DEVICES
from .hidio import ReadOnlyHid
from .model import Reading


class BaseProvider:
    provider_id = "base"

    def __init__(self, device: dict, cfg: dict):
        self.dev = device
        self.cfg = cfg

    def reading(self, **kw) -> Reading:
        return Reading(key=self.dev["key"], name=self.dev["name"], short=self.dev["short"], **kw)

    def collections(self) -> list[dict]:
        return list(hid.enumerate(self.dev["vid"], self.dev["pid"]))

    @staticmethod
    def pick(infos: list[dict], iface=None, usage_page=None, usage=None):
        for info in infos:
            if iface is not None and info["interface_number"] != iface:
                continue
            if usage_page is not None and info["usage_page"] != usage_page:
                continue
            if usage is not None and info["usage"] != usage:
                continue
            return info
        return None

    def poll(self) -> Reading:
        raise NotImplementedError


class RazerProvider(BaseProvider):
    """雷蛇 DeathAdder V3 Pro：91 字节 feature report（report id + 90 字节报文）。"""

    provider_id = "razer"
    REPORT_LEN = 91

    @classmethod
    def build_query(cls, cmd_class: int, cmd_id: int, data_size: int = 0x02) -> bytes:
        buf = bytearray(cls.REPORT_LEN)
        buf[0] = 0x00   # report id
        buf[1] = 0x00   # status
        buf[2] = 0x1F   # transaction id
        buf[4] = 0x00   # protocol type
        buf[6] = data_size
        buf[7] = cmd_class
        buf[8] = cmd_id
        crc = 0
        for idx in range(3, 89):
            crc ^= buf[idx]
        buf[89] = crc
        buf[90] = 0x00
        return bytes(buf)

    @staticmethod
    def _crc_ok(resp: bytes) -> bool:
        if len(resp) < 91:
            return False
        crc = 0
        for idx in range(3, 89):
            crc ^= resp[idx]
        return crc == resp[89]

    def _ask(self, handle, cmd_class: int, cmd_id: int, tries: int = 3) -> bytes:
        """雷蛇查询：0x01=BUSY 时重试，0x02=SUCCESS 才算成功。"""
        last = b""
        for attempt in range(tries):
            last = handle.query(self.build_query(cmd_class, cmd_id), cmd_class, cmd_id)
            if len(last) > 1:
                if last[1] == 0x02:
                    return last
                if last[1] != 0x01:  # 非 BUSY 就没必要重试
                    return last
            time.sleep(0.12 * (attempt + 1))
        return last

    def poll(self) -> Reading:
        infos = self.collections()
        if not infos:
            return self.reading(status="offline", detail="接收器未连接")

        info = self.pick(infos, 0, 0x0001, 0x0002) or self.pick(infos, 0)
        if not info:
            return self.reading(status="pending", detail="未找到控制接口")

        try:
            with ReadOnlyHid(info["path"], "razer") as h:
                resp = self._ask(h, 0x07, 0x80)
                charging = None
                if len(resp) > 10 and resp[1] == 0x02:
                    chg = self._ask(h, 0x07, 0x81, tries=2)
                    if len(chg) > 10 and chg[1] == 0x02:
                        charging = chg[10] == 0x01
        except OSError:
            return self.reading(status="sleep", detail="无响应，可能休眠")
        except Exception as exc:  # noqa: BLE001
            return self.reading(status="error", detail=str(exc)[:60])

        if len(resp) < 12:
            return self.reading(status="error", detail="响应过短")
        if resp[1] != 0x02:
            return self.reading(status="error", detail=f"设备返回状态 0x{resp[1]:02X}")

        idx = int(self.cfg.get("razer_level_byte", 10))
        raw = resp[idx]
        percent = round(raw * 100 / 255)
        detail = "" if self._crc_ok(resp) else "CRC 异常"
        return self.reading(percent=percent, charging=charging, status="ok", detail=detail)


class AulaProvider(BaseProvider):
    """狼蛛 F87 Pro：2.4G 接收器 FF02/0002 集合，20 字节查询帧。

    实测确认的帧格式（report id 0x13，全程 20 字节）：
        请求  13 4A 00 … 00 <sum>     sum = 前 19 字节之和 & 0xFF
        回复  13 4A 01 00 02 LL SS 00 … 00 <sum>
              [5] = 电量百分比(1..100)
              [6] = 状态，低半字节 1=用电池、0=满电；0x10=插线充电
    该接收器没有纯 GET 通道，只能发查询帧；传输层已白名单限定只允许 0x4A。
    """

    provider_id = "aula"
    CMD_BATTERY = 0x4A

    def poll(self) -> Reading:
        infos = self.collections()
        if not infos:
            return self.reading(status="offline", detail="接收器未连接")

        info = self.pick(infos, 1, 0xFF02, 0x0002) or self.pick(infos, 1, 0xFF04, 0x0002)
        if not info:
            return self.reading(status="pending", detail="未找到厂商查询通道")

        resp = None
        try:
            with ReadOnlyHid(info["path"], "aula") as h:
                h.drain()
                # 键盘刚唤醒时首帧可能被吞，1.3s 内补发一次
                for attempt in range(2):
                    h.send_query_frame(self.CMD_BATTERY)
                    resp = h.read_query_reply(self.CMD_BATTERY, 0.9 if attempt == 0 else 0.6)
                    if resp:
                        break
        except OSError:
            return self.reading(status="sleep", detail="键盘休眠，按键唤醒后自动刷新")
        except Exception as exc:  # noqa: BLE001
            return self.reading(status="error", detail=str(exc)[:60])

        if not resp:
            return self.reading(status="sleep", detail="无应答，键盘可能休眠")

        level, state = resp[5], resp[6]
        if not 1 <= level <= 100:
            return self.reading(status="error", detail=f"电量字段异常 0x{level:02X}")

        # 实测：状态字节两个半字节各管一件事
        #   0x01 → 低半字节 1，用电池（未插线）
        #   0x10 → 高半字节 1，插线充电中
        charging = None
        if (state >> 4) & 0x0F == 0x01:
            charging = True
        elif state & 0x0F == 0x01:
            charging = False
        sum_ok = (sum(resp[:-1]) & 0xFF) == resp[-1]
        return self.reading(
            percent=level,
            charging=charging,
            status="ok",
            verified=bool(self.cfg.get("aula_verified", True)),
            detail="" if sum_ok else "校验和异常",
        )


class SonyProvider(BaseProvider):
    """索尼 INZONE H9 II：FF04 / report 0x02，只读查询帧（MODE=0x01）。

    实测确认（与 INZONE Hub 同时运行，互不影响）：
        请求  02 0C 01 00 FC 08 96 C3 41 04 01 01 00 A0   后补 0 至 64 字节
        回复  02 0E 04 FF .. 96 C3 14 04 ..
              [13] = 充电状态（1=充电中，0=未充电）
              [14] = 电量百分比
        0x41/0x06（Audio Status）可交叉印证：[14]=充电, [15]=电量

    只发 MODE=0x01 的查询；改音量/降噪用的 MODE=0x02 在传输层被硬封禁。
    """

    provider_id = "sony"

    def poll(self) -> Reading:
        infos = self.collections()
        if not infos:
            return self.reading(status="offline", detail="接收器未连接")

        info = self.pick(infos, 5, 0xFF04, 0x0001) or self.pick(infos, usage_page=0xFF04)
        if not info:
            return self.reading(status="pending", detail="未找到厂商控制通道")

        resp = None
        try:
            with ReadOnlyHid(info["path"], "sony") as h:
                h.drain()
                # 耳机刚唤醒或与 Hub 抢帧时会漏一帧，补一次
                for _ in range(2):
                    resp = h.sony_query(0x04)
                    if resp:
                        break
        except OSError:
            return self.reading(status="offline", detail="耳机未开机或已休眠")
        except Exception as exc:  # noqa: BLE001
            return self.reading(status="error", detail=str(exc)[:60])

        if not resp:
            return self.reading(status="offline", detail="耳机无应答（未开机/已休眠）")

        percent = resp[14]
        if not 0 <= percent <= 100:
            return self.reading(status="error", detail=f"电量字段异常 0x{percent:02X}")

        return self.reading(
            percent=percent,
            charging=resp[13] != 0,
            status="ok",
            verified=True,
        )


PROVIDER_MAP = {
    "razer": RazerProvider,
    "aula": AulaProvider,
    "sony": SonyProvider,
}


def build_providers(cfg: dict) -> list[BaseProvider]:
    return [PROVIDER_MAP[d["provider"]](d, cfg) for d in DEVICES if d["provider"] in PROVIDER_MAP]
