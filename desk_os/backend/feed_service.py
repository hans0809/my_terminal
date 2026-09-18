"""FLOW — Feed 存储、抓取、定时刷新。"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.rss_parser import TITLE_LIMIT, URL_LIMIT, parse_feed_bytes

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "flow.db"
USER_AGENT = "DeskOS-FLOW/1.0 (+local)"
FETCH_TIMEOUT = 18.0
POLL_TICK = 60
DEFAULT_INTERVAL = 30
CATEGORIES = ("AI", "BIO", "PAPER", "TECH", "HARDWARE", "OTHER")
INTERVALS = (15, 30, 60, 360, 0)
SEED_FEEDS = (
    ("Hacker News", "https://news.ycombinator.com/rss", "TECH"),
    ("阮一峰的网络日志", "https://www.ruanyifeng.com/blog/atom.xml", "TECH"),
)

_lock = threading.Lock()
_started = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=12)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _guess_category(url: str, name: str) -> str:
    blob = f"{url} {name}".lower()
    if "arxiv" in blob:
        return "PAPER"
    if "biorxiv" in blob or "pubmed" in blob or "nature.com" in blob:
        return "BIO"
    if "huggingface" in blob or "openai" in blob or "anthropic" in blob:
        return "AI"
    if "nvidia" in blob or "tomshardware" in blob:
        return "HARDWARE"
    return "TECH"


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS feeds (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL UNIQUE,
          category TEXT NOT NULL DEFAULT 'OTHER',
          enabled INTEGER NOT NULL DEFAULT 1,
          update_interval INTEGER NOT NULL DEFAULT 30,
          last_fetch_at TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS articles (
          id INTEGER PRIMARY KEY,
          feed_id INTEGER NOT NULL,
          guid TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '',
          summary TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL DEFAULT '',
          author TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT '',
          published_at TEXT NOT NULL DEFAULT '',
          fetched_at TEXT NOT NULL,
          is_read INTEGER NOT NULL DEFAULT 0,
          is_saved INTEGER NOT NULL DEFAULT 0,
          is_read_later INTEGER NOT NULL DEFAULT 0,
          body_html TEXT NOT NULL DEFAULT '',
          UNIQUE(feed_id, guid),
          FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS tags (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS article_tags (
          article_id INTEGER NOT NULL,
          tag_id INTEGER NOT NULL,
          PRIMARY KEY (article_id, tag_id),
          FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
          FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS articles_pub ON articles(published_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS articles_flags ON articles(is_read, is_saved, is_read_later);
        """
    )


