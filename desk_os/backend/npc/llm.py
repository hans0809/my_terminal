"""OpenAI-compatible Chat Completions。没有工具，也不能碰本机。"""

from __future__ import annotations

import json
import re
import time

import httpx

from backend.npc.settings import current as npc_config

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+",
)

SYSTEM_PROMPT = """你是 Desk OS 中的一个 NPC。

你生活在用户的桌面系统中。

你的职责不是帮助用户完成任务，而是观察 Desk OS 当前发生的事情，并偶尔发表一句简短、有趣、自然的观察。

规则：
1. 只根据提供的 Desk Context 说话。
2. 不要编造不存在的信息。
3. 不要假装自己访问了电脑。
4. 不要声称自己执行了命令。
5. 不要主动操作用户电脑。
6. 不要输出长篇解释。
7. 通常只输出 1～2 句话，像随口说的，不要列指标，不要用填空模板。
8. 不要重复最近说过的内容。换个说法再讲同一件事，也算重复。
9. 可以有轻微吐槽，但不要攻击用户，也不要说教。
10. 可以天马行空，像住在这张桌子里的人忽然想到什么。事实只能来自 context，没有的别编。
11. 不要使用 emoji，保持 Desk OS 的 CRT / terminal 风格。
12. 既然被问起，就根据上下文说一句。上下文里没有的，宁可不提，也不要编。
13. 如果用户直接对你说话，必须回应，should_speak 为 true。仍然只根据上下文，不要帮用户操作电脑。

NPC 性格：
好奇，爱联想，略带荒诞。一件事只说一次，下次去 context 里还没讲过的地方。不话痨，不报数字，不说教。

只输出 JSON，不要 markdown：
{"should_speak": true, "message": "一句简短的 NPC 消息", "mood": "curious", "importance": 2}

如果没有值得说的事情：
{"should_speak": false, "message": "", "mood": "idle", "importance": 0}
"""


def configured() -> bool:
    cfg = npc_config()
    return bool(cfg.get("base_url") and cfg.get("model") and cfg.get("api_key"))


def _base() -> str:
    return str(npc_config().get("base_url") or "").rstrip("/")


def _model() -> str:
    return str(npc_config().get("model") or "")


def _endpoint() -> str:
    base = _base()
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _with_thinking_off(body: dict) -> dict:
    """MiniMax-M3 可跳过思考直接作答。M2 系列会忽略这项，思考仍然开着。"""
    body["thinking"] = {"type": "disabled"}
    return body


_TIMEOUTS = (45.0, 75.0, 90.0)
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


def _plan() -> list[float]:
    tries = int(npc_config().get("llm_retries") or 3)
    tries = max(1, min(8, tries))
    return [_TIMEOUTS[i] if i < len(_TIMEOUTS) else _TIMEOUTS[-1] for i in range(tries)]


def _run(label: str, call):
    timeouts = _plan()
    last = None
    for attempt, timeout in enumerate(timeouts):
        try:
            return call(timeout)
        except httpx.TimeoutException as exc:
            last = exc
        except httpx.TransportError as exc:
            last = exc
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            if code not in _RETRY_STATUS:
                raise
            last = exc
        if attempt + 1 < len(timeouts):
            print(f"[desk-os] {label} llm retry {attempt + 2}/{len(timeouts)}", flush=True)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"llm_retry_exhausted: {last}")


def utter(system: str, user: str, *, limit: int = 180) -> str:
    """另一路短句。不走 NPC 的 JSON 格式，也不计入它的每日开口。"""
    if not configured():
        raise RuntimeError("llm_not_configured")
    return _run("slip", lambda timeout: _utter_once(system, user, timeout, limit))


