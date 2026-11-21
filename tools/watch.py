"""观察设备状态块的变化，用来确认哪个字段是电量。

用法：
    python watch.py aula 25      # 观察狼蛛 25 秒
    python watch.py razer 25

狼蛛用法：运行后 25 秒内，按 FN + ↑ / FN + ↓（或 FN + 灯光键）把亮度调到最亮再降到最低。
- 如果某个字节跟着亮度变 → 那个是亮度，电量在剩下的字节里
- 如果 7 个字节一个都没动 → 这一块是纯状态块，0x64 就是电量
程序只读，不发送任何报文。
"""
from __future__ import annotations

import os
import sys

# 允许从 tools/ 目录直接运行：把项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sys
import time

import hid

AULA = (0x3554, 0xFA09)


def _aula_payload() -> bytes | None:
    for info in hid.enumerate(*AULA):
        if info["interface_number"] == 1 and info["usage_page"] == 0xFF04 and info["usage"] == 0x0002:
            try:
                dev = hid.device()
                dev.open_path(info["path"])
                data = bytes(dev.get_feature_report(0x06, 8))
                dev.close()
                return data
            except OSError:
                return None
    return None


def watch_aula(seconds: int) -> None:
    print(f"基线读取中……请在这 {seconds} 秒内操作键盘：先 FN+↑ 调到最亮，再 FN+↓ 降到最低。\n")
    base = _aula_payload()
    if base is None:
        print("读取失败：键盘可能在休眠，敲一下键再重跑。")
        return
    print(f"baseline  {base.hex(' ')}")
    print(f"          id=0x{base[0]:02X}  payload={[f'0x{b:02X}({b})' for b in base[1:]]}\n")

    end = time.time() + seconds
    last = base
    changes = 0
    while time.time() < end:
        time.sleep(0.5)
        cur = _aula_payload()
        if cur is None:
            continue
        if cur != last:
            changes += 1
            diff = [f"#{i}: 0x{last[i]:02X}->0x{cur[i]:02X}" for i in range(min(len(last), len(cur)))
                    if last[i] != cur[i]]
            print(f"[{time.strftime('%H:%M:%S')}] 变化 {', '.join(diff)}   全帧 {cur.hex(' ')}")
            last = cur

    print(f"\n共捕获 {changes} 次变化。")
    if changes == 0:
        print("未捕获任何变化。注意：只有你在这段时间里真的按了键盘上的键，结论才有效。")
        print("  · 若你确实调过亮度 → 这块是纯状态块，0x64(100) 就是电量")
        print("  · 若你没操作 → 重跑一次，并在提示期间按 FN+↑ / FN+↓")
    else:
        print("有字节随操作变化 → 变动的是亮度/灯效字段，电量在未变动的字节里（贴给我即可定稿）。")


def scan_aula() -> None:
    """扫描狼蛛所有 HID 接口的 Feature 报告（纯 GET，不下发任何配置）。"""
    infos = hid.enumerate(*AULA)
    if not infos:
        print("未找到狼蛛接收器")
        return
    print(f"共 {len(infos)} 个 HID 集合：")
    for info in infos:
        print(f"  iface={info['interface_number']:<3} page=0x{info['usage_page']:04X} usage=0x{info['usage']:04X}")
    print()

    for info in infos:
        try:
            dev = hid.device()
            dev.open_path(info["path"])
        except OSError as exc:
            print(f"iface={info['interface_number']} 打不开: {exc}")
            continue
        print(f"=== iface={info['interface_number']} page=0x{info['usage_page']:04X} ===          ", end="")
        hits = 0
        for rid in range(0x00, 0x41):
            try:
                data = bytes(dev.get_feature_report(rid, 64))
            except OSError:
                continue
            if len(data) > 1 and any(data[1:]):
                hits += 1
                print(f"\n  id=0x{rid:02X} len={len(data):<3} {data.hex(' ')}", end="")
        print(f"\n  → 非空 Feature {hits} 个")
        dev.close()
        print()

    print("提示：若除了 06 之外还有别的非空 ID，那些才是候选实时状态通道。")
    print("      若只有 06，则这个块是唯一数据源，需要再做「关机对照」来确认它是否实时。")


