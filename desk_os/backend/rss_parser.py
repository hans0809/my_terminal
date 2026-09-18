"""FLOW — RSS / Atom 解析（feedparser + 纯文本摘要）。"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from time import struct_time
from typing import Any
from urllib.parse import urljoin, urlparse

TITLE_LIMIT = 240
URL_LIMIT = 800
SUMMARY_LIMIT = 4000
AUTHOR_LIMIT = 120


class _HTMLText(HTMLParser):
    BLOCK = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4",
        "blockquote", "section", "article", "ul", "ol",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip = True
            return
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("· ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip = False
        if tag in {"p", "div", "h1", "h2", "h3", "li", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r" *\n *", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    parser = _HTMLText()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()
    return parser.text()


def _iso_from_struct(st: struct_time | None) -> str:
    if not st:
        return ""
    try:
        dt = datetime(*st[:6], tzinfo=timezone.utc)
        return dt.isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def _iso_from_text(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return raw[:40]


def parse_feed_bytes(data: bytes, base_url: str = "") -> dict[str, Any]:
    import feedparser

    parsed = feedparser.parse(data)
    entries = list(parsed.entries or [])
    if parsed.bozo and not entries:
        err = getattr(parsed, "bozo_exception", None)
        raise ValueError(str(err) if err else "INVALID FEED")

    feed_title = html_to_text(getattr(parsed.feed, "title", "") or "")[:TITLE_LIMIT]
    if not feed_title:
        feed_title = urlparse(base_url).netloc

    items: list[dict[str, str]] = []
    for entry in entries:
        title = html_to_text(entry.get("title") or "")[:TITLE_LIMIT]
        link = (entry.get("link") or "").strip()
        if link:
            link = urljoin(base_url, link)[:URL_LIMIT]
        guid = str(
            entry.get("id")
            or entry.get("guid")
            or link
            or title
        ).strip()[:URL_LIMIT]
        content = ""
        if entry.get("content"):
            content = entry.content[0].get("value") or ""
        summary_html = content or entry.get("summary") or entry.get("description") or ""
        author = html_to_text(
            entry.get("author")
            or (entry.get("author_detail") or {}).get("name")
            or ""
        )[:AUTHOR_LIMIT]
        published = (
            _iso_from_struct(entry.get("published_parsed"))
            or _iso_from_struct(entry.get("updated_parsed"))
            or _iso_from_text(entry.get("published") or "")
            or _iso_from_text(entry.get("updated") or "")
        )
        if not title and not link:
            continue
        items.append({
            "guid": guid or link or title,
            "url": link,
            "title": title or "(untitled)",
            "summary": html_to_text(summary_html)[:SUMMARY_LIMIT],
            "author": author,
            "published_at": published,
        })

    return {"title": feed_title, "items": items}
