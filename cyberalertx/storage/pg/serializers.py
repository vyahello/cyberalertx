"""Row ↔ NewsItem converters.

Pure, no I/O — exists so the store class stays thin and the round-trip
logic is unit-testable without a live database.

`news_item_to_row` returns a dict ready for SQLAlchemy `insert().values()`.
`row_to_news_item` accepts a `Row._mapping` (dict-like) from a SELECT and
reconstructs a `NewsItem`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from ...models import NewsItem


def _utc(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def news_item_to_row(item: NewsItem) -> dict[str, Any]:
    """Project a `NewsItem` into the column-key dict the PG store inserts."""
    return {
        "fingerprint": item.fingerprint,
        "title": item.title,
        "source": item.source,
        "url": item.url,
        "published_at": _utc(item.published_at),
        "raw_content": item.raw_content or "",
        "threat_score": float(item.threat_score),
        "tags": list(item.tags or []),
        "fetched_at": _utc(item.fetched_at),
        "language": item.language or "unknown",
        "original_language": item.original_language or "unknown",
        "category": item.category or "other",
        "category_confidence": float(item.category_confidence),
        "affected_platforms": list(item.affected_platforms or []),
        "audience_targets": list(item.audience_targets or []),
        "audience_relevance_score": float(item.audience_relevance_score),
        "actionability_level": item.actionability_level or "informational",
        "actionability_score": float(item.actionability_score),
        "source_tier": item.source_tier or "unverified",
        "source_credibility_score": float(item.source_credibility_score),
        "corroborating_sources": list(item.corroborating_sources or []),
    }


def row_to_news_item(row: Mapping[str, Any]) -> NewsItem:
    """Reconstruct a `NewsItem` from a SELECT row mapping."""
    return NewsItem(
        title=row["title"],
        source=row["source"],
        url=row["url"],
        published_at=_utc(row["published_at"]),
        raw_content=row.get("raw_content", "") or "",
        threat_score=float(row.get("threat_score", 0.0) or 0.0),
        tags=list(row.get("tags") or []),
        fetched_at=_utc(row.get("fetched_at")),
        language=row.get("language") or "unknown",
        original_language=row.get("original_language") or "unknown",
        category=row.get("category") or "other",
        category_confidence=float(row.get("category_confidence", 0.0) or 0.0),
        affected_platforms=list(row.get("affected_platforms") or []),
        audience_targets=list(row.get("audience_targets") or []),
        audience_relevance_score=float(row.get("audience_relevance_score", 0.0) or 0.0),
        actionability_level=row.get("actionability_level") or "informational",
        actionability_score=float(row.get("actionability_score", 0.0) or 0.0),
        source_tier=row.get("source_tier") or "unverified",
        source_credibility_score=float(row.get("source_credibility_score", 0.0) or 0.0),
        corroborating_sources=list(row.get("corroborating_sources") or []),
    )


__all__ = ["news_item_to_row", "row_to_news_item"]
