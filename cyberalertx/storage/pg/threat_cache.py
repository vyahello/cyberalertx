"""Postgres-backed ThreatPost cache.

Drop-in replacement for `cyberalertx.ai.cache.ThreatPostCache` (same
`get` / `set` / `all` surface). Storage lives in `threat_posts`
(PK = fingerprint + locale, JSONB payload).

Denormalized columns (`published_at`, `category`, `actionability_level`)
are auto-filled by the `sync_threat_posts_denormalized` trigger in
migration 003 — Python code never has to know about them.

The PG store is the **primary** read source for the homepage feed when
`STORAGE_BACKEND=dual` (per PR-2 design). JSON cache remains as a
fallback layer in the dual-write wrapper.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...ai.models import ThreatPost
from .engine import get_engine
from .schema import threat_posts

logger = logging.getLogger(__name__)


class PgThreatPostStore:
    """ThreatPostCache-compatible PostgreSQL backend.

    Interface match:
        get(fingerprint, locale="en") -> ThreatPost | None
        set(fingerprint, locale, post: ThreatPost) -> None
        all() -> Iterable[ThreatPost]
        __len__() -> int

    Plus PG-only conveniences:
        list_latest(language, limit) -> list of (fingerprint, ThreatPost)
            Single-table query against `threat_posts` ordered by the
            denormalized `published_at DESC`. Used by the feed.
    """

    # ----- ThreatPostCache surface --------------------------------------

    def get(self, fingerprint: str, locale: str = "en") -> Optional[ThreatPost]:
        with get_engine().connect() as conn:
            row = conn.execute(
                select(threat_posts.c.payload).where(
                    threat_posts.c.fingerprint == fingerprint,
                    threat_posts.c.locale == locale,
                )
            ).first()
        if row is None:
            return None
        try:
            return ThreatPost.from_dict(row[0])
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning(
                "PG cache: malformed payload for %s/%s (%s) — treating as miss.",
                fingerprint, locale, exc,
            )
            return None

    def set(self, fingerprint: str, locale: str, post: ThreatPost) -> None:
        payload = post.to_dict()
        # The trigger fills published_at/category/actionability_level from
        # news_items. We only write the columns we own at the Python layer.
        row = {
            "fingerprint": fingerprint,
            "locale": locale,
            "title": post.title or "",
            "threat_level": post.threat_level or "Low",
            "generated_by": post.generated_by or "rule_based",
            "language": post.language or locale,
            "payload": payload,
        }
        stmt = pg_insert(threat_posts).values(row)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["fingerprint", "locale"],
            set_={
                "title": excluded.title,
                "threat_level": excluded.threat_level,
                "generated_by": excluded.generated_by,
                "language": excluded.language,
                "payload": excluded.payload,
                # updated_at touched by trigger? No — we own this.
                "updated_at": text("now()"),
            },
        )
        with get_engine().begin() as conn:
            conn.execute(stmt)

    def all(self) -> Iterable[ThreatPost]:
        with get_engine().connect() as conn:
            for row in conn.execute(select(threat_posts.c.payload)):
                try:
                    yield ThreatPost.from_dict(row[0])
                except (KeyError, ValueError, TypeError):
                    continue

    def __len__(self) -> int:
        with get_engine().connect() as conn:
            return conn.execute(
                select(threat_posts.c.fingerprint).select_from(threat_posts)
            ).rowcount or sum(1 for _ in self.all())

    # ----- PG-only convenience -----------------------------------------

    def list_latest(
        self,
        language: str,
        limit: int = 15,
    ) -> list[tuple[str, ThreatPost]]:
        """Return up to `limit` freshest posts in `language`, ordered by
        the denormalized `published_at DESC`. Single-table query — no
        JOIN with news_items needed.

        Returns (fingerprint, ThreatPost) pairs so the caller can join
        with NewsItem metadata for the API response shape. Items with
        NULL published_at (the trigger couldn't find a matching news_items
        row at insert time) sort last via NULLS LAST.
        """
        with get_engine().connect() as conn:
            rows = conn.execute(
                select(threat_posts.c.fingerprint, threat_posts.c.payload)
                .where(threat_posts.c.locale == language)
                .order_by(threat_posts.c.published_at.desc().nulls_last())
                .limit(limit)
            ).fetchall()
        result: list[tuple[str, ThreatPost]] = []
        for fp, payload in rows:
            try:
                result.append((fp, ThreatPost.from_dict(payload)))
            except (KeyError, ValueError, TypeError):
                continue
        return result


__all__ = ["PgThreatPostStore"]
