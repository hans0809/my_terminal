"""与窗口无关的后台任务。窗口就绪后才需要的逻辑放在 shell。"""

from backend.cursor_usage import start as start_cursor_usage
from backend.flow import start as start_flow


def start_workers() -> None:
    start_cursor_usage()
    start_flow()
