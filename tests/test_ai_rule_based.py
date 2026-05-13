"""Tests for the deterministic rule-based generator.

The rule-based path is the always-on safety net. These tests pin its public
contract: every NewsItem produces a structurally valid ThreatPost, no matter
how impoverished the metadata is.
"""
from __future__ import annotations

from datetime import datetime, timezone

from cyberalertx.ai.rule_based import RuleBasedGenerator
from cyberalertx.models import NewsItem


def _item(**overrides) -> NewsItem:
    base = dict(
        title="Critical phishing campaign targets Microsoft 365 users",
        source="BleepingComputer",
        url="https://e.test/x",
        published_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        raw_content=(
            "A new phishing campaign is targeting Microsoft 365 users. "
            "Attackers send fake login pages to harvest credentials. "
            "Defenders can use multi-factor authentication to reduce risk."
        ),
        threat_score=42.0,
        category="phishing",
        affected_platforms=["Outlook"],
        audience_targets=["normal_users", "enterprise"],
        actionability_level="recommended_action",
        actionability_score=0.55,
        source_tier="trusted",
        source_credibility_score=0.85,
        language="en",
    )
    base.update(overrides)
    return NewsItem(**base)


def test_minimal_item_produces_valid_post():
    """Even an empty-body item must yield a structurally valid post."""
    item = _item(raw_content="", category="other", affected_platforms=[],
                 audience_targets=[], actionability_level="informational",
                 actionability_score=0.0, threat_score=5.0)
    post = RuleBasedGenerator().generate(item)
    assert post.title
    assert post.short_summary
    assert post.threat_level in {"Low", "Medium", "High", "Critical"}
    assert post.why_it_matters
    assert post.affected_users      # never empty — always has a fallback
    assert post.what_to_do          # never empty — always has a fallback
    assert post.quick_facts         # always at least 1
    assert 0.0 <= post.emotional_weight <= 1.0
    assert 15 <= post.reading_time_seconds <= 45
    assert post.generated_by == "rule_based"


def test_threat_level_calibration():
    """threat_level reflects (actionability_level, threat_score)."""
    urgent_high = _item(actionability_level="urgent_action", threat_score=60.0)
    assert RuleBasedGenerator().generate(urgent_high).threat_level == "Critical"

    urgent_low = _item(actionability_level="urgent_action", threat_score=20.0)
    assert RuleBasedGenerator().generate(urgent_low).threat_level == "High"

    rec = _item(actionability_level="recommended_action", threat_score=40.0)
    assert RuleBasedGenerator().generate(rec).threat_level == "Medium"

    informational = _item(actionability_level="informational", threat_score=10.0)
    assert RuleBasedGenerator().generate(informational).threat_level == "Low"


def test_actively_exploited_appears_in_quick_facts():
    item = _item(
        raw_content="This vulnerability is actively exploited in the wild.",
        actionability_level="urgent_action",
    )
    post = RuleBasedGenerator().generate(item)
    assert any("Actively exploited" in f for f in post.quick_facts)


def test_patch_available_appears_in_quick_facts():
    item = _item(raw_content="The vendor confirmed: a patch is available now.")
    post = RuleBasedGenerator().generate(item)
    assert any("Patch available" in f for f in post.quick_facts)


def test_affected_users_combines_platforms_and_audiences():
    item = _item(affected_platforms=["Windows"], audience_targets=["normal_users"])
    post = RuleBasedGenerator().generate(item)
    assert any("Windows" in s for s in post.affected_users)
    # The internal audience id should be converted to a human label.
    assert any("Everyday users" in s for s in post.affected_users)


def test_phishing_category_produces_phishing_specific_actions():
    item = _item(category="phishing")
    post = RuleBasedGenerator().generate(item)
    joined = " | ".join(post.what_to_do)
    assert "2fa" in joined.lower() or "two-factor" in joined.lower()


def test_ukrainian_item_preserves_language_tag():
    item = _item(language="ua")
    post = RuleBasedGenerator().generate(item)
    assert post.language == "ua"


def test_unknown_language_falls_back_to_en():
    item = _item(language="other")
    post = RuleBasedGenerator().generate(item)
    assert post.language == "en"


def test_emotional_weight_increases_with_actionability():
    low = _item(actionability_score=0.0, threat_score=10.0,
                source_credibility_score=0.0)
    high = _item(actionability_score=1.0, threat_score=80.0,
                 source_credibility_score=1.0)
    assert RuleBasedGenerator().generate(high).emotional_weight > \
           RuleBasedGenerator().generate(low).emotional_weight


def test_fingerprint_is_preserved():
    item = _item()
    post = RuleBasedGenerator().generate(item)
    assert post.source_fingerprint == item.fingerprint
