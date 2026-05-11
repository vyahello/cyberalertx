"""Backward-compat: legacy JSON snapshots (pre-enrichment-fields) must load."""
from __future__ import annotations

import json
from pathlib import Path

from cyberalertx.storage.json_store import JsonNewsStore


def test_legacy_snapshot_loads_with_defaults(tmp_path: Path) -> None:
    legacy = {
        "items": [
            {
                "fingerprint": "abc123",
                "title": "Old breach story",
                "source": "Legacy",
                "url": "https://e.test/legacy",
                "published_at": "2024-01-01T00:00:00+00:00",
                "raw_content": "data was breached",
                "threat_score": 42.0,
                "tags": [],
                "fetched_at": "2024-01-01T00:01:00+00:00",
                # No language / category / affected_platforms fields.
            }
        ]
    }
    path = tmp_path / "items.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    store = JsonNewsStore(path)
    items = store.all()
    assert len(items) == 1
    item = items[0]
    assert item.title == "Old breach story"
    # Defaults applied:
    assert item.language == "unknown"
    assert item.original_language == "unknown"
    assert item.category == "other"
    assert item.category_confidence == 0.0
    assert item.affected_platforms == []
    assert item.audience_targets == []
    assert item.audience_relevance_score == 0.0
    assert item.actionability_level == "informational"
    assert item.actionability_score == 0.0
    assert item.source_tier == "unverified"
    assert item.source_credibility_score == 0.0


def test_round_trip_preserves_enrichments(tmp_path: Path) -> None:
    from datetime import datetime, timezone
    from cyberalertx.models import NewsItem

    path = tmp_path / "items.json"
    store = JsonNewsStore(path)
    item = NewsItem(
        title="t",
        source="s",
        url="https://e.test/1",
        published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        raw_content="",
        threat_score=10.0,
        language="uk",
        original_language="uk",
        category="ransomware",
        category_confidence=0.85,
        affected_platforms=["Windows", "Linux"],
    )
    store.upsert_many([item])

    reopened = JsonNewsStore(path).all()
    assert len(reopened) == 1
    r = reopened[0]
    assert r.language == "uk"
    assert r.original_language == "uk"
    assert r.category == "ransomware"
    assert r.category_confidence == 0.85
    assert r.affected_platforms == ["Windows", "Linux"]
