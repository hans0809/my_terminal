"""FastAPI 本地 API"""

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend import key_state
from backend.cursor_usage import get_cursor_usage
from backend.focus import get_focus
from backend.system_monitor import get_system_status

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

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


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
