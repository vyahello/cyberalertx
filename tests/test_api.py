"""Tests for the FastAPI surface.

We test through the app factory with an injected `_PostService` backed by
an in-memory NewsItem list — keeps tests fast and avoids touching disk.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest
from fastapi.testclient import TestClient

from cyberalertx.api.app import _PostService, build_app
from cyberalertx.ai.generator import ContentGenerator
from cyberalertx.models import NewsItem


def _item(**overrides) -> NewsItem:
    base = dict(
        title="Critical RCE in widget framework",
        source="BleepingComputer",
        url=f"https://e.test/{overrides.get('url_id', 'x')}",
        published_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        raw_content="A widget framework has an RCE flaw under active exploitation.",
        threat_score=70.0,
        category="vulnerability",
        affected_platforms=["Linux"],
        audience_targets=["sysadmins"],
        actionability_level="urgent_action",
        actionability_score=0.85,
        source_tier="trusted",
        source_credibility_score=0.85,
        language="en",
    )
    overrides.pop("url_id", None)
    base.update(overrides)
    return NewsItem(**base)


class _FakeStore:
    """In-memory replacement for JsonNewsStore. Just enough for the service."""
    def __init__(self, items: List[NewsItem]) -> None:
        self._items = items

    def all(self) -> List[NewsItem]:
        return list(self._items)


class _FakeService(_PostService):
    """Bypasses disk — uses a fixed list of items + the real generator."""
    def __init__(self, items: List[NewsItem]) -> None:
        self._items = items
        # Provider-less generator → all output via rule-based path. Cache
        # disabled (cache=None) so tests don't leak across instances.
        self._generator = ContentGenerator(provider=None, cache=None)

    def list_items(self) -> List[NewsItem]:
        return list(self._items)


@pytest.fixture
def client() -> TestClient:
    items = [
        _item(url_id="a", threat_score=70.0, actionability_level="urgent_action"),
        _item(url_id="b", threat_score=40.0, actionability_level="recommended_action",
              category="phishing"),
        _item(url_id="c", threat_score=15.0, actionability_level="informational",
              category="other", language="uk", title="Звичайна новина"),
    ]
    app = build_app(service=_FakeService(items))
    return TestClient(app)


# ---------- /healthz ----------

def test_healthz_ok(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    payload = r.json()
    assert payload["ok"] is True
    assert payload["stored_items"] == 3


# ---------- /posts ----------

def test_list_posts_returns_all_sorted(client: TestClient) -> None:
    r = client.get("/posts")
    assert r.status_code == 200
    payload = r.json()
    assert payload["total"] == 3
    # Sorted by threat_score desc.
    scores_in_order = [p["actionability_score"] for p in payload["items"]]
    assert scores_in_order == sorted(scores_in_order, reverse=True)


def test_list_posts_respects_limit(client: TestClient) -> None:
    r = client.get("/posts?limit=2")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_list_posts_filters_by_language(client: TestClient) -> None:
    r = client.get("/posts?language=uk")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    # New shape: filter against available_locales, not a flat language field.
    assert "uk" in items[0]["available_locales"]
    assert "uk" in items[0]["translations"]


# ---------- /posts/trending ----------

def test_trending_includes_only_urgent_or_critical(client: TestClient) -> None:
    r = client.get("/posts/trending")
    assert r.status_code == 200
    items = r.json()["items"]
    # Only the urgent_action item qualifies (the score=15 one doesn't).
    assert len(items) == 1
    assert items[0]["actionability_level"] == "urgent_action"


# ---------- /posts/latest ----------

def test_latest_returns_all_when_under_limit(client: TestClient) -> None:
    r = client.get("/posts/latest")
    assert r.status_code == 200
    assert r.json()["total"] == 3


# ---------- /posts/{id} ----------

def test_post_by_id_returns_match(client: TestClient) -> None:
    listing = client.get("/posts").json()["items"]
    target = listing[0]
    r = client.get(f"/posts/{target['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == target["id"]


def test_post_by_id_404s_when_missing(client: TestClient) -> None:
    r = client.get("/posts/nonexistent-fingerprint")
    assert r.status_code == 404


# ---------- schema sanity ----------

def test_response_shape_matches_frontend_contract(client: TestClient) -> None:
    """Every required field on the frontend's LocalizedThreatPost type is present."""
    item = client.get("/posts?limit=1").json()["items"][0]
    required_shared = {
        "id", "source", "source_url", "source_tier", "source_credibility_score",
        "published_at", "threat_level", "category", "affected_platforms",
        "audience_targets", "actionability_level", "actionability_score",
        "emotional_weight", "available_locales", "translations",
    }
    assert not (required_shared - set(item.keys())), \
        f"missing shared fields: {required_shared - set(item.keys())}"

    # Every present locale in `translations` must have the full text content.
    required_text = {
        "title", "short_summary", "why_it_matters", "affected_users",
        "what_to_do", "what_not_to_do", "quick_facts", "reading_time_seconds",
    }
    for locale in item["available_locales"]:
        assert locale in item["translations"], f"locale {locale} missing from translations"
        content = item["translations"][locale]
        missing = required_text - set(content.keys())
        assert not missing, f"locale {locale} missing fields: {missing}"
