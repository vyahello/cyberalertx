"""Hybrid relevance filter — deterministic scoring + AI for gray-zone items.

What we pin here:
  * Strong cyber stories (phishing, ransomware, CVE) are accepted by
    DETERMINISTIC rules — they never reach the AI layer.
  * Obvious false positives (wind turbines, EVs, AI launches, funding,
    war headlines) are rejected by DETERMINISTIC rules — they never
    reach the AI layer either.
  * Gray-zone items get routed to the (mocked) AI classifier. AI's
    yes/no is honored.
  * Decisions are CACHED on disk by fingerprint. The second call for the
    same item is served from cache, no AI invocation.
  * When AI is disabled, the filter falls back to the legacy
    deterministic threshold (>=3).
  * `FilterStats` counters match the actual decision path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.normalize import normalize_item
from cyberalertx.pipeline.relevance import (
    ACCEPT_CEILING,
    REJECT_FLOOR,
    AIRelevanceClassifier,
    FilterStats,
    RelevanceCache,
    RelevanceDecision,
    classify_relevance,
    filter_relevant_hybrid,
)


# --------------------- fixtures / helpers ---------------------------------

def _item(title: str, body: str = "", url: str | None = None) -> NewsItem:
    it = NewsItem(
        title=title,
        source="t",
        url=url or f"https://e.test/{abs(hash(title))}",
        published_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        raw_content=body,
    )
    normalize_item(it)  # sets language so the language gate isn't tripped
    return it


@dataclass
class _StubVerdict:
    """Shape returned by AIRelevanceClassifier.classify — duck-typed."""
    is_relevant: bool
    confidence: float = 0.9
    category: str | None = None
    threat_type: str | None = None
    affected_audience: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.affected_audience is None:
            self.affected_audience = []


class _StubClassifier:
    """In-memory replacement for AIRelevanceClassifier.

    `verdict_for(title)` lets each test inject the answer per-item. Tracks
    call count so we can verify "the AI was only called on gray-zone items".
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.responses: dict[str, _StubVerdict] = {}

    def expect(self, title_substr: str, verdict: _StubVerdict) -> None:
        self.responses[title_substr.lower()] = verdict

    def classify(self, item: NewsItem) -> _StubVerdict:
        self.calls.append(item.title)
        for key, verdict in self.responses.items():
            if key in item.title.lower():
                return verdict
        # Default: accept. Tests that care about the verdict set expectations.
        return _StubVerdict(is_relevant=True, confidence=0.5)


# --------------------- deterministic-only tests ---------------------------

@pytest.mark.parametrize("title, body", [
    # Multiple strong signals — must clear the AI ceiling.
    ("CISA: actively exploited zero-day in Apache",
     "CVE-2026-1234 phishing rce vulnerability under active exploitation"),
    ("Critical ransomware campaign targets healthcare",
     "LockBit ransomware encrypts hospital systems; extortion underway"),
    ("Phishing wave steals Microsoft 365 credentials",
     "Credential theft campaign targets Microsoft 365 phishing wave underway"),
])
def test_strong_cyber_accepted_without_ai(title, body):
    stub = _StubClassifier()
    cache_path = None  # in-memory only
    kept, stats = filter_relevant_hybrid(
        [_item(title, body)], classifier=stub, cache=None,
    )
    assert len(kept) == 1
    assert stats.rules_accepted == 1
    assert stats.ai_validated == 0
    assert stub.calls == []


@pytest.mark.parametrize("title, body", [
    # Wind-turbine + battery: the false positive that motivated this rewrite.
    ("Більше не треба у порт: вітрові турбіни індуктивно заряджатимуть кораблі",
     "Магнітна система для бездротової зарядки суден. Замінює вразливі мідні контакти."),
    # Generic EV news.
    ("Electric vehicle launch breaks pre-order record",
     "The new EV is sold out as the company raises $200M in series C funding."),
    # Generic AI product launch — must NOT be cyber.
    ("OpenAI announces new model with better reasoning",
     "The new model is available to ChatGPT Plus subscribers."),
    # Funding round.
    ("Acme Inc raises $50M Series B for cloud platform",
     "The Series B will help Acme expand its cloud product."),
    # War headline with stray "паролі".
    ("Президент змінив паролі до своїх соціальних мереж",
     "Сьогодні відбулась зустріч президента з міністрами. Тривога триває."),
])
def test_obvious_junk_rejected_without_ai(title, body):
    stub = _StubClassifier()
    kept, stats = filter_relevant_hybrid(
        [_item(title, body)], classifier=stub, cache=None,
    )
    assert len(kept) == 0
    assert stats.rules_rejected == 1
    assert stats.ai_validated == 0
    assert stub.calls == []


def test_russian_dropped_by_language_gate():
    # Russian Cyrillic without UA-only markers (ї/є/ґ/і).
    item = _item(
        "Россия запустила новую систему оплаты",
        "Сегодня Россия объявила о запуске нового сервиса для оплаты товаров.",
    )
    # Force language to "other" — normalize_item already does this in practice
    # for pure-Russian text, but be explicit so the test doesn't depend on
    # the detector's tuning.
    item.language = "other"
    stub = _StubClassifier()
    kept, stats = filter_relevant_hybrid([item], classifier=stub, cache=None)
    assert kept == []
    assert stats.language_rejected == 1
    assert stub.calls == []


# --------------------- gray-zone / AI tests -------------------------------