def _migrate_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=OFF")
    feed_cols = _cols(conn, "feeds")
    if "name" not in feed_cols:
        conn.execute(
            """
            CREATE TABLE feeds_v2 (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL DEFAULT '',
              url TEXT NOT NULL UNIQUE,
              category TEXT NOT NULL DEFAULT 'OTHER',
              enabled INTEGER NOT NULL DEFAULT 1,
              update_interval INTEGER NOT NULL DEFAULT 30,
              last_fetch_at TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL DEFAULT '',
              error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        for row in conn.execute("SELECT * FROM feeds"):
            item = dict(row)
            name = item.get("name") or item.get("title") or ""
            url = item.get("url") or ""
            conn.execute(
                """
                INSERT INTO feeds_v2 (
                  id, name, url, category, enabled, update_interval,
                  last_fetch_at, created_at, error
                ) VALUES (?, ?, ?, ?, 1, 30, ?, ?, ?)
                """,
                (
                    item["id"],
                    name,
                    url,
                    _guess_category(url, name),
                    item.get("fetched_at") or item.get("last_fetch_at") or "",
                    item.get("added_at") or item.get("created_at") or _now(),
                    item.get("error") or "",
                ),
            )
        conn.execute("DROP TABLE feeds")
        conn.execute("ALTER TABLE feeds_v2 RENAME TO feeds")

    art_cols = _cols(conn, "articles")
    if "is_read" not in art_cols:
        conn.execute(
            """
            CREATE TABLE articles_v2 (
              id INTEGER PRIMARY KEY,
              feed_id INTEGER NOT NULL,
              guid TEXT NOT NULL,
              title TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              url TEXT NOT NULL DEFAULT '',
              author TEXT NOT NULL DEFAULT '',
              category TEXT NOT NULL DEFAULT '',
              published_at TEXT NOT NULL DEFAULT '',
              fetched_at TEXT NOT NULL,
              is_read INTEGER NOT NULL DEFAULT 0,
              is_saved INTEGER NOT NULL DEFAULT 0,
              is_read_later INTEGER NOT NULL DEFAULT 0,
              UNIQUE(feed_id, guid),
              FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
            )
            """
        )
        for row in conn.execute("SELECT * FROM articles"):
            item = dict(row)
            conn.execute(
                """
                INSERT INTO articles_v2 (
                  id, feed_id, guid, title, summary, url, author, category,
                  published_at, fetched_at, is_read, is_saved, is_read_later
                ) VALUES (?, ?, ?, ?, ?, ?, '', '', ?, ?, ?, 0, 0)
                """,
                (
                    item["id"],
                    item["feed_id"],
                    item.get("guid") or item.get("url") or str(item["id"]),
                    item.get("title") or "",
                    item.get("summary") or "",
                    item.get("url") or "",
                    item.get("published_at") or "",
                    item.get("fetched_at") or _now(),
                    int(bool(item.get("is_read", item.get("read", 0)))),
                ),
            )
        conn.execute("DROP TABLE articles")
        conn.execute("ALTER TABLE articles_v2 RENAME TO articles")

    _create_schema(conn)
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_columns(conn)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    cols = _cols(conn, "articles")
    if "body_html" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN body_html TEXT NOT NULL DEFAULT ''")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not DB_PATH.exists()
    with _connect() as conn:
        if is_new:
            _create_schema(conn)
            _ensure_columns(conn)
            now = _now()
            conn.executemany(
                """
                INSERT INTO feeds (name, url, category, enabled, update_interval, created_at)
                VALUES (?, ?, ?, 1, 30, ?)
                """,
                [(name, url, cat, now) for name, url, cat in SEED_FEEDS],
            )
        else:
            _migrate_schema(conn)


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for key in ("enabled", "is_read", "is_saved", "is_read_later"):
        if key in item:
            item[key] = bool(item[key])
    return item


def _norm_category(value: str | None) -> str:
    raw = (value or "").strip().upper()
    return raw if raw in CATEGORIES else "OTHER"


def _norm_interval(value: int | None) -> int:
    try:
        n = int(value if value is not None else DEFAULT_INTERVAL)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL
    return n if n in INTERVALS else DEFAULT_INTERVAL


def list_feeds() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT f.*,
                   (SELECT COUNT(*) FROM articles a WHERE a.feed_id = f.id) AS n
            FROM feeds f
            ORDER BY f.category ASC, f.id ASC
            """
        ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def get_feed(fid: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT f.*,
                   (SELECT COUNT(*) FROM articles a WHERE a.feed_id = f.id) AS n
            FROM feeds f WHERE f.id = ?
            """,
            (fid,),
        ).fetchone()
    return _row(row)


def add_feed(name: str, url: str, category: str = "OTHER", update_interval: int = 30) -> dict[str, Any]:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"ok": False, "error": "INVALID FEED"}
    raw = parsed.geturl()[:URL_LIMIT]
    cat = _norm_category(category)
    interval = _norm_interval(update_interval)
    label = (name or "").strip()[:TITLE_LIMIT]
    now = _now()
    try:
        with _connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO feeds (name, url, category, enabled, update_interval, created_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (label, raw, cat, interval, now),
            )
            feed_id = int(cur.lastrowid)
    except sqlite3.IntegrityError:
        with _connect() as conn:
            row = conn.execute("SELECT id FROM feeds WHERE url = ?", (raw,)).fetchone()
        return {"ok": True, "id": int(row["id"]) if row else 0, "dup": True, "new": 0}

    result = fetch_feed(feed_id)
    if not result.get("ok"):
        drop_feed(feed_id)
        return {"ok": False, "error": "INVALID FEED"}
    if not label and result.get("name"):
        with _connect() as conn:
            conn.execute("UPDATE feeds SET name = ? WHERE id = ?", (result["name"][:TITLE_LIMIT], feed_id))
    result["id"] = feed_id
    return result


def update_feed(fid: int, **fields: Any) -> dict[str, Any]:
    item = get_feed(fid)
    if not item:
        return {"ok": False, "error": "missing feed"}
    name = item["name"]
    url = item["url"]
    category = item["category"]
    enabled = 1 if item["enabled"] else 0
    interval = item["update_interval"]
    if "name" in fields and fields["name"] is not None:
        name = str(fields["name"]).strip()[:TITLE_LIMIT]
    if "url" in fields and fields["url"] is not None:
        raw = str(fields["url"]).strip()
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"ok": False, "error": "INVALID FEED"}
        url = parsed.geturl()[:URL_LIMIT]
    if "category" in fields and fields["category"] is not None:
        category = _norm_category(str(fields["category"]))
    if "enabled" in fields and fields["enabled"] is not None:
        enabled = 1 if fields["enabled"] else 0
    if "update_interval" in fields and fields["update_interval"] is not None:
        interval = _norm_interval(fields["update_interval"])
    with _connect() as conn:
        conn.execute(
            """
            UPDATE feeds
            SET name = ?, url = ?, category = ?, enabled = ?, update_interval = ?
            WHERE id = ?
            """,
            (name, url, category, enabled, interval, fid),
        )
    return {"ok": True, "feed": get_feed(fid)}


def drop_feed(fid: int) -> dict[str, Any]:
    with _connect() as conn:
        conn.execute("DELETE FROM articles WHERE feed_id = ?", (fid,))
        cur = conn.execute("DELETE FROM feeds WHERE id = ?", (fid,))
        n = cur.rowcount
    return {"ok": True, "dropped": n}


def _download(url: str) -> bytes:
    import httpx

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.content
    if len(data) > 2_000_000:
        data = data[:2_000_000]
    return data


def _insert_items(conn: sqlite3.Connection, feed_id: int, category: str, items: list[dict[str, str]]) -> int:
    now = _now()
    new_n = 0
    for item in items:
        guid = (item.get("guid") or item.get("url") or item.get("title") or "")[:URL_LIMIT]
        if not guid:
            continue
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO articles (
              feed_id, guid, title, summary, url, author, category,
              published_at, fetched_at, is_read, is_saved, is_read_later
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
            """,
            (
                feed_id,
                guid,
                (item.get("title") or "")[:TITLE_LIMIT],
                item.get("summary") or "",
                (item.get("url") or "")[:URL_LIMIT],
                item.get("author") or "",
                category,
                (item.get("published_at") or "")[:40],
                now,
            ),
        )
        new_n += cur.rowcount
    return new_n


def fetch_feed(fid: int) -> dict[str, Any]:
    item = get_feed(fid)
    if not item:
        return {"ok": False, "error": "missing feed"}
    try:
        data = _download(item["url"])
        parsed = parse_feed_bytes(data, item["url"])
        name = item["name"] or parsed["title"]
        with _connect() as conn:
            new_n = _insert_items(conn, fid, item["category"], parsed["items"])
            conn.execute(
                """
                UPDATE feeds
                SET name = CASE WHEN name = '' THEN ? ELSE name END,
                    last_fetch_at = ?, error = ''
                WHERE id = ?
                """,
                (name[:TITLE_LIMIT], _now(), fid),
            )
        return {"ok": True, "id": fid, "name": name, "new": new_n}
    except Exception as exc:
        err = str(exc)[:180] or "FETCH ERROR"
        with _connect() as conn:
            conn.execute(
                "UPDATE feeds SET last_fetch_at = ?, error = ? WHERE id = ?",
                (_now(), err, fid),
            )
        print(f"[desk-os] flow fetch fail id={fid} {err}", flush=True)
        return {"ok": False, "id": fid, "error": "FETCH ERROR", "detail": err, "new": 0}


def fetch_all(enabled_only: bool = True) -> dict[str, Any]:
    with _lock:
        feeds = [f for f in list_feeds() if (f["enabled"] if enabled_only else True)]
        results = [fetch_feed(int(f["id"])) for f in feeds]
        new_n = sum(int(r.get("new") or 0) for r in results)
        ok_n = sum(1 for r in results if r.get("ok"))
        if feeds and ok_n == 0:
            return {"ok": False, "error": "FETCH ERROR", "new": 0, "feeds": len(feeds)}
        return {"ok": True, "new": new_n, "feeds": len(feeds), "ok_n": ok_n}


def _due(feed: dict[str, Any], now: datetime) -> bool:
    if not feed.get("enabled"):
        return False
    interval = int(feed.get("update_interval") or 0)
    if interval <= 0:
        return False
    last = feed.get("last_fetch_at") or ""
    if not last:
        return True
    try:
        dt = datetime.fromisoformat(last)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (now - dt).total_seconds() >= interval * 60


def fetch_due() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    due = [f for f in list_feeds() if _due(f, now)]
    if not due:
        return {"ok": True, "new": 0, "feeds": 0}
    with _lock:
        results = [fetch_feed(int(f["id"])) for f in due]
        new_n = sum(int(r.get("new") or 0) for r in results)
        return {"ok": True, "new": new_n, "feeds": len(due)}


def start() -> None:
    global _started
    init_db()
    if _started:
        return
    _started = True

    def loop() -> None:
        time.sleep(0.6)
        while True:
            try:
                fetch_due()
            except Exception as exc:
                print(f"[desk-os] flow poll error {exc}", flush=True)
            time.sleep(POLL_TICK)

    threading.Thread(target=loop, name="flow-poll", daemon=True).start()
    print("[desk-os] flow poller started", flush=True)
