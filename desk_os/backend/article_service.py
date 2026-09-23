"""FLOW — 文章查询、已读 / 收藏 / 稍后阅读。"""

from __future__ import annotations

import sqlite3
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.article_fetch import fetch_article_html, is_richer, looks_teaser, proxied_body
from backend.feed_service import CATEGORIES, _connect, _row

ARTICLE_LIMIT = 80
PAGE_SIZE = 40

_meta_lock = threading.Lock()
_meta_gen = 0
_meta_counts: dict[str, Any] | None = None
_meta_sources: list[dict[str, Any]] | None = None


def _when_expr() -> str:
    return "CASE WHEN a.published_at = '' THEN a.fetched_at ELSE a.published_at END"


def invalidate_lists() -> None:
    global _meta_gen, _meta_counts, _meta_sources
    with _meta_lock:
        _meta_gen += 1
        _meta_counts = None
        _meta_sources = None


def _fts_query(text: str) -> str:
    parts: list[str] = []
    for raw in (text or "").replace('"', " ").split():
        token = "".join(ch for ch in raw if ch.isalnum() or ch in "-_+")
        if not token:
            continue
        if token.isascii():
            parts.append(f'"{token}"*')
        else:
            parts.append('"' + token + '"')
    return " AND ".join(parts)


def _range_start(date_range: str) -> str:
    raw = (date_range or "all").strip().lower()
    if raw in {"", "all"}:
        return ""
    now = datetime.now().astimezone()
    if raw == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif raw in {"week", "this_week"}:
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif raw in {"month", "this_month"}:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        return ""
    return start.astimezone(timezone.utc).isoformat()


def _article_category(item: dict[str, Any]) -> str:
    own = (item.get("category") or "").strip().upper()
    if own in CATEGORIES:
        return own
    src = (item.get("feed_category") or "").strip().upper()
    return src if src in CATEGORIES else "OTHER"


