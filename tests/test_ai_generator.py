"""End-to-end generator tests with a mock provider.

These tests cover:
  * provider success path → cache write → cache read on second call
  * provider failure path → rule-based fallback engaged
  * no-provider path → rule-based directly
  * language / audience routing
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cyberalertx.ai.cache import ThreatPostCache
from cyberalertx.ai.generator import ContentGenerator
from cyberalertx.ai.models import ThreatPostResponse
from cyberalertx.models import NewsItem


def _item(**overrides) -> NewsItem:
    base = dict(
        title="Critical RCE in widget framework",
        source="BleepingComputer",
        url="https://e.test/abc",
        published_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        raw_content="A remote code execution flaw was disclosed in widget v1.2.",
        threat_score=42.0,
        category="vulnerability",
        affected_platforms=["Linux"],
        audience_targets=["developers", "sysadmins"],
        actionability_level="recommended_action",
        actionability_score=0.6,
        source_tier="trusted",
        source_credibility_score=0.85,
        language="en",
    )
    base.update(overrides)
    return NewsItem(**base)


@dataclass
class MockProvider:
    """Records every call. Configurable to succeed, fail, or alternate."""
    name: str = "mock:test"
    fail: bool = False
    calls: list[tuple[str, str]] = None
    response: ThreatPostResponse | None = None

    def __post_init__(self):
        if self.calls is None:
            self.calls = []
        if self.response is None:
            self.response = ThreatPostResponse(
                title="Patch widget v1.2 — remote code execution disclosed",
                short_summary="A flaw in widget v1.2 lets attackers run code on your server. A patch is available.",
                threat_level="High",
                why_it_matters="If exploited, attackers could fully take over the affected server.",
                affected_users=["Developers using widget", "Sysadmins running widget services"],
                what_to_do=["Update widget to v1.3 or later", "Audit your servers for IoCs"],
                what_not_to_do=["Don't expose the widget admin port to the public internet"],
                quick_facts=["Patch available", "Affects widget v1.2", "RCE"],
                emotional_weight=0.65,
                reading_time_seconds=25,
            )

    def generate_post(self, system: str, user: str) -> ThreatPostResponse:
        self.calls.append((system, user))
        if self.fail:
            raise RuntimeError("simulated provider failure")
        return self.response


# ---------- success path ----------

def test_provider_success_writes_to_cache(tmp_path: Path) -> None:
    cache = ThreatPostCache(tmp_path / "posts.json")
    provider = MockProvider()
    gen = ContentGenerator(provider=provider, cache=cache)

    post = gen.generate(_item())

    assert post.generated_by == "mock:test"
    assert post.threat_level == "High"
    assert len(provider.calls) == 1
    # And it's now cached.
    assert cache.get(_item().fingerprint) is not None


def test_second_call_hits_cache_not_provider(tmp_path: Path) -> None:
    cache = ThreatPostCache(tmp_path / "posts.json")
    provider = MockProvider()
    gen = ContentGenerator(provider=provider, cache=cache)

    gen.generate(_item())
    gen.generate(_item())  # same fingerprint

    assert len(provider.calls) == 1  # provider was only called once


# ---------- failure path ----------

def test_provider_failure_falls_back_to_rule_based(tmp_path: Path) -> None:
    cache = ThreatPostCache(tmp_path / "posts.json")
    provider = MockProvider(fail=True)
    gen = ContentGenerator(provider=provider, cache=cache)

    post = gen.generate(_item())

    assert post.generated_by == "rule_based"
    assert post.threat_level in {"Low", "Medium", "High", "Critical"}
    # Rule-based output is NOT cached — next call should retry the provider.
    assert cache.get(_item().fingerprint) is None
    assert len(provider.calls) == 1


def test_rule_based_path_runs_provider_again_on_retry(tmp_path: Path) -> None:
    """If the provider fails once, the next call still tries it."""
    cache = ThreatPostCache(tmp_path / "posts.json")
    provider = MockProvider(fail=True)
    gen = ContentGenerator(provider=provider, cache=cache)

    gen.generate(_item())
    gen.generate(_item())

    assert len(provider.calls) == 2  # both calls hit the provider


# ---------- no-provider path ----------

def test_no_provider_uses_rule_based_directly() -> None:
    gen = ContentGenerator(provider=None, cache=None)
    post = gen.generate(_item())
    assert post.generated_by == "rule_based"


# ---------- routing ----------

def test_force_language_routes_to_ukrainian_template() -> None:
    provider = MockProvider()
    gen = ContentGenerator(provider=provider, cache=None, force_language="ua")
    gen.generate(_item(language="en"))

    system, _ = provider.calls[0]
    # Ukrainian-default template's persona starts with "Ви пишете для CyberAlertX".
    assert "Ви пишете" in system or "ua" in system


def test_prefer_audience_routes_to_developer_template() -> None:
    provider = MockProvider()
    gen = ContentGenerator(provider=provider, cache=None, prefer_audience="developers")
    gen.generate(_item(audience_targets=["developers", "sysadmins"]))

    system, _ = provider.calls[0]
    # Developer template advertises CVE / dependency framing.
    assert "CVE" in system or "engineers" in system.lower() or "engineer" in system.lower()


def test_generate_many_returns_one_post_per_item() -> None:
    provider = MockProvider()
    gen = ContentGenerator(provider=provider, cache=None)
    items = [_item(url=f"https://e.test/{i}") for i in range(3)]
    posts = gen.generate_many(items)
    assert len(posts) == 3
    assert {p.source_fingerprint for p in posts} == {i.fingerprint for i in items}


# ---------- output bounds enforcement ----------

def test_generator_clamps_emotional_weight_out_of_range() -> None:
    """If the LLM returns a value outside [0,1], the generator clamps it."""
    bad_response = ThreatPostResponse(
        title="x", short_summary="y", threat_level="Low",
        why_it_matters="z", affected_users=["a"], what_to_do=["b"],
        what_not_to_do=[], quick_facts=["c", "d"],
        emotional_weight=1.7,           # ← out of range
        reading_time_seconds=200,       # ← out of range
    )
    provider = MockProvider(response=bad_response)
    gen = ContentGenerator(provider=provider, cache=None)
    post = gen.generate(_item())
    assert 0.0 <= post.emotional_weight <= 1.0
    assert post.reading_time_seconds <= 120
