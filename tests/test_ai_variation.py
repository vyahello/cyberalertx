"""Tests for the rule-based variation / mobile-readability improvements.

What we pin:

  * `why_it_matters` is **deterministic** — same fingerprint always picks
    the same variant. (Cache-safety + test-stability.)
  * `why_it_matters` is **distributed** — across many fingerprints in the
    same (category, urgency) bucket, more than one variant fires. This is
    what kills template fatigue.
  * Summaries respect the 220-char mobile cap.
  * Shouty titles are sentence-cased (while preserving short acronyms).
  * Quick facts use noun-phrase labels (no `"Type: "` prefix).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from cyberalertx.ai.rule_based import (
    RuleBasedGenerator,
    _CATEGORY_FACT_LABEL,
    _WHY_IT_MATTERS,
    _normalize_shouty_title,
    _variant_index,
)
from cyberalertx.models import NewsItem


def _item(url: str = "https://e.test/x", **overrides) -> NewsItem:
    base = dict(
        title="Critical RCE in widget framework",
        source="BleepingComputer",
        url=url,
        published_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        raw_content="A widget framework was found to have an RCE vulnerability.",
        threat_score=42.0,
        category="phishing",
        affected_platforms=["Outlook"],
        # Empty audience targets so the per-template `rule_based` override
        # for phishing/normal_users doesn't intercept the variant logic.
        audience_targets=["developers"],
        actionability_level="urgent_action",
        actionability_score=0.85,
        source_tier="trusted",
        source_credibility_score=0.85,
        language="en",
    )
    base.update(overrides)
    return NewsItem(**base)


# ---------------- variant determinism ----------------

def test_same_fingerprint_picks_same_variant():
    a = _item(url="https://e.test/same")
    b = _item(url="https://e.test/same")
    # Same URL → same fingerprint → same picked variant.
    assert a.fingerprint == b.fingerprint
    gen = RuleBasedGenerator()
    assert gen.generate(a).why_it_matters == gen.generate(b).why_it_matters


def test_variant_index_is_deterministic():
    # Pure-function check on the helper itself.
    assert _variant_index("deadbeefcafef00d", 3) == _variant_index("deadbeefcafef00d", 3)
    assert _variant_index("deadbeefcafef00d", 3) in (0, 1, 2)


def test_variant_index_handles_short_or_bad_input():
    # Should not crash on malformed input — falls back to index 0.
    assert _variant_index("", 3) == 0
    assert _variant_index("not-hex", 3) == 0
    assert _variant_index("abc", 1) == 0


# ---------------- variant distribution ----------------

def _phishing_urgent_variants() -> Sequence[str]:
    return _WHY_IT_MATTERS[("phishing", "urgent")]


def test_many_items_in_same_bucket_hit_multiple_variants():
    """20 different items in (phishing, urgent) should hit at least 2 variants."""
    pool_size = len(_phishing_urgent_variants())
    assert pool_size >= 2, "the variant pool itself needs to have >=2 entries"

    gen = RuleBasedGenerator()
    seen: set[str] = set()
    for i in range(20):
        item = _item(url=f"https://e.test/{i}")
        seen.add(gen.generate(item).why_it_matters)
    # With uniform hash distribution and 20 trials over 2-3 variants, the
    # probability of all 20 hitting the same variant is < 1 / 2^18. Still,
    # we only assert >= 2 to keep the test stable.
    assert len(seen) >= 2, f"got only {len(seen)} unique variants out of {pool_size}"


def test_every_picked_variant_is_in_the_table():
    """The picked line must come from the registered pool (sanity check)."""
    gen = RuleBasedGenerator()
    pool = set(_phishing_urgent_variants())
    for i in range(10):
        post = gen.generate(_item(url=f"https://e.test/{i}"))
        assert post.why_it_matters in pool


# ---------------- mobile readability ----------------

def test_summary_respects_mobile_cap():
    long_body = " ".join(["This is a fairly long sentence about a vulnerability."] * 30)
    post = RuleBasedGenerator().generate(_item(raw_content=long_body))
    assert len(post.short_summary) <= 222  # 220 + ellipsis


def test_short_body_summary_not_truncated():
    short_body = "A new flaw lets attackers steal saved passwords from the browser."
    post = RuleBasedGenerator().generate(_item(raw_content=short_body))
    assert not post.short_summary.endswith("…")


# ---------------- shouty title normalization ----------------

def test_normalize_shouty_title_fixes_yelling():
    assert _normalize_shouty_title("URGENT HACKERS BREACH MAJOR SYSTEM") == \
        "Urgent Hackers Breach Major System"


def test_normalize_shouty_title_preserves_short_acronyms():
    assert _normalize_shouty_title("CVE-2026-1234 AFFECTS APACHE WEB SERVER") == \
        "CVE-2026-1234 Affects Apache Web Server"


def test_normalize_shouty_title_leaves_titlecase_alone():
    original = "Critical zero-day flaw being actively exploited in Windows"
    assert _normalize_shouty_title(original) == original


def test_rule_based_title_applies_normalization():
    item = _item(title="URGENT! NEW MALWARE TARGETS WINDOWS USERS")
    post = RuleBasedGenerator().generate(item)
    # No more all-caps shouting.
    assert "URGENT" not in post.title
    assert post.title.startswith("Urgent")


# ---------------- quick fact labels ----------------

def test_quick_facts_use_noun_phrase_labels():
    """No `"Type: "` prefix; category appears as a clean noun phrase."""
    post = RuleBasedGenerator().generate(_item(category="ransomware"))
    assert "Ransomware" in post.quick_facts
    assert not any("Type:" in f for f in post.quick_facts)


def test_quick_facts_phrase_two_platforms_naturally():
    post = RuleBasedGenerator().generate(
        _item(affected_platforms=["Windows", "Linux"], category="vulnerability")
    )
    assert any(f == "Affects Windows & Linux" for f in post.quick_facts)


def test_quick_facts_collapse_many_platforms():
    post = RuleBasedGenerator().generate(
        _item(affected_platforms=["Windows", "Linux", "macOS", "Android"],
              category="vulnerability")
    )
    assert "Multi-platform" in post.quick_facts


def test_category_label_table_covers_every_category():
    """Every category we declare in audience.py should have a fact label."""
    expected = {
        "phishing", "ransomware", "vulnerability", "exploit", "zero-day",
        "breach", "data leak", "malware", "spyware", "scam", "botnet",
        "social engineering",
    }
    missing = expected - set(_CATEGORY_FACT_LABEL.keys())
    assert not missing, f"missing fact labels for: {missing}"
