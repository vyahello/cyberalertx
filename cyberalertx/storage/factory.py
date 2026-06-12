"""Storage-backend factory.

One env var (`CYBERALERTX_STORAGE_BACKEND`) selects what the build_* helpers
return. Default is `"json"` — bit-for-bit identical to legacy behavior.

Allowed values:
  * `"json"`  → JSON-only stores. MVP / rollback default.
  * `"dual"`  → JSON + PostgreSQL.
        - News store: writes fan out to both; reads from JSON.
        - Threat-post cache: writes fan out to both; reads from PG with
          JSON fallback (per PR-2: feed reads from PG).
        PG init failure is LOGGED then silently falls back to JSON-only —
        the pipeline must never break because Postgres is down.

`"postgres"` (read-from-PG for news) reserved for a later PR.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from ..config import SETTINGS
from .base import NewsRepository
from .json_store import JsonNewsStore

if TYPE_CHECKING:  # avoids ai.cache → storage import cycle at runtime
    from ..ai.cache import ThreatPostCache
    from .dual_write import ThreatPostStore

logger = logging.getLogger(__name__)


def _selected_backend() -> str:
    return os.getenv("CYBERALERTX_STORAGE_BACKEND", "json").strip().lower()


def build_news_repository(
    storage_path: Optional[Path] = None,
    max_items: Optional[int] = None,
) -> NewsRepository:
    """Return the configured `NewsRepository` implementation.

    `storage_path` / `max_items` default to `SETTINGS` so callers normally
    pass nothing. Tests pass an isolated path so a parallel test run
    doesn't fight over `data/items.json`.
    """
    storage_path = storage_path or SETTINGS.storage_path
    max_items = max_items if max_items is not None else SETTINGS.max_items_retained
    primary: NewsRepository = JsonNewsStore(storage_path, max_items=max_items)

    backend = _selected_backend()
    if backend == "json":
        return primary

    if backend == "dual":
        # Lazy import — keeps SQLAlchemy / psycopg off the import path
        # when the user runs JSON-only (the common case).
        #
        # We eagerly probe `get_engine()` here so a misconfigured
        # CYBERALERTX_PG_URL fails LOUDLY at startup with a logged
        # warning, rather than silently degrading to JSON-only with
        # every PG write logging a quiet failure. Better operator UX —
        # the message tells you to fix the URL, not chase phantom
        # "shadow write failed" logs in production.
        try:
            from .pg.engine import get_engine
            from .pg.news_store import PgNewsStore
            from .dual_write import DualWriteNewsStore
            get_engine()  # raises if CYBERALERTX_PG_URL is missing/malformed
            secondary = PgNewsStore()
            return DualWriteNewsStore(primary=primary, secondary=secondary)
        except Exception as exc:
            logger.warning(
                "CYBERALERTX_STORAGE_BACKEND=dual but Postgres setup failed "
                "(%s: %s); serving JSON-only.",
                type(exc).__name__, exc,
            )
            return primary

    logger.warning(
        "Unknown CYBERALERTX_STORAGE_BACKEND=%r; falling back to json.",
        backend,
    )
    return primary


def build_threat_post_cache(cache_path: Path) -> "ThreatPostStore":
    """Return the configured ThreatPost cache.

    Returns:
        * JSON-only `ThreatPostCache` when STORAGE_BACKEND=json (default).
        * `DualWriteThreatPostCache(primary=JSON, secondary=PG)` when
          STORAGE_BACKEND=dual. Reads PG-preferred with JSON fallback;
          writes go to both.

    Caller (cyberalertx.ai.generator.build_default_generator) passes the
    existing on-disk cache path so the JSON layer keeps its location.
    """
    # Local import — keeps the ai → storage dependency one-way.
    from ..ai.cache import ThreatPostCache

    primary = ThreatPostCache(cache_path)

    if _selected_backend() != "dual":
        return primary

    # Dual mode — wrap with PG-aware dual-write. Probe the engine first
    # so a misconfigured URL surfaces with a single warning here, not
    # quietly on every cache hit.
    try:
        from .pg.engine import get_engine
        from .pg.threat_cache import PgThreatPostStore
        from .dual_write import DualWriteThreatPostCache
        get_engine()
        secondary = PgThreatPostStore()
        return DualWriteThreatPostCache(primary=primary, secondary=secondary)
    except Exception as exc:
        logger.warning(
            "CYBERALERTX_STORAGE_BACKEND=dual but PG threat-post cache setup "
            "failed (%s: %s); serving JSON-only.",
            type(exc).__name__, exc,
        )
        return primary


__all__ = ["build_news_repository", "build_threat_post_cache"]
