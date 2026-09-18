"""FLOW — 打开文章时拉取原文 HTML（含图片），供阅读页显示。"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse

BODY_LIMIT = 180_000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_BODY_HINTS = (
    "article__main__content",
    "wangEditor-txt",
    "article-body",
    "article__content",
    "post-content",
    "entry-content",
    "post__content",
    "rich-text",
    "article-content",
    "post-body",
    "entry__content",
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


def _http_get(url: str, headers: dict) -> object:
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


class _Capture(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cands: list[str] = []
        self._buf: list[str] = []
        self._depth = 0
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP:
            self._skip += 1
            return
        cls = _attr(attrs, "class")
        hit = any(h in cls for h in _BODY_HINTS)
        if self._depth == 0 and hit:
            self._depth = 1
            self._buf = [self.get_starttag_text() or ""]
            if tag in _VOID:
                self.cands.append("".join(self._buf))
                self._depth = 0
            return
        if self._depth and not self._skip:
            self._buf.append(self.get_starttag_text() or "")
            if tag not in _VOID:
                self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
            return
        if self._depth and not self._skip and tag not in _VOID:
            self._buf.append(f"</{tag}>")
            self._depth -= 1
            if self._depth <= 0:
                self.cands.append("".join(self._buf))
                self._depth = 0
                self._buf = []

    def handle_data(self, data: str) -> None:
        if self._depth and not self._skip:
            self._buf.append(data)

    def best(self) -> str:
        if self._depth and self._buf:
            self.cands.append("".join(self._buf))
        if not self.cands:
            return ""

        def score(html: str) -> tuple[int, int, int]:
            return (html.count("<img"), html.count("<p"), len(html))

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
            candidates = (
                _attr(attrs, "src"),
                _attr(attrs, "data-src"),
                _attr(attrs, "data-original"),
                _srcset_first(_attr(attrs, "srcset") or _attr(attrs, "data-srcset")),
            )
            src = ""
            for cand in candidates:
                src = _abs(self.base, cand)
                if src:
                    break
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
    fragment = cap.best() or html
    return sanitize_html(fragment, base)


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


def proxied_body(html: str) -> str:
    if not html:
        return ""

    def repl(match: re.Match[str]) -> str:
        url = match.group(1)
        return f'src="/api/img?u={quote(url, safe="")}"'

    return re.sub(r"src=['\"](https?://[^'\"]+)['\"]", repl, html)


def proxy_image(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("bad image url")
    host = (parsed.hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"} or host.endswith(".localhost"):
        raise ValueError("bad image url")
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    if host.endswith("sspai.com"):
        referer = "https://sspai.com/"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": referer,
    }
    resp = _http_get(url, headers)
    resp.raise_for_status()
    data = resp.content
    ctype = resp.headers.get("content-type") or ""
    if len(data) > 2_500_000:
        data = data[:2_500_000]
    return data, _sniff_image(data, ctype)
