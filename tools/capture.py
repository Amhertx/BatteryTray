"""只读抓帧工具：补齐索尼 / 狼蛛电量协议用。

用法：
    python capture.py sony 20      # 抓索尼 20 秒
    python capture.py aula 20      # 抓狼蛛 20 秒
    python capture.py all 20

它只调用 read()，不发送任何报文，不会影响设备任何功能。
抓之前请把设备开机/唤醒，并打开对应的厂商软件（INZONE Hub）让它去轮询，
我们就能收到它触发的响应副本（HID 输入报告对多个句柄是广播的）。
"""
from __future__ import annotations

import os
import sys

# 允许从 tools/ 目录直接运行：把项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sys
import threading
import time

import hid

SONY = (0x054C, 0x0FA8)
AULA = (0x3554, 0xFA09)

# (标签, vid/pid, interface, usage_page, usage, 读取长度)
CHANNELS = {
    "sony": [
        ("FF04", SONY, 5, 0xFF04, 0x0001, 64),
        ("FF13", SONY, 5, 0xFF13, 0x0001, 64),
        ("CONSUMER", SONY, 5, 0x000C, 0x0001, 8),
    ],
    "aula": [
        ("FF02", AULA, 1, 0xFF02, 0x0002, 32),
        ("SYSCTL", AULA, 1, 0x0001, 0x0080, 16),
    ],
}


def _find(vidpid, iface, up, us):
    for info in hid.enumerate(vidpid[0], vidpid[1]):
        if info["interface_number"] == iface and info["usage_page"] == up and info["usage"] == us:
            return info
    return None


def _sniff(label, vidpid, iface, up, us, length, seconds, sink):
    info = _find(vidpid, iface, up, us)
    if not info:
        print(f"[{label}] 未找到集合")
        return
    try:
        dev = hid.device()
        dev.open_path(info["path"])
    except Exception as exc:  # noqa: BLE001
        print(f"[{label}] 打开失败 {exc}")
        return

    print(f"[{label}] 开始嗅探 {seconds}s（只读）")
    end = time.time() + seconds
    last = None
    while time.time() < end:
        try:
            data = bytes(dev.read(length, 300))
        except Exception as exc:  # noqa: BLE001
            print(f"[{label}] 读取中断 {exc}")
            break
        if data and data != last:
            last = data
            stamp = time.strftime("%H:%M:%S")
            print(f"[{label}] {stamp} +{len(data)}B  {data.hex(' ')}")
            sink.append((label, data))
    dev.close()


def run(target: str, seconds: int) -> None:
    groups = CHANNELS if target == "all" else {target: CHANNELS.get(target, [])}
    if not any(groups.values()):
        print(f"未知目标 {target}，可选：sony / aula / all")
        return

    sink: list[tuple[str, bytes]] = []
    threads = []
    for label, vidpid, iface, up, us, length in (c for g in groups.values() for c in g):
        th = threading.Thread(target=_sniff, args=(label, vidpid, iface, up, us, length, seconds, sink),
                              daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join()

    print("\n===== 汇总（去重后的帧）=====")
    seen = {}
    for label, data in sink:
        seen.setdefault((label, data), 0)
        seen[(label, data)] += 1
    if not seen:
        print("没有抓到任何输入报告。请确认：设备已开机 / 已唤醒，厂商软件在运行。")
    for (label, data), count in sorted(seen.items(), key=lambda kv: -kv[1])[:40]:
        print(f"{label:<10} x{count:<3} {data.hex(' ')}")


if __name__ == "__main__":
    tgt = sys.argv[1] if len(sys.argv) > 1 else "all"
    sec = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    run(tgt, sec)
