"""FLOW — 文章查询、已读 / 收藏 / 稍后阅读。"""

from __future__ import annotations

import webbrowser
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.article_fetch import fetch_article_html, proxied_body
from backend.feed_service import CATEGORIES, _connect, _row

ARTICLE_LIMIT = 300


def _when_expr() -> str:
    return "CASE WHEN a.published_at = '' THEN a.fetched_at ELSE a.published_at END"


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
    limit: int = 120,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 120), ARTICLE_LIMIT))
    where = ["1=1"]
    args: list[Any] = []
    cat = (category or "").strip().upper()
    if cat in CATEGORIES:
        where.append("UPPER(CASE WHEN a.category != '' THEN a.category ELSE f.category END) = ?")
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
    if q:
        like = f"%{q}%"
        where.append("(a.title LIKE ? OR a.summary LIKE ? OR a.author LIKE ?)")
        args.extend([like, like, like])
    start = _range_start(date_range)
    if start:
        where.append(f"{_when_expr()} >= ?")
        args.append(start)

    sql = f"""
        SELECT a.id, a.feed_id, a.title, a.summary, a.url, a.author,
               a.category AS category, f.category AS feed_category,
               a.published_at, a.fetched_at, a.is_read, a.is_saved, a.is_read_later,
               f.name AS source
        FROM articles a
        JOIN feeds f ON f.id = a.feed_id
        WHERE {' AND '.join(where)}
        ORDER BY {_when_expr()} DESC, a.id DESC
        LIMIT ?
    """
    args.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
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
    return {"articles": articles, "n": len(articles), "counts": counts()}


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
        item["body_html"] = proxied_body(item.get("body_html") or "")
    return item


def _needs_body(html: str, summary: str = "") -> bool:
    raw = (html or "").strip()
    if "<img" in raw and len(raw) >= 400:
        return False
    blob = raw + (summary or "")
    if "查看全文" in blob or "阅读全文" in blob:
        return True
    return "<img" not in raw and len(raw) < 800


def ensure_body(aid: int) -> dict[str, Any] | None:
    item = get_article(aid, proxy=False)
    if not item:
        return None
    html = (item.get("body_html") or "").strip()
    if _needs_body(html, item.get("summary") or ""):
        url = (item.get("url") or "").strip()
        if url:
            try:
                fetched = fetch_article_html(url)
            except Exception as exc:
                print(f"[desk-os] flow body fetch fail id={aid} {exc}", flush=True)
                fetched = ""
            if fetched:
                html = fetched
                with _connect() as conn:
                    conn.execute("UPDATE articles SET body_html = ? WHERE id = ?", (html, aid))
                item["body_html"] = html
    item["body_html"] = proxied_body(item.get("body_html") or "")
    return item


def mark_read(aid: int, value: bool = True) -> dict[str, Any] | None:
    with _connect() as conn:
        conn.execute("UPDATE articles SET is_read = ? WHERE id = ?", (1 if value else 0, aid))
    return get_article(aid)


def toggle_saved(aid: int) -> dict[str, Any] | None:
    item = get_article(aid)
    if not item:
        return None
    nxt = 0 if item["is_saved"] else 1
    with _connect() as conn:
        conn.execute("UPDATE articles SET is_saved = ? WHERE id = ?", (nxt, aid))
    return get_article(aid)


def toggle_read_later(aid: int) -> dict[str, Any] | None:
    item = get_article(aid)
    if not item:
        return None
    nxt = 0 if item["is_read_later"] else 1
    with _connect() as conn:
        conn.execute("UPDATE articles SET is_read_later = ? WHERE id = ?", (nxt, aid))
    return get_article(aid)


def open_article(aid: int) -> dict[str, Any]:
    item = mark_read(aid, True)
    if not item or not item.get("url"):
        return {"ok": False, "error": "missing article"}
    webbrowser.open(item["url"])
    return {"ok": True, "id": aid, "article": item}


def counts() -> dict[str, Any]:
    cats = {c: 0 for c in CATEGORIES}
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        unread = conn.execute("SELECT COUNT(*) FROM articles WHERE is_read = 0").fetchone()[0]
        saved = conn.execute("SELECT COUNT(*) FROM articles WHERE is_saved = 1").fetchone()[0]
        later = conn.execute("SELECT COUNT(*) FROM articles WHERE is_read_later = 1").fetchone()[0]
        rows = conn.execute(
            """
            SELECT UPPER(CASE WHEN a.category != '' THEN a.category ELSE f.category END) AS cat,
                   COUNT(*) AS n
            FROM articles a
            JOIN feeds f ON f.id = a.feed_id
            GROUP BY cat
            """
        ).fetchall()
        last = conn.execute(
            "SELECT MAX(last_fetch_at) FROM feeds WHERE last_fetch_at != ''"
        ).fetchone()[0] or ""
        feeds_n = conn.execute("SELECT COUNT(*) FROM feeds").fetchone()[0]
    for row in rows:
        cat = row["cat"]
        if cat in cats:
            cats[cat] = int(row["n"])
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
