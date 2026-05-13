"""Editorial brief format + anti-plagiarism gate.

Two product invariants this test file pins:

  1. The rule-based short_summary NEVER contains long substrings from
     `item.raw_content`. CyberAlertX is positioned as an intelligence
     feed, not an RSS mirror, so the deterministic fallback must read
     as a curated brief — even when the LLM journalist layer is off.

  2. The AI journalist validator (`validate_journalist_response`) rejects
     AI output that paraphrases the source body too closely (>25% of
     5-gram shingles overlap). When that happens, the generator falls
     back to the rule-based brief — which by construction is plagiarism-
     free.

These tests run without any network — the validator is pure, and the
rule-based generator is offline.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cyberalertx.ai.models import ThreatPostResponse
from cyberalertx.ai.rule_based import RuleBasedGenerator
from cyberalertx.ai.validation import (
    NEAR_COPY_SHINGLE_RATIO,
    ValidationFailure,
    near_copy_ratio,
    validate_journalist_response,
)
from cyberalertx.models import NewsItem


# A long, distinctive source body — the kind of paragraph a real RSS feed
# delivers. Used both as input to the rule-based generator (to confirm
# the summary doesn't reuse it) and as the "source body" against which we
# benchmark plagiarism.
_LONG_BODY = (
    "Researchers at Trend Micro have identified a new phishing campaign "
    "targeting Microsoft 365 users in eight US states. The campaign uses "
    "lookalike domains and OAuth abuse to harvest credentials and pivot "
    "into the victims' OneDrive accounts. The threat actor, tracked as "
    "Storm-1124, has been active since at least March 2026."
)


def _item(category: str = "phishing", platforms: list[str] | None = None,
          audience: list[str] | None = None,
          actionability: str = "recommended_action",
          source: str = "BleepingComputer",
          url: str = "https://example.test/article",
          body: str = _LONG_BODY) -> NewsItem:
    return NewsItem(
        title="Phishing campaign hits Microsoft 365 in eight US states",
        source=source,
        url=url,
        published_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        raw_content=body,
        language="en",
        category=category,
        affected_platforms=platforms or [],
        audience_targets=audience or [],
        actionability_level=actionability,
        actionability_score=0.7,
        threat_score=55.0,
        source_tier="trusted",
        source_credibility_score=0.85,
    )


# --------------------- rule-based: editorial brief invariants -------------

def test_brief_contains_source_attribution():
    """Every brief must lead with the source name. Anchors trust without
    requiring the reader to scroll for provenance."""
    gen = RuleBasedGenerator()
    item = _item(platforms=["Microsoft 365"])
    post = gen.generate(item, language="en")
    assert post.short_summary.startswith("BleepingComputer "), post.short_summary


def test_brief_uses_alarm_verb_for_urgent_items():
    """Urgent-bucket items use 'warns of' instead of generic reportage so
    the brief itself carries severity signal, before the threat-level
    badge is rendered."""
    gen = RuleBasedGenerator()
    urgent = _item(actionability="urgent_action", platforms=["Apache"])
    post = gen.generate(urgent, language="en")
    assert "warns of" in post.short_summary


def test_brief_does_not_reuse_source_body_phrases():
    """The hard invariant: the rule-based summary must NEVER reuse
    distinctive multi-word phrases from the article body. This is the
    test that catches a regression to the old _extract_lead() behavior."""
    gen = RuleBasedGenerator()
    item = _item(platforms=["Microsoft 365"])
    post = gen.generate(item, language="en")
    body_lower = _LONG_BODY.lower()
    summary_lower = post.short_summary.lower()
    # Substrings from the body that absolutely should NOT leak into the
    # summary if we're synthesizing rather than copying.
    forbidden_phrases = [
        "researchers at trend micro",
        "have identified a new phishing",
        "eight us states",
        "lookalike domains and oauth",
        "harvest credentials",
        "pivot into the victims",
        "tracked as storm-1124",
        "active since at least march",
    ]
    for phrase in forbidden_phrases:
        assert phrase not in summary_lower, (
            f"summary leaked source phrase {phrase!r}: {post.short_summary!r}"
        )
    assert phrase in body_lower  # sanity: phrase really is in the body


def test_brief_includes_platform_target():
    """When the item targets a known platform, the brief should name it
    so the reader knows immediately whether it applies to them."""
    gen = RuleBasedGenerator()
    post = gen.generate(_item(platforms=["Microsoft 365"]), language="en")
    assert "Microsoft 365" in post.short_summary


def test_brief_falls_back_to_audience_when_no_platform():
    """No platform but an audience tag → use the audience modifier."""
    gen = RuleBasedGenerator()
    post = gen.generate(_item(audience=["normal_users"]), language="en")
    assert "everyday users" in post.short_summary.lower()


def test_brief_works_with_only_source_and_category():
    """The minimum case — no platforms, no audience. The brief should
    still produce a coherent sentence."""
    gen = RuleBasedGenerator()
    item = _item()
    item.affected_platforms = []
    item.audience_targets = []
    post = gen.generate(item, language="en")
    # One short sentence ending in a period.
    assert post.short_summary.endswith(".")
    assert len(post.short_summary.split()) <= 14


def test_brief_uk_uses_natural_ukrainian():
    """UK brief: native Ukrainian wording — not a literal calque."""
    gen = RuleBasedGenerator()
    item = _item(category="phishing", platforms=["Microsoft 365"],
                 source="BleepingComputer")
    post = gen.generate(item, language="ua")
    # UK output must use a Ukrainian attribution verb, not the EN one.
    en_verbs = ("reports", "details", "documents", "describes",
                "outlines", "warns of")
    for verb in en_verbs:
        assert verb not in post.short_summary
    # And must use a Ukrainian category noun.
    assert "фішинг" in post.short_summary.lower()


def test_brief_uk_no_russian_grammar_artifacts():
    """UK brief must avoid Russian-grammar tells ('путем', 'являться')."""
    gen = RuleBasedGenerator()
    post = gen.generate(_item(category="ransomware"), language="ua")
    russisms = ("путем", "являться", "только что", "обнаружено")
    for r in russisms:
        assert r not in post.short_summary.lower()


def test_brief_varies_by_fingerprint():
    """Two items in the same category with different fingerprints should
    pick DIFFERENT attribution verbs — keeps the feed from feeling
    rubber-stamped."""
    gen = RuleBasedGenerator()
    seen_verbs: set[str] = set()
    for url in (f"https://example.test/{i}" for i in range(8)):
        # Use a non-urgent bucket — urgent items always pick the same
        # alarm verb, by design.
        item = _item(url=url, actionability="recommended_action")
        post = gen.generate(item, language="en")
        # First word after the source name is the verb.
        rest = post.short_summary.removeprefix("BleepingComputer ").split()
        if rest:
            seen_verbs.add(rest[0])
    # 5 attribution verbs in the pool; 8 different fingerprints; expect
    # at least 2 distinct verbs to fire.
    assert len(seen_verbs) >= 2, f"only saw verb(s) {seen_verbs}"


# --------------------- anti-plagiarism validator --------------------------

def _good_response(**overrides) -> ThreatPostResponse:
    base = dict(
        title="Storm-1124 phishing kit targets US school staff",
        short_summary=(
            "BleepingComputer reports a credential-harvesting phishing kit "
            "operated by a group tracked as Storm-1124. Victims include "
            "Microsoft 365 mailboxes at universities and K-12 districts."
        ),
        threat_level="High",
        why_it_matters=(
            "If attackers got into a school's M365 inbox they can read "
            "every 2FA code that gets delivered there and pivot to OneDrive."
        ),
        affected_users=["Microsoft 365 admins", "US school staff"],
        what_to_do=[
            "Open security.microsoft.com → Sign-in activity",
            "Switch the account from SMS to Authenticator-app 2FA",
            "Revoke OAuth permissions for any unfamiliar app",
        ],
        what_not_to_do=["Don't approve a 2FA prompt you didn't trigger"],
        quick_facts=["Microsoft 365", "Credential theft"],
        emotional_weight=0.7,
        reading_time_seconds=25,
    )
    base.update(overrides)
    return ThreatPostResponse(**base)


def test_near_copy_summary_is_rejected():
    """AI output that essentially mirrors the source body must be rejected
    — even though it would otherwise pass every other check."""
    near_copy = _good_response(
        # Same opening, same names, same phrasing — only minor edits.
        short_summary=(
            "Researchers at Trend Micro have identified a new phishing "
            "campaign targeting Microsoft 365 users in eight US states. "
            "The campaign uses lookalike domains and OAuth abuse to "
            "harvest credentials and pivot into OneDrive accounts."
        ),
    )
    with pytest.raises(ValidationFailure, match="near-copy"):
        validate_journalist_response(
            near_copy, source_title="Phishing campaign hits Microsoft 365",
            source_body=_LONG_BODY,
        )


def test_synthesized_summary_passes():
    """A genuinely transformed summary — same facts, different structure
    and wording — passes the plagiarism gate."""
    validate_journalist_response(
        _good_response(),
        source_title="Phishing campaign hits Microsoft 365 in eight US states",
        source_body=_LONG_BODY,
    )


def test_near_copy_why_it_matters_also_rejected():
    """Plagiarism gate fires on why_it_matters too — not just summary."""
    bad = _good_response(
        why_it_matters=(
            "Researchers at Trend Micro have identified a new phishing "
            "campaign targeting Microsoft 365 users in eight US states. "
            "The threat actor uses lookalike domains and OAuth abuse."
        ),
    )
    with pytest.raises(ValidationFailure, match="near-copy"):
        validate_journalist_response(
            bad, source_title="phishing", source_body=_LONG_BODY,
        )


def test_near_copy_ratio_helper_returns_high_value_for_copy():
    """Sanity-check the helper directly. Identical strings → 1.0.
    Disjoint text → 0.0. A near-copy paragraph → above threshold."""
    assert near_copy_ratio(_LONG_BODY, _LONG_BODY) == pytest.approx(1.0)
    assert near_copy_ratio("hello world", "the quick brown fox jumped over") == 0.0
    near = _LONG_BODY.replace("Trend Micro", "Researchers").replace(
        "Storm-1124", "an unnamed actor",
    )
    # Should still flag — most of the 5-grams are intact.
    assert near_copy_ratio(near, _LONG_BODY) >= NEAR_COPY_SHINGLE_RATIO


def test_short_summary_with_unique_phrasing_under_threshold():
    """When the candidate is short and uses different words, overlap is
    near zero — confirms we're not flagging legitimate brief output."""
    candidate = (
        "BleepingComputer reports a phishing campaign targeting "
        "Microsoft 365."
    )
    assert near_copy_ratio(candidate, _LONG_BODY) < NEAR_COPY_SHINGLE_RATIO


# --------------------- regression: existing API tests still work ---------

def test_no_source_body_skips_plagiarism_check():
    """Tests / callers that pass no source_body must not be penalized —
    the check is optional and only fires when source_body is non-empty."""
    validate_journalist_response(
        _good_response(),
        source_title="anything",
        source_body="",
    )
