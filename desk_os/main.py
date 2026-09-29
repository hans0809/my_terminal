"""
Desk OS 进程入口。

启动顺序：本地 API → 后台采集 → 副屏窗口。
新功能的接口挂到 backend.routes，窗口无关的后台任务挂到 backend.boot。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.boot import start_workers  # noqa: E402
from backend.shell import open_window, serve  # noqa: E402


def main():
    port = serve()
    start_workers()
    open_window(port)


if __name__ == "__main__":
    main()
