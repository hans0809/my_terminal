"""全局键盘监听：GetAsyncKeyState 轮询（任意窗口焦点都有效，含长按重复）"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.SystemParametersInfoW.argtypes = [
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.c_void_p,
    ctypes.c_uint,
]
user32.SystemParametersInfoW.restype = ctypes.c_int

SPI_GETKEYBOARDDELAY = 0x0016
SPI_GETKEYBOARDSPEED = 0x000A

# Esc, F11 — 留给窗口自己处理
_DEFAULT_IGNORE = frozenset({0x1B, 0x7A})
# 1–6 是鼠标键，从 Backspace(8) 开始扫键盘
_VK_START = 8
_VK_END = 256

# 修饰键 / 锁定键：按下算一次，长按不连发
_NO_REPEAT = frozenset({
    0x10, 0x11, 0x12,       # Shift, Ctrl, Alt
    0x14, 0x90, 0x91,       # Caps, Num, Scroll
    0x5B, 0x5C,             # Win
    0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5,  # L/R Shift/Ctrl/Alt
})


def _repeat_timing() -> tuple[float, float]:
    """读取系统键盘延迟和重复率，返回 (首次重复延迟秒, 连发间隔秒)。"""
    delay_idx = wintypes.UINT(0)
    speed_idx = wintypes.UINT(0)
    user32.SystemParametersInfoW(SPI_GETKEYBOARDDELAY, 0, ctypes.byref(delay_idx), 0)
    user32.SystemParametersInfoW(SPI_GETKEYBOARDSPEED, 0, ctypes.byref(speed_idx), 0)
    delay_s = (int(delay_idx.value) + 1) * 0.25
    hz = 2.5 + (int(speed_idx.value) / 31.0) * 27.5
    interval_s = 1.0 / max(hz, 2.5)
    return delay_s, interval_s


def start_global_keyboard_listener(on_key_down, *, ignore_vk: frozenset[int] | None = None):
    """
    后台线程轮询全局按键。
    按下瞬间触发一次；按住后按系统键盘重复率继续触发（和窗口内 keydown 连发一致）。
    返回 stop()。
    """
    ignore = ignore_vk or _DEFAULT_IGNORE
    stop_event = threading.Event()

    def _run():
        prev = [0] * _VK_END
        held_at = [0.0] * _VK_END
        last_fire = [0.0] * _VK_END
        delay_s, interval_s = _repeat_timing()
        print(
            f"[desk-os] global keyboard listener started "
            f"(repeat delay={delay_s:.2f}s interval={interval_s:.3f}s)",
            flush=True,
        )
        announced = False

        while not stop_event.wait(0.012):
            now = time.perf_counter()
            for vk in range(_VK_START, _VK_END):
                if vk in ignore:
                    continue
                down = 1 if (user32.GetAsyncKeyState(vk) & 0x8000) else 0
                fire = False
                if down and not prev[vk]:
                    fire = True
                    held_at[vk] = now
                    last_fire[vk] = now
                elif down and vk not in _NO_REPEAT:
                    if (now - held_at[vk]) >= delay_s and (now - last_fire[vk]) >= interval_s:
                        fire = True
                        last_fire[vk] = now
                elif not down:
                    held_at[vk] = 0.0

                if fire:
                    try:
                        on_key_down(vk)
                    except Exception as exc:
                        if not announced:
                            print(f"[desk-os] key callback failed: {exc!r}", flush=True)
                    if not announced:
                        announced = True
                        print(f"[desk-os] first global key vk={vk}", flush=True)
                prev[vk] = down

    thread = threading.Thread(target=_run, name="desk-os-kbd", daemon=True)
    thread.start()

    def stop():
        stop_event.set()

    return stop
