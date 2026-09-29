"""运行日志。"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend import logbook

router = APIRouter()

_CLIENT_LOG = {
    "dog-bone": ("event", "DOG BONE"),
    "crt-on": ("event", "CRT ON"),
    "crt-off": ("event", "CRT OFF"),
}


class LogIn(BaseModel):
    code: str = Field(default="", max_length=24)


@router.get("/api/log")
def api_log_get(n: int = 180):
    return {"lines": logbook.recent(n), "apps": logbook.top_apps()}


@router.post("/api/log")
def api_log_post(body: LogIn):
    spec = _CLIENT_LOG.get((body.code or "").strip().lower())
    if not spec:
        return {"ok": False}
    line = logbook.record(*spec)
    return {"ok": bool(line), "line": line}
