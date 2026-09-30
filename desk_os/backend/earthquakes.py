"""USGS 最近一小时地震。

前端只读本地接口。USGS 最多 60 秒打一次；失败时退回上一份成功数据。
震级达到地图阈值的，另记在本地，超出这一小时也还在。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from backend.paths import DATA_DIR

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
HISTORY_FILE = DATA_DIR / "earthquakes.json"
FETCH_TIMEOUT = 10
USGS_TTL = 60
FAIL_TTL = 60
EARTHQUAKE_MIN_MAGNITUDE = 2.0
HISTORY_HOURS = 24
HISTORY_MAX = 48

_lock = threading.Lock()
_state = {
    "fetched_at": 0.0,
    "fresh_until": 0.0,
    "updated_at": None,
    "stale": True,
    "events": [],
    "inflight": False,
}
_history: list[dict] = []
_history_loaded = False


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(ms) -> str | None:
    stamp = _num(ms)
    if stamp is None:
        return None
    try:
        return datetime.fromtimestamp(stamp / 1000.0, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _place(raw) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if "," in text:
        return text.rsplit(",", 1)[-1].strip()
    return text


def _parse_feature(feature) -> dict | None:
    try:
        if not isinstance(feature, dict):
            return None
        eid = str(feature.get("id") or "").strip()
        if not eid:
            return None
        props = feature.get("properties")
        geom = feature.get("geometry")
        if not isinstance(props, dict) or not isinstance(geom, dict):
            return None
        coords = geom.get("coordinates")
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            return None
        lon = _num(coords[0])
        lat = _num(coords[1])
        depth = _num(coords[2]) if len(coords) > 2 else None
        if lon is None or lat is None:
            return None
        if lon < -180 or lon > 180 or lat < -90 or lat > 90:
            return None
        mag = _num(props.get("mag"))
        if mag is None:
            return None
        when = _iso(props.get("time"))
        if not when:
            return None
        return {
            "id": eid[:48],
            "magnitude": round(mag, 2),
            "place": _place(props.get("place"))[:80],
            "time": when,
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "depth": None if depth is None else round(depth, 1),
        }
    except Exception:
        return None


def _copy() -> dict:
    return {
        "updated_at": _state["updated_at"],
        "stale": bool(_state["stale"] or not _state["updated_at"]),
        "events": [dict(item) for item in _state["events"]],
    }


def _fetch() -> None:
    req = urllib.request.Request(
        USGS_URL,
        headers={"User-Agent": "DeskOS/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("usgs")
    rows = payload.get("features")
    if not isinstance(rows, list):
        raise RuntimeError("usgs")
    events = []
    for row in rows:
        item = _parse_feature(row)
        if item:
            events.append(item)
    events.sort(key=lambda item: item["time"], reverse=True)
    now = time.time()
    with _lock:
        _state["fetched_at"] = now
        _state["fresh_until"] = now + USGS_TTL
        _state["updated_at"] = datetime.now(timezone.utc).isoformat()
        _state["stale"] = False
        _state["events"] = events
        _remember(events)


def _epoch(iso: str) -> float:
    try:
        parsed = datetime.fromisoformat(str(iso))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.timestamp()
    except (OSError, OverflowError, ValueError):
        return 0.0


def _load_history() -> None:
    global _history, _history_loaded
    if _history_loaded:
        return
    _history_loaded = True
    try:
        raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        _history = []
        return
    rows = raw.get("events") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        _history = []
        return
    kept = []
    seen = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("id") or "").strip()[:48]
        when = str(item.get("time") or "").strip()
        mag = _num(item.get("magnitude"))
        if not eid or not when or mag is None or eid in seen:
            continue
        if mag < EARTHQUAKE_MIN_MAGNITUDE:
            continue
        seen.add(eid)
        kept.append({
            "id": eid,
            "magnitude": round(mag, 2),
            "place": str(item.get("place") or "").strip()[:80],
            "time": when,
        })
    _history = _prune(kept)


def _prune(rows: list[dict]) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=HISTORY_HOURS)).timestamp()
    fresh = [item for item in rows if _epoch(item.get("time")) >= cutoff]
    fresh.sort(key=lambda item: item.get("time") or "", reverse=True)
    return fresh[:HISTORY_MAX]


def _remember(events: list[dict]) -> None:
    """把这一小时里够得上地图的地震并进本地记录。调用时已持有 _lock。"""
    global _history
    _load_history()
    by_id = {item["id"]: item for item in _history}
    for item in events:
        mag = item.get("magnitude")
        if mag is None or mag < EARTHQUAKE_MIN_MAGNITUDE:
            continue
        by_id[item["id"]] = {
            "id": item["id"],
            "magnitude": item["magnitude"],
            "place": item.get("place") or "",
            "time": item["time"],
        }
    _history = _prune(list(by_id.values()))
    try:
        payload = json.dumps({"events": _history}, ensure_ascii=False, indent=2)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(HISTORY_FILE)
    except OSError as exc:
        print(f"[desk-os] earthquake history: {exc}", flush=True)


def history() -> list[dict]:
    """最近一天里记下的地震，新的在前。会顺手刷新 USGS。"""
    try:
        get_earthquakes()
    except Exception:
        pass
    with _lock:
        _load_history()
        return [dict(item) for item in _history]


def get_earthquakes() -> dict:
    """缓存命中直接返回。失败时保留上一份成功数据，并标 stale。"""
    try:
        now = time.time()
        with _lock:
            age_ok = now < float(_state.get("fresh_until") or 0)
            if _state["inflight"] or age_ok:
                return _copy()
            _state["inflight"] = True
        try:
            _fetch()
        except Exception:
            with _lock:
                _state["stale"] = True
                _state["fetched_at"] = time.time()
                _state["fresh_until"] = time.time() + FAIL_TTL
        finally:
            with _lock:
                _state["inflight"] = False
        with _lock:
            return _copy()
    except Exception:
        return {
            "updated_at": None,
            "stale": True,
            "events": [],
        }
