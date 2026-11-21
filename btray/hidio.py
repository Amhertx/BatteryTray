"""只读 HID 传输层。

硬性约束（这是本项目的核心安全设计，别改）：
1. 只允许 get_feature_report / read 两种读取动作。
2. 唯一的写入式调用是雷蛇的「查询类」feature 报文，且必须命中
   ALLOWED_QUERIES 白名单；报文载荷区必须全 0，防止夹带任何配置写入。
3. SET_DEVICE_MODE(0x00/0x04) 被显式列入 BLOCKED，命中即抛异常并写审计日志。
   该命令会把设备从板载模式抢到驱动模式，直接破坏雷云 DPI 切换与板载配置。
4. 打开设备使用共享方式（hidapi 默认 FILE_SHARE_READ|WRITE），不独占、不抢占。
"""
from __future__ import annotations

import time

import hid

from .config import AUDIT

# 雷蛇只读查询：(command_class, command_id)
ALLOWED_QUERIES = {
    (0x07, 0x80),  # get battery level
    (0x07, 0x81),  # get charging status
}

BLOCKED_QUERIES = {
    (0x00, 0x04): "SET_DEVICE_MODE(会破坏雷云DPI与板载配置)",
    (0x00, 0x03): "SET_DEVICE_MODE",
    (0x0D, 0x14): "SET_DPI",
    (0x04, 0x03): "SET_LED_EFFECT",
}

# 狼蛛 2.4G 接收器：硬件层面没有「只 GET」通道，只能写一条查询帧再收回包。
# 白名单只放行 0x4A（读电量）。载荷区必须全 0，校验和必须正确，长度必须 20。
AULA_FRAME_LEN = 20
AULA_REPORT_ID = 0x13
AULA_ALLOWED_CMDS = {
    0x4A: "GET_BATTERY",
}

# 索尼 INZONE H9 II：FF04 / report 0x02 的 64 字节双向管道。
# 请求头 14 字节，第 10 字节是 MODE：
#   0x01 = 只读查询（本项目只发这个）
#   0x02 = 配置写入（改音量/降噪/平衡），显式封禁
# 第 13 字节校验 = (cmd_id + 0x9C) & 0xFF
SONY_REPORT_ID = 0x02
SONY_ALLOWED_CMDS = {
    0x04: "GET_POWER_STATUS",    # 回复 [13]=充电中, [14]=电量
    0x06: "GET_AUDIO_STATUS",    # 回复 [14]=充电中, [15]=电量
}
SONY_READ_MODE = 0x01
SONY_BLOCKED_MODE = 0x02


class ReadOnlyViolation(RuntimeError):
    pass


