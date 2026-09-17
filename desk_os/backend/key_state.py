"""全局键盘脉冲计数（监听线程写入，推送/SSE/前端读取）"""

from __future__ import annotations

import atexit
import json
import os
import threading
import time
from collections import deque
from datetime import date
from pathlib import Path

_lock = threading.Lock()
_changed = threading.Event()
key_pulse: int = 0
_read_mark: int = 0

_WINDOW_SEC = 300.0
_recent: deque[float] = deque()
_day = date.today().isoformat()
_day_count = 0
_last_save = 0.0
_dirty = False

_STATE_PATH = (
    Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DeskOS" / "keys.json"
)


def _load() -> None:
    global _day, _day_count
    try:
        raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return
    saved_day = str(raw.get("date") or "")
    try:
        count = int(raw.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    today = date.today().isoformat()
    if saved_day == today and count > 0:
        _day = today
        _day_count = count


def _flush() -> None:
    global _last_save, _dirty
    with _lock:
        if not _dirty:
            return
        payload = {"date": _day, "count": _day_count}
        _dirty = False
        _last_save = time.time()
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(_STATE_PATH)
    except OSError:
        pass


def bump(*_args) -> None:
    global key_pulse, _day, _day_count, _dirty
    now = time.time()
    today = date.today().isoformat()
    with _lock:
        key_pulse += 1
        if today != _day:
            _day = today
            _day_count = 0
            _recent.clear()
        _day_count += 1
        _recent.append(now)
        cutoff = now - _WINDOW_SEC
        while _recent and _recent[0] < cutoff:
            _recent.popleft()
        _dirty = True
        should_save = _day_count % 20 == 0 or now - _last_save > 8
    _changed.set()
    if should_save:
        _flush()


def read() -> int:
    with _lock:
        return key_pulse


def wait_pulse(timeout: float = 0.4) -> int:
    _changed.wait(timeout)
    _changed.clear()
    return read()


def pending() -> int:
    with _lock:
        return key_pulse - _read_mark


def confirm(count: int) -> None:
    global _read_mark
    if count <= 0:
        return
    with _lock:
        _read_mark = min(key_pulse, _read_mark + count)


def consume() -> int:
    global _read_mark
    with _lock:
        delta = key_pulse - _read_mark
        _read_mark = key_pulse
        return delta


def get_stats() -> dict:
    now = time.time()
    with _lock:
        cutoff = now - _WINDOW_SEC
        while _recent and _recent[0] < cutoff:
            _recent.popleft()
        recent = len(_recent)
        today = _day_count
    return {
        "today": today,
        "recent_5m": recent,
        "per_min": round(recent / 5.0, 1),
    }


_load()
atexit.register(_flush)
