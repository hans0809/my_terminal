"""全局按键计数。"""

import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend import key_state

router = APIRouter()


@router.get("/api/key-pulse")
def api_key_pulse():
    return {"pulse": key_state.read(), "delta": key_state.consume()}


@router.get("/api/key-stream")
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
