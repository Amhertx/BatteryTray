"""充电天数（history）自测：不碰真设备，只用临时文件验证日期数学与文案。"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btray.history import ChargeHistory  # noqa: E402
from btray.model import Reading            # noqa: E402

FAILS: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {got!r}（期望 {want!r}）")
    if not ok:
        FAILS.append(name)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="btray_hist_"))
    path = tmp / "charge_history.json"
    today = dt.date(2026, 11, 22)

    h = ChargeHistory(path)
    check("无记录返回 None", h.days_since("k", today), None)

    h.note_charging("k", today)
    check("今天充电 → 0 天", h.days_since("k", today), 0)

    # 12 天前
    h.note_charging("k", today - dt.timedelta(days=12))
    check("12 天前 → 12 天", h.days_since("k", today), 12)

    # 跨年
    h.note_charging("ny", dt.date(2025, 12, 31))
    check("跨年 11/22 - 12/31", h.days_since("ny", dt.date(2026, 1, 31)), 31)

    # 系统时间回拨：记录在未来
    h.note_charging("future", today + dt.timedelta(days=5))
    check("未来记录收敛到 0", h.days_since("future", today), 0)

    # 持久化：换一个实例读同一个文件
    h2 = ChargeHistory(path)
    check("重启后仍读得到", h2.days_since("k", today), 12)

    # 同一天重复记不重复落盘
    mtime = path.stat().st_mtime_ns
    h2.note_charging("k", today - dt.timedelta(days=12))
    check("同日重复调用不写盘", path.stat().st_mtime_ns, mtime)

    # 损坏文件不应崩
    path.write_text("{ not json", encoding="utf-8")
    check("坏 JSON 容忍", ChargeHistory(path).days_since("k", today), None)

    # 字段格式非法也不应崩
    path.write_text(json.dumps({"k": "2026-13-45", "j": 123}), encoding="utf-8")
    h3 = ChargeHistory(path)
    check("非法日期跳过", h3.days_since("k", today), None)
    check("非字符串跳过", h3.days_since("j", today), None)

    # 面板 / tooltip 文案
    r = Reading(key="aula_f87", name="狼蛛 F87 Pro", short="F8", percent=85,
                charging=False, status="ok", charged_days=3)
    check("Reading.charge_note", r.charge_note, "3 天前充过")
    check("tooltip 含天数", r.one_line(), "狼蛛 F87 Pro  85%  ·  3 天前充过")

    r.charging = True
    check("充电中不重复报今天", r.one_line(), "狼蛛 F87 Pro  85% ⚡")

    r2 = Reading(key="sony_h9", name="索尼 INZONE H9 二代", short="H9", percent=48,
                 charging=False, status="ok", charged_days=0)
    check("0 天文案", r2.charge_note, "今天充过")

    r3 = Reading(key="razer_dav3", name="雷蛇 炼狱蝰蛇 V3 Pro", short="DA",
                 status="sleep", percent=64, charged_days=None)
    check("无记录时 note 为空", r3.charge_note, "")

    print("\n结果:", "PASS" if not FAILS else f"FAIL {FAILS}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
