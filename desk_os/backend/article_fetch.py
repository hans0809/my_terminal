"""FLOW — 打开文章时得到可读 HTML（含图片）。对任意 RSS 源同一套规则。"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse

BODY_LIMIT = 180_000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# class / id 子串，覆盖常见 CMS，不是某个站点的特例
_BODY_HINTS = (
    "article-body", "article_body", "article__content", "article__main",
    "article-content", "article_content", "article-text", "articleBody",
    "post-content", "post_content", "post__content", "post-body", "post__body",
    "entry-content", "entry__content", "entry-body", "entry__body",
    "story-body", "story__body", "story-content", "story__content",
    "rich-text", "rich_text", "markdown-body", "prose", "content-body",
    "news-content", "news_content", "item-body", "item__body",
    "wangeditor", "postbody", "articlebody", "main-content", "main__content",
)
_BODY_TAGS = {"article", "main"}
_BODY_IDS = {"content", "main", "main-content", "article", "post", "entry", "body", "article-body"}
_LAZY_SRC = (
    "src", "data-src", "data-original", "data-lazy-src",
    "data-actualsrc", "data-original-src", "data-url",
)
_TEASER = (
    "查看全文", "阅读全文", "阅读原文", "继续阅读", "全文",
    "read more", "continue reading", "view full", "full article",
    "read the rest", "keep reading", "read on",
)
_SKIP = {"script", "style", "noscript", "svg", "iframe", "form", "button", "nav", "footer", "header"}
_VOID = {"img", "br", "hr", "source"}
_KEEP = {
    "p", "h1", "h2", "h3", "h4", "ul", "ol", "li", "blockquote",
    "figure", "figcaption", "img", "a", "strong", "em", "b", "i",
    "br", "code", "pre",
}
_VERIFY: bool | None = None


def _srcset_first(srcset: str) -> str:
    raw = (srcset or "").split(",")[0].strip().split(" ")[0].strip()
    return raw


def _sniff_image(data: bytes, ctype: str) -> str:
    kind = (ctype or "").split(";", 1)[0].strip().lower()
    if kind.startswith("image/") and kind not in {"image/octet-stream", "image/*"}:
        return kind
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "image/avif"
    return kind if kind.startswith("image/") else "image/jpeg"


def _http_get(url: str, headers: dict):
    import httpx

    global _VERIFY
    order = [True, False] if _VERIFY is None else [_VERIFY]
    last: Exception | None = None
    for verify in order:
        try:
            with httpx.Client(
                timeout=18.0,
                follow_redirects=True,
                headers=headers,
                verify=verify,
            ) as client:
                resp = client.get(url)
            _VERIFY = verify
            return resp
        except httpx.ConnectError as exc:
            last = exc
            msg = str(exc).upper()
            if verify and ("SSL" in msg or "CERT" in msg):
                continue
            raise
    raise last or RuntimeError("request failed")


def _attr(attrs, name: str) -> str:
    want = name.lower()
    for key, val in attrs:
        if key.lower() == want:
            return val or ""
    return ""


def _abs(base: str, src: str) -> str:
    raw = (src or "").strip()
    if not raw or raw.startswith("data:") or raw.startswith("javascript:"):
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    out = urljoin(base, raw)
    parsed = urlparse(out)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return out


def _is_body_start(tag: str, attrs) -> bool:
    if tag in _BODY_TAGS:
        return True
    if _attr(attrs, "role").lower() == "main":
        return True
    if _attr(attrs, "itemprop") == "articleBody":
        return True
    blob = f"{_attr(attrs, 'class')} {_attr(attrs, 'id')}".lower()
    if any(hint in blob for hint in _BODY_HINTS):
        return True
    eid = _attr(attrs, "id").lower()
    return eid in _BODY_IDS


def _richness(html: str) -> tuple[int, int, int]:
    raw = html or ""
    return (raw.count("<img"), raw.count("<p"), len(raw))


def is_richer(new_html: str, old_html: str) -> bool:
    return _richness(new_html) > _richness(old_html)


def looks_complete(html: str) -> bool:
    raw = (html or "").strip()
    if not raw:
        return False
    imgs = raw.count("<img")
    ps = raw.count("<p")
    if imgs >= 1 and ps >= 2:
        return True
    if ps >= 4 and len(raw) >= 800:
        return True
    return len(raw) >= 2500


def looks_teaser(html: str, summary: str = "") -> bool:
    if looks_complete(html):
        return False
    blob = f"{html or ''} {summary or ''}".lower()
    if any(token.lower() in blob for token in _TEASER):
        return True
    return not looks_complete(html)


class _Frame:
    __slots__ = ("depth", "buf")

    def __init__(self, start: str) -> None:
        self.depth = 1
        self.buf = [start]


class _Capture(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cands: list[str] = []
        self._frames: list[_Frame] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP:
            self._skip += 1
            return
        start = self.get_starttag_text() or ""
        if self._skip:
            return
        for frame in self._frames:
            frame.buf.append(start)
            if tag not in _VOID:
                frame.depth += 1
        if _is_body_start(tag, attrs):
            if tag in _VOID:
                self.cands.append(start)
            else:
                self._frames.append(_Frame(start))

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
            return
        if self._skip or tag in _VOID:
            return
        end = f"</{tag}>"
        keep: list[_Frame] = []
        for frame in self._frames:
            frame.buf.append(end)
            frame.depth -= 1
            if frame.depth <= 0:
                self.cands.append("".join(frame.buf))
            else:
                keep.append(frame)
        self._frames = keep

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        for frame in self._frames:
            frame.buf.append(data)

    def best(self) -> str:
        for frame in self._frames:
            self.cands.append("".join(frame.buf))
        self._frames = []
        if not self.cands:
            return ""

        def score(html: str) -> tuple[int, int, int]:
            imgs, ps, n = _richness(html)
            return (imgs, ps, n - html.count("<a ") * 80)

        return max(self.cands, key=score)


class _Sanitize(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.parts: list[str] = []
        self._skip = 0
        self._a_open: list[bool] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP:
            self._skip += 1
            return
        if self._skip or tag not in _KEEP:
            return
        if tag == "img":
            src = ""
            for name in _LAZY_SRC:
                src = _abs(self.base, _attr(attrs, name))
                if src:
                    break
            if not src:
                src = _abs(self.base, _srcset_first(
                    _attr(attrs, "srcset") or _attr(attrs, "data-srcset")
                ))
            if not src:
                return
            alt = _attr(attrs, "alt").replace('"', "")
            self.parts.append(f'<img src="{src}" alt="{alt}">')
            return
        if tag == "a":
            href = _abs(self.base, _attr(attrs, "href"))
            if href:
                self.parts.append(f'<a href="{href}" target="_blank" rel="noreferrer">')
                self._a_open.append(True)
            else:
                self._a_open.append(False)
            return
        if tag == "br":
            self.parts.append("<br>")
            return
        self.parts.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
            return
        if self._skip or tag not in _KEEP or tag in _VOID:
            return
        if tag == "a":
            real = self._a_open.pop() if self._a_open else False
            if real:
                self.parts.append("</a>")
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.parts.append(text)

    def html(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()[:BODY_LIMIT]


def sanitize_html(html: str, base: str = "") -> str:
    if not html:
        return ""
    parser = _Sanitize(base)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return ""
    return parser.html()


def extract_body(html: str, base: str) -> str:
    cap = _Capture()
    try:
        cap.feed(html)
        cap.close()
    except Exception:
        pass
    fragment = cap.best()
    picked = sanitize_html(fragment, base) if fragment else ""
    if looks_complete(picked) or picked.count("<p") >= 2 or "<img" in picked:
        return picked
    return sanitize_html(html, base) or picked


def fetch_article_html(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": f"{parsed.scheme}://{parsed.netloc}/",
    }
    resp = _http_get(url, headers)
    resp.raise_for_status()
    data = resp.content
    final = str(resp.url)
    if len(data) > 2_500_000:
        data = data[:2_500_000]
    text = data.decode(resp.encoding or "utf-8", errors="ignore")
    return extract_body(text, final or url)


def proxied_body(html: str, page_url: str = "") -> str:
    if not html:
        return ""
    ref = quote(page_url, safe="") if page_url else ""

    def repl(match: re.Match[str]) -> str:
        url = match.group(1)
        src = f'src="/api/img?u={quote(url, safe="")}'
        if ref:
            src += f"&r={ref}"
        return src + '"'

    return re.sub(r"src=['\"](https?://[^'\"]+)['\"]", repl, html)


def _site_referer(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 3:
        return f"{parsed.scheme}://{'.'.join(parts[1:])}/"
    if host:
        return f"{parsed.scheme}://{host}/"
    return ""


def proxy_image(url: str, referer: str = "") -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("bad image url")
    host = (parsed.hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"} or host.endswith(".localhost"):
        raise ValueError("bad image url")
    refs: list[str] = []
    page = (referer or "").strip()
    if page.startswith("http://") or page.startswith("https://"):
        refs.append(page)
    site = _site_referer(url)
    if site and site not in refs:
        refs.append(site)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    if origin not in refs:
        refs.append(origin)
    refs.append("")
    last: Exception | None = None
    for ref in refs:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        if ref:
            headers["Referer"] = ref
        try:
            resp = _http_get(url, headers)
            if resp.status_code == 403:
                continue
            resp.raise_for_status()
            data = resp.content
            ctype = resp.headers.get("content-type") or ""
            if len(data) > 2_500_000:
                data = data[:2_500_000]
            return data, _sniff_image(data, ctype)
        except Exception as exc:
            last = exc
            continue
    raise last or ValueError("image fetch failed")
