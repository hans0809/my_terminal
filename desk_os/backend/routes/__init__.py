"""HTTP 路由。

新功能：在本目录加一个模块，导出 `router`，再加进下面的列表。
"""

from fastapi import APIRouter

from backend.routes.flow import router as flow_router
from backend.routes.keys import router as keys_router
from backend.routes.log import router as log_router
from backend.routes.npc import router as npc_router
from backend.routes.system import router as system_router
from backend.routes.tasks import router as tasks_router
from backend.routes.world import router as world_router

api_router = APIRouter()
for _router in (
    keys_router,
    world_router,
    system_router,
    tasks_router,
    flow_router,
    log_router,
    npc_router,
):
    api_router.include_router(_router)