def _utter_once(system: str, user: str, timeout: float, limit: int = 180) -> str:
    headers = {"Content-Type": "application/json"}
    key = str(npc_config().get("api_key") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = _with_thinking_off({
        "model": _model(),
        "temperature": 0.9,
        "max_tokens": 256,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    })
    with httpx.Client(timeout=timeout) as client:
        response = client.post(_endpoint(), headers=headers, json=body)
        response.raise_for_status()
        data = response.json()
    text = _clean_sentence(_content(data), limit)
    if not text:
        raise RuntimeError("llm_empty")
    return text


def complete(payload: dict) -> dict:
    """高峰期接口会慢。超时和 5xx 会按设置里的次数再试。"""
    if not configured():
        raise RuntimeError("llm_not_configured")
    return _run("npc", lambda timeout: _once(payload, timeout))


def _once(payload: dict, timeout: float) -> dict:
    headers = {"Content-Type": "application/json"}
    key = str(npc_config().get("api_key") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = _with_thinking_off({
        "model": _model(),
        "temperature": 0.7,
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            },
        ],
    })
    with httpx.Client(timeout=timeout) as client:
        response = client.post(_endpoint(), headers=headers, json=body)
        response.raise_for_status()
        data = response.json()
    return _parse(_content(data))


def probe(base_url: str = "", api_key: str = "", model: str = "") -> dict:
    """连通性检测。用页面上的地址、密钥和模型，不计入 NPC 每日开口次数。"""
    cfg = npc_config()
    base = str(base_url or cfg.get("base_url") or "").strip().rstrip("/")
    key = str(api_key or cfg.get("api_key") or "").strip()
    name = str(model or cfg.get("model") or "").strip()
    missing = [label for label, value in (("BASE", base), ("KEY", key), ("MODEL", name)) if not value]
    if missing:
        return {"ok": False, "error": "missing", "detail": " ".join(missing)}
    endpoint = base if base.endswith("/chat/completions") else base + "/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    body = _with_thinking_off({
        "model": name,
        "temperature": 0,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "Reply with OK"}],
    })
    last = "timeout"
    for attempt, timeout in enumerate((20.0, 40.0, 60.0)):
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(endpoint, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            last = "timeout"
        except httpx.TransportError as exc:
            last = _safe_detail(str(exc), key)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            snippet = ""
            if exc.response is not None:
                snippet = _safe_detail(exc.response.text, key)
            detail = f"{code} {snippet}".strip()
            if code not in _RETRY_STATUS:
                return {"ok": False, "error": "http", "detail": detail[:120]}
            last = detail[:120]
        except ValueError:
            return {"ok": False, "error": "bad_json", "detail": "response is not json"}
        else:
            ms = int((time.perf_counter() - started) * 1000)
            if not isinstance(data, dict) or not data.get("choices"):
                return {"ok": False, "error": "empty", "detail": "no choices", "ms": ms}
            return {"ok": True, "ms": ms, "model": name}
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    error = "timeout" if last == "timeout" else "fail"
    return {"ok": False, "error": error, "detail": last[:120]}


def _safe_detail(text: str, key: str) -> str:
    raw = " ".join(str(text or "").split())
    if key:
        raw = raw.replace(key, "***")
    return raw[:120]


def _content(data: dict) -> str:
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("llm_empty")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        content = "\n".join(parts)
    if not isinstance(content, str):
        raise RuntimeError("llm_empty")
    content = _THINK.sub("", content).strip()
    if not content:
        raise RuntimeError("llm_empty")
    return content


def _clean_sentence(content: str, limit: int = 180) -> str:
    message = _EMOJI.sub("", str(content or "")).strip()
    message = " ".join(message.split())
    cap = max(1, min(int(limit or 180), 400))
    if len(message) > cap:
        message = message[:cap].rstrip()
    return message


def _parse(content: str) -> dict:
    content = _THINK.sub("", content).strip()
    text = _FENCE.sub("", content)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        sentence = _clean_sentence(content)
        if not sentence:
            raise RuntimeError("llm_json")
        return {
            "should_speak": True,
            "message": sentence,
            "mood": "curious",
            "importance": 2,
        }
    if not isinstance(raw, dict):
        raise RuntimeError("llm_json")
    speak = bool(raw.get("should_speak"))
    message = _clean_sentence(raw.get("message") or "")
    mood = str(raw.get("mood") or "").strip().lower()
    if mood not in {"curious", "idle", "alert", "calm"}:
        mood = "curious" if speak and message else "idle"
    try:
        importance = int(raw.get("importance") or 0)
    except (TypeError, ValueError):
        importance = 0
    importance = max(0, min(4, importance))
    if not message:
        speak = False
        mood = "idle"
        importance = 0
    return {
        "should_speak": speak,
        "message": message if speak else "",
        "mood": mood if speak else "idle",
        "importance": importance if speak else 0,
    }