class ReadOnlyHid:
    def __init__(self, path, tag: str):
        self.tag = tag
        self.path = path
        self._dev = hid.device()
        self._dev.open_path(path)
        AUDIT.write("OPEN", f"{tag} shared-handle")

    def __enter__(self) -> "ReadOnlyHid":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._dev.close()
        except Exception:  # noqa: BLE001
            pass

    # ---------- 纯读取 ----------
    def get_descriptor(self) -> bytes:
        desc = bytes(self._dev.get_report_descriptor())
        AUDIT.write("GET", f"{self.tag} report-descriptor {len(desc)}B")
        return desc

    def get_feature(self, report_id: int, size: int) -> bytes:
        data = bytes(self._dev.get_feature_report(report_id, size))
        AUDIT.write("GET", f"{self.tag} feature rid=0x{report_id:02X} len={size} -> {len(data)}B")
        return data

    def read(self, size: int, timeout_ms: int = 300) -> bytes:
        data = bytes(self._dev.read(size, timeout_ms))
        if data:
            AUDIT.write("READ", f"{self.tag} input {len(data)}B")
        return data

    # ---------- 唯一允许的写入：白名单查询报文 ----------
    def query(self, report: bytes, cmd_class: int, cmd_id: int) -> bytes:
        if (cmd_class, cmd_id) in BLOCKED_QUERIES:
            AUDIT.write("BLOCKED", f"{self.tag} class=0x{cmd_class:02X} cmd=0x{cmd_id:02X} "
                                    f"reason={BLOCKED_QUERIES[(cmd_class, cmd_id)]}")
            raise ReadOnlyViolation(
                f"禁止发送 {cmd_class:02X}/{cmd_id:02X}：该命令会修改设备状态"
            )
        if (cmd_class, cmd_id) not in ALLOWED_QUERIES:
            AUDIT.write("BLOCKED", f"{self.tag} class=0x{cmd_class:02X} cmd=0x{cmd_id:02X} reason=not-whitelisted")
            raise ReadOnlyViolation(f"未在白名单内的命令 {cmd_class:02X}/{cmd_id:02X}")

        # 报文第 7/8 字节必须是该命令，且载荷区必须为 0，杜绝夹带配置写入
        if report[7] != cmd_class or report[8] != cmd_id:
            raise ReadOnlyViolation("报文命令与声明不一致")
        if any(report[9:88]):
            AUDIT.write("BLOCKED", f"{self.tag} payload-not-empty")
            raise ReadOnlyViolation("查询报文载荷非空，拒绝发送")

        sent = self._dev.send_feature_report(report)
        AUDIT.write("TX-READONLY", f"{self.tag} class=0x{cmd_class:02X} cmd=0x{cmd_id:02X} len={len(report)} sent={sent}")
        if sent < 0:
            raise OSError("send_feature_report failed")
        time.sleep(0.08)  # 设备需要处理时间，立即读会拿到 BUSY(0x01)
        return bytes(self._dev.get_feature_report(report[0], len(report)))

    # ---------- 狼蛛：唯一允许的查询帧 ----------
    def send_query_frame(self, cmd: int) -> None:
        """构造并发出一条 20 字节查询帧；载荷区强制全 0，校验和强制正确。"""
        if cmd not in AULA_ALLOWED_CMDS:
            AUDIT.write("BLOCKED", f"{self.tag} frame-cmd=0x{cmd:02X} reason=not-whitelisted")
            raise ReadOnlyViolation(f"未在白名单内的帧命令 0x{cmd:02X}")

        frame = bytearray(AULA_FRAME_LEN)
        frame[0] = AULA_REPORT_ID
        frame[1] = cmd
        frame[-1] = sum(frame[:-1]) & 0xFF

        if any(frame[2:-1]):
            raise ReadOnlyViolation("查询帧载荷非空，拒绝发送")

        sent = self._dev.write(bytes(frame))
        AUDIT.write("TX-QUERY", f"{self.tag} rid=0x{AULA_REPORT_ID:02X} cmd=0x{cmd:02X} "
                                f"({AULA_ALLOWED_CMDS[cmd]}) len={len(frame)} sent={sent}")
        if sent < 0:
            raise OSError("write failed")

    def drain(self) -> None:
        """清空输入缓冲，避免把上一次的残留帧当成本次回复。"""
        while self._dev.read(64, 20):
            pass

    # ---------- 索尼：唯一允许的只读查询帧 ----------
    def sony_query(self, cmd_id: int, timeout_s: float = 1.0) -> bytes | None:
        """发一条 MODE=0x01 的只读查询，返回对应该 cmd 的回复帧。

        与 INZONE Hub 完全共存：句柄共享打开、只发只读查询、不抢占、不改配置。
        INZONE Hub 要是在同一通道上发帧，read 可能收到它的回复，
        所以必须用回复帧的 [9] 是否等于本次 cmd 来认领，认不到就重试。
        """
        if cmd_id not in SONY_ALLOWED_CMDS:
            AUDIT.write("BLOCKED", f"{self.tag} sony-cmd=0x{cmd_id:02X} reason=not-whitelisted")
            raise ReadOnlyViolation(f"未在白名单内的索尼命令 0x{cmd_id:02X}")

        req = bytearray(64)
        req[0:14] = bytes([
            SONY_REPORT_ID, 0x0C, 0x01, 0x00, 0xFC, 0x08,
            0x96, 0xC3, 0x41, cmd_id, SONY_READ_MODE, 0x01, 0x00,
            (cmd_id + 0x9C) & 0xFF,
        ])
        # 三道闸：MODE 必须是只读、载荷区必须全 0、校验字节必须自算得出
        if req[10] != SONY_READ_MODE:
            raise ReadOnlyViolation("索尼查询帧 MODE 非只读，拒绝发送")
        if any(req[14:]):
            AUDIT.write("BLOCKED", f"{self.tag} sony-payload-not-empty")
            raise ReadOnlyViolation("索尼查询帧载荷非空，拒绝发送")
        if req[13] != (cmd_id + 0x9C) & 0xFF:
            raise ReadOnlyViolation("索尼查询帧校验错误")

        sent = self._dev.write(bytes(req))
        AUDIT.write("TX-READONLY", f"{self.tag} sony cat=0x41 cmd=0x{cmd_id:02X} "
                                   f"({SONY_ALLOWED_CMDS[cmd_id]}) mode=0x01 len=64 sent={sent}")
        if sent < 0:
            raise OSError("write failed")

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            data = bytes(self._dev.read(64, 80))
            if not data or len(data) < 64:
                continue
            if data[9] != cmd_id:
                continue      # 不是本次查询的回复（可能是 INZONE Hub 的或异步事件）
            AUDIT.write("RX", f"{self.tag} sony cmd=0x{cmd_id:02X} frame={data[:24].hex(' ')}")
            return data
        return None

    def read_query_reply(self, cmd: int, timeout_s: float = 1.2) -> bytes | None:
        """在超时窗口内找到对指定命令的回复帧（receiver 也会推无关的 0x13 帧）。"""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            data = bytes(self._dev.read(64, 160))
            if not data:
                continue
            # 部分 HID 栈会剥掉 report id，两种排布都兼容
            off = 0 if data[0] == AULA_REPORT_ID else (1 if len(data) > 1 and data[1] == AULA_REPORT_ID else None)
            if off is None:
                continue
            body = data[off:]
            if len(body) < AULA_FRAME_LEN:
                continue
            if body[1] & 0x7F != cmd:
                continue            # 无关帧（例如 0x0A 状态推送）
            AUDIT.write("RX", f"{self.tag} cmd=0x{cmd:02X} frame={body[:AULA_FRAME_LEN].hex(' ')}")
            return body[:AULA_FRAME_LEN]
        return None


