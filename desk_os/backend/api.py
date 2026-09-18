"""FastAPI 本地 API"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import key_state
from backend.cursor_usage import get_cursor_usage
from backend.focus import get_focus
from backend.system_monitor import get_system_status

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
DATA_DIR = FRONTEND_DIR.parent / "data"
NOTE_FILE = DATA_DIR / "note.txt"
NOTE_LIMIT = 20000
CLIP_LIMIT = 4000
TASKS_FILE = DATA_DIR / "tasks.json"
TASK_LIMIT = 48
TASK_LOG_LIMIT = 200
TASK_TITLE_LIMIT = 80
TASK_TEXT_LIMIT = 200

app = FastAPI(title="Desk OS", docs_url=None, redoc_url=None)


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


class NoteBody(BaseModel):
    text: str = Field(default="", max_length=NOTE_LIMIT)


@app.get("/api/note")
def api_note_get():
    try:
        text = NOTE_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except OSError:
        text = ""
    return {"text": text[:NOTE_LIMIT]}


@app.put("/api/note")
def api_note_put(body: NoteBody):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    NOTE_FILE.write_text(body.text[:NOTE_LIMIT], encoding="utf-8")
    return {"ok": True}


@app.get("/api/clipboard")
def api_clipboard():
    text = ""
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "[Console]::OutputEncoding = [Text.UTF8Encoding]::UTF8; Get-Clipboard",
                ],
                timeout=2,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,
            )
            text = out.decode("utf-8", errors="replace")
        except (subprocess.SubprocessError, OSError):
            text = ""
    return {"text": text[:CLIP_LIMIT]}


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


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
