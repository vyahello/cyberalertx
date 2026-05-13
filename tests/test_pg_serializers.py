"""Pure-Python serializer round-trips for PgNewsStore.

No live database required. These tests catch schema/dataclass drift
by exercising every NewsItem field through the row converters and
asserting equality after a round trip.
"""
from __future__ import annotations

from datetime import datetime, timezone

from cyberalertx.models import NewsItem
from cyberalertx.storage.pg.serializers import news_item_to_row, row_to_news_item


def _rich_item() -> NewsItem:
    return NewsItem(
        title="TrickMo Android banker uses TON",
        source="BleepingComputer",
        url="https://www.bleepingcomputer.com/trickmo-ton/",
        published_at=datetime(2026, 5, 12, 14, 30, tzinfo=timezone.utc),
        raw_content="Body. " * 50,
        threat_score=78.2,
        tags=["android", "banker", "TON"],
        fetched_at=datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc),
        language="en",
        original_language="en",
        category="malware",
        category_confidence=0.91,
        affected_platforms=["Android"],
        audience_targets=["mobile_users"],
        audience_relevance_score=0.74,
        actionability_level="recommended_action",
        actionability_score=0.65,
        source_tier="trusted",
        source_credibility_score=0.88,
        corroborating_sources=["The Hacker News", "Krebs on Security"],
    )


def test_round_trip_preserves_all_fields():
    src = _rich_item()
    row = news_item_to_row(src)
    rebuilt = row_to_news_item(row)

    for field in (
        "title", "source", "url", "raw_content",
        "threat_score", "language", "original_language",
        "category", "category_confidence", "audience_relevance_score",
        "actionability_level", "actionability_score",
        "source_tier", "source_credibility_score",
    ):
        assert getattr(rebuilt, field) == getattr(src, field), field

    assert rebuilt.published_at == src.published_at
    assert rebuilt.tags == src.tags
    assert rebuilt.affected_platforms == src.affected_platforms
    assert rebuilt.audience_targets == src.audience_targets
    assert rebuilt.corroborating_sources == src.corroborating_sources


def test_row_contains_fingerprint_as_pk():
    """fingerprint isn't a stored dataclass field on NewsItem (it's a
    property), but the row converter must include it so ON CONFLICT
    works against the PK."""
    src = _rich_item()
    row = news_item_to_row(src)
    assert row["fingerprint"] == src.fingerprint


def test_naive_datetime_is_coerced_to_utc():
    """Defensive: a naive datetime entering the converter must become tz-aware."""
    item = NewsItem(
        title="t", source="s", url="https://e.test/x",
        # Intentionally naive — not a normal code path, but the
        # converter promises tolerance.
        published_at=datetime(2026, 1, 1, 12, 0),
        raw_content="",
    )
    row = news_item_to_row(item)
    assert row["published_at"].tzinfo is not None
    assert row["published_at"].utcoffset().total_seconds() == 0


def test_empty_lists_round_trip_as_empty_lists():
    item = NewsItem(
        title="t", source="s", url="https://e.test/empty",
        published_at=datetime.now(timezone.utc),
        raw_content="",
    )
    row = news_item_to_row(item)
    rebuilt = row_to_news_item(row)
    assert rebuilt.tags == []
    assert rebuilt.affected_platforms == []
    assert rebuilt.audience_targets == []
    assert rebuilt.corroborating_sources == []
