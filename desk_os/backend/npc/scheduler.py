"""决定要不要开口。默认沉默，冷却十分钟，一天有调用上限。"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from backend.npc import llm, memory
from backend.npc.context import build_context, compact, set_view
from backend.npc.events import detect, prepare_trigger
from backend.npc.settings import current as npc_config

TICK_SEC = 45
DAILY_CAP = 24
HOLD_SEC = 180
BACKOFF_SEC = 120
SEEN_SEC = 6 * 3600

_lock = threading.Lock()
_call_lock = threading.Lock()
_started = False
_state = "idle"
_mood = "idle"
_message = ""
_spoken_at = ""
_hold_until = 0.0
_last_call = 0.0
_day = ""
_calls = 0
_seen: dict[str, float] = {}
_retry_after: dict[str, float] = {}
_pending: dict | None = None
_config_warned = False


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    _set("observing", "idle", "", "")
    threading.Thread(target=_loop, name="desk-npc", daemon=True).start()
    print("[desk-os] npc observer started", flush=True)


def _loop() -> None:
    time.sleep(2)
    while True:
        try:
            tick()
        except Exception as exc:
            print(f"[desk-os] npc tick: {exc}", flush=True)
        time.sleep(TICK_SEC)


def tick() -> None:
    global _pending
    cfg = npc_config()
    if not cfg.get("enabled"):
        _pending = None
        _relax()
        return
    ctx = build_context()
    events = detect(ctx)
    best = _pending
    floor = int(cfg.get("min_importance") or 2)
    for item in events:
        if best is None or int(item.get("importance") or 0) > int(best.get("importance") or 0):
            best = item
    if best is not None and int(best.get("importance") or 0) >= floor:
        outcome = speak(best, ctx, force=False)
        if outcome.get("skipped") in {"llm_error", "busy", "backoff"}:
            _pending = best
            return
        spoken = outcome.get("skipped") is None and bool((outcome.get("result") or {}).get("should_speak"))
        _pending = None
        if spoken:
            return
    else:
        _pending = None
    if _ambient_due(cfg):
        speak(_ambient_event(), ctx, force=False)
        return
    _relax()


def _ambient_due(cfg: dict) -> bool:
    cool = int(cfg.get("cooldown_min") or 3) * 60
    if not _last_call:
        return True
    return time.time() - _last_call >= cool


def _ambient_event() -> dict:
    now = time.time()
    return {
        "type": "ambient",
        "timestamp": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
        "importance": 2,
        "data": {"key": f"ambient-{int(now)}"},
    }


def note_view(layer: str, app: str = "") -> dict:
    return set_view(layer, app)


def status() -> dict:
    cfg = npc_config()
    with _lock:
        _roll_day()
        return {
            "state": _state,
            "message": _message,
            "timestamp": _spoken_at or None,
            "mood": _mood,
            "calls_today": _calls,
            "cooldown_s": int(cfg.get("cooldown_min") or 10) * 60,
            "enabled": bool(cfg.get("enabled")),
            "last_call_at": _stamp(_last_call) if _last_call else None,
        }


def history(n: int = 30) -> list[dict]:
    return memory.recent(n)


def conversations() -> list[dict]:
    return memory.conversations()


def forget(session_id: str) -> dict:
    removed = memory.drop_session(session_id)
    _blank_if_missing()
    return {"ok": True, "removed": removed}


def forget_all() -> dict:
    removed = memory.drop_chats()
    _blank_if_missing()
    return {"ok": True, "removed": removed}


def chat(text: str, session: str = "", new: bool = False) -> dict:
    """用户主动开口。不受冷却限制，也不会去操作电脑。"""
    said = " ".join(str(text or "").split())[:200]
    if not said:
        return {"ok": False, "skipped": "empty", "result": _silent()}
    if not llm.configured():
        _warn_config()
        return {"ok": False, "skipped": "llm_not_configured", "result": _silent()}
    sid = memory.open_session(new=new, wanted=session)
    stamp = datetime.now().isoformat(timespec="seconds")
    memory.add({
        "timestamp": stamp,
        "event_type": "user",
        "session": sid,
        "project": None,
        "message": said,
        "mood": "idle",
    })
    ctx = build_context()
    event = {
        "type": "chat",
        "timestamp": stamp,
        "importance": 3,
        "data": {"key": f"chat-{time.time()}", "text": said, "session": sid},
    }
    outcome = speak(event, ctx, force=True, wait=True)
    outcome["session"] = sid
    outcome["ok"] = bool(outcome.get("result", {}).get("should_speak")) and outcome.get("skipped") not in {
        "llm_error",
        "busy",
        "llm_not_configured",
    }
    return outcome


def trigger(event_type: str) -> dict:
    ctx = build_context()
    event = prepare_trigger(event_type, ctx)
    if event is None:
        return {
            "ok": False,
            "skipped": "unknown_event",
            "event": None,
            "result": _silent(),
        }
    outcome = speak(event, ctx, force=True)
    outcome["ok"] = outcome.get("skipped") not in {"llm_not_configured", "llm_error", "busy"}
    return outcome


def gate(event: dict, force: bool = False) -> str | None:
    cfg = npc_config()
    importance = int(event.get("importance") or 0)
    floor = int(cfg.get("min_importance") or 2)
    if event.get("type") != "ambient" and (importance < 2 or (not force and importance < floor)):
        return "quiet"
    if not force and not cfg.get("enabled"):
        return "disabled"
    cap = int(cfg.get("daily_cap") or DAILY_CAP)
    cool = int(cfg.get("cooldown_min") or 10) * 60
    with _lock:
        _roll_day()
        if event.get("type") != "chat" and _calls >= cap:
            return "daily_cap"
    sig = _signature(event)
    now = time.time()
    if not force and now < _retry_after.get(sig, 0):
        return "backoff"
    if not force and _duplicate(sig, importance, now):
        return "duplicate"
    if not force and importance < 4 and _last_call and now - _last_call < cool:
        return "cooldown"
    if not llm.configured():
        _warn_config()
        return "llm_not_configured"
    return None


def speak(event: dict, ctx: dict, force: bool = False, wait: bool = False) -> dict:
    reason = gate(event, force=force)
    if reason:
        if reason in {"quiet", "cooldown", "duplicate", "daily_cap", "llm_not_configured", "disabled"}:
            _relax()
        return {"skipped": reason, "event": event, "result": _silent()}
    if wait:
        got = _call_lock.acquire(timeout=180)
    else:
        got = _call_lock.acquire(blocking=False)
    if not got:
        return {"skipped": "busy", "event": event, "result": _silent()}
    sig = _signature(event)
    try:
        _set("thinking", _mood, _message, _spoken_at)
        _mark_attempt()
        try:
            user_text = ""
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            if event.get("type") == "chat":
                user_text = str(data.get("text") or "")
            notice = (
                "从 context 里挑一件 recent 里还没讲过的事，用一两句说出来。"
                "可以联想，可以轻轻跑开，但不要编造 context 里没有的事实。"
                "同一件事换个说法也算重复。不要罗列数据。"
            )
            ask = {
                "context": compact(ctx),
                "event": event,
                "recent": [
                    {"message": item["message"], "mood": item["mood"], "event_type": item["event_type"]}
                    for item in memory.recent(8)
                ],
                "ask": (
                    f"用户对你说：{user_text}。用一两句自然的话回应。只根据 context 和 recent，没有的就说没看到。不要罗列数据，不要声称你操作了电脑。"
                    if user_text
                    else notice
                ),
            }
            parsed = llm.complete(ask)
            if event.get("type") in {"ambient", "chat"} and not parsed.get("should_speak"):
                try:
                    again = llm.complete(ask)
                except Exception:
                    again = None
                if again and again.get("should_speak"):
                    parsed = again
            if not user_text:
                for _ in range(2):
                    if not _echoes(parsed.get("message") or ""):
                        break
                    ask["ask"] = notice + "上一句和最近说过的太像，丢掉。换一件还没讲过的。"
                    try:
                        again = llm.complete(ask)
                    except Exception:
                        break
                    if again and again.get("should_speak"):
                        parsed = again
        except Exception as exc:
            _retry_after[sig] = time.time() + BACKOFF_SEC
            print(f"[desk-os] npc llm: {exc}", flush=True)
            _relax()
            return {"skipped": "llm_error", "event": event, "result": _silent()}
        _mark_success()
        _remember_seen(sig)
        if not parsed.get("should_speak"):
            _relax()
            return {"skipped": None, "event": event, "result": parsed}
        if event.get("type") != "chat" and _echoes(parsed.get("message") or ""):
            _relax()
            parsed = _silent()
            return {"skipped": "repeat", "event": event, "result": parsed}
        stamp = datetime.now().isoformat(timespec="seconds")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        memory.add({
            "timestamp": stamp,
            "event_type": event.get("type"),
            "session": str(data.get("session") or ""),
            "project": None,
            "message": parsed["message"],
            "mood": parsed["mood"],
        })
        _publish(parsed, stamp, int(event.get("importance") or 0))
        return {"skipped": None, "event": event, "result": parsed}
    finally:
        _call_lock.release()


def _silent() -> dict:
    return {"should_speak": False, "message": "", "mood": "idle", "importance": 0}


def _signature(event: dict) -> str:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    key = data.get("key") or data.get("id") or event.get("type")
    return f"{event.get('type')}:{key}"


def _duplicate(sig: str, importance: int, now: float) -> bool:
    seen = _seen.get(sig)
    if seen is None:
        return False
    return now - seen < SEEN_SEC


def _mark_attempt() -> None:
    global _calls
    with _lock:
        _roll_day()
        _calls += 1


def _mark_success() -> None:
    global _last_call
    _last_call = time.time()


def _remember_seen(sig: str) -> None:
    _seen[sig] = time.time()
    _retry_after.pop(sig, None)


def _echoes(message: str) -> bool:
    """和最近自己说过的话太像，就不算新话题。不针对某一种事件。"""
    fresh = _norm(message)
    if not fresh:
        return True
    grams = _grams(fresh)
    if len(grams) < 4:
        return False
    for item in memory.recent(8):
        if item.get("event_type") == "user":
            continue
        old = _norm(item.get("message") or "")
        if not old:
            continue
        if fresh == old:
            return True
        prev = _grams(old)
        if not prev:
            continue
        shared = len(grams & prev)
        if shared >= 4 and shared / len(grams) >= 0.4:
            return True
    return False


def _grams(text: str) -> set[str]:
    if len(text) < 2:
        return set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _norm(text: str) -> str:
    return "".join(str(text or "").lower().split())


def _publish(parsed: dict, stamp: str, event_importance: int) -> None:
    mood = parsed.get("mood") or "curious"
    rank = max(int(parsed.get("importance") or 0), event_importance)
    if mood == "alert" or rank >= 4:
        state = "alert"
    else:
        state = "curious"
    _set(state, mood, parsed.get("message") or "", stamp, hold=HOLD_SEC)


def _blank_if_missing() -> None:
    if _message and not memory.has_text(_message):
        _set("observing", "idle", "", "")


def _relax() -> None:
    with _lock:
        if time.time() < _hold_until:
            return
        if _state == "thinking":
            nxt = "observing"
        elif _message:
            nxt = "observing"
        elif _started:
            nxt = "observing"
        else:
            nxt = "idle"
        _set_unlocked(nxt, _mood if _message else "idle", _message, _spoken_at)


def _set(state: str, mood: str, message: str, stamp: str, hold: float = 0) -> None:
    with _lock:
        _set_unlocked(state, mood, message, stamp, hold)


def _set_unlocked(state: str, mood: str, message: str, stamp: str, hold: float = 0) -> None:
    global _state, _mood, _message, _spoken_at, _hold_until
    _state = state
    _mood = mood or "idle"
    _message = message or ""
    _spoken_at = stamp or ""
    if hold:
        _hold_until = time.time() + hold


def _roll_day() -> None:
    global _day, _calls
    today = datetime.now().strftime("%Y-%m-%d")
    if today != _day:
        _day = today
        _calls = 0


def _stamp(value: float) -> str:
    return datetime.fromtimestamp(value).isoformat(timespec="seconds")


def _warn_config() -> None:
    global _config_warned
    if _config_warned:
        return
    _config_warned = True
    print("[desk-os] npc llm not configured", flush=True)
