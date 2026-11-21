"""通知区（托盘）可见性辅助。

Windows 11 会把所有新注册的通知区图标塞进 `^` 溢出面板，程序侧没有 API 能强制
展开。系统对每个图标在 HKCU\\Control Panel\\NotifyIconSettings\\<id> 下记一条设置，
其中 IsPromoted=1 表示「在任务栏上显示」。新路径第一次运行时这条记录还不存在，
所以只能等图标注册完再把它改成 1——改动会在下一次 explorer 启动（重新登录）生效，
本次运行仍需要用户手动把图标从 `^` 里拖出来一次。
"""
from __future__ import annotations

import sys
import winreg

ROOT = r"Control Panel\NotifyIconSettings"


def promote(exe_path: str | None = None, mark_fixed: bool = True) -> int:
    """把指向本程序的图标登记项标为常显，返回改动条目数。"""
    target = (exe_path or sys.executable or "").lower()
    if not target:
        return 0
    changed = 0
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ROOT) as root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(root, name, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                        path = winreg.QueryValueEx(key, "ExecutablePath")[0]
                        if str(path).lower() != target:
                            continue
                        if mark_fixed:
                            winreg.SetValueEx(key, "IsPromoted", 0, winreg.REG_DWORD, 1)
                        changed += 1
                except OSError:
                    continue
    except OSError:
        return 0
    return changed
