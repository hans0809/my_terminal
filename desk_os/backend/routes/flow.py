"""订阅源与文章。"""

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend import article_service, feed_service
from backend.article_fetch import proxy_image

router = APIRouter()


class FeedIn(BaseModel):
    name: str = Field(default="", max_length=240)
    url: str = Field(default="", max_length=800)
    category: str = Field(default="OTHER", max_length=16)
    update_interval: int | None = None


class FeedPatch(BaseModel):
    name: str | None = Field(default=None, max_length=240)
    url: str | None = Field(default=None, max_length=800)
    category: str | None = Field(default=None, max_length=16)
    enabled: bool | None = None
    update_interval: int | None = None


def _as_bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


@router.get("/api/feeds")
def api_feeds_list():
    return {"feeds": feed_service.list_feeds(), "counts": article_service.counts()}


@router.post("/api/feeds")
def api_feeds_add(body: FeedIn):
    interval = 30 if body.update_interval is None else body.update_interval
    return feed_service.add_feed(body.name, body.url, body.category, interval)


@router.put("/api/feeds/{fid}")
def api_feeds_put(fid: int, body: FeedPatch):
    dump = getattr(body, "model_dump", None) or body.dict
    fields = dump(exclude_unset=True)
    return feed_service.update_feed(fid, **fields)


@router.delete("/api/feeds/{fid}")
def api_feeds_delete(fid: int):
    return feed_service.drop_feed(fid)


@router.post("/api/feeds/{fid}/refresh")
def api_feeds_refresh(fid: int):
    return feed_service.fetch_feed(fid)


@router.post("/api/feeds/refresh")
def api_feeds_refresh_all():
    return feed_service.fetch_all()


@router.post("/api/feeds/prune")
def api_feeds_prune():
    return feed_service.drop_invalid_feeds()


@router.get("/api/articles")
def api_articles_list(
    category: str = "",
    unread: str | None = None,
    saved: str | None = None,
    read_later: str | None = None,
    search: str = "",
    date_range: str = "all",
    lang: str = "",
    feed_id: int = 0,
    offset: int = 0,
    limit: int = 40,
):
    return article_service.list_articles(
        category=category,
        unread=_as_bool(unread),
        saved=_as_bool(saved),
        read_later=_as_bool(read_later),
        search=search,
        date_range=date_range,
        lang=lang,
        feed_id=feed_id,
        offset=offset,
        limit=limit,
    )


@router.get("/api/img")
def api_img(u: str, r: str = ""):
    try:
        data, ctype = proxy_image(u, r)
    except Exception:
        return Response(status_code=404)
    return Response(
        content=data,
        media_type=ctype,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/api/articles/{aid}")
def api_articles_get(aid: int):
    item = article_service.ensure_body(aid)
    if not item:
        return {"ok": False, "error": "missing"}
    return {"ok": True, "article": item}


@router.post("/api/articles/{aid}/read")
def api_articles_read(aid: int):
    item = article_service.mark_read(aid, True)
    if not item:
        return {"ok": False, "error": "missing"}
    return {"ok": True, "article": item}


@router.post("/api/articles/{aid}/save")
def api_articles_save(aid: int):
    item = article_service.toggle_saved(aid)
    if not item:
        return {"ok": False, "error": "missing"}
    return {"ok": True, "article": item}


@router.post("/api/articles/{aid}/read-later")
def api_articles_later(aid: int):
    item = article_service.toggle_read_later(aid)
    if not item:
        return {"ok": False, "error": "missing"}
    return {"ok": True, "article": item}


@router.post("/api/articles/{aid}/open")
def api_articles_open(aid: int):
    return article_service.open_article(aid)
