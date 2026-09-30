"""与窗口无关的后台任务。窗口就绪后才需要的逻辑放在 shell。"""

from backend.cursor_usage import start as start_cursor_usage
from backend.flights import start as start_flights
from backend.flow import start as start_flow
from backend.npc.scheduler import start as start_npc
from backend.npc.slips import start as start_slips


def start_workers() -> None:
    start_flights()
    start_cursor_usage()
    start_flow()
    start_npc()
    start_slips()
