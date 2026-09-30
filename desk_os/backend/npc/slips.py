"""右侧一句短话。按类别生成，记在本地，不进 NPC 的对话。"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

from backend.npc import llm
from backend.npc.settings import current as npc_config
from backend.paths import DATA_DIR

SLIP_FILE = DATA_DIR / "slips.json"
MAX_ITEMS = 200
TICK_SEC = 20

_LEGACY = {"sci": "科学", "wit": "幽默", "math": "数学", "lit": "文学"}


def _label(kind: str) -> str:
    raw = str(kind or "").strip()
    return (_LEGACY.get(raw.lower(), raw))[:16]


_DRAFT = (
    "用户要给一言新增一个类型。根据类型名字，写一段给写作模型用的提示词，说明这一句该怎么写。"
    "两三句，不要标题，不要引号，不要 markdown，不要 emoji。"
)

_SYSTEM = (
    "你在 Desk OS 右侧留一句短话。"
    "只输出这一句正文，不要标题，不要引号，不要 markdown，不要 emoji。"
    "不超过 60 个字。不要重复 recent 里已经写过的句子，换个说法讲同一件事也算重复。"
)

_lock = threading.Lock()
_gen = threading.Lock()
_items: list[dict] = []
_loaded = False
_started = False
_last_kind = ""
_retry_at = 0.0


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="desk-slip", daemon=True).start()


def _loop() -> None:
    boot = True
    while True:
        try:
            due(boot=boot)
        except Exception as exc:
            print(f"[desk-os] slip: {exc}", flush=True)
        boot = False
        time.sleep(TICK_SEC)


def due(*, boot: bool = False) -> None:
    global _retry_at
    cfg = npc_config()
    if not cfg.get("slip_enabled") or not llm.configured():
        return
    if not boot:
        if time.time() < _retry_at:
            return
        latest = _latest()
        wait = int(cfg.get("slip_min") or 30) * 60
        if latest and time.time() - _epoch(latest.get("timestamp")) < wait:
            return
    if not _gen.acquire(blocking=False):
        return
    try:
        if not _make(cfg):
            _retry_at = time.time() + 120
    finally:
        _gen.release()


def now() -> dict:
    cfg = npc_config()
    if not cfg.get("slip_enabled"):
        return {"ok": False, "skipped": "disabled"}
    if not llm.configured():
        return {"ok": False, "skipped": "llm_not_configured"}
    if not _gen.acquire(timeout=180):
        return {"ok": False, "skipped": "busy"}
    try:
        item = _make(cfg)
    finally:
        _gen.release()
    if not item:
        return {"ok": False, "skipped": "empty"}
    return {"ok": True, "item": item}


def status() -> dict:
    cfg = npc_config()
    items = recent()
    latest = items[0] if items else None
    wait = int(cfg.get("slip_min") or 30) * 60
    elapsed = time.time() - _epoch(latest.get("timestamp")) if latest else wait
    return {
        "enabled": bool(cfg.get("slip_enabled")),
        "minutes": int(cfg.get("slip_min") or 30),
        "kinds": list(cfg.get("slip_kinds") or []),
        "current": latest,
        "items": items,
        "next_in": max(0, int(wait - elapsed)),
    }


def recent() -> list[dict]:
    with _lock:
        _load()
        return [dict(item) for item in reversed(_items)]


def drop(slip_id: str) -> dict:
    wanted = str(slip_id or "").strip()[:40]
    with _lock:
        _load()
        before = len(_items)
        _items[:] = [item for item in _items if item.get("id") != wanted]
        removed = before - len(_items)
        if removed:
            _write()
    return {"ok": True, "removed": removed}


def drop_all() -> dict:
    with _lock:
        _load()
        removed = len(_items)
        _items.clear()
        _write()
    return {"ok": True, "removed": removed}


def _latest() -> dict | None:
    with _lock:
        _load()
        return dict(_items[-1]) if _items else None


def draft_prompt(name: str) -> dict:
    label = _label(name)
    if not label:
        return {"ok": False, "skipped": "empty"}
    if not llm.configured():
        return {"ok": False, "skipped": "llm_not_configured", "name": label}
    if not _gen.acquire(timeout=90):
        return {"ok": False, "skipped": "busy", "name": label}
    try:
        raw = llm.utter(_DRAFT, json.dumps({"name": label}, ensure_ascii=False), limit=240)
    except Exception as exc:
        print(f"[desk-os] slip prompt: {exc}", flush=True)
        raw = ""
    finally:
        _gen.release()
    prompt = str(raw or "").strip().strip("\"“”「」『』")
    if not prompt:
        prompt = f"按「{label}」写一句。不要罗列，不要编造你不确定的事实。"
    return {"ok": True, "name": label, "prompt": prompt[:240]}


def _make(cfg: dict) -> dict | None:
    rows = [item for item in (cfg.get("slip_kinds") or []) if isinstance(item, dict) and item.get("name")]
    if not rows:
        rows = [{"name": "科学", "prompt": "写一句你确定为真的科学事实。不要编造，不要罗列。"}]
    kind = _pick([str(item["name"]) for item in rows])
    prompt = next((str(item.get("prompt") or "") for item in rows if item.get("name") == kind), "")
    recent_text = [item.get("text") or "" for item in recent()[:8]]
    text = ""
    for attempt in range(2):
        ask = prompt or f"按「{kind}」写一句。"
        if attempt:
            ask += "上一句和最近写过的太像，丢掉，换一句完全不同的。"
        try:
            raw = llm.utter(_SYSTEM, json.dumps({
                "kind": kind,
                "ask": ask,
                "recent": recent_text,
            }, ensure_ascii=False))
        except Exception as exc:
            print(f"[desk-os] slip llm: {exc}", flush=True)
            return None
        text = _fit(raw)
        if text and not _close(text, recent_text):
            break
    if not text or _close(text, recent_text):
        return None
    item = {
        "id": f"p{int(time.time() * 1000)}",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "text": text,
    }
    with _lock:
        _load()
        _items.append(item)
        del _items[:-MAX_ITEMS]
        _write()
    return item


def _pick(kinds: list[str]) -> str:
    global _last_kind
    pool = [name for name in kinds if name != _last_kind] or kinds
    kind = pool[int(time.time()) % len(pool)]
    _last_kind = kind
    return kind


def _fit(text: str) -> str:
    line = str(text or "").strip().strip("\"“”「」『』")
    if len(line) <= 90:
        return line
    cut = line[:90]
    for mark in "。！？!?":
        at = cut.rfind(mark)
        if at >= 20:
            return cut[:at + 1]
    return cut.rstrip() + "…"


def _close(text: str, recent_text: list[str]) -> bool:
    fresh = "".join(str(text or "").split())
    if len(fresh) < 4:
        return True
    for old in recent_text:
        other = "".join(str(old or "").split())
        if not other:
            continue
        if fresh == other or fresh[:8] in other or other[:8] in fresh:
            return True
    return False


def _epoch(stamp) -> float:
    try:
        return datetime.fromisoformat(str(stamp)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _load() -> None:
    global _items, _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(SLIP_FILE.read_text(encoding="utf-8"))
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
        kind = _label(str(item.get("kind") or ""))
        text = " ".join(str(item.get("text") or "").split())
        if not kind or not text:
            continue
        kept.append({
            "id": str(item.get("id") or "")[:40],
            "timestamp": str(item.get("timestamp") or ""),
            "kind": kind,
            "text": text[:120],
        })
    _items = kept


def _write() -> None:
    payload = json.dumps({"items": _items}, ensure_ascii=False, indent=2)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SLIP_FILE.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, SLIP_FILE)
