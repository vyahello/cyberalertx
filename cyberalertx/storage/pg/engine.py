"""Lazy SQLAlchemy engine + connection pool for Postgres.

Why lazy: the rest of the codebase imports `storage` freely, and we
don't want a missing `CYBERALERTX_PG_URL` to crash module load — only
the code that actually tries to use Postgres should care.

Driver: psycopg3 via SQLAlchemy's `postgresql+psycopg` dialect. We
auto-rewrite raw `postgresql://` / `postgres://` URLs so a user can
paste their Supabase connection string verbatim from the dashboard.

Pool tuning (sane production defaults; tweak via env if needed):
  * pool_size=2          — idle connections kept warm
  * max_overflow=8       — burst capacity up to 10 concurrent
  * pool_pre_ping=True   — validate before checkout (catches stale conns)
  * pool_recycle=1800    — recycle every 30 min (Supabase idle timeout)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import Engine, create_engine

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None


# Env-var-overridable pool parameters. Defaults match the docstring above.
_POOL_SIZE = int(os.getenv("CYBERALERTX_PG_POOL_SIZE", "2"))
_MAX_OVERFLOW = int(os.getenv("CYBERALERTX_PG_MAX_OVERFLOW", "8"))
_POOL_RECYCLE = int(os.getenv("CYBERALERTX_PG_POOL_RECYCLE_S", "1800"))


def _normalize_pg_url(url: str) -> str:
    """Rewrite raw `postgresql://` / `postgres://` to use the psycopg3 dialect.

    Supabase's dashboard hands users a plain `postgresql://...` URL that
    SQLAlchemy would route to psycopg2 by default. Force psycopg3 (faster,
    actively maintained, our installed driver) without making the user
    care about the dialect prefix.
    """
    if url.startswith(("postgresql+psycopg://", "postgres+psycopg://")):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


def get_engine() -> Engine:
    """Return the process-wide engine, constructing it on first call."""
    global _engine
    if _engine is not None:
        return _engine
    raw_url = os.getenv("CYBERALERTX_PG_URL")
    if not raw_url:
        raise RuntimeError(
            "CYBERALERTX_PG_URL is not set. Set it to your Supabase / Postgres "
            "connection string (e.g. postgresql://USER:PASS@HOST:5432/DB?sslmode=require)."
        )
    url = _normalize_pg_url(raw_url)
    logger.info(
        "creating Postgres engine (pool_size=%d, max_overflow=%d, recycle=%ds)",
        _POOL_SIZE, _MAX_OVERFLOW, _POOL_RECYCLE,
    )
    _engine = create_engine(
        url,
        pool_size=_POOL_SIZE,
        max_overflow=_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=_POOL_RECYCLE,
        future=True,
    )
    return _engine


def dispose_engine() -> None:
    """Tear down the pool. Useful in tests and clean shutdown."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


__all__ = ["get_engine", "dispose_engine"]