# ---------------- HID report descriptor 解析 ----------------
_MAIN_INPUT, _MAIN_OUTPUT, _MAIN_FEATURE = 0x8, 0x9, 0xB


def parse_descriptor(desc: bytes) -> list[dict]:
    """解析出所有 Input/Output/Feature 字段，用于判定 Battery Strength。"""
    out: list[dict] = []
    i = 0
    usage_page = report_id = rsize = rcount = 0
    local: list[tuple[int, int]] = []
    stack: list[tuple[int, int]] = []
    offsets: dict[tuple[int, int], int] = {}  # (kind_tag, report_id) -> 已用 bit 数

    while i < len(desc):
        prefix = desc[i]
        size = 3 if (prefix & 0x03) == 3 else (prefix & 0x03)
        typ = (prefix >> 2) & 0x03
        tag = (prefix >> 4) & 0x0F
        val = 0
        for k in range(size):
            val |= desc[i + 1 + k] << (8 * k)
        i += 1 + size

        if typ == 1:  # Global
            if tag == 0x0:
                usage_page = val
            elif tag == 0x7:
                rsize = val
            elif tag == 0x8:
                report_id = val
            elif tag == 0x9:
                rcount = val
        elif typ == 2:  # Local
            if tag == 0x0:
                local.append((usage_page, val))
        elif typ == 0:  # Main
            if tag == 0xA:
                stack.append(local[0] if local else (usage_page, 0))
                local = []
            elif tag == 0xC:
                if stack:
                    stack.pop()
            elif tag in (_MAIN_INPUT, _MAIN_OUTPUT, _MAIN_FEATURE):
                if rcount * rsize:
                    slot = (tag, report_id)
                    bit_cursor = offsets.get(slot, 0)
                    out.append({
                        "kind": {_MAIN_INPUT: "Input", _MAIN_OUTPUT: "Output", _MAIN_FEATURE: "Feature"}[tag],
                        "report_id": report_id,
                        "bytes": rcount * rsize // 8,
                        "offset": bit_cursor // 8,
                        "collection": stack[-1] if stack else (0, 0),
                        "locals": list(local),
                    })
                    offsets[slot] = bit_cursor + rcount * rsize
                local = []
    return out


def find_battery_strength(items: list[dict]) -> list[dict]:
    """Usage Page 0x06 / Usage 0x20 = Battery Strength，标准电量上报。"""
    hits = []
    for it in items:
        if it["kind"] != "Input":
            continue
        for page, usage in it["locals"]:
            if page == 0x06 and usage == 0x20:
                hits.append(it)
                break
    return hits


def battery_strength_field(desc: bytes) -> tuple[int, int, int] | None:
    """返回 (report_id, 字段字节偏移, 位宽)；无标准电量上报时返回 None。"""
    hits = find_battery_strength(parse_descriptor(desc))
    if not hits:
        return None
    field = hits[0]
    return field["report_id"], field["offset"], field["bytes"] * 8