def query_aula() -> None:
    """按公开协议尝试狼蛛的 20 字节查询帧（仅查询命令，载荷全 0）。"""
    target = None
    for info in hid.enumerate(*AULA):
        if info["interface_number"] == 1 and info["usage_page"] == 0xFF02:
            target = info
            break
    if not target:
        print("未找到 FF02 厂商集合")
        return
    print(f"目标集合: iface={target['interface_number']} page=0x{target['usage_page']:04X}\n")

    dev = hid.device()
    dev.open_path(target["path"])

    # 先清空输入缓冲
    while dev.read(64, 30):
        pass

    for label, cmd, with_sum in (("版本/信息 0x0B", 0x0B, False), ("电量 0x4A", 0x4A, True)):
        frame = bytearray(20)
        frame[0] = 0x13
        frame[1] = cmd
        if with_sum:
            frame[19] = sum(frame[:19]) & 0xFF
        print(f"===== {label}  发送 {frame.hex(' ')}")
        try:
            sent = dev.write(bytes(frame))
            print(f"  write -> {sent} 字节")
        except OSError as exc:
            print(f"  写入失败: {exc}")
            continue

        deadline = time.time() + 4.0
        last_req = time.time()
        got = 0
        while time.time() < deadline:
            data = dev.read(64, 300)
            if data:
                got += 1
                print(f"  [{time.strftime('%H:%M:%S')}] 收到 len={len(data):<3} {bytes(data).hex(' ')}")
            # 文档：休眠/刚连接的键盘可能吞掉第一帧，1.3s 后重发
            if time.time() - last_req > 1.3 and got == 0:
                dev.write(bytes(frame))
                last_req = time.time()
                print("  (重发查询)")
        if got == 0:
            print("  → 4 秒内无任何应答")
        print()

    dev.close()
    print("判读方法：若回复里某字节 = 电量百分比，且另一字节表示连接/充电状态，")
    print("          则按 回复[6]=电量、回复[7]=连接类型(0x01 无线) 或 回复[5]=电量 两种口径比对。")


def query_sony(seconds: int = 3) -> None:
    """索尼 INZONE H9 II：HID 通道 0xFF04 / report id 2，发 Sony HCI 电量查询帧。"""
    SONY = (0x054C, 0x0FA8)
    EVENT_BATTERY = 0x04

    def build(event_id: int, event_type: int = 0x01, params: bytes = b"", tx: int = 1) -> bytes:
        body = bytes([0x96, 0xC3, 0x41, event_id, event_type,
                      tx & 0xFF, (tx >> 8) & 0xFF]) + params
        total = bytes([0x01, 0x00, 0xFC, len(body) + 1]) + body
        return bytes([total[0]]) + total[1:] + bytes([sum(body) & 0xFF])

    target = None
    for info in hid.enumerate(*SONY):
        if info["usage_page"] == 0xFF04:
            target = info
            break
    if not target:
        print("未找到索尼 FF04 通道")
        return
    print(f"目标: iface={target['interface_number']} page=0x{target['usage_page']:04X} "
          f"usage=0x{target['usage']:04X}")

    frame = build(EVENT_BATTERY)
    print(f"发送帧 (report id 0x02 + MDR): 02 {frame.hex(' ')}")

    dev = hid.device()
    dev.open_path(target["path"])
    while dev.read(64, 40):
        pass
    dev.write(bytes([0x02]) + frame)

    deadline = time.time() + seconds
    got = 0
    while time.time() < deadline:
        data = bytes(dev.read(64, 250))
        if not data:
            continue
        got += 1
        body = data[1:] if data[0] == 0x02 else data
        tag = ""
        if len(body) >= 13 and body[0] == 0x04 and body[1] == 0xFF:
            event_id, event_type = body[7], body[8]
            params = body[11:-1]
            calc = sum(body[4:-1]) & 0xFF
            ok = "✓" if calc == body[-1] else f"✗(算得 {calc:02X})"
            tag = (f" ← HCI event id=0x{event_id:02X} type=0x{event_type:02X} "
                   f"params={params.hex(' ')} chk={ok}")
        print(f"  收到 len={len(data)} {data.hex(' ')}{tag}")
    dev.close()
    if got == 0:
        print("  无应答（耳机可能已关机，或被 INZONE Hub 独占）")


def watch_razer(seconds: int) -> None:
    from btray.providers import RazerProvider

    target = None
    for info in hid.enumerate(0x1532, 0x00B7):
        if info["interface_number"] == 0 and info["usage"] == 0x0002:
            target = info
            break
    if not target:
        print("未找到雷蛇控制接口")
        return

    dev = hid.device()
    dev.open_path(target["path"])
    print(f"雷蛇采样 {seconds}s（只读 0x07/0x80）")
    for _ in range(seconds):
        dev.send_feature_report(RazerProvider.build_query(0x07, 0x80))
        time.sleep(0.08)
        r = bytes(dev.get_feature_report(0x00, 91))
        print(f"  status=0x{r[1]:02X} args={r[9]:02X} {r[10]:02X} {r[11]:02X}")
        time.sleep(1)
    dev.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "aula"
    sec = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    if target == "aula":
        watch_aula(sec)
    elif target == "scan":
        scan_aula()
    elif target == "query":
        query_aula()
    elif target == "sony":
        query_sony(sec)
    elif target == "razer":
        watch_razer(sec)
    else:
        print("用法：python watch.py aula|razer [秒数]")
