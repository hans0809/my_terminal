"""Cursor 额度 — 读取本机登录态，拉取当前计费周期用量 / 剩余。

无官方个人 API。沿用 Cursor 本机 state.vscdb 中的 accessToken，
请求 api2.cursor.sh 的 DashboardService（与 OpenUsage / Usage Status 相同路径）。
Token 只在内存中短暂使用，不写入日志、不返回给前端。
"""

from __future__ import annotations

import json
import os
import sqlite3
import ssl
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

USAGE_URL = (
    "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
)
REFRESH_INTERVAL = 90
FAIL_RETRY_INTERVAL = 12
HTTP_TIMEOUT = 25
HTTP_RETRIES = 3
AUTH_TTL = 600

UNAVAILABLE = {"available": False, "pending": False, "label": "N/A"}
PENDING = {"available": False, "pending": True, "label": "--"}

PLAN_LABELS = {
    "free": "Free",
    "pro": "Pro",
    "pro_plus": "Pro+",
    "ultra": "Ultra",
    "business": "Biz",
    "team": "Team",
    "enterprise": "Ent",
}

_lock = threading.Lock()
_cache: dict = dict(PENDING)
_cache_time = 0.0
_worker_started = False
_ssl_ctx = ssl.create_default_context()
_auth_cache = {"token": "", "plan": "", "time": 0.0}


def _log(msg: str) -> None:
    print(f"[desk-os] cursor usage: {msg}", flush=True)


def _state_db_path() -> Path | None:
    override = os.environ.get("DESK_OS_CURSOR_STATE_DB")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    return None


def _open_state_db(db_path: Path) -> sqlite3.Connection:
    p = str(db_path).replace("\\", "/")
    last_err: Exception | None = None
    candidates = (
        ("uri", f"file:{p}?mode=ro"),
        ("uri", f"file:{p}?mode=ro&immutable=1"),
        ("path", str(db_path)),
    )
    for kind, target in candidates:
        conn = None
        try:
            if kind == "uri":
                conn = sqlite3.connect(target, uri=True, timeout=8)
            else:
                conn = sqlite3.connect(target, timeout=8)
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute(
                "SELECT value FROM ItemTable WHERE key=? LIMIT 1",
                ("cursorAuth/accessToken",),
            ).fetchone()
            return conn
        except sqlite3.Error as exc:
            last_err = exc
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
    raise last_err or sqlite3.Error("unable to open Cursor state db")


def _read_item(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
    if not row or row[0] is None:
        return ""
    value = row[0]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def _read_auth() -> tuple[str, str]:
    env_token = (os.environ.get("DESK_OS_CURSOR_TOKEN") or "").strip()
    now = time.time()
    with _lock:
        cached_token = _auth_cache["token"]
        cached_plan = _auth_cache["plan"]
        cached_at = _auth_cache["time"]
    if cached_token and now - cached_at < AUTH_TTL:
        return env_token or cached_token, cached_plan

    db_path = _state_db_path()
    plan = cached_plan
    token = env_token
    if db_path and db_path.exists():
        conn = _open_state_db(db_path)
        try:
            if not token:
                token = _read_item(conn, "cursorAuth/accessToken")
            plan = _read_item(conn, "cursorAuth/stripeMembershipType") or plan
        finally:
            conn.close()

    if token:
        with _lock:
            _auth_cache["token"] = token
            _auth_cache["plan"] = plan
            _auth_cache["time"] = now
    return token, plan


def _ms_label(raw) -> str:
    if raw is None or raw == "":
        return ""
    try:
        n = int(raw)
        ts = n / 1000.0 if n > 10**12 else float(n)
        return datetime.fromtimestamp(ts).strftime("%d %b").upper()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _plan_label(raw: str) -> str:
    key = (raw or "").strip().lower()
    return PLAN_LABELS.get(key, raw.replace("_", " ").title() if raw else "")


def _fetch_period_usage(token: str) -> dict:
    body = b"{}"
    last_err: Exception | None = None
    for attempt in range(1, HTTP_RETRIES + 1):
        req = urllib.request.Request(USAGE_URL, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        req.add_header("Connect-Protocol-Version", "1")
        req.add_header("User-Agent", "DeskOS/1.0")
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_ssl_ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
        except Exception as exc:
            last_err = exc
            _log(f"http attempt {attempt}/{HTTP_RETRIES} failed: {type(exc).__name__}")
            if attempt < HTTP_RETRIES:
                time.sleep(1.5 * attempt)
    if last_err:
        raise last_err
    raise RuntimeError("cursor usage request failed")


def _normalize(payload: dict, plan_raw: str) -> dict:
    usage = payload.get("planUsage") or {}
    if "autoPercentUsed" not in usage and "apiPercentUsed" not in usage:
        _log("unexpected payload: missing auto/api percent used")
        return dict(UNAVAILABLE)

    auto_used = float(usage.get("autoPercentUsed") or 0)
    api_used = float(usage.get("apiPercentUsed") or 0)
    auto_pct = int(round(max(0.0, min(100.0, auto_used))))
    api_pct = int(round(max(0.0, min(100.0, api_used))))
    reset_label = _ms_label(payload.get("billingCycleEnd"))
    plan = _plan_label(plan_raw)

    return {
        "available": True,
        "pending": False,
        "plan": plan,
        "auto_used_pct": auto_pct,
        "api_used_pct": api_pct,
        "auto_used_ratio": round(max(0.0, min(1.0, auto_used / 100.0)), 4),
        "api_used_ratio": round(max(0.0, min(1.0, api_used / 100.0)), 4),
        "reset_label": reset_label,
        "value": f"{auto_pct}% / {api_pct}%",
        "label": f"CUR {auto_pct}%  OTH {api_pct}%",
    }


def _refresh() -> dict:
    token, plan_raw = _read_auth()
    if not token:
        _log("no local token — sign in to Cursor")
        return dict(UNAVAILABLE)
    payload = _fetch_period_usage(token)
    data = _normalize(payload, plan_raw)
    if data.get("available"):
        _log(f"ok {data.get('plan') or ''} {data.get('value')}".strip())
    return data


def _worker() -> None:
    global _cache, _cache_time
    while True:
        delay = REFRESH_INTERVAL
        try:
            data = _refresh()
            with _lock:
                if data.get("available") or not _cache.get("available"):
                    _cache = data
                _cache_time = time.time()
            if not data.get("available"):
                delay = FAIL_RETRY_INTERVAL
        except Exception as exc:
            _log(f"refresh failed: {type(exc).__name__}: {exc}")
            with _lock:
                if not _cache.get("available"):
                    _cache = dict(UNAVAILABLE)
            delay = FAIL_RETRY_INTERVAL
        time.sleep(delay)


def start() -> None:
    """启动后台刷新。失败不影响主流程。"""
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True
    _log("polling started")
    threading.Thread(target=_worker, daemon=True, name="cursor-usage").start()


def get_cursor_usage() -> dict:
    start()
    with _lock:
        return dict(_cache)
