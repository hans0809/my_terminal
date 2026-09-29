"""项目内固定路径。新的本地数据文件放在 DATA_DIR。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"
DATA_DIR = ROOT / "data"
