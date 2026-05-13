"""Postgres-backed `NewsRepository` implementation.

Read-path is NOT switched in this PR — the API still reads from JSON.
This class exists so the dual-write wrapper can fan-out writes to
Postgres without changing any caller. It also satisfies the
`compare_storage` validator's need for a read interface on PG to
compare against JSON.

Concurrency: SQLAlchemy Engine maintains its own connection pool
(see `engine.py`); each method acquires a connection, runs its
statement, releases. No long-lived sessions, no per-instance state
beyond config.
"""
from __future__ import annotations

import logging
from typing import Iterable, List

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...models import NewsItem
from ..base import NewsRepository
from .engine import get_engine
from .schema import news_items
from .serializers import news_item_to_row, row_to_news_item

logger = logging.getLogger(__name__)


class PgNewsStore(NewsRepository):
    """Backend that reads / writes `news_items` in Postgres.

    Interface matches `JsonNewsStore` exactly so the dual-write wrapper
    can treat both as `NewsRepository`. `max_items` is accepted for
    interface parity but NOT enforced — PG retains full history; the
    JSON store's retention cap is a file-size hack we don't need here.
    """

    def __init__(self, max_items: int = 5000) -> None:
        # Retained for parity with JsonNewsStore signature; intentionally unused.
        self._max_items = max_items

    # ------------------------------------------------------------------
    # NewsRepository surface
    # ------------------------------------------------------------------

    def known_fingerprints(self) -> set[str]:
        with get_engine().connect() as conn:
            result = conn.execute(select(news_items.c.fingerprint))
            return {row[0] for row in result}

    def all(self) -> List[NewsItem]:
        with get_engine().connect() as conn:
            result = conn.execute(
                select(news_items).order_by(news_items.c.published_at.desc())
            )
            return [row_to_news_item(r._mapping) for r in result]

    def upsert_many(self, items: Iterable[NewsItem]) -> List[NewsItem]:
        """INSERT ... ON CONFLICT (fingerprint) DO UPDATE.

        Mirrors `JsonNewsStore.upsert_many` semantics for re-ingest:
          * threat_score uses GREATEST() — a re-score never lowers an
            already-bumped value (e.g. cross-source corroboration bump
            from an earlier cycle is preserved).
          * tags union — additive, never dropped.
          * Other enrichment fields are overwritten on conflict so a
            re-classification (better category model, new audience
            heuristics) propagates cleanly.

        Returns the subset that was new. Implemented via a separate
        "what's already there?" SELECT — PG's `xmax = 0` trick is too
        clever and breaks under concurrent writers.
        """
        items_list = list(items)
        if not items_list:
            return []
        fps = {i.fingerprint for i in items_list}

        engine = get_engine()
        with engine.begin() as conn:
            existing = {
                row[0] for row in conn.execute(
                    select(news_items.c.fingerprint).where(
                        news_items.c.fingerprint.in_(fps)
                    )
                )
            }
            rows = [news_item_to_row(i) for i in items_list]
            stmt = pg_insert(news_items).values(rows)
            excluded = stmt.excluded
            # Array-union expressions written as raw text to avoid SQLAlchemy
            # auto-correlating an inner SELECT with `news_items` + `excluded`
            # (it can't tell the subquery is column-scoped, and emits a
            # cartesian-product warning). Both sides are column references —
            # no parameter injection risk.
            tags_union = text(
                "ARRAY(SELECT DISTINCT unnest("
                "news_items.tags || EXCLUDED.tags))"
            )
            corroborating_union = text(
                "ARRAY(SELECT DISTINCT unnest("
                "news_items.corroborating_sources || EXCLUDED.corroborating_sources))"
            )
            update_cols = {
                # Greatest-wins on numeric fields where re-scoring should not regress.
                "threat_score": func.greatest(news_items.c.threat_score, excluded.threat_score),
                "actionability_score": func.greatest(
                    news_items.c.actionability_score, excluded.actionability_score,
                ),
                "source_credibility_score": func.greatest(
                    news_items.c.source_credibility_score, excluded.source_credibility_score,
                ),
                # Additive (set-union) for list fields where downstream code
                # relies on accumulation across cycles. `corroborating_sources`
                # in particular gets recomputed per-batch from the current
                # peers; without the union, a solo re-ingest would wipe peers
                # added in earlier cycles.
                "tags": tags_union,
                "corroborating_sources": corroborating_union,
                # Latest-wins on classification fields.
                "title": excluded.title,
                "raw_content": excluded.raw_content,
                "language": excluded.language,
                "original_language": excluded.original_language,
                "category": excluded.category,
                "category_confidence": excluded.category_confidence,
                "affected_platforms": excluded.affected_platforms,
                "audience_targets": excluded.audience_targets,
                "audience_relevance_score": excluded.audience_relevance_score,
                "actionability_level": excluded.actionability_level,
                "source_tier": excluded.source_tier,
                "fetched_at": excluded.fetched_at,
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["fingerprint"],
                set_=update_cols,
            )
            conn.execute(stmt)

        return [i for i in items_list if i.fingerprint not in existing]


__all__ = ["PgNewsStore"]
