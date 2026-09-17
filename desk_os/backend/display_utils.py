"""多显示器定位工具（Windows）"""

import ctypes
import os
from ctypes import wintypes

MONITORINFOF_PRIMARY = 1


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_monitors() -> list[dict]:
    """枚举所有显示器（含是否为主屏）"""
    monitors: list[dict] = []

    def _callback(hmonitor, _hdc, lprect, _data):
        rect = lprect.contents
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(info))

        monitors.append(
            {
                "handle": hmonitor,
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
                "is_primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
            }
        )
        return True

    proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(_RECT),
        wintypes.LPARAM,
    )(_callback)

    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc, 0)
    return monitors


def resolve_target_monitor() -> int:
    """
    确定目标显示器序号（0 起）。

    优先级：
    1. 环境变量 DESK_OS_MONITOR
    2. 非主屏中面积最小的一块（通常是 iPad 副屏）
    3. 第一块非主屏
    """
    if "DESK_OS_MONITOR" in os.environ:
        return int(os.environ["DESK_OS_MONITOR"])

    monitors = get_monitors()
    if not monitors:
        return 0

    non_primary = [(i, m) for i, m in enumerate(monitors) if not m["is_primary"]]
    if not non_primary:
        return 0

    # 面积最小的非主屏 — 适配 iPad 等小尺寸副屏
    return min(non_primary, key=lambda x: x[1]["width"] * x[1]["height"])[0]


TARGET_MONITOR = resolve_target_monitor()


def _clamp_monitor_index(index: int) -> int:
    monitors = get_monitors()
    if not monitors:
        return 0
    return max(0, min(index, len(monitors) - 1))


def center_on_monitor(monitor_index: int, width: int, height: int) -> tuple[int, int]:
    """计算窗口在指定显示器上居中时的 (x, y)"""
    monitors = get_monitors()
    if not monitors:
        return 100, 100

    idx = _clamp_monitor_index(monitor_index)
    mon = monitors[idx]
    x = mon["left"] + max(0, (mon["width"] - width) // 2)
    y = mon["top"] + max(0, (mon["height"] - height) // 2)
    return x, y


def get_monitor_index_at(x: int, y: int) -> int:
    """根据坐标点判断所在显示器序号"""
    monitors = get_monitors()
    if not monitors:
        return 0

    point = _POINT(x, y)
    handle = ctypes.windll.user32.MonitorFromPoint(point, 2)

    for i, mon in enumerate(monitors):
        if mon["handle"] == handle:
            return i
    return 0


def get_window_monitor_index(win) -> int:
    """根据窗口中心点判断当前所在显示器"""
    cx = win.x + win.width // 2
    cy = win.y + win.height // 2
    return get_monitor_index_at(cx, cy)


def move_window_to_monitor(win, monitor_index: int, width: int, height: int) -> bool:
    """将窗口移动到指定显示器并居中，成功返回 True"""
    x, y = center_on_monitor(monitor_index, width, height)
    try:
        win.move(x, y)
        return True
    except Exception:
        return False


def print_monitors():
    """打印显示器列表，方便确认 DESK_OS_MONITOR 序号"""
    for i, m in enumerate(get_monitors()):
        tag = " [主屏]" if m["is_primary"] else ""
        mark = " <-- 当前默认" if i == TARGET_MONITOR else ""
        print(
            f"  [{i}] {m['width']}x{m['height']}  "
            f"位置 ({m['left']}, {m['top']}){tag}{mark}"
        )


if __name__ == "__main__":
    print("显示器列表（序号 ≠ Windows 设置里的编号，以本列表为准）：")
    print_monitors()
    print(f"\n默认目标: 显示器 {TARGET_MONITOR}")
    print("手动指定: set DESK_OS_MONITOR=0  (PowerShell: $env:DESK_OS_MONITOR=0)")
