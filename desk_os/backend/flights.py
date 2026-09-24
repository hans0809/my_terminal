"""实时航迹。

全球位置用 OpenSky 的 /states/all。匿名账号每天 400 点，一次全球查询花 4 点，
所以大约 16 分钟才打一次，避免再被限流。额度用完时退回 adsb.lol 的几处空域。
"""

import http.client
import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlparse

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


def _retain(found: dict[str, dict], now: float) -> list[dict]:
    """把这一轮看到的并进记忆，太久没再出现的才删掉。"""
    for icao, plane in found.items():
        _seen[icao] = (now, plane)
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
    return {
        "updated_at": _state["updated_at"],
        "stale": bool(_state["stale"] or not has),
        "offline": bool(_state["offline"] and not _state["aircraft"]),
        "count": int(_state["count"]),
        "aircraft": [dict(plane) for plane in _state["aircraft"]],
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
    rows = []
    if isinstance(payload, dict):
        got = payload.get("ac")
        if not isinstance(got, list):
            got = payload.get("aircraft")
        if isinstance(got, list):
            rows = got
    planes = []
    for row in rows:
        item = _from_adsb(row)
        if item:
            planes.append(item)
    return planes


def _gather(template: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    urls = [template.format(lat=lat, lon=lon) for lat, lon in _HUBS]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(_pull, url) for url in urls]
        for fut in as_completed(futures):
            try:
                for plane in fut.result():
                    found[plane["icao24"]] = plane
            except Exception:
                continue
    return found


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
        found = _gather(_ADSB_URL)
        if len(found) < 8:
            for icao, plane in _gather(_ADSB_FALLBACK).items():
                found.setdefault(icao, plane)
        ttl = HUB_TTL
    if not found:
        raise RuntimeError("adsb")
    now = time.time()
    updated = datetime.now(timezone.utc).isoformat()
    with _lock:
        planes = _retain(found, now)
        _state["fetched_at"] = now
        _state["fresh_until"] = now + ttl
        _state["updated_at"] = updated
        _state["stale"] = False
        _state["offline"] = False
        _state["count"] = len(planes)
        _state["aircraft"] = planes


_route_lock = threading.Lock()
_route_cache: dict[str, tuple[float, dict]] = {}
_route_wait: dict[str, threading.Event] = {}
ROUTE_TTL = 6 * 3600
ROUTE_MISS_TTL = 15 * 60


class _HostPool:
    """复用到同一主机的连接，避免每次查航线都重新握手。"""

    def __init__(self, host: str, size: int = 4):
        self.host = host
        self.size = size
        self.idle: list[http.client.HTTPSConnection] = []
        self.live = 0
        self.cv = threading.Condition()

    def acquire(self) -> http.client.HTTPSConnection:
        with self.cv:
            while True:
                if self.idle:
                    return self.idle.pop()
                if self.live < self.size:
                    self.live += 1
                    break
                self.cv.wait()
        try:
            return _connect_adsbdb()
        except Exception:
            with self.cv:
                self.live = max(0, self.live - 1)
                self.cv.notify()
            raise

    def release(self, conn: http.client.HTTPSConnection, reuse: bool) -> None:
        if not reuse:
            try:
                conn.close()
            except Exception:
                pass
        with self.cv:
            if reuse:
                self.idle.append(conn)
            else:
                self.live = max(0, self.live - 1)
            self.cv.notify()


_adsbdb_pool = _HostPool("api.adsbdb.com")


def _connect_adsbdb() -> http.client.HTTPSConnection:
    """走系统代理。直连这条接口时证书过不了，和浏览器不是同一条路。"""
    raw = urllib.request.getproxies().get("https") or ""
    parsed = urlparse(raw) if raw else None
    if parsed and parsed.hostname:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        conn = http.client.HTTPSConnection(parsed.hostname, port, timeout=6)
        conn.set_tunnel("api.adsbdb.com", 443)
        return conn
    return http.client.HTTPSConnection("api.adsbdb.com", timeout=6)


def _place_name(node) -> str:
    if not isinstance(node, dict):
        return ""
    city = str(node.get("municipality") or "").strip()
    if city:
        return city.upper()
    name = str(node.get("name") or "").strip()
    if name:
        return name.upper()
    code = str(node.get("iata_code") or node.get("icao_code") or "").strip()
    return code.upper()


def _adsbdb_route(key: str) -> dict:
    """查一条航线。连接断了就换一条再试一次。"""
    last = None
    for _ in range(2):
        conn = _adsbdb_pool.acquire()
        reuse = False
        try:
            conn.request(
                "GET",
                f"/v0/callsign/{key}",
                headers={
                    "User-Agent": "DeskOS/1.0",
                    "Accept": "application/json",
                    "Connection": "keep-alive",
                },
            )
            resp = conn.getresponse()
            raw = resp.read()
            if resp.status == 404:
                return {}
            if resp.status != 200:
                raise RuntimeError(f"adsbdb {resp.status}")
            reuse = True
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                return {}
            return payload
        except Exception as exc:
            last = exc
        finally:
            _adsbdb_pool.release(conn, reuse)
    if last:
        raise last
    return {}


def get_route(callsign: str) -> dict:
    """按呼号查起飞、降落城市。查不到就空着，不让主页报错。"""
    key = "".join(ch for ch in str(callsign or "").upper() if ch.isalnum())[:8]
    empty = {"callsign": key, "origin": "", "destination": ""}
    if len(key) < 3:
        return empty
    now = time.time()
    with _route_lock:
        hit = _route_cache.get(key)
        if hit and now - hit[0] < (ROUTE_TTL if hit[1].get("origin") else ROUTE_MISS_TTL):
            return dict(hit[1])
        waited = _route_wait.get(key)
        if waited is None:
            waited = threading.Event()
            _route_wait[key] = waited
            owner = True
        else:
            owner = False
    if not owner:
        waited.wait(timeout=8)
        with _route_lock:
            hit = _route_cache.get(key)
            if hit:
                return dict(hit[1])
        return dict(empty)
    found = dict(empty)
    keep = False
    try:
        payload = _adsbdb_route(key)
        route = {}
        response = payload.get("response") if isinstance(payload, dict) else None
        if isinstance(response, dict) and isinstance(response.get("flightroute"), dict):
            route = response["flightroute"]
        origin = _place_name(route.get("origin"))
        destination = _place_name(route.get("destination"))
        if origin and destination:
            found = {"callsign": key, "origin": origin, "destination": destination}
        keep = True
    except Exception:
        found = dict(empty)
    with _route_lock:
        if keep:
            _route_cache[key] = (time.time(), dict(found))
            if len(_route_cache) > 400:
                oldest = sorted(_route_cache, key=lambda item: _route_cache[item][0])[:80]
                for item in oldest:
                    _route_cache.pop(item, None)
        _route_wait.pop(key, None)
    waited.set()
    return found


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
