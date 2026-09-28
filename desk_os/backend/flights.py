"""实时航迹。

全球位置用 OpenSky 的 /states/all。匿名账号每天 400 点，一次全球查询花 4 点，
所以大约 16 分钟才打一次，避免再被限流。额度用完时退回 adsb.lol 的几处空域。
"""

import json
import math
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

FETCH_TIMEOUT = 8
OPENSKY_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TIMEOUT = 25
# 匿名 400 点/天，全球一次 4 点。16 分钟一次大约 90 次，留一点余量。
OPENSKY_TTL = 16 * 60
HUB_TTL = 60
_ADSB_URL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/250"
_ADSB_FALLBACK = "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/250"
# 几处繁忙空域，拼起来能看见亚洲、欧洲、北美和南半球。
_HUBS = (
    (39.90, 116.40),
    (31.20, 121.50),
    (35.70, 139.80),
    (1.35, 103.80),
    (25.25, 55.36),
    (51.47, -0.45),
    (50.04, 8.56),
    (40.64, -73.78),
    (33.94, -118.41),
    (-33.95, 151.18),
)
# 飞出半径或某次请求漏掉时，先按上次位置再留一会儿。
HOLD_SEC = 100
HUB_NM = 250
MAX_DRAW = 900

_lock = threading.Lock()
_seen: dict[str, tuple[float, dict]] = {}
_opensky_block_until = 0.0
_state = {
    "fetched_at": 0.0,
    "fresh_until": 0.0,
    "updated_at": None,
    "stale": True,
    "offline": True,
    "count": 0,
    "aircraft": [],
    "inflight": False,
}


class _RateLimited(Exception):
    def __init__(self, seconds: float):
        super().__init__("opensky")
        self.seconds = seconds


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_row(row) -> dict | None:
    try:
        if not isinstance(row, (list, tuple)) or len(row) < 9:
            return None
        icao = str(row[0] or "").strip().lower()
        if not icao:
            return None
        if row[8] is True or row[8] == 1:
            return None
        lon = _num(row[5]) if len(row) > 5 else None
        lat = _num(row[6]) if len(row) > 6 else None
        if lon is None or lat is None:
            return None
        if lon < -180 or lon > 180 or lat < -90 or lat > 90:
            return None
        call = str(row[1] or "").strip().upper() if len(row) > 1 else ""
        if not call:
            call = icao.upper()
        alt = _num(row[7]) if len(row) > 7 else None
        vel = _num(row[9]) if len(row) > 9 else None
        hdg = _num(row[10]) if len(row) > 10 else None
        rate = _num(row[11]) if len(row) > 11 else None
        return {
            "icao24": icao,
            "callsign": call,
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "altitude": None if alt is None else round(alt),
            "velocity": 0 if vel is None else round(vel, 1),
            "heading": 0 if hdg is None else round(hdg, 1),
            "vertical_rate": None if rate is None else round(rate, 1),
            "on_ground": False,
        }
    except Exception:
        return None


def _within_nm(lat: float, lon: float, hub_lat: float, hub_lon: float, nm: float) -> bool:
    scale = 6371.0 * math.pi / 180.0
    mean = math.radians((lat + hub_lat) / 2.0)
    dy = (lat - hub_lat) * scale
    dx = (lon - hub_lon) * scale * max(0.2, math.cos(mean))
    limit = nm * 1.852
    return dx * dx + dy * dy <= limit * limit


def _retain(found: dict[str, dict], now: float, hold_hubs: tuple = ()) -> list[dict]:
    """把这一轮看到的并进记忆，太久没再出现的才删掉。

    某个城市的请求失败时，hold_hubs 里的空域先按上次位置留着，
    避免这一片飞机被当成已经飞走而整片消失。
    """
    for icao, plane in found.items():
        _seen[icao] = (now, plane)
    if hold_hubs:
        for icao, (_, plane) in list(_seen.items()):
            lat = plane.get("lat")
            lon = plane.get("lon")
            if lat is None or lon is None:
                continue
            for hub_lat, hub_lon in hold_hubs:
                if _within_nm(float(lat), float(lon), hub_lat, hub_lon, HUB_NM + 30):
                    _seen[icao] = (now, plane)
                    break
    for icao, (seen_at, _) in list(_seen.items()):
        if now - seen_at > HOLD_SEC:
            del _seen[icao]
    ordered = [plane for _, plane in _seen.values()]
    if len(ordered) > MAX_DRAW:
        ordered = sorted(ordered, key=lambda plane: (plane["lon"], plane["lat"], plane["icao24"]))
        step = len(ordered) / MAX_DRAW
        chosen = [ordered[int(i * step)] for i in range(MAX_DRAW)]
        keep = {plane["icao24"] for plane in chosen}
        for icao in list(_seen):
            if icao not in keep:
                del _seen[icao]
        return chosen
    return ordered


