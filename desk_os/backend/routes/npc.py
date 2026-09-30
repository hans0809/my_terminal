"""NPC 状态。刷新这个接口不会调用模型。"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.npc import scheduler
from backend.npc import settings as npc_settings
from backend.npc import llm
from backend.npc import slips

router = APIRouter()


class ViewIn(BaseModel):
    layer: str = Field(default="status", max_length=16)
    app: str = Field(default="", max_length=24)


class TriggerIn(BaseModel):
    event_type: str = Field(default="ordinary_state", max_length=32)


class PingIn(BaseModel):
    base_url: str = Field(default="", max_length=300)
    api_key: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=80)


class KindIn(BaseModel):
    name: str = Field(default="", max_length=16)
    prompt: str = Field(default="", max_length=240)


class SettingsIn(BaseModel):
    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=300)
    api_key: str | None = Field(default=None, max_length=400)
    model: str | None = Field(default=None, max_length=80)
    cooldown_min: int | None = None
    daily_cap: int | None = None
    llm_retries: int | None = None
    min_importance: int | None = None
    slip_enabled: bool | None = None
    slip_min: int | None = None
    slip_kinds: list[KindIn] | None = None


class KindPromptIn(BaseModel):
    name: str = Field(default="", max_length=16)


@router.get("/api/npc/status")
def api_npc_status():
    return scheduler.status()


@router.get("/api/npc/history")
def api_npc_history(n: int = 30):
    return {"items": scheduler.history(n)}


@router.post("/api/npc/view")
def api_npc_view(body: ViewIn):
    return {"ok": True, "view": scheduler.note_view(body.layer, body.app)}


@router.post("/api/npc/trigger")
def api_npc_trigger(body: TriggerIn):
    return scheduler.trigger(body.event_type)


class ChatIn(BaseModel):
    text: str = Field(default="", max_length=200)
    session: str = Field(default="", max_length=40)
    new: bool = False


@router.get("/api/npc/sessions")
def api_npc_sessions():
    return {"items": scheduler.conversations()}


@router.delete("/api/npc/sessions")
def api_npc_sessions_clear():
    return scheduler.forget_all()


@router.delete("/api/npc/sessions/{session_id}")
def api_npc_session_delete(session_id: str):
    return scheduler.forget(session_id)


@router.post("/api/npc/chat")
def api_npc_chat(body: ChatIn):
    return scheduler.chat(body.text, body.session, body.new)


@router.get("/api/npc/slips")
def api_npc_slips():
    return slips.status()


@router.post("/api/npc/slips")
def api_npc_slips_next():
    return slips.now()


@router.post("/api/npc/kinds/prompt")
def api_npc_kind_prompt(body: KindPromptIn):
    return slips.draft_prompt(body.name)


@router.delete("/api/npc/slips")
def api_npc_slips_clear():
    return slips.drop_all()


@router.delete("/api/npc/slips/{slip_id}")
def api_npc_slip_delete(slip_id: str):
    return slips.drop(slip_id)


@router.post("/api/npc/ping")
def api_npc_ping(body: PingIn):
    return llm.probe(body.base_url, body.api_key, body.model)


@router.get("/api/npc/settings")
def api_npc_settings():
    return npc_settings.current()


@router.put("/api/npc/settings")
def api_npc_settings_put(body: SettingsIn):
    dump = getattr(body, "model_dump", None) or body.dict
    return npc_settings.save(dump(exclude_unset=True))
