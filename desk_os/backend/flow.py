"""FLOW 入口：供 main.py 启动定时抓取。"""

from backend.feed_service import init_db, start

__all__ = ["init_db", "start"]
