"""当前窗口 / 正在播放，供状态行显示。"""

from __future__ import annotations

import ctypes
import os
import re
import sys
import time
from ctypes import wintypes

import psutil

CACHE_SEC = 0.8
SELF_PID = os.getpid()
LABEL_LIMIT = 32

_cache: dict = {"data": None, "time": 0.0}
_last_external: dict | None = None
_proc_names: dict[int, str] = {}

SKIP_TITLES = {
    "program manager",
    "windows input experience",
    "msctfime ui",
    "desk os",
    "task switching",
    "search",
    "settings",
}

SKIP_EXE = {
    "textinputhost.exe",
    "searchhost.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
}

MEDIA_EXE = {
    "spotify.exe",
    "cloudmusic.exe",
    "qqmusic.exe",
    "lyricalyf.exe",
    "music.ui.exe",
    "aimp.exe",
    "foobar2000.exe",
    "vlc.exe",
    "potplayer.exe",
    "potplayermini64.exe",
    "wmplayer.exe",
}

MEDIA_IDLE = {
    "spotify",
    "spotify premium",
    "spotify free",
    "qqmusic",
    "qq音乐",
    "netease cloud music",
    "网易云音乐",
    "vlc media player",
    "vlc",
    "groove music",
    "windows media player",
}

APP_TAIL = {
    "cursor",
    "visual studio code",
    "vs code",
    "code",
    "google chrome",
    "microsoft edge",
    "mozilla firefox",
    "firefox",
    "notepad",
    "notepad++",
    "windows terminal",
    "powershell",
    "windows powershell",
    "sublime text",
    "notion",
    "obsidian",
    "figma",
    "discord",
    "slack",
    "telegram",
    "weixin",
    "微信",
    "spotify",
    "spotify premium",
}

EMPTY = {"available": False, "label": "", "kind": "none", "app": ""}

APP_NAMES = {
    "cursor": "CURSOR",
    "code": "CODE",
    "chrome": "CHROME",
    "msedge": "EDGE",
    "firefox": "FIREFOX",
    "explorer": "EXPLORER",
    "windowsterminal": "TERMINAL",
    "powershell": "POWERSHELL",
    "pwsh": "POWERSHELL",
    "notepad": "NOTEPAD",
    "notepad++": "NOTEPAD",
    "spotify": "SPOTIFY",
    "cloudmusic": "MUSIC",
    "qqmusic": "MUSIC",
    "vlc": "VLC",
    "potplayer": "PLAYER",
    "potplayermini64": "PLAYER",
}


def _empty() -> dict:
    return dict(EMPTY)


if sys.platform == "win32":
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]


def _window_title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value.strip()


def _window_pid(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _proc_name(pid: int) -> str:
    if not pid:
        return ""
    cached = _proc_names.get(pid)
    if cached is not None:
        return cached
    try:
        name = (psutil.Process(pid).name() or "").lower()
    except (psutil.Error, OSError):
        name = ""
    if len(_proc_names) > 96:
        _proc_names.clear()
    _proc_names[pid] = name
    return name


def _enum_windows() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []

    def _cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            title = _window_title(hwnd)
            if title:
                pid = _window_pid(hwnd)
                found.append((title, pid, _proc_name(pid)))
        return True

    cb = WNDENUMPROC(_cb)
    user32.EnumWindows(cb, 0)
    return found


def _is_self(title: str, pid: int) -> bool:
    if pid == SELF_PID:
        return True
    t = (title or "").strip().lower()
    if t == "desk os" or t.startswith("desk os"):
        return True
    cleaned = _strip_app(title).strip().lower()
    return cleaned == "desk os"


def _is_noise(title: str, exe: str) -> bool:
    t = (title or "").strip().lower()
    if not t or t in SKIP_TITLES:
        return True
    if t.startswith("jump list"):
        return True
    return exe in SKIP_EXE


def _strip_app(title: str) -> str:
    parts = [p.strip() for p in re.split(r"\s+[-—–|]\s+", title.strip()) if p.strip()]
    if len(parts) < 2:
        return title.strip()
    last = parts[-1].lower()
    if last in APP_TAIL or last.endswith(" chrome") or last.endswith(" edge"):
        return " / ".join(parts[:-1])
    return title.strip()


def _label(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    if all(ord(c) < 128 for c in text):
        text = text.upper()
    if len(text) > LABEL_LIMIT:
        text = text[: LABEL_LIMIT - 1] + "…"
    return text


def _app_name(exe: str) -> str:
    stem = os.path.splitext(os.path.basename(exe or ""))[0]
    known = APP_NAMES.get(stem.lower())
    if known:
        return known
    if not stem:
        return ""
    name = stem.upper()
    if len(name) <= 12:
        return name
    token = re.split(r"[\s._\-]+", name)[0]
    return (token or name)[:12]


def _pack(title: str, kind: str, exe: str = "") -> dict:
    cleaned = _strip_app(title)
    label = _label(cleaned or title)
    if not label:
        return _empty()
    return {"available": True, "label": label, "kind": kind, "app": _app_name(exe)}


def _media_from(windows: list[tuple[str, int, str]]) -> dict | None:
    for title, _pid, exe in windows:
        if exe not in MEDIA_EXE:
            continue
        packed = _pack(title, "media", exe)
        if not packed["available"]:
            continue
        raw = packed["label"].rstrip("…").lower()
        if raw in MEDIA_IDLE:
            continue
        return packed
    return None


def _read_focus() -> dict:
    global _last_external

    hwnd = user32.GetForegroundWindow()
    title = _window_title(hwnd) if hwnd else ""
    pid = _window_pid(hwnd) if hwnd else 0
    exe = _proc_name(pid)

    if title and not _is_self(title, pid) and not _is_noise(title, exe):
        kind = "media" if exe in MEDIA_EXE else "app"
        packed = _pack(title, kind, exe)
        if packed["available"]:
            if kind == "media":
                raw = packed["label"].rstrip("…").lower()
                if raw in MEDIA_IDLE:
                    packed = _empty()
            if packed["available"]:
                _last_external = packed
                return packed

    media = _media_from(_enum_windows())
    if media:
        _last_external = media
        return media

    if _last_external:
        return _last_external
    return _empty()


def get_focus() -> dict:
    """当前焦点窗口；自己在前台时回落到播放中的歌或上一个窗口。"""
    if sys.platform != "win32":
        return _empty()
    now = time.time()
    if _cache["data"] is not None and now - _cache["time"] < CACHE_SEC:
        return _cache["data"]
    try:
        data = _read_focus()
    except Exception:
        data = _empty()
    _cache["data"] = data
    _cache["time"] = now
    return data
