"""会话日志。只记状态变化，环形保留，落到 data/log.json。"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_FILE = DATA_DIR / "log.json"
APPS_FILE = DATA_DIR / "apps.json"
MAX_LINES = 180
TAIL = 4
HOME_LINES = 32
TOP_APPS = 4
DEDUPE_SEC = 4
FLOW_FAIL_COOLDOWN = 30 * 60
QUOTA_ON = 80
QUOTA_OFF = 75
TEMP_ON = 80
TEMP_OFF = 74
TITLE_LIMIT = 18
TEXT_LIMIT = 36

LEVELS = {"info", "warn", "event"}

_lock = threading.Lock()
_lines: list[dict] = []
_apps: dict[str, int] = {}
_edges: dict = {}
_flow_fail_at = 0.0
_booted = False


def _load() -> None:
    global _lines
    try:
        raw = json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        _lines = []
        return
    if isinstance(raw, dict):
        raw = raw.get("lines")
    if not isinstance(raw, list):
        _lines = []
        return
    kept = []
    for item in raw[-MAX_LINES:]:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level") or "")
        text = str(item.get("text") or "")
        clock = str(item.get("t") or "")
        if level not in LEVELS or not text or not clock:
            continue
        kept.append({
            "t": clock[:8],
            "level": level,
            "text": text[:TEXT_LIMIT],
            "ts": float(item.get("ts") or 0),
        })
    _lines = kept


def _save() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"lines": _lines[-MAX_LINES:]}, ensure_ascii=False, indent=2)
    tmp = LOG_FILE.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, LOG_FILE)


def _app_label(name: str) -> str:
    name = re.sub(r"\s+", " ", (name or "").strip())
    name = re.sub(r"\s+ACTIVE$", "", name)
    if "…" in name or "/" in name:
        name = re.split(r"[\s/]", name)[0].replace("…", "")
    name = name.strip()
    if name and all(ord(c) < 128 for c in name):
        name = name.upper()
    return name[:12]


def _load_apps() -> None:
    global _apps
    try:
        raw = json.loads(APPS_FILE.read_text(encoding="utf-8"))
        loaded = True
    except (OSError, ValueError, TypeError):
        raw = None
        loaded = False
    apps: dict[str, int] = {}
    if isinstance(raw, dict):
        for key, val in raw.items():
            label = _app_label(str(key))
            try:
                count = int(val)
            except (TypeError, ValueError):
                continue
            if label and count > 0:
                apps[label] = apps.get(label, 0) + count
    if not loaded:
        for row in _lines:
            if not str(row.get("text") or "").endswith(" ACTIVE"):
                continue
            label = _app_label(str(row.get("text") or ""))
            if label:
                apps[label] = apps.get(label, 0) + 1
        _apps = apps
        try:
            _save_apps()
        except OSError as exc:
            print(f"[desk-os] app tally save failed: {exc}", flush=True)
        return
    _apps = apps


def _save_apps() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_apps, ensure_ascii=False, indent=2)
    tmp = APPS_FILE.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, APPS_FILE)


def _touch_app(name: str) -> None:
    label = _app_label(name)
    if not label:
        return
    with _lock:
        _apps[label] = int(_apps.get(label) or 0) + 1
        try:
            _save_apps()
        except OSError as exc:
            print(f"[desk-os] app tally save failed: {exc}", flush=True)


def top_apps(n: int = TOP_APPS) -> list[dict]:
    n = max(1, min(int(n or TOP_APPS), 8))
    with _lock:
        ranked = sorted(_apps.items(), key=lambda item: (-item[1], item[0]))[:n]
    return [{"name": name, "n": count} for name, count in ranked]


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if text and all(ord(c) < 128 for c in text):
        text = text.upper()
    if len(text) > TEXT_LIMIT:
        text = text[: TEXT_LIMIT - 1] + "…"
    return text


def record(level: str, text: str) -> dict | None:
    """写入一行。相同内容在几秒内重复出现时丢掉。"""
    level = (level or "").strip().lower()
    text = _clean(text)
    if level not in LEVELS or not text:
        return None
    now = time.time()
    with _lock:
        if _lines:
            last = _lines[-1]
            if last["level"] == level and last["text"] == text and now - float(last.get("ts") or 0) < DEDUPE_SEC:
                return None
        entry = {
            "t": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "text": text,
            "ts": now,
        }
        _lines.append(entry)
        if len(_lines) > MAX_LINES:
            del _lines[: len(_lines) - MAX_LINES]
        try:
            _save()
        except OSError as exc:
            print(f"[desk-os] log save failed: {exc}", flush=True)
        return {"t": entry["t"], "level": entry["level"], "text": entry["text"]}


def tail(n: int = TAIL) -> list[dict]:
    n = max(1, min(int(n or TAIL), MAX_LINES))
    with _lock:
        rows = _lines[-n:]
    return [{"t": row["t"], "level": row["level"], "text": row["text"]} for row in rows]


def recent(n: int = MAX_LINES) -> list[dict]:
    return tail(n)


def boot() -> None:
    global _booted
    with _lock:
        if _booted:
            return
        _booted = True
    record("info", "SYSTEM ONLINE")


def note_flow(new_n: int, failed: bool) -> None:
    """一批抓取记一行。连续失败半小时内只警告一次。"""
    global _flow_fail_at
    try:
        count = int(new_n or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0:
        record("info", f"FLOW +{count}")
    if not failed:
        _flow_fail_at = 0.0
        return
    now = time.time()
    if now - _flow_fail_at < FLOW_FAIL_COOLDOWN:
        return
    _flow_fail_at = now
    record("warn", "FLOW FETCH FAIL")


def _title(item: dict) -> str:
    text = re.sub(r"\s+", " ", str(item.get("title") or "").strip())
    if not text:
        return "UNTITLED"
    if len(text) > TITLE_LIMIT:
        return text[: TITLE_LIMIT - 1] + "…"
    return text


def note_tasks(before: list[dict], after: list[dict]) -> None:
    prev = {str(item.get("id") or ""): item for item in before if item.get("id")}
    now = {str(item.get("id") or ""): item for item in after if item.get("id")}
    for tid, item in prev.items():
        if tid not in now:
            record("event", f"TASK DROP {_title(item)}")
    for tid, item in now.items():
        old = prev.get(tid)
        if old and not old.get("done") and item.get("done"):
            record("event", f"TASK DONE {_title(item)}")


def _held(key: str, value: float | None, on: float, off: float) -> bool | None:
    if value is None:
        return None
    if _edges.get(key) and value >= off:
        return True
    return value >= on


def _cross(key: str, hot: bool | None, warn: str, ok: str) -> None:
    if hot is None:
        return
    prev = _edges.get(key)
    _edges[key] = hot
    if prev is None:
        if hot:
            record("warn", warn)
        return
    if hot and not prev:
        record("warn", warn)
    elif prev and not hot:
        record("info", ok)


def observe(status: dict) -> None:
    """从一次系统采样里抽出跨线事件。平稳读数不记。"""
    if not isinstance(status, dict):
        return

    focus = status.get("focus") or {}
    label = str(focus.get("label") or "").strip()
    app = str(focus.get("app") or "").strip()
    if focus.get("available") and (app or label):
        kind = focus.get("kind") or ""
        if kind == "media":
            key = f"media:{label}"
            text = f"PLAY {label}"
        else:
            name = app or label
            key = f"app:{name}"
            text = f"{name} ACTIVE"
        if key != _edges.get("focus"):
            wrote = record("event", text)
            _edges["focus"] = key
            if wrote and kind != "media":
                _touch_app(name)
    else:
        _edges["focus"] = ""

    cursor = status.get("cursor") or {}
    if cursor.get("available"):
        cur = float(cursor.get("auto_used_pct") or 0)
        oth = float(cursor.get("api_used_pct") or 0)
        cur_hot = _held("cur", cur, QUOTA_ON, QUOTA_OFF)
        oth_hot = _held("oth", oth, QUOTA_ON, QUOTA_OFF)
        _cross("cur", cur_hot, f"CUR {int(round(cur))}%", "CUR OK")
        _cross("oth", oth_hot, f"OTH {int(round(oth))}%", "OTH OK")

    gpu = status.get("gpu") or {}
    temp = gpu.get("temp_c") if gpu.get("available") else None
    try:
        temp_v = float(temp) if temp is not None else None
    except (TypeError, ValueError):
        temp_v = None
    hot = _held("gpu", temp_v, TEMP_ON, TEMP_OFF)
    warn = f"GPU {int(round(temp_v))}°" if temp_v is not None else "GPU HOT"
    _cross("gpu", hot, warn, "GPU COOL")

    ping = status.get("ping") or {}
    if "available" in ping:
        ok = bool(ping.get("available"))
        prev = _edges.get("ping")
        if prev is None:
            _edges["ping"] = ok
            if not ok:
                _edges["ping_ts"] = time.time()
                record("warn", "PING LOST")
        elif prev != ok and time.time() - float(_edges.get("ping_ts") or 0) >= 60:
            _edges["ping"] = ok
            _edges["ping_ts"] = time.time()
            record("warn" if not ok else "info", "PING LOST" if not ok else "PING OK")


_load()
_load_apps()
