"""NPC 参数。存在 data/npc_settings.json，环境变量只在对应项为空时补上。"""

from __future__ import annotations

import json
import os
import threading

from backend.paths import DATA_DIR

SETTINGS_FILE = DATA_DIR / "npc_settings.json"

_lock = threading.Lock()
_cache: dict | None = None
_mtime: float | None = None


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _clip(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


_SLIP_LEGACY = {"sci": "科学", "wit": "幽默", "math": "数学", "lit": "文学"}
_SLIP_PROMPTS = {
    "科学": "写一句你确定为真的科学事实。不确定就换一句。不要编造，不要罗列，不要展开解释。",
    "幽默": "写一句干净的幽默。可以轻一点荒诞，不要攻击具体的人，不要低俗，不要解释笑点。",
    "数学": "写一句你确定为真的数学事实，或一个很短的洞察。不要出题，不要让人计算，不要编造定理。",
    "文学": "写一句原创的、有文学意味的短句。不要引用诗歌、小说或歌词原文。",
}


def _kind_name(value) -> str:
    raw = str(value or "").strip()
    return (_SLIP_LEGACY.get(raw.lower(), raw))[:16]


def _kind_prompt(name: str, prompt: str) -> str:
    text = " ".join(str(prompt or "").split())[:240]
    if text:
        return text
    return _SLIP_PROMPTS.get(name) or f"按「{name}」写一句。不要罗列，不要编造你不确定的事实。"


def _kinds(value) -> list[dict]:
    if not isinstance(value, list):
        value = list(_SLIP_PROMPTS)
    picked = []
    seen = set()
    for item in value:
        if isinstance(item, str):
            name = _kind_name(item)
            prompt = ""
        elif isinstance(item, dict):
            name = _kind_name(item.get("name") or item.get("kind") or "")
            prompt = item.get("prompt") or ""
        else:
            continue
        if not name or name in seen:
            continue
        seen.add(name)
        picked.append({"name": name, "prompt": _kind_prompt(name, prompt)})
        if len(picked) >= 12:
            break
    if picked:
        return picked
    return [{"name": name, "prompt": text} for name, text in _SLIP_PROMPTS.items()]


def _int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def normalize(raw: dict | None) -> dict:
    src = raw if isinstance(raw, dict) else {}
    if "base_url" in src:
        base = _clip(src.get("base_url"), 300)
    else:
        base = _clip(_env("DESK_OS_LLM_BASE_URL", "LLM_API_BASE") or "https://api.minimaxi.com/v1", 300)
    if "api_key" in src:
        key = _clip(src.get("api_key"), 400)
    else:
        key = _clip(_env("DESK_OS_LLM_API_KEY", "LLM_API_KEY"), 400)
    if "model" in src:
        model = _clip(src.get("model"), 80)
    else:
        model = _clip(_env("DESK_OS_LLM_MODEL", "LLM_MODEL") or "MiniMax-M3", 80)
    rank = _int(src.get("min_importance"), 2, 2, 4)
    if rank not in {2, 3, 4}:
        rank = 2
    return {
        "enabled": bool(src.get("enabled", True)),
        "base_url": base.rstrip("/"),
        "api_key": key,
        "model": model,
        "cooldown_min": _int(src.get("cooldown_min"), 3, 1, 180),
        "daily_cap": _int(src.get("daily_cap"), 120, 1, 400),
        "llm_retries": _int(src.get("llm_retries"), 3, 1, 8),
        "min_importance": rank,
        "slip_enabled": bool(src.get("slip_enabled", True)),
        "slip_min": _int(src.get("slip_min"), 30, 1, 720),
        "slip_kinds": _kinds(src.get("slip_kinds")),
    }


def current() -> dict:
    global _cache, _mtime
    with _lock:
        try:
            mtime = SETTINGS_FILE.stat().st_mtime
        except OSError:
            mtime = None
        if _cache is not None and mtime == _mtime:
            return dict(_cache)
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            raw = None
        data = normalize(raw if isinstance(raw, dict) else None)
        _cache = data
        _mtime = mtime
        return dict(data)


def save(fields: dict) -> dict:
    global _cache, _mtime
    merged = current()
    if not isinstance(fields, dict):
        fields = {}
    for key in (
        "enabled", "base_url", "api_key", "model", "cooldown_min", "daily_cap", "llm_retries", "min_importance",
        "slip_enabled", "slip_min", "slip_kinds",
    ):
        if key in fields and fields[key] is not None:
            merged[key] = fields[key]
    data = normalize(merged)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, SETTINGS_FILE)
        _cache = data
        try:
            _mtime = SETTINGS_FILE.stat().st_mtime
        except OSError:
            _mtime = None
    return dict(data)