def _copy() -> dict:
    has = bool(_state["updated_at"])
    aircraft = []
    for plane in _state["aircraft"]:
        row = dict(plane)
        route = _cached_route(plane.get("callsign"))
        if route and route.get("origin") and route.get("destination"):
            row.update(route)
        aircraft.append(row)
    return {
        "updated_at": _state["updated_at"],
        "stale": bool(_state["stale"] or not has),
        "offline": bool(_state["offline"] and not _state["aircraft"]),
        "count": int(_state["count"]),
        "aircraft": aircraft,
    }


def _from_adsb(row) -> dict | None:
    try:
        if not isinstance(row, dict):
            return None
        alt = row.get("alt_baro")
        if alt == "ground":
            return None
        lat = _num(row.get("lat"))
        lon = _num(row.get("lon"))
        if lat is None or lon is None:
            return None
        if lon < -180 or lon > 180 or lat < -90 or lat > 90:
            return None
        icao = str(row.get("hex") or "").strip().lower()
        if not icao:
            return None
        call = str(row.get("flight") or "").strip().upper()
        if not call:
            call = icao.upper()
        alt_ft = _num(alt)
        alt_m = None if alt_ft is None else round(alt_ft / 3.2808399)
        gs = _num(row.get("gs"))
        heading = _num(row.get("track"))
        if heading is None:
            heading = _num(row.get("true_heading"))
        rate = _num(row.get("baro_rate"))
        return {
            "icao24": icao,
            "callsign": call,
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "altitude": alt_m,
            "velocity": 0 if gs is None else round(gs * 0.514444, 1),
            "heading": 0 if heading is None else round(heading, 1),
            "vertical_rate": None if rate is None else round(rate * 0.00508, 1),
            "on_ground": False,
        }
    except Exception:
        return None


def _pull(url: str) -> list[dict]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DeskOS/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("adsb")
    got = payload.get("ac")
    if not isinstance(got, list):
        got = payload.get("aircraft")
    if not isinstance(got, list):
        raise RuntimeError("adsb")
    rows = got
    planes = []
    for row in rows:
        item = _from_adsb(row)
        if item:
            planes.append(item)
    return planes


def _gather(template: str, hubs=_HUBS) -> tuple[dict[str, dict], tuple]:
    """返回这一轮看到的飞机，以及请求失败的城市中心。"""
    found: dict[str, dict] = {}
    failed = []
    urls = [(lat, lon, template.format(lat=lat, lon=lon)) for lat, lon in hubs]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_pull, url): (lat, lon) for lat, lon, url in urls}
        for fut in as_completed(futures):
            hub = futures[fut]
            try:
                for plane in fut.result():
                    found[plane["icao24"]] = plane
            except Exception:
                failed.append(hub)
    return found, tuple(failed)