def list_articles(
    category: str = "",
    unread: bool | None = None,
    saved: bool | None = None,
    read_later: bool | None = None,
    search: str = "",
    date_range: str = "all",
    lang: str = "",
    feed_id: int = 0,
    offset: int = 0,
    limit: int = PAGE_SIZE,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or PAGE_SIZE), ARTICLE_LIMIT))
    try:
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        offset = 0
    where = ["1=1"]
    args: list[Any] = []
    cat = (category or "").strip().upper()
    if cat in CATEGORIES:
        where.append("a.category = ?")
        args.append(cat)
    if unread is True:
        where.append("a.is_read = 0")
    elif unread is False:
        where.append("a.is_read = 1")
    if saved is True:
        where.append("a.is_saved = 1")
    if read_later is True:
        where.append("a.is_read_later = 1")
    q = (search or "").strip()
    match = _fts_query(q) if q else ""
    if match:
        where.append("a.id IN (SELECT rowid FROM articles_fts WHERE articles_fts MATCH ?)")
        args.append(match)
    start = _range_start(date_range)
    if start:
        where.append(f"{_when_expr()} >= ?")
        args.append(start)
    lang = (lang or "").strip().upper()
    if lang in {"ZH", "EN"}:
        where.append("a.lang = ?")
        args.append(lang)
    try:
        fid = int(feed_id or 0)
    except (TypeError, ValueError):
        fid = 0
    if fid > 0:
        where.append("a.feed_id = ?")
        args.append(fid)

    clause = " AND ".join(where) if where else "1=1"
    order_sql = f"ORDER BY {_when_expr()} DESC, a.id DESC"
    with _connect() as conn:
        try:
            total = int(
                conn.execute(f"SELECT COUNT(*) FROM articles a WHERE {clause}", args).fetchone()[0]
            )
        except sqlite3.OperationalError as exc:
            print(f"[desk-os] flow query fail {exc}", flush=True)
            return _empty_page(limit)
        if total and offset >= total:
            offset = ((total - 1) // limit) * limit
        rows = conn.execute(
            f"""
            SELECT a.id, a.feed_id, a.title, a.summary, a.url, a.author,
                   a.category AS category, f.category AS feed_category, a.lang,
                   a.published_at, a.fetched_at, a.is_read, a.is_saved, a.is_read_later,
                   f.name AS source
            FROM articles a
            JOIN feeds f ON f.id = a.feed_id
            WHERE {clause}
            {order_sql}
            LIMIT ? OFFSET ?
            """,
            [*args, limit, offset],
        ).fetchall()
        sources = _sources(conn)
    articles = []
    for row in rows:
        item = _row(row)
        if not item:
            continue
        item["category"] = _article_category(item)
        item.pop("feed_category", None)
        summary = item.pop("summary", "") or ""
        item["excerpt"] = summary.replace("\n", " ").strip()[:160]
        articles.append(item)
    pages = max(1, (total + limit - 1) // limit) if total else 1
    page = (offset // limit) + 1 if total else 1
    return {
        "articles": articles,
        "n": len(articles),
        "total": total,
        "page": page,
        "pages": pages,
        "limit": limit,
        "offset": offset,
        "sources": sources,
        "counts": counts(),
    }


def _empty_page(limit: int) -> dict[str, Any]:
    return {
        "articles": [],
        "n": 0,
        "total": 0,
        "page": 1,
        "pages": 1,
        "limit": limit,
        "offset": 0,
        "sources": _sources_cached() or [],
        "counts": counts(),
    }


def _sources_cached() -> list[dict[str, Any]] | None:
    with _meta_lock:
        return _meta_sources


def _sources(conn: Any) -> list[dict[str, Any]]:
    global _meta_sources
    with _meta_lock:
        gen = _meta_gen
        cached = _meta_sources
    if cached is not None:
        return cached
    rows = conn.execute(
        """
        SELECT f.id, f.name, COUNT(a.id) AS n
        FROM feeds f
        JOIN articles a ON a.feed_id = f.id
        GROUP BY f.id
        ORDER BY n DESC, f.name ASC
        """
    ).fetchall()
    data = [{"id": int(r["id"]), "name": r["name"] or "", "n": int(r["n"])} for r in rows]
    with _meta_lock:
        if _meta_gen == gen:
            _meta_sources = data
    return data


def get_article(aid: int, proxy: bool = True) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT a.*, f.name AS source, f.category AS feed_category, f.url AS feed_url
            FROM articles a
            JOIN feeds f ON f.id = a.feed_id
            WHERE a.id = ?
            """,
            (aid,),
        ).fetchone()
    item = _row(row)
    if not item:
        return None
    item["category"] = _article_category(item)
    item.pop("feed_category", None)
    item.pop("guid", None)
    if proxy:
        item["body_html"] = proxied_body(item.get("body_html") or "", item.get("url") or "")
    return item


def ensure_body(aid: int) -> dict[str, Any] | None:
    item = get_article(aid, proxy=False)
    if not item:
        return None
    html = (item.get("body_html") or "").strip()
    page = (item.get("url") or "").strip()
    if looks_teaser(html, item.get("summary") or "") and page:
        try:
            fetched = fetch_article_html(page)
        except Exception as exc:
            print(f"[desk-os] flow body fetch fail id={aid} {exc}", flush=True)
            fetched = ""
        if fetched and is_richer(fetched, html):
            html = fetched
            with _connect() as conn:
                conn.execute("UPDATE articles SET body_html = ? WHERE id = ?", (html, aid))
            item["body_html"] = html
    item["body_html"] = proxied_body(item.get("body_html") or "", page)
    return item


def mark_read(aid: int, value: bool = True) -> dict[str, Any] | None:
    with _connect() as conn:
        conn.execute("UPDATE articles SET is_read = ? WHERE id = ?", (1 if value else 0, aid))
    invalidate_lists()
    return get_article(aid)


def toggle_saved(aid: int) -> dict[str, Any] | None:
    item = get_article(aid)
    if not item:
        return None
    nxt = 0 if item["is_saved"] else 1
    with _connect() as conn:
        conn.execute("UPDATE articles SET is_saved = ? WHERE id = ?", (nxt, aid))
    invalidate_lists()
    return get_article(aid)


def toggle_read_later(aid: int) -> dict[str, Any] | None:
    item = get_article(aid)
    if not item:
        return None
    nxt = 0 if item["is_read_later"] else 1
    with _connect() as conn:
        conn.execute("UPDATE articles SET is_read_later = ? WHERE id = ?", (nxt, aid))
    invalidate_lists()
    return get_article(aid)


def open_article(aid: int) -> dict[str, Any]:
    item = mark_read(aid, True)
    if not item or not item.get("url"):
        return {"ok": False, "error": "missing article"}
    webbrowser.open(item["url"])
    return {"ok": True, "id": aid, "article": item}


def counts() -> dict[str, Any]:
    global _meta_counts
    with _meta_lock:
        gen = _meta_gen
        cached = _meta_counts
    if cached is not None:
        return cached
    data = _compute_counts()
    with _meta_lock:
        if _meta_gen == gen:
            _meta_counts = data
    return data


def _compute_counts() -> dict[str, Any]:
    cats = {c: 0 for c in CATEGORIES}
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        unread = conn.execute("SELECT COUNT(*) FROM articles WHERE is_read = 0").fetchone()[0]
        saved = conn.execute("SELECT COUNT(*) FROM articles WHERE is_saved = 1").fetchone()[0]
        later = conn.execute("SELECT COUNT(*) FROM articles WHERE is_read_later = 1").fetchone()[0]
        rows = conn.execute(
            "SELECT category AS cat, COUNT(*) AS n FROM articles GROUP BY category"
        ).fetchall()
        last = conn.execute(
            "SELECT MAX(last_fetch_at) FROM feeds WHERE last_fetch_at != ''"
        ).fetchone()[0] or ""
        feeds_n = conn.execute("SELECT COUNT(*) FROM feeds").fetchone()[0]
    for row in rows:
        cat = (row["cat"] or "").strip().upper()
        if cat in cats:
            cats[cat] += int(row["n"])
        else:
            cats["OTHER"] += int(row["n"])
    return {
        "all": total,
        "unread": unread,
        "saved": saved,
        "later": later,
        "feeds": feeds_n,
        "fetched_at": last,
        "categories": cats,
    }
