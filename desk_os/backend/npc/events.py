"""对比前后两份 DeskContext，决定有没有值得说的事。不调用模型。"""

from __future__ import annotations

import time
from datetime import datetime

GPU_HOT = 90
CPU_HOT = 90
HOLD_SEC = 10 * 60
DISK_RATIO = 0.95
DISK_FREE_GB = 5
TEMP_HOT = 85
TEMP_SEVERE = 95
PLANE_JUMP = 40
LONG_WORK_SEC = 60 * 60

_prev: dict | None = None


def reset() -> None:
    global _prev
    _prev = None


def _event(kind: str, importance: int, data: dict, now: float) -> dict:
    stamp = datetime.fromtimestamp(now).isoformat(timespec="seconds")
    return {
        "type": kind,
        "timestamp": stamp,
        "importance": max(0, min(4, int(importance))),
        "data": data,
    }


def _num(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def detect(ctx: dict, now: float | None = None) -> list[dict]:
    """第一眼只建立基线。磁盘将满、GPU 温度极高例外，避免漏掉已经发生的严重情况。"""
    global _prev
    now = time.time() if now is None else float(now)
    ctx = ctx if isinstance(ctx, dict) else {}
    found: list[dict] = []
    baseline = _prev
    snap = _snapshot(ctx, now, baseline)
    if baseline is None:
        found.extend(_critical(snap, now))
        _prev = snap
        return found
    found.extend(_diff(baseline, snap, now))
    _prev = snap
    return found


def _snapshot(ctx: dict, now: float, prev: dict | None) -> dict:
    system = ctx.get("system") if isinstance(ctx.get("system"), dict) else {}
    gpu = system.get("gpu") if isinstance(system.get("gpu"), dict) else {}
    desk = ctx.get("desk") if isinstance(ctx.get("desk"), dict) else {}
    weather = ctx.get("weather") if isinstance(ctx.get("weather"), dict) else {}
    rss = ctx.get("rss") if isinstance(ctx.get("rss"), dict) else {}
    quake = ctx.get("earthquake") if isinstance(ctx.get("earthquake"), dict) else {}
    planes = ctx.get("aircraft") if isinstance(ctx.get("aircraft"), dict) else {}
    network = system.get("network") if isinstance(system.get("network"), dict) else {}
    usage = _num(gpu.get("usage"))
    cpu = _num(system.get("cpu"))
    app = str(desk.get("current_app") or "")
    earlier = prev or {}
    held_gpu = earlier.get("gpu_since")
    held_cpu = earlier.get("cpu_since")
    focus_since = earlier.get("focus_since")
    focus_key = earlier.get("focus_key")
    if usage is not None and usage >= GPU_HOT:
        gpu_since = now if held_gpu is None else held_gpu
    else:
        gpu_since = None
    if cpu is not None and cpu >= CPU_HOT:
        cpu_since = now if held_cpu is None else held_cpu
    else:
        cpu_since = None
    if app and app == focus_key and focus_since is not None:
        since = focus_since
    elif app:
        since = now
    else:
        since = None
    return {
        "cpu": cpu,
        "gpu": usage,
        "gpu_temp": _num(gpu.get("temp_c")),
        "gpu_since": gpu_since,
        "gpu_held": bool(earlier.get("gpu_held")) if gpu_since is not None else False,
        "cpu_since": cpu_since,
        "cpu_held": bool(earlier.get("cpu_held")) if cpu_since is not None else False,
        "disks": _disks(system.get("disk")),
        "disk_hot": set((prev or {}).get("disk_hot") or ()),
        "weather_desc": str(weather.get("description") or ""),
        "weather_temp": _num(weather.get("temp_c")),
        "article_id": rss.get("id"),
        "article_title": rss.get("title"),
        "article_source": rss.get("source"),
        "quake_id": quake.get("id"),
        "quake_mag": _num(quake.get("magnitude")),
        "quake_place": quake.get("place"),
        "planes": _num(planes.get("count")),
        "page": str(desk.get("current_page") or ""),
        "app": app,
        "kind": str(desk.get("kind") or ""),
        "window": desk.get("window"),
        "focus_key": app,
        "focus_since": since,
        "focus_sent": bool((prev or {}).get("focus_sent")) if app and app == focus_key else False,
        "ping_ok": network.get("ping_ok"),
        "cursor": _num((system.get("cursor") or {}).get("auto_used_pct")) if isinstance(system.get("cursor"), dict) else None,
        "cursor_hot": bool((prev or {}).get("cursor_hot")),
        "temp_hot": bool((prev or {}).get("temp_hot")),
    }


def _disks(rows) -> list[dict]:
    found = []
    if not isinstance(rows, list):
        return found
    for item in rows:
        if not isinstance(item, dict):
            continue
        ratio = _num(item.get("used_ratio"))
        total = _num(item.get("total_gb"))
        used = _num(item.get("used_gb"))
        free = None if total is None or used is None else total - used
        found.append({
            "drive": str(item.get("drive") or ""),
            "used_ratio": ratio,
            "free_gb": free,
        })
    return found


def _disk_hot(item: dict) -> bool:
    ratio = item.get("used_ratio")
    free = item.get("free_gb")
    if ratio is not None and ratio >= DISK_RATIO:
        return True
    return free is not None and free <= DISK_FREE_GB


def _disk_cool(item: dict) -> bool:
    """腾出一截空间才算恢复，免得在阈值边上反复告警。"""
    ratio = item.get("used_ratio")
    free = item.get("free_gb")
    ratio_ok = ratio is None or ratio < 0.90
    free_ok = free is None or free > 8
    return ratio_ok and free_ok and not _disk_hot(item)


def _critical(snap: dict, now: float) -> list[dict]:
    found = []
    hot = set()
    for item in snap["disks"]:
        if not _disk_hot(item):
            continue
        hot.add(item["drive"])
        found.append(_event("disk_warning", 4, {
            "key": item["drive"] or "disk",
            "drive": item["drive"],
            "used_ratio": item["used_ratio"],
            "free_gb": None if item["free_gb"] is None else round(item["free_gb"], 1),
        }, now))
    snap["disk_hot"] = hot
    temp = snap.get("gpu_temp")
    if temp is not None and temp >= TEMP_SEVERE:
        snap["temp_hot"] = True
        found.append(_event("system_change", 4, {
            "key": "gpu-temp",
            "gpu_c": temp,
        }, now))
    return found


def _diff(old: dict, snap: dict, now: float) -> list[dict]:
    found = []
    found.extend(_load_events(old, snap, now))
    found.extend(_disk_events(old, snap, now))
    found.extend(_quiet_events(old, snap, now))
    return found


def _load_events(old: dict, snap: dict, now: float) -> list[dict]:
    found = []
    gpu = snap.get("gpu")
    if gpu is not None and gpu >= GPU_HOT and (old.get("gpu") is None or old.get("gpu") < GPU_HOT):
        found.append(_event("high_gpu", 2, {"key": "cross", "usage": gpu, "phase": "cross"}, now))
    if snap.get("gpu_since") is not None and not snap.get("gpu_held") and now - float(snap["gpu_since"]) >= HOLD_SEC:
        snap["gpu_held"] = True
        found.append(_event("high_gpu", 3, {
            "key": "hold",
            "usage": gpu,
            "minutes": int((now - float(snap["gpu_since"])) // 60),
            "phase": "hold",
        }, now))
    cpu = snap.get("cpu")
    if cpu is not None and cpu >= CPU_HOT and (old.get("cpu") is None or old.get("cpu") < CPU_HOT):
        found.append(_event("high_cpu", 2, {"key": "cross", "usage": cpu, "phase": "cross"}, now))
    if snap.get("cpu_since") is not None and not snap.get("cpu_held") and now - float(snap["cpu_since"]) >= HOLD_SEC:
        snap["cpu_held"] = True
        found.append(_event("high_cpu", 3, {
            "key": "hold",
            "usage": cpu,
            "minutes": int((now - float(snap["cpu_since"])) // 60),
            "phase": "hold",
        }, now))
    temp = snap.get("gpu_temp")
    was = old.get("gpu_temp")
    if temp is not None and temp >= TEMP_HOT and (was is None or was < TEMP_HOT):
        rank = 4 if temp >= TEMP_SEVERE else 3
        snap["temp_hot"] = True
        found.append(_event("system_change", rank, {"key": "gpu-temp", "gpu_c": temp}, now))
    elif temp is None or temp < TEMP_HOT - 5:
        snap["temp_hot"] = False
    return found


def _disk_events(old: dict, snap: dict, now: float) -> list[dict]:
    found = []
    hot = set(old.get("disk_hot") or ())
    for item in snap["disks"]:
        drive = item["drive"]
        if _disk_hot(item) and drive not in hot:
            hot.add(drive)
            found.append(_event("disk_warning", 4, {
                "key": drive or "disk",
                "drive": drive,
                "used_ratio": item["used_ratio"],
                "free_gb": None if item["free_gb"] is None else round(item["free_gb"], 1),
            }, now))
        elif _disk_cool(item):
            hot.discard(drive)
    snap["disk_hot"] = hot
    return found


def _quiet_events(old: dict, snap: dict, now: float) -> list[dict]:
    found = []
    desc = snap.get("weather_desc") or ""
    temp = snap.get("weather_temp")
    old_temp = old.get("weather_temp")
    if desc and old.get("weather_desc") and (
        desc != old.get("weather_desc") or (
            temp is not None and old_temp is not None and abs(temp - old_temp) >= 3
        )
    ):
        found.append(_event("weather_change", 2, {
            "key": f"{desc}:{temp}",
            "description": desc,
            "temp_c": temp,
        }, now))
    if snap.get("page") and old.get("page") and snap["page"] != old["page"]:
        found.append(_event("app_change", 1, {
            "key": snap["page"],
            "page": snap["page"],
            "app": snap.get("app") or None,
        }, now))
    elif snap.get("app") and old.get("app") and snap["app"] != old["app"]:
        rank = 2 if snap.get("kind") == "media" else 1
        found.append(_event("app_change", rank, {
            "key": snap["app"],
            "app": snap["app"],
            "window": snap.get("window"),
        }, now))
    article = snap.get("article_id")
    if article and old.get("article_id") and article != old.get("article_id"):
        found.append(_event("rss_update", 2, {
            "key": str(article),
            "id": article,
            "title": snap.get("article_title"),
            "source": snap.get("article_source"),
        }, now))
    quake = snap.get("quake_id")
    if quake and old.get("quake_id") and quake != old.get("quake_id"):
        mag = snap.get("quake_mag") or 0
        if mag >= 6:
            rank = 4
        elif mag >= 5:
            rank = 3
        elif mag >= 4.5:
            rank = 2
        else:
            rank = 1
        found.append(_event("earthquake_update", rank, {
            "key": str(quake),
            "id": quake,
            "magnitude": snap.get("quake_mag"),
            "place": snap.get("quake_place"),
        }, now))
    planes = snap.get("planes")
    old_planes = old.get("planes")
    if planes is not None and old_planes is not None and abs(planes - old_planes) >= PLANE_JUMP:
        found.append(_event("aircraft_update", 2, {
            "key": str(int(planes) // PLANE_JUMP),
            "count": planes,
            "delta": planes - old_planes,
        }, now))
    if (
        snap.get("focus_since") is not None
        and snap.get("app")
        and snap.get("kind") != "media"
        and not snap.get("focus_sent")
        and now - float(snap["focus_since"]) >= LONG_WORK_SEC
    ):
        snap["focus_sent"] = True
        found.append(_event("long_work", 2, {
            "key": snap["app"],
            "app": snap["app"],
            "minutes": int((now - float(snap["focus_since"])) // 60),
        }, now))
    ping = snap.get("ping_ok")
    old_ping = old.get("ping_ok")
    if old_ping is True and ping is False:
        found.append(_event("system_change", 2, {"key": "ping-lost", "ping_ok": False}, now))
    elif old_ping is False and ping is True:
        found.append(_event("system_change", 1, {"key": "ping-ok", "ping_ok": True}, now))
    cursor = snap.get("cursor")
    old_cursor = old.get("cursor")
    if cursor is not None and cursor >= 90 and (old_cursor is None or old_cursor < 90) and not snap.get("cursor_hot"):
        snap["cursor_hot"] = True
        found.append(_event("system_change", 3, {"key": "cursor", "auto_used_pct": cursor}, now))
    elif cursor is not None and cursor < 85:
        snap["cursor_hot"] = False
    return found


def prepare_trigger(kind: str, ctx: dict) -> dict | None:
    """开发触发。只改这份临时上下文，不写回监控。未知类型返回 None。"""
    kind = (kind or "").strip().lower()
    now = time.time()
    system = ctx.setdefault("system", {}) if isinstance(ctx.get("system"), dict) else {}
    if not isinstance(ctx.get("system"), dict):
        ctx["system"] = system
    desk = ctx.setdefault("desk", {}) if isinstance(ctx.get("desk"), dict) else {}
    if not isinstance(ctx.get("desk"), dict):
        ctx["desk"] = desk

    if kind == "ordinary_state":
        return _event(kind, 0, {"key": "ordinary"}, now)
    if kind == "git_commit":
        ctx["projects"] = None
        return _event(kind, 0, {"key": "git", "available": False}, now)
    if kind == "high_gpu":
        gpu = system.get("gpu") if isinstance(system.get("gpu"), dict) else {}
        gpu["usage"] = 96
        system["gpu"] = gpu
        return _event(kind, 3, {"key": "trigger", "usage": 96, "phase": "trigger"}, now)
    if kind == "high_cpu":
        system["cpu"] = 96
        return _event(kind, 3, {"key": "trigger", "usage": 96}, now)
    if kind == "long_work":
        app = desk.get("current_app") or "CURSOR"
        desk["current_app"] = app
        return _event(kind, 2, {"key": "trigger", "app": app, "minutes": 90}, now)
    if kind == "rss_update":
        rss = ctx.get("rss") if isinstance(ctx.get("rss"), dict) else {}
        if not rss.get("title"):
            rss = {"id": "trigger", "title": "TEST FEED ITEM", "source": "TEST", "unread": rss.get("unread")}
            ctx["rss"] = rss
        return _event(kind, 2, {
            "key": "trigger",
            "id": rss.get("id"),
            "title": rss.get("title"),
            "source": rss.get("source"),
        }, now)
    if kind == "earthquake_update":
        quake = ctx.get("earthquake") if isinstance(ctx.get("earthquake"), dict) else {}
        if quake.get("magnitude") is None:
            quake = {"id": "trigger", "magnitude": 5.6, "place": "TEST", "time": None}
            ctx["earthquake"] = quake
        mag = quake.get("magnitude")
        rank = 4 if isinstance(mag, (int, float)) and mag >= 6 else 3
        return _event(kind, rank, {
            "key": "trigger",
            "id": quake.get("id"),
            "magnitude": mag,
            "place": quake.get("place"),
        }, now)
    if kind == "disk_warning":
        system["disk"] = [{
            "drive": "C",
            "used_gb": 498,
            "total_gb": 500,
            "used_ratio": 0.996,
        }]
        return _event(kind, 4, {"key": "trigger", "drive": "C", "used_ratio": 0.996, "free_gb": 2}, now)
    if kind == "weather_change":
        weather = ctx.get("weather") if isinstance(ctx.get("weather"), dict) else {}
        return _event(kind, 2, {
            "key": "trigger",
            "description": weather.get("description"),
            "temp_c": weather.get("temp_c"),
        }, now)
    if kind == "aircraft_update":
        planes = ctx.get("aircraft") if isinstance(ctx.get("aircraft"), dict) else {}
        return _event(kind, 2, {"key": "trigger", "count": planes.get("count")}, now)
    if kind == "app_change":
        return _event(kind, 1, {"key": "trigger", "app": desk.get("current_app"), "page": desk.get("current_page")}, now)
    if kind == "system_change":
        return _event(kind, 2, {"key": "trigger"}, now)
    return None
