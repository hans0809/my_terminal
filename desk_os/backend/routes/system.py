"""主页状态快照。"""

from datetime import datetime

from fastapi import APIRouter

from backend import key_state, logbook
from backend.cursor_usage import get_cursor_usage
from backend.focus import get_focus
from backend.system_monitor import get_system_status

router = APIRouter()


@router.get("/api/system")
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
    try:
        logbook.observe(status)
    except Exception:
        pass
    status["log"] = logbook.tail(logbook.HOME_LINES)
    status["apps"] = logbook.top_apps()
    status["datetime"] = {
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%a %d %b").upper(),
        "iso": now.isoformat(),
    }
    return status
