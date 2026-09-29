"""任务列表接口。存储在 tasks_store。"""

from fastapi import APIRouter

from backend import logbook
from backend.tasks_store import TasksBody, load_tasks, save_tasks

router = APIRouter()


@router.get("/api/tasks")
def api_tasks_get():
    return {"tasks": load_tasks()}


@router.put("/api/tasks")
def api_tasks_put(body: TasksBody):
    before = load_tasks()
    tasks = save_tasks(body.tasks)
    try:
        logbook.note_tasks(before, tasks)
    except Exception:
        pass
    return {"ok": True, "n": len(tasks)}
