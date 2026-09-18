"""FastAPI 本地 API"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import article_service, feed_service, key_state
from backend.article_fetch import proxy_image
from backend.cursor_usage import get_cursor_usage
from backend.focus import get_focus
from backend.system_monitor import get_system_status

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
DATA_DIR = FRONTEND_DIR.parent / "data"
TASKS_FILE = DATA_DIR / "tasks.json"
TASK_LIMIT = 48
TASK_LOG_LIMIT = 200
TASK_TITLE_LIMIT = 80
TASK_TEXT_LIMIT = 200

app = FastAPI(title="Desk OS", docs_url=None, redoc_url=None)
feed_service.init_db()


@app.get("/api/key-pulse")
def api_key_pulse():
    return {"pulse": key_state.read(), "delta": key_state.consume()}


@app.get("/api/key-stream")
async def api_key_stream():
    """SSE：全局按键计数。窗口失焦时仍可推到前端。"""

    async def gen():
        last = -1
        while True:
            pulse = await asyncio.to_thread(key_state.wait_pulse, 0.35)
            if pulse != last:
                last = pulse
                yield f"data: {pulse}\n\n"
            else:
                yield ": keepalive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/system")
def api_system():
    """系统状态 + 当前时间"""
    now = datetime.now()
    status = get_system_status()
    try:
        status["cursor"] = get_cursor_usage()
    except Exception:
        status["cursor"] = {"available": False, "label": "N/A"}
    try:
        status["keys"] = key_state.get_stats()
    except Exception:
        status["keys"] = {"today": 0, "recent_5m": 0, "per_min": 0}
    try:
        status["focus"] = get_focus()
    except Exception:
        status["focus"] = {"available": False, "label": "", "kind": "none"}
    status["datetime"] = {
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%a %d %b").upper(),
        "iso": now.isoformat(),
    }
    return status


class TaskBeat(BaseModel):
    t: str = ""
    text: str = Field(default="", max_length=TASK_TEXT_LIMIT)


class TaskItem(BaseModel):
    id: str = Field(max_length=40)
    title: str = Field(default="", max_length=TASK_TITLE_LIMIT)
    log: list[TaskBeat] = Field(default_factory=list)
    done: bool = False


class TasksBody(BaseModel):
    tasks: list[TaskItem] = Field(default_factory=list)


def _load_tasks() -> list[dict]:
    try:
        raw = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("tasks")
    if not isinstance(raw, list):
        return []
    return raw


def _clean_tasks(items: list[TaskItem]) -> list[dict]:
    out = []
    for item in items[:TASK_LIMIT]:
        beats = []
        for beat in item.log[:TASK_LOG_LIMIT]:
            text = (beat.text or "").strip()[:TASK_TEXT_LIMIT]
            if not text:
                continue
            t = beat.t.strip()[:40]
            beats.append({"t": t, "text": text})
        out.append({
            "id": (item.id or "")[:40],
            "title": (item.title or "").strip()[:TASK_TITLE_LIMIT],
            "log": beats,
            "done": bool(item.done),
        })
    return out


@app.get("/api/tasks")
def api_tasks_get():
    return {"tasks": _load_tasks()}


@app.put("/api/tasks")
def api_tasks_put(body: TasksBody):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tasks = _clean_tasks(body.tasks)
    payload = json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2)
    tmp = TASKS_FILE.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, TASKS_FILE)
    print(f"[desk-os] tasks saved n={len(tasks)}", flush=True)
    return {"ok": True, "n": len(tasks)}


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


@app.get("/api/feeds")
def api_feeds_list():
    return {"feeds": feed_service.list_feeds(), "counts": article_service.counts()}


@app.post("/api/feeds")
def api_feeds_add(body: FeedIn):
    interval = 30 if body.update_interval is None else body.update_interval
    return feed_service.add_feed(body.name, body.url, body.category, interval)


@app.put("/api/feeds/{fid}")
def api_feeds_put(fid: int, body: FeedPatch):
    dump = getattr(body, "model_dump", None) or body.dict
    fields = dump(exclude_unset=True)
    return feed_service.update_feed(fid, **fields)


@app.delete("/api/feeds/{fid}")
def api_feeds_delete(fid: int):
    return feed_service.drop_feed(fid)


@app.post("/api/feeds/{fid}/refresh")
def api_feeds_refresh(fid: int):
    return feed_service.fetch_feed(fid)


@app.post("/api/feeds/refresh")
def api_feeds_refresh_all():
    return feed_service.fetch_all()


@app.get("/api/articles")
def api_articles_list(
    category: str = "",
    unread: str | None = None,
    saved: str | None = None,
    read_later: str | None = None,
    search: str = "",
    date_range: str = "all",
    limit: int = 120,
):
    return article_service.list_articles(
        category=category,
        unread=_as_bool(unread),
        saved=_as_bool(saved),
        read_later=_as_bool(read_later),
        search=search,
        date_range=date_range,
        limit=limit,
    )


@app.get("/api/img")
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


@app.get("/api/articles/{aid}")
def api_articles_get(aid: int):
    item = article_service.ensure_body(aid)
    if not item:
        return {"ok": False, "error": "missing"}
    return {"ok": True, "article": item}


@app.post("/api/articles/{aid}/read")
def api_articles_read(aid: int):
    item = article_service.mark_read(aid, True)
    if not item:
        return {"ok": False, "error": "missing"}
    return {"ok": True, "article": item}


@app.post("/api/articles/{aid}/save")
def api_articles_save(aid: int):
    item = article_service.toggle_saved(aid)
    if not item:
        return {"ok": False, "error": "missing"}
    return {"ok": True, "article": item}


@app.post("/api/articles/{aid}/read-later")
def api_articles_later(aid: int):
    item = article_service.toggle_read_later(aid)
    if not item:
        return {"ok": False, "error": "missing"}
    return {"ok": True, "article": item}


@app.post("/api/articles/{aid}/open")
def api_articles_open(aid: int):
    return article_service.open_article(aid)


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
