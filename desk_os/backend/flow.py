"""FLOW 定时抓取。由 backend.boot 启动。"""

from backend.feed_service import init_db, start

__all__ = ["init_db", "start"]
