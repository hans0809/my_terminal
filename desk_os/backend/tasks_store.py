"""任务列表的本地存储。"""

import json
import os

from pydantic import BaseModel, Field

from backend.paths import DATA_DIR

TASKS_FILE = DATA_DIR / "tasks.json"
TASK_LIMIT = 48
TASK_LOG_LIMIT = 200
TASK_TITLE_LIMIT = 80
TASK_TEXT_LIMIT = 200


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


def load_tasks() -> list[dict]:
    try:
        raw = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("tasks")
    if not isinstance(raw, list):
        return []
    return raw


def clean_tasks(items: list[TaskItem]) -> list[dict]:
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


def save_tasks(items: list[TaskItem]) -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tasks = clean_tasks(items)
    payload = json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2)
    tmp = TASKS_FILE.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, TASKS_FILE)
    print(f"[desk-os] tasks saved n={len(tasks)}", flush=True)
    return tasks
