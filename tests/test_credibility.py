from datetime import datetime, timezone

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.credibility import (
    DEFAULT_PROFILE,
    SOURCE_PROFILES,
    analyze_all,
    analyze_credibility,
    profile_for,
)


def _item(source: str, title: str = "Critical RCE in widget", body: str = "") -> NewsItem:
    return NewsItem(
        title=title,
        source=source,
        url=f"https://e.test/{abs(hash((source, title)))}",
        published_at=datetime.now(timezone.utc),
        raw_content=body,
    )


# ---------- registry lookup ----------

def test_registered_trusted_source_scores_high():
    tier, score, _ = analyze_credibility(_item("CISA Alerts"))
    assert tier == "trusted"
    assert score >= 0.7


def test_registered_bleeping_computer_is_trusted():
    tier, _, _ = analyze_credibility(_item("BleepingComputer"))
    assert tier == "trusted"


def test_unknown_source_defaults_to_unverified():
    tier, score, _ = analyze_credibility(_item("Random Repost Blog"))
    assert tier == "unverified"
    assert score == DEFAULT_PROFILE.base_score


def test_profile_for_lookup_helper():
    assert profile_for("CISA Alerts").tier == "trusted"
    assert profile_for("Some Unknown Source").tier == "unverified"


# ---------- sensationalism penalty ----------

def test_sensational_wording_reduces_score():
    plain = _item("BleepingComputer", title="Critical RCE flaw in widget")
    sens = _item(
        "BleepingComputer",
        title="SHOCKING TRUTH: you won't believe this jaw-dropping bombshell",
        body="The shocking truth that nobody wants you to read.",
    )
    _, plain_score, _ = analyze_credibility(plain)
    _, sens_score, _ = analyze_credibility(sens)
    assert sens_score < plain_score


def test_sensationalism_cannot_drop_trusted_below_verified():
    """Penalty is capped (max 0.30); even very breathless writing on a
    high-base source cannot drop it past `verified`.
    """
    sens = _item(
        "CISA Alerts",
        title="SHOCKING bombshell you won't believe — unbelievable apocalypse",
        body="mind-blowing shocking truth secret revealed click here must read",
    )
    tier, _, _ = analyze_credibility(sens)
    assert tier in {"trusted", "verified"}  # never "unverified"


# ---------- cross-source corroboration ----------

def test_corroboration_from_trusted_peers_boosts_score():
    target = _item(
        "The Hacker News",
        title="New ransomware strain hits hospital networks worldwide",
    )
    peers = [
        _item("BleepingComputer", title="Ransomware strain devastates hospital networks"),
        _item("Krebs on Security", title="Hospitals worldwide hit by new ransomware strain"),
    ]
    _, solo_score, _ = analyze_credibility(target)
    _, group_score, _ = analyze_credibility(target, batch=[target] + peers)
    assert group_score > solo_score


def test_corroboration_ignores_unverified_peers():
    """A swarm of unverified blogs reposting the same story does NOT lift
    credibility — only TRUSTED peers count.
    """
    target = _item(
        "The Hacker News",
        title="New ransomware strain hits hospital networks worldwide",
    )
    spam_peers = [
        _item("Random Repost Blog A", title="Ransomware strain devastates hospital networks"),
        _item("Random Repost Blog B", title="Hospitals worldwide hit by new ransomware strain"),
        _item("Random Repost Blog C", title="New ransomware strain hits hospital networks"),
    ]
    _, solo_score, _ = analyze_credibility(target)
    _, group_score, _ = analyze_credibility(target, batch=[target] + spam_peers)
    assert group_score == solo_score  # bonus exactly zero


# ---------- batch processing ----------

def test_analyze_all_populates_fields():
    items = [
        _item("CISA Alerts", title="Advisory for CVE-2026-1234 in core lib"),
        _item("Random Repost Blog", title="Advisory for CVE-2026-1234 in core lib"),
    ]
    analyze_all(items)
    cisa, blog = items
    assert cisa.source_tier == "trusted"
    assert blog.source_tier == "unverified"
    assert cisa.source_credibility_score > blog.source_credibility_score


def test_score_is_within_unit_interval():
    item = _item(
        "CISA Alerts",
        title="Critical advisory: emergency patch, mass exploitation observed",
        body="shocking SHOCKING shocking truth bombshell mind-blowing apocalypse",
    )
    _, score, _ = analyze_credibility(item)
    assert 0.0 <= score <= 1.0


# ---------- spec examples ----------

def test_cisa_advisory_is_trusted():
    """CISA advisory → trusted (per spec example)."""
    tier, _, _ = analyze_credibility(_item("CISA Alerts"))
    assert tier == "trusted"


def test_bleeping_computer_is_trusted():
    """BleepingComputer → trusted (per spec example)."""
    tier, _, _ = analyze_credibility(_item("BleepingComputer"))
    assert tier == "trusted"


def test_random_repost_blog_is_unverified():
    """Random repost blog → unverified (per spec example)."""
    tier, _, _ = analyze_credibility(_item("SomeRandom Reposting Blog"))
    assert tier == "unverified"
