"""设计令牌：跟随 Windows 深浅色，供面板绘制使用。

Tk 的 Canvas 没有透明度，所以所有半透明底色都在这里预计算成实色，
例如设备色块（chip）是「强调色 + 6%~12% 底色」的等效色值。
"""
from __future__ import annotations

import winreg
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    dark: bool
    bg: str            # 面板底色
    card: str          # 卡片
    card_hover: str    # 卡片悬停
    border: str        # 卡片描边
    divider: str       # 分隔线
    text: str          # 主文字
    sub: str           # 次要文字
    faint: str         # 分组标签 / 弱提示
    track: str         # 进度条轨道
    chip: str          # 中性胶囊底
    btn_hover: str     # 按钮悬停底
    accent: str        # 强调色（选中、链接）
    ok: str            # 电量条 高
    ok_text: str
    warn: str          # 电量条 中
    warn_text: str
    bad: str           # 电量条 低
    bad_text: str
    info: str          # 充电描边
    info_text: str
    toggle_off: str


LIGHT = Palette(
    dark=False,
    bg="#F7F8FA", card="#FFFFFF", card_hover="#FCFDFF", border="#E6E9EE",
    divider="#EDEFF3", text="#12151A", sub="#6B7280", faint="#8A929E",
    track="#EDEFF3", chip="#ECEEF2", btn_hover="#E3E6EB", accent="#1B63D6",
    ok="#2BA35A", ok_text="#15803D", warn="#E0A03C", warn_text="#B4740F",
    bad="#E24B4A", bad_text="#B4382F", info="#CFE3F5", info_text="#1B6FBF",
    toggle_off="#D8DCE3",
)

DARK = Palette(
    dark=True,
    bg="#1E1F23", card="#272A2F", card_hover="#2D3037", border="#34373E",
    divider="#33363D", text="#F2F4F8", sub="#9AA2AE", faint="#8B93A0",
    track="#3A3E45", chip="#2E3238", btn_hover="#353940", accent="#5B95F0",
    ok="#34C06B", ok_text="#4ADE80", warn="#E0A03C", warn_text="#F0B357",
    bad="#EF5B5B", bad_text="#FF8A85", info="#2F5C8C", info_text="#79B8F2",
    toggle_off="#3E424A",
)

# 设备强调色：浅色 (图形色, 色块底) / 深色 (图形色, 色块底)
DEVICE_TINT = {
    "sony_h9": (("#2F6FE0", "#EAF1FE"), ("#6BA5F5", "#22314D")),
    "razer_dav3": (("#7C3AED", "#F3ECFE"), ("#B18CFA", "#332A4D")),
    "aula_f87": (("#C2620E", "#FDEEE3"), ("#E8964A", "#3D2A1C")),
}


def system_dark() -> bool:
    """读注册表判断「应用模式」是否为深色（不是任务栏/窗口边框那个值）。"""
    try:
        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as h:
            value, _ = winreg.QueryValueEx(h, "AppsUseLightTheme")
            return int(value) == 0
    except OSError:
        return False


def current() -> Palette:
    return DARK if system_dark() else LIGHT


def mix_hex(a: str, b: str, t: float) -> str:
    """按 t 混合两色（t=0 全 a，t=1 全 b），用于在色块底上压出环轨道色。"""
    a = a.lstrip("#")
    b = b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        va, vb = int(a[i:i + 2], 16), int(b[i:i + 2], 16)
        out.append(round(va * (1 - t) + vb * t))
    return "#%02X%02X%02X" % tuple(out)


def device_tint(key: str, pal: Palette) -> tuple[str, str]:
    light, dark = DEVICE_TINT.get(key, (("#6B7280", "#ECEEF2"), ("#9AA2AE", "#2E3238")))
    return dark if pal.dark else light
