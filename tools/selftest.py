"""命令行自检：跑一轮采集并打印结果，用于验证是否读到电量、是否零写入。"""
from __future__ import annotations

import os
import sys

# 允许从 tools/ 目录直接运行：把项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time

from btray.config import AUDIT_PATH, load
from btray.service import BatteryService


def main() -> None:
    cfg = load()
    service = BatteryService(cfg)
    started = time.time()
    service.poll_once()
    cost = (time.time() - started) * 1000

    print(f"轮询耗时 {cost:.0f} ms\n")
    print(f"{'设备':<22}{'状态':<10}{'读数':<10}详情")
    print("-" * 68)
    for r in service.snapshot():
        print(f"{r.name:<22}{r.status:<10}{str(r.label):<10}{r.detail}")

    print()
    if AUDIT_PATH.exists():
        lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()
        today = lines[-200:]
        tx = [ln for ln in today if "TX-READONLY" in ln]
        blocked = [ln for ln in today if "BLOCKED" in ln]
        print(f"审计日志：{AUDIT_PATH}")
        print(f"  只读查询报文 {len(tx)} 条，被拦截 {len(blocked)} 条")
        for ln in tx[-3:]:
            print(f"    {ln}")
    else:
        print("审计日志尚未生成")


if __name__ == "__main__":
    main()
