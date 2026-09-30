"""最近的 NPC 发言。环形 JSON，不进 RSS 数据库。"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

from backend.paths import DATA_DIR

NPC_FILE = DATA_DIR / "npc.json"
MAX_ITEMS = 200
CHAT_GAP_SEC = 30 * 60
_CHAT = {"user", "chat"}

_lock = threading.Lock()
_items: list[dict] = []
_loaded = False
_seq = 0


def _load() -> None:
    global _items, _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(NPC_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        _items = []
        return
    rows = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        _items = []
        return
    kept = []
    for item in rows[-MAX_ITEMS:]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("message") or "").strip()
        if not text:
            continue
        kept.append({
            "id": str(item.get("id") or ""),
            "timestamp": str(item.get("timestamp") or ""),
            "event_type": str(item.get("event_type") or ""),
            "session": str(item.get("session") or ""),
            "project": item.get("project"),
            "message": text[:240],
            "mood": str(item.get("mood") or "idle"),
        })
    changed = _fill(kept)
    _items = kept
    if changed:
        try:
            _save()
        except OSError as exc:
            print(f"[desk-os] npc memory: {exc}", flush=True)


def _save() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"items": _items[-MAX_ITEMS:]}, ensure_ascii=False, indent=2)
    tmp = NPC_FILE.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, NPC_FILE)


def _epoch(text: str) -> float | None:
    try:
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError):
        return None


def _new_id(prefix: str) -> str:
    global _seq
    _seq += 1
    return f"{prefix}{int(time.time() * 1000)}{_seq}"


def _fill(items: list[dict]) -> bool:
    """给旧记录补上 id，并把相邻的用户对话收成一次。"""
    changed = False
    current = ""
    last = 0.0
    for item in items:
        if not item.get("id"):
            item["id"] = _new_id("m")
            changed = True
        if item.get("event_type") not in _CHAT:
            continue
        ts = _epoch(item.get("timestamp") or "") or 0.0
        if not item.get("session"):
            if not current or (last and ts and ts - last > CHAT_GAP_SEC):
                current = _new_id("s")
            item["session"] = current
            changed = True
        else:
            current = item["session"]
        if ts:
            last = ts
    return changed


def add(entry: dict) -> dict | None:
    text = str(entry.get("message") or "").strip()
    if not text:
        return None
    row = {
        "id": str(entry.get("id") or "")[:32],
        "timestamp": str(entry.get("timestamp") or ""),
        "event_type": str(entry.get("event_type") or "")[:32],
        "session": str(entry.get("session") or "")[:40],
        "project": entry.get("project"),
        "message": text[:240],
        "mood": str(entry.get("mood") or "idle")[:16],
    }
    with _lock:
        _load()
        if not row["id"]:
            row["id"] = _new_id("m")
        _items.append(row)
        if len(_items) > MAX_ITEMS:
            del _items[: len(_items) - MAX_ITEMS]
        try:
            _save()
        except OSError as exc:
            print(f"[desk-os] npc memory: {exc}", flush=True)
    return row


def recent(n: int = 8) -> list[dict]:
    n = max(1, min(int(n or 8), MAX_ITEMS))
    with _lock:
        _load()
        return [dict(item) for item in _items[-n:]]


def has_text(text: str) -> bool:
    wanted = str(text or "").strip()
    if not wanted:
        return False
    with _lock:
        _load()
        return any(item.get("message") == wanted for item in _items)


def open_session(new: bool = False, wanted: str = "") -> str:
    """接着某一次对话，或另起一次。半小时内没指定就续最近一次。"""
    wanted = str(wanted or "").strip()[:40]
    with _lock:
        _load()
        if not new and wanted and any(item.get("session") == wanted for item in _items):
            return wanted
        if not new:
            latest = ""
            latest_ts = 0.0
            for item in _items:
                if item.get("event_type") not in _CHAT or not item.get("session"):
                    continue
                ts = _epoch(item.get("timestamp") or "") or 0.0
                if ts >= latest_ts:
                    latest_ts = ts
                    latest = item["session"]
            if latest and latest_ts and time.time() - latest_ts <= CHAT_GAP_SEC:
                return latest
        return _new_id("s")


def conversations() -> list[dict]:
    with _lock:
        _load()
        groups: dict[str, list[dict]] = {}
        order: list[str] = []
        for item in _items:
            sid = item.get("session") or ""
            if not sid or item.get("event_type") not in _CHAT:
                continue
            if sid not in groups:
                groups[sid] = []
                order.append(sid)
            groups[sid].append(dict(item))
    rows = []
    for sid in reversed(order):
        messages = groups[sid]
        preview = next(
            (item["message"] for item in messages if item.get("event_type") == "user"),
            messages[0]["message"],
        )
        rows.append({
            "id": sid,
            "started": messages[0].get("timestamp") or "",
            "preview": preview,
            "messages": [
                {
                    "id": item.get("id") or "",
                    "timestamp": item.get("timestamp") or "",
                    "event_type": item.get("event_type") or "",
                    "message": item.get("message") or "",
                    "mood": item.get("mood") or "idle",
                }
                for item in messages
            ],
        })
    return rows


def drop_session(session_id: str) -> int:
    sid = str(session_id or "").strip()[:40]
    if not sid:
        return 0
    with _lock:
        _load()
        kept = [item for item in _items if item.get("session") != sid]
        removed = len(_items) - len(kept)
        if not removed:
            return 0
        _items[:] = kept
        try:
            _save()
        except OSError as exc:
            print(f"[desk-os] npc memory: {exc}", flush=True)
        return removed


def drop_chats() -> int:
    with _lock:
        _load()
        kept = [item for item in _items if item.get("event_type") not in _CHAT]
        removed = len(_items) - len(kept)
        if not removed:
            return 0
        _items[:] = kept
        try:
            _save()
        except OSError as exc:
            print(f"[desk-os] npc memory: {exc}", flush=True)
        return removed
