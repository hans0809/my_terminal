"""把已有采集结果收成一份 DeskContext。这里不发起新的外部数据源。"""

from __future__ import annotations

import threading
from datetime import datetime

_lock = threading.Lock()
_view = {"layer": "status", "app": ""}


def set_view(layer: str, app: str = "") -> dict:
    """前端汇报当前层。这是界面自己的状态，不是新的采集。"""
    name = (layer or "status").strip().lower()
    if name not in {"status", "desk", "app"}:
        name = "status"
    opened = (app or "").strip().lower()[:24]
    with _lock:
        _view["layer"] = name
        _view["app"] = opened
        return dict(_view)


def get_view() -> dict:
    with _lock:
        return dict(_view)


def _page_name(layer: str, app: str) -> str:
    if layer == "desk":
        return "desk"
    if layer == "app" and app:
        return app
    return "home"


def _clip(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _system() -> dict | None:
    from backend.system_monitor import get_system_status

    raw = get_system_status()
    if not isinstance(raw, dict):
        return None
    gpu = raw.get("gpu") if isinstance(raw.get("gpu"), dict) else {}
    gpu_ok = bool(gpu.get("available"))
    ram = raw.get("ram") if isinstance(raw.get("ram"), dict) else {}
    disks = []
    for item in raw.get("disks") or []:
        if not isinstance(item, dict):
            continue
        try:
            used = float(item.get("used_gb"))
            total = float(item.get("total_gb"))
        except (TypeError, ValueError):
            continue
        ratio = round(used / total, 3) if total > 0 else None
        disks.append({
            "drive": item.get("drive"),
            "used_gb": used,
            "total_gb": total,
            "used_ratio": ratio,
        })
    network = raw.get("network") if isinstance(raw.get("network"), dict) else {}
    ping = raw.get("ping") if isinstance(raw.get("ping"), dict) else {}
    temp = gpu.get("temp_c") if gpu_ok else None
    block = {
        "cpu": raw.get("cpu"),
        "ram": {
            "used_gb": ram.get("used_gb"),
            "total_gb": ram.get("total_gb"),
            "percent": ram.get("percent"),
        },
        "gpu": None,
        "vram": None,
        "temperature": None,
        "network": {
            "download": network.get("download"),
            "upload": network.get("upload"),
            "ping_ms": ping.get("ms") if ping.get("available") else None,
            "ping_ok": bool(ping.get("available")),
        },
        "disk": disks,
        "uptime": raw.get("uptime"),
    }
    if gpu_ok:
        block["gpu"] = {
            "usage": gpu.get("usage"),
            "temp_c": temp,
            "mem_used_gb": gpu.get("mem_used_gb"),
            "mem_total_gb": gpu.get("mem_total_gb"),
        }
        block["vram"] = {
            "used_gb": gpu.get("mem_used_gb"),
            "total_gb": gpu.get("mem_total_gb"),
        }
        if temp is not None:
            block["temperature"] = {"gpu_c": temp}
    return block


def _focus() -> dict:
    from backend.focus import get_focus

    data = get_focus()
    if not isinstance(data, dict) or not data.get("available"):
        return {"window": None, "app": None, "kind": None}
    return {
        "window": _clip(data.get("label"), 48) or None,
        "app": data.get("app") or None,
        "kind": data.get("kind") or None,
    }


def _keys() -> dict:
    from backend import key_state

    stats = key_state.get_stats()
    if not isinstance(stats, dict):
        return {"today": None, "recent_5m": None}
    return {
        "today": stats.get("today"),
        "recent_5m": stats.get("recent_5m"),
    }


def _cursor() -> dict | None:
    from backend.cursor_usage import get_cursor_usage

    data = get_cursor_usage()
    if not isinstance(data, dict) or not data.get("available"):
        return None
    return {
        "auto_used_pct": data.get("auto_used_pct"),
        "api_used_pct": data.get("api_used_pct"),
        "reset_label": data.get("reset_label") or None,
    }


def _weather(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        from backend.system_monitor import get_weather

        raw = get_weather()
    if not isinstance(raw, dict) or not raw.get("available"):
        return None
    return {
        "temp_c": raw.get("temp_c"),
        "description": raw.get("description"),
        "place": raw.get("place"),
        "sky": raw.get("sky"),
        "is_day": raw.get("is_day"),
    }


def _rss() -> dict | None:
    from backend.article_service import list_articles

    page = list_articles(limit=1)
    if not isinstance(page, dict):
        return None
    articles = page.get("articles") or []
    counts = page.get("counts") if isinstance(page.get("counts"), dict) else {}
    if not articles:
        if not counts:
            return None
        return {"id": None, "title": None, "source": None, "unread": counts.get("unread")}
    item = articles[0]
    return {
        "id": item.get("id"),
        "title": _clip(item.get("title"), 120) or None,
        "source": _clip(item.get("source"), 40) or None,
        "category": item.get("category") or None,
        "unread": counts.get("unread"),
    }


def _earthquake() -> dict | None:
    from backend.earthquakes import get_earthquakes

    data = get_earthquakes()
    events = data.get("events") if isinstance(data, dict) else None
    if not events:
        return None
    item = events[0]
    if not isinstance(item, dict):
        return None
    return {
        "id": item.get("id"),
        "magnitude": item.get("magnitude"),
        "place": _clip(item.get("place"), 80) or None,
        "time": item.get("time"),
    }


def _aircraft() -> dict | None:
    from backend.flights import get_flights

    data = get_flights()
    if not isinstance(data, dict):
        return None
    if data.get("updated_at") is None and not data.get("count"):
        return None
    return {
        "count": data.get("count"),
        "stale": bool(data.get("stale")),
        "updated_at": data.get("updated_at"),
    }


def _section(fn, fallback):
    try:
        return fn()
    except Exception as exc:
        print(f"[desk-os] npc context: {exc}", flush=True)
        return fallback


def build_context() -> dict:
    """只调用现有读取函数。Git 项目当前没有，projects 为 null。"""
    now = datetime.now()
    view = get_view()
    system = _section(_system, None)
    focus = _section(_focus, {"window": None, "app": None, "kind": None})
    keys = _section(_keys, {"today": None, "recent_5m": None})
    cursor = _section(_cursor, None)
    if isinstance(system, dict) and cursor:
        system["cursor"] = cursor
    page = _page_name(view["layer"], view["app"])
    current_app = view["app"] if view["layer"] == "app" and view["app"] else focus.get("app")
    return {
        "time": now.isoformat(timespec="seconds"),
        "system": system,
        "desk": {
            "current_page": page,
            "current_app": current_app or None,
            "window": focus.get("window"),
            "kind": focus.get("kind"),
            "keys_today": keys.get("today"),
            "keys_recent_5m": keys.get("recent_5m"),
        },
        "projects": None,
        "weather": _section(lambda: _weather(None), None),
        "rss": _section(_rss, None),
        "earthquake": _section(_earthquake, None),
        "aircraft": _section(_aircraft, None),
    }


def compact(ctx: dict) -> dict:
    """去掉空字段，避免把无关 null 整表塞给模型。"""

    def walk(value):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                packed = walk(item)
                if packed is None or packed == {} or packed == []:
                    continue
                out[key] = packed
            return out
        if isinstance(value, list):
            return [walk(item) for item in value if walk(item) is not None]
        return value

    packed = walk(ctx if isinstance(ctx, dict) else {})
    if isinstance(packed, dict) and "projects" not in packed and isinstance(ctx, dict):
        packed["projects"] = None
    return packed if isinstance(packed, dict) else {}