def _opensky() -> dict[str, dict]:
    req = urllib.request.Request(
        OPENSKY_URL,
        headers={"User-Agent": "DeskOS/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=OPENSKY_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            retry = 0
            if exc.headers:
                try:
                    retry = int(exc.headers.get("X-Rate-Limit-Retry-After-Seconds") or 0)
                except (TypeError, ValueError):
                    retry = 0
            raise _RateLimited(retry or 60 * 60)
        raise
    rows = payload.get("states") if isinstance(payload, dict) else None
    found: dict[str, dict] = {}
    if isinstance(rows, list):
        for row in rows:
            item = _parse_row(row)
            if item:
                found[item["icao24"]] = item
    if not found:
        raise RuntimeError("opensky")
    return found


def _fetch() -> None:
    global _opensky_block_until
    now = time.time()
    found: dict[str, dict] = {}
    hold_hubs: tuple = ()
    ttl = HUB_TTL
    if now >= _opensky_block_until:
        try:
            found = _opensky()
            ttl = OPENSKY_TTL
        except _RateLimited as exc:
            _opensky_block_until = time.time() + max(60.0, float(exc.seconds))
        except Exception:
            _opensky_block_until = time.time() + 10 * 60
    if not found:
        found, failed = _gather(_ADSB_URL)
        if failed:
            extra, failed = _gather(_ADSB_FALLBACK, failed)
            for icao, plane in extra.items():
                found.setdefault(icao, plane)
        if len(found) < 8 and not failed:
            extra, failed = _gather(_ADSB_FALLBACK)
            for icao, plane in extra.items():
                found.setdefault(icao, plane)
        hold_hubs = failed
        ttl = HUB_TTL
    if not found and not hold_hubs:
        raise RuntimeError("adsb")
    now = time.time()
    updated = datetime.now(timezone.utc).isoformat()
    with _lock:
        if not found and not _seen:
            raise RuntimeError("adsb")
        planes = _retain(found, now, hold_hubs)
        _state["fetched_at"] = now
        _state["fresh_until"] = now + ttl
        _state["updated_at"] = updated
        _state["stale"] = not bool(found)
        _state["offline"] = False
        _state["count"] = len(planes)
        _state["aircraft"] = planes
    _schedule_warm(planes)


_route_lock = threading.Lock()
_route_cache: dict[str, tuple[float, dict]] = {}
_route_wait: dict[str, threading.Event] = {}
_warm_lock = threading.Lock()
_warm_on = False
_save_timer = None
ROUTE_TTL = 6 * 3600
ROUTE_MISS_TTL = 15 * 60
ROUTE_CACHE_MAX = 2000
ROUTE_URL = "https://api.adsb.lol/api/0/route/{callsign}"
ROUTE_FILE = Path(__file__).resolve().parent.parent / "data" / "routes.json"
HOME = (39.90, 116.40)
WARM_WORKERS = 16
WARM_MAX = 900


def _route_key(callsign: str) -> str:
    return "".join(ch for ch in str(callsign or "").upper() if ch.isalnum())[:8]


def _empty_route(key: str) -> dict:
    return {
        "callsign": key,
        "origin": "",
        "destination": "",
        "origin_lat": None,
        "origin_lon": None,
        "destination_lat": None,
        "destination_lon": None,
    }


def _airport_name(node) -> str:
    if not isinstance(node, dict):
        return ""
    place = str(node.get("location") or "").strip()
    if place:
        return place.upper()
    name = str(node.get("name") or "").strip()
    if name:
        return name.upper()
    code = str(node.get("iata") or node.get("icao") or "").strip()
    return code.upper()


def _airport_coord(node, key: str):
    if not isinstance(node, dict):
        return None
    value = _num(node.get(key))
    if value is None:
        return None
    return round(value, 4)


def _from_routeset_row(row) -> dict | None:
    if not isinstance(row, dict):
        return None
    key = _route_key(row.get("callsign"))
    if len(key) < 3:
        return None
    airports = row.get("_airports")
    origin_node = airports[0] if isinstance(airports, list) and airports else None
    dest_node = airports[-1] if isinstance(airports, list) and len(airports) >= 2 else None
    origin = _airport_name(origin_node)
    destination = _airport_name(dest_node)
    if not origin or not destination or origin_node is dest_node:
        return None
    return {
        "callsign": key,
        "origin": origin,
        "destination": destination,
        "origin_lat": _airport_coord(origin_node, "lat"),
        "origin_lon": _airport_coord(origin_node, "lon"),
        "destination_lat": _airport_coord(dest_node, "lat"),
        "destination_lon": _airport_coord(dest_node, "lon"),
    }


def _cache_fresh(hit, now: float) -> bool:
    if not hit:
        return False
    ttl = ROUTE_TTL if hit[1].get("origin") else ROUTE_MISS_TTL
    return now - hit[0] < ttl


def _put_route(key: str, found: dict) -> None:
    with _route_lock:
        _route_cache[key] = (time.time(), dict(found))
        if len(_route_cache) > ROUTE_CACHE_MAX:
            oldest = sorted(_route_cache, key=lambda item: _route_cache[item][0])[:200]
            for item in oldest:
                _route_cache.pop(item, None)
    _schedule_save()


def _cached_route(callsign: str):
    key = _route_key(callsign)
    if len(key) < 3:
        return None
    now = time.time()
    with _route_lock:
        hit = _route_cache.get(key)
        if _cache_fresh(hit, now):
            return dict(hit[1])
    return None


def _load_route_cache() -> None:
    try:
        raw = json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(raw, dict):
        return
    now = time.time()
    loaded = 0
    with _route_lock:
        for key, row in raw.items():
            if not isinstance(row, dict):
                continue
            stamp = _num(row.get("t"))
            if stamp is None:
                continue
            found = _empty_route(_route_key(key))
            found.update({
                "callsign": _route_key(key),
                "origin": str(row.get("origin") or "").strip(),
                "destination": str(row.get("destination") or "").strip(),
                "origin_lat": _num(row.get("origin_lat")),
                "origin_lon": _num(row.get("origin_lon")),
                "destination_lat": _num(row.get("destination_lat")),
                "destination_lon": _num(row.get("destination_lon")),
            })
            hit = (stamp, found)
            if _cache_fresh(hit, now):
                _route_cache[found["callsign"]] = hit
                loaded += 1
                if loaded >= ROUTE_CACHE_MAX:
                    break


def _write_route_cache() -> None:
    now = time.time()
    with _route_lock:
        rows = {}
        for key, (stamp, found) in _route_cache.items():
            if not _cache_fresh((stamp, found), now) or not found.get("origin"):
                continue
            rows[key] = {
                "t": stamp,
                "origin": found.get("origin") or "",
                "destination": found.get("destination") or "",
                "origin_lat": found.get("origin_lat"),
                "origin_lon": found.get("origin_lon"),
                "destination_lat": found.get("destination_lat"),
                "destination_lon": found.get("destination_lon"),
            }
    try:
        ROUTE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = ROUTE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        tmp.replace(ROUTE_FILE)
    except Exception:
        pass


def _schedule_save() -> None:
    global _save_timer
    with _route_lock:
        if _save_timer is not None:
            _save_timer.cancel()
        _save_timer = threading.Timer(2.0, _write_route_cache)
        _save_timer.daemon = True
        _save_timer.start()


def _lol_route(key: str):
    """查一条计划航线。404 表示没有，空着。其它错误往外抛，不写进缓存。"""
    req = urllib.request.Request(
        ROUTE_URL.format(callsign=key),
        headers={"User-Agent": "DeskOS/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 404):
            return {}
        raise
    if not raw:
        raise RuntimeError("route empty")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("route")
    return payload


def _looks_flight(callsign, icao24) -> bool:
    key = _route_key(callsign)
    if len(key) < 3:
        return False
    return key != str(icao24 or "").strip().upper()


def _home_dist(plane: dict) -> float:
    lat = _num(plane.get("lat")) or 0.0
    lon = _num(plane.get("lon")) or 0.0
    dy = lat - HOME[0]
    dx = (lon - HOME[1]) * 0.7
    return dx * dx + dy * dy


def get_route(callsign: str, lat=None, lon=None) -> dict:
    """按呼号查起飞、降落城市和坐标。查不到就空着，不让主页报错。"""
    key = _route_key(callsign)
    empty = _empty_route(key)
    if len(key) < 3:
        return empty
    now = time.time()
    with _route_lock:
        hit = _route_cache.get(key)
        if _cache_fresh(hit, now):
            return dict(hit[1])
        waited = _route_wait.get(key)
        if waited is None:
            waited = threading.Event()
            _route_wait[key] = waited
            owner = True
        else:
            owner = False
    if not owner:
        waited.wait(timeout=14)
        cached = _cached_route(key)
        return dict(cached) if cached else dict(empty)
    found = dict(empty)
    keep = False
    try:
        payload = _lol_route(key)
        parsed = _from_routeset_row(payload)
        found = dict(parsed) if parsed else dict(empty)
        keep = True
    except Exception:
        found = dict(empty)
    if keep:
        _put_route(key, found)
    with _route_lock:
        _route_wait.pop(key, None)
    waited.set()
    return found


def _warm_body(todo: list[dict]) -> None:
    global _warm_on
    try:
        with ThreadPoolExecutor(max_workers=WARM_WORKERS) as pool:
            list(pool.map(lambda item: get_route(item["callsign"]), todo))
    finally:
        with _warm_lock:
            _warm_on = False
        _schedule_save()


def _schedule_warm(planes: list[dict]) -> None:
    global _warm_on
    now = time.time()
    todo = []
    seen = set()
    ranked = sorted(
        (plane for plane in planes if _looks_flight(plane.get("callsign"), plane.get("icao24"))),
        key=_home_dist,
    )
    with _route_lock:
        for plane in ranked:
            key = _route_key(plane.get("callsign"))
            if key in seen:
                continue
            hit = _route_cache.get(key)
            if _cache_fresh(hit, now):
                continue
            seen.add(key)
            todo.append({"callsign": key})
            if len(todo) >= WARM_MAX:
                break
    if not todo:
        return
    with _warm_lock:
        if _warm_on:
            return
        _warm_on = True
    threading.Thread(target=_warm_body, args=(todo,), daemon=True).start()


_load_route_cache()


def get_flights() -> dict:
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
                _state["fresh_until"] = time.time() + 45
                if not _state["updated_at"]:
                    _state["offline"] = True
                    _state["count"] = 0
                    _state["aircraft"] = []
        finally:
            with _lock:
                _state["inflight"] = False
        with _lock:
            return _copy()
    except Exception:
        return {
            "updated_at": None,
            "stale": True,
            "offline": True,
            "count": 0,
            "aircraft": [],
        }