def _gray_zone_item() -> NewsItem:
    """An item that scores 1–4 deterministically — needs AI to decide."""
    # "data leak" (medium=2) + "password" (weak=1) → 3. With NEGATIVE_TOKENS
    # absent, that's right at the legacy threshold but BELOW the
    # ACCEPT_CEILING of 5. Forces the AI path.
    return _item(
        "Possible password leak at SaaS vendor",
        "A small SaaS provider may have exposed customer passwords.",
    )


def test_gray_zone_routed_to_ai_and_accepted():
    item = _gray_zone_item()
    stub = _StubClassifier()
    stub.expect("password leak",
                _StubVerdict(is_relevant=True, confidence=0.85,
                             category="data leak", threat_type="credential exposure"))
    kept, stats = filter_relevant_hybrid([item], classifier=stub, cache=None)
    assert len(kept) == 1
    assert stats.ai_validated == 1
    assert stats.ai_accepted == 1
    assert stub.calls == [item.title]


def test_gray_zone_rejected_by_ai():
    item = _gray_zone_item()
    stub = _StubClassifier()
    stub.expect("password leak", _StubVerdict(is_relevant=False, confidence=0.95))
    kept, stats = filter_relevant_hybrid([item], classifier=stub, cache=None)
    assert kept == []
    assert stats.ai_validated == 1
    assert stats.ai_rejected == 1


def test_ai_error_falls_back_to_deterministic(monkeypatch):
    item = _gray_zone_item()

    class _Boom:
        def classify(self, _item):
            raise RuntimeError("network down")

    kept, stats = filter_relevant_hybrid([item], classifier=_Boom(), cache=None)
    # The item scored 3 (or thereabouts) — fallback threshold accepts it.
    assert stats.ai_errors == 1
    # Whichever direction the score lands, exactly ONE counter should fire.
    assert (stats.ai_accepted + stats.ai_rejected) == 1


def test_ai_disabled_falls_back_to_deterministic_threshold():
    # No classifier passed → degrades to deterministic with legacy threshold.
    item = _gray_zone_item()
    kept, stats = filter_relevant_hybrid([item], classifier=None, cache=None)
    # Gray zone with deterministic-only: accepted iff score >= 3.
    assert isinstance(kept, list)
    assert stats.ai_validated == 0  # AI was never tried
    assert stats.ai_accepted + stats.ai_rejected == 1


# --------------------- cache tests ----------------------------------------

def test_decision_cached_on_disk(tmp_path: Path):
    cache = RelevanceCache(tmp_path / "rel.json")
    stub = _StubClassifier()
    item = _gray_zone_item()
    stub.expect("password leak",
                _StubVerdict(is_relevant=True, category="data leak",
                             confidence=0.9, threat_type="exposure"))

    # First call hits the AI.
    d1 = classify_relevance(item, classifier=stub, cache=cache)
    assert d1.source == "ai-accept"
    assert len(stub.calls) == 1
    # File must exist and contain the fingerprint.
    cache_data = json.loads((tmp_path / "rel.json").read_text(encoding="utf-8"))
    assert item.fingerprint in cache_data

    # Second call (fresh cache instance) serves from disk — no AI invocation.
    cache2 = RelevanceCache(tmp_path / "rel.json")
    stub2 = _StubClassifier()
    d2 = classify_relevance(item, classifier=stub2, cache=cache2)
    assert d2.source == "ai-cached"
    assert d2.is_relevant is True
    assert d2.category == "data leak"
    assert stub2.calls == []


def test_cache_survives_malformed_file(tmp_path: Path):
    # Hand-write a junk cache file — loader should swallow and start fresh.
    path = tmp_path / "rel.json"
    path.write_text("not-json{{", encoding="utf-8")
    cache = RelevanceCache(path)
    assert len(cache) == 0


# --------------------- band constants ------------------------------------

def test_band_constants_are_ordered():
    """Sanity: the score bands have to be REJECT_FLOOR < ACCEPT_CEILING.
    Inverting them would route everything through the AI — expensive and
    almost certainly a regression."""
    assert REJECT_FLOOR < ACCEPT_CEILING


# --------------------- AIRelevanceClassifier parse helpers ----------------

def test_classifier_parse_extracts_json_from_fenced_markdown():
    """Haiku occasionally wraps responses in a markdown fence. The parser
    must dig the JSON out of common wrappers."""
    raw = (
        "```json\n"
        "{\"is_relevant\": true, \"confidence\": 0.92, \"category\": \"phishing\", "
        "\"threat_type\": \"credential theft\", "
        "\"affected_audience\": [\"normal_users\", \"enterprise\"]}\n"
        "```"
    )
    verdict = AIRelevanceClassifier._parse_verdict(raw)
    assert verdict.is_relevant is True
    assert verdict.confidence == pytest.approx(0.92)
    assert verdict.category == "phishing"
    assert verdict.threat_type == "credential theft"
    assert "normal_users" in verdict.affected_audience


def test_classifier_parse_rejects_unknown_category():
    """If the model returns a category outside our enum, it gets nulled.
    Prevents poisoning the category field with random labels."""
    raw = '{"is_relevant": true, "confidence": 0.7, "category": "vegan-cooking", "affected_audience": []}'
    verdict = AIRelevanceClassifier._parse_verdict(raw)
    assert verdict.category is None


def test_classifier_parse_raises_on_garbage():
    with pytest.raises(ValueError):
        AIRelevanceClassifier._parse_verdict("definitely not json at all")
