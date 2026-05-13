"""Storage layer.

Default backend remains JSON. Postgres is opt-in via
`CYBERALERTX_STORAGE_BACKEND=dual` (writes go to both; reads stay on JSON).
"""
from .base import NewsRepository
from .factory import build_news_repository, build_threat_post_cache
from .json_store import JsonNewsStore

__all__ = [
    "NewsRepository",
    "JsonNewsStore",
    "build_news_repository",
    "build_threat_post_cache",
]
