"""项目内固定路径。新的本地数据文件放在 DATA_DIR。

开发时数据在仓库的 data/。打包安装后数据在 %LOCALAPPDATA%\\DeskOS\\data，
重新安装不会覆盖。需要两边共用一份数据时，设置环境变量 DESK_OS_DATA。
"""

import os
import sys
from pathlib import Path


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resource_root() -> Path:
    if _frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    override = os.environ.get("DESK_OS_DATA", "").strip()
    if override:
        return Path(override)
    if _frozen():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "DeskOS" / "data"
    return Path(__file__).resolve().parent.parent / "data"


ROOT = _resource_root()
FRONTEND_DIR = ROOT / "frontend"
DATA_DIR = _data_dir()
