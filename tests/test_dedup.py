"""Story-clustering tests.

The cases here are drawn from the live production store rather than
invented: every "must merge" pair is real coverage of one story by two
outlets, and every "must not merge" pair is two genuinely different
advisories that a naive title-similarity check collapses.

The asymmetry in this file is deliberate. A missed duplicate shows the
reader one redundant card; a false merge silently deletes a real advisory.
So the negative cases are the ones worth being paranoid about.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.dedup import (
    StoryFeatures,
    assign_incremental,
    assign_story_keys,
    choose_canonical,
    cluster_items,
    collapse_duplicates,
    extract_cves,
    headline_quality,
    same_story,
)

BASE = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)

_URL_SEQ = itertools.count()


def item(
    title: str,
    source: str = "BleepingComputer",
    *,
    body: str = "",
    days: float = 0.0,
    credibility: float = 0.85,
    url: str | None = None,
) -> NewsItem:
    # Every call gets a unique URL, and therefore a unique fingerprint. Two
    # advisories really can share a headline — that is the whole point of
    # several tests below — so deriving the URL from the title would make
    # them collide on fingerprint and pass for the wrong reason.
    return NewsItem(
        title=title,
        source=source,
        url=url or f"https://example.test/{next(_URL_SEQ)}",
        published_at=BASE + timedelta(days=days),
        raw_content=body,
        source_credibility_score=credibility,
    )


def matches(a: NewsItem, b: NewsItem) -> bool:
    return same_story(StoryFeatures.from_item(a), StoryFeatures.from_item(b))


# --------------------------------------------------------------------------
# CVE extraction
# --------------------------------------------------------------------------

def test_extract_cves_is_case_insensitive_and_uppercases():
    assert extract_cves("fixed cve-2026-50522 today") == {"CVE-2026-50522"}


def test_extract_cves_finds_ids_deep_in_the_body():
    # Advisory feeds list CVEs well past the lede; VETO 1 depends on us
    # finding them, so the scan must not stop at the first paragraph.
    body = "filler. " * 400 + "See CVE-2025-3756 for details."
    assert "CVE-2025-3756" in extract_cves(body)


def test_extract_cves_empty_when_none_present():
    assert extract_cves("No identifiers in this headline") == frozenset()


# --------------------------------------------------------------------------
# MUST MERGE — real cross-source coverage of one story
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("title_a", "source_a", "title_b", "source_b", "gap_days"),
    [
        (
            "VMware fixes three critical flaws allowing auth bypass, VM escapes",
            "BleepingComputer",
            "Three Critical VMware Flaws Allow Auth Bypass, Code Execution, and VM Escape",
            "The Hacker News",
            1.0,
        ),
        (
            "OpenAI agent used exposed credentials at 4 services in Hugging Face breach",
            "BleepingComputer",
            "OpenAI Agent Used Exposed Credentials Across Four Services During Hugging Face Breach",
            "The Hacker News",
            0.0,
        ),
        (
            "New msaRAT malware uses Chrome, Edge browsers to route C2 traffic",
            "BleepingComputer",
            "Chaos Ransomware Uses msaRAT to Route C2 Traffic Through Headless Chrome and Edge",
            "The Hacker News",
            0.0,
        ),
        (
            "Hackers target over 30 Minnesota water utilities in coordinated OT attack",
            "BleepingComputer",
            "Coordinated Cyberattack Targets 30+ Minnesota Water Systems as One Plant Goes Offline",
            "The Hacker News",
            0.0,
        ),
    ],
)
def test_real_cross_source_coverage_merges(
    title_a, source_a, title_b, source_b, gap_days,
):
    assert matches(item(title_a, source_a), item(title_b, source_b, days=gap_days))


def test_headline_pair_too_generic_alone_merges_once_cves_agree():
    # Strip the security boilerplate out of these two and only "vBulletin"
    # and "pre-auth" survive — under the minimum for a text-only decision.
    # Both articles name the same CVE, which is what settles it. This is the
    # common shape for vulnerability coverage, and the reason the CVE rules
    # exist rather than relying on headline wording.
    a = item("vBulletin fixes critical pre-auth RCE flaw with public exploit",
             body="Tracked as CVE-2026-31337.")
    b = item("Public Exploit Released for Patched vBulletin Pre-Auth Code Execution Flaw",
             "The Hacker News", body="The flaw, CVE-2026-31337, is now public.", days=1)
    assert matches(a, b)


def test_identical_cve_sets_merge_without_title_similarity():
    # A developing story: disclosure first, active exploitation days later.
    # The headlines share almost nothing but the CVE settles it.
    a = item("18-Year-Old NGINX Rewrite Module Flaw Enables Unauthenticated RCE",
             "The Hacker News", body="Tracked as CVE-2026-42945.")
    b = item("NGINX CVE-2026-42945 Exploited in the Wild, Causing Worker Crashes",
             "The Hacker News", days=3)
    assert matches(a, b)


def test_same_source_republish_with_different_headline_merges():
    # BleepingComputer ran this story twice in one day under two headlines.
    a = item("Claude uploaded malware to PyPI in Anthropic's botched test")
    b = item("Anthropic's Claude breached 3 orgs, uploaded PyPI malware during tests")
    assert matches(a, b)


# --------------------------------------------------------------------------
# MUST NOT MERGE — the expensive failures
# --------------------------------------------------------------------------

def test_disjoint_cves_veto_beats_any_title_similarity():
    # The CISA KEV catalog ships this identical headline every few days for
    # completely different vulnerabilities. Merging them deletes advisories.
    a = item("CISA Adds One Known Exploited Vulnerability to Catalog", "CISA Alerts",
             body="CVE-2026-20316 added.")
    b = item("CISA Adds One Known Exploited Vulnerability to Catalog", "CISA Alerts",
             body="CVE-2026-42897 added.", days=2)
    assert not matches(a, b)


def test_seven_identical_kev_headlines_stay_seven_stories():
    items = [
        item("CISA Adds One Known Exploited Vulnerability to Catalog", "CISA Alerts",
             body=f"CVE-2026-4200{n} added.", days=-n)
        for n in range(7)
    ]
    assert len(cluster_items(items)) == 7


def test_generic_security_phrasing_does_not_merge_different_products():
    # Both are "critical RCE, exploited" — the words that make unrelated
    # advisories look alike. Only the product names differ, and that is
    # exactly what has to carry the decision.
    a = item("JetBrains warns of critical TeamCity remote code execution flaw")
    b = item("Critical ServiceNow AI Platform Flaw Exploited for Unauthenticated Code Execution",
             "The Hacker News", days=1)
    assert not matches(a, b)


def test_multi_cve_roundup_does_not_absorb_a_single_vendor_story():
    # A four-CVE KEV roundup shares two CVEs with this WordPress story. If it
    # merged, it would also merge the other two CVEs' stories and chain three
    # unrelated items into one.
    roundup = item(
        "CISA Adds Four Known Exploited Vulnerabilities to Catalog", "CISA Alerts",
        body="CVE-2021-27137, CVE-2026-0770, CVE-2026-60137, CVE-2026-63030",
    )
    story = item(
        "Critical wp2shell WordPress flaws exploited to install webshells",
        body="Tracked as CVE-2026-60137 and CVE-2026-63030.",
    )
    assert not matches(roundup, story)


def test_same_source_identical_terse_product_headline_stays_apart():
    # CISA titles ICS advisories after the product. Two "Siemens SIMATIC"
    # entries are two advisories, and only one of them happens to name a CVE
    # in the lede — so the disjoint-CVE veto cannot save us here.
    a = item("Siemens SIMATIC", "CISA Alerts", body="Advisory with no identifier yet.")
    b = item("Siemens SIMATIC", "CISA Alerts", body="CVE-2026-27662 affects it.")
    assert not matches(a, b)


def test_related_products_in_one_family_stay_apart():
    a = item("ABB Ability Symphony Plus Engineering", "CISA Alerts",
             body="CVE-2023-5869 applies.")
    b = item("ABB System 800xA, Symphony Plus IEC 61850", "CISA Alerts",
             body="CVE-2025-3756 applies.")
    assert not matches(a, b)


def test_similar_headlines_outside_the_time_window_stay_apart():
    a = item("Patch Tuesday, May 2026 Edition", "Krebs on Security")
    b = item("Patch Tuesday, June 2026 Edition", "Krebs on Security", days=30)
    assert not matches(a, b)


def test_no_shared_entity_means_no_text_merge():
    a = item("Acme Portal ships hardcoded root password")
    b = item("Globex Gateway patches privilege escalation", "The Hacker News")
    assert not matches(a, b)


def test_two_local_root_flaws_in_different_products_stay_apart():
    # Real pair from the corpus. Both are "nine-year-old local privilege
    # escalation gives root on a default install"; only the product differs.
    # Nothing about the phrasing separates them — the CVE veto does.
    a = item("Nine-Year-Old RefluXFS Linux Flaw Gives Local Users Root on Default RHEL Installs",
             "The Hacker News", body="Tracked as CVE-2026-64600.")
    b = item("Ubuntu snap-confine Flaw Could Give Local Users Root on Default Desktop Installs",
             "The Hacker News", body="Tracked as CVE-2026-8933.")
    assert not matches(a, b)


# --------------------------------------------------------------------------
# Clustering behaviour
# --------------------------------------------------------------------------

def test_clustering_is_deterministic_regardless_of_input_order():
    items = [
        item("VMware fixes three critical flaws allowing auth bypass, VM escapes"),
        item("Three Critical VMware Flaws Allow Auth Bypass, Code Execution, and VM Escape",
             "The Hacker News", days=1),
        item("Unrelated phishing wave hits Acme Bank customers", "Krebs on Security"),
    ]
    forward = {c.key: sorted(m.fingerprint for m in c.members) for c in cluster_items(items)}
    backward = {
        c.key: sorted(m.fingerprint for m in c.members)
        for c in cluster_items(list(reversed(items)))
    }
    assert forward == backward


def test_a_weak_edge_cannot_chain_two_unrelated_stories():
    # B is close to both A and C, but A and C have nothing in common. Single
    # link clustering would fuse all three; anchor matching must not.
    a = item("Acme Portal authentication bypass exploited in the wild")
    b = item("Acme Portal and Globex Gateway both patched this week", "The Hacker News")
    c = item("Globex Gateway ships fix for memory corruption", "SecurityWeek")
    clusters = cluster_items([a, b, c])
    for cluster in clusters:
        fingerprints = {m.fingerprint for m in cluster.members}
        assert not {a.fingerprint, c.fingerprint} <= fingerprints


def test_assign_story_keys_marks_exactly_one_canonical_per_story():
    items = [
        item("VMware fixes three critical flaws allowing auth bypass, VM escapes"),
        item("Three Critical VMware Flaws Allow Auth Bypass, Code Execution, and VM Escape",
             "The Hacker News", days=1),
    ]
    assign_story_keys(items)
    assert items[0].story_key == items[1].story_key
    assert sum(1 for i in items if not i.duplicate_of) == 1


# --------------------------------------------------------------------------
# Canonical selection
# --------------------------------------------------------------------------

def test_bureaucratic_headline_loses_to_reporting_even_when_more_credible():
    # CISA is the most credible source in the corpus and simultaneously the
    # worst headline to show a reader.
    kev = item("CISA Adds One Known Exploited Vulnerability to Catalog",
               "CISA Alerts", credibility=0.95)
    story = item("Cisco warns of FMC static credential flaw exploited in zero-day attacks",
                 "BleepingComputer", credibility=0.85)
    assert choose_canonical([kev, story]) is story


def test_headline_quality_tiers():
    assert headline_quality("CISA Adds Two Known Exploited Vulnerabilities to Catalog") == 0
    assert headline_quality("Siemens SIMATIC") == 1
    assert headline_quality("Cisco warns of FMC static credential flaw in zero-day attacks") == 2


def test_prefer_callback_outranks_everything():
    # An unrenderable "better" article must not win the slot and leave the
    # feed with a card we cannot fill.
    good = item("Cisco warns of FMC static credential flaw exploited", credibility=0.9)
    renderable = item("Cisco FMC zero-day actively exploited, credentials exposed",
                      "The Hacker News", credibility=0.5)
    chosen = choose_canonical(
        [good, renderable], prefer=lambda i: i.fingerprint == renderable.fingerprint,
    )
    assert chosen is renderable


def test_newer_article_wins_within_the_same_source_tier():
    older = item("Acme Portal flaw disclosed", credibility=0.85)
    newer = item("Acme Portal flaw now exploited in attacks", credibility=0.85, days=2)
    assert choose_canonical([older, newer]) is newer


def test_choose_canonical_rejects_empty_input():
    with pytest.raises(ValueError):
        choose_canonical([])


# --------------------------------------------------------------------------
# Incremental assignment (the pipeline's entry point)
# --------------------------------------------------------------------------

def test_incremental_join_keeps_the_existing_story_key():
    stored = item("VMware fixes three critical flaws allowing auth bypass, VM escapes")
    assign_story_keys([stored])
    original_key = stored.story_key

    arriving = item(
        "Three Critical VMware Flaws Allow Auth Bypass, Code Execution, and VM Escape",
        "The Hacker News", days=1,
    )
    duplicates = assign_incremental([arriving], [stored])

    assert arriving.story_key == original_key
    assert stored.story_key == original_key, "an arrival must not re-key a stored story"
    assert arriving.duplicate_of == stored.fingerprint
    assert duplicates == [arriving]


def test_incremental_marks_later_coverage_duplicate_even_if_it_reads_better():
    # First-seen-wins keeps rendering and publishing idempotent; picking the
    # nicer article to display is a separate read-time decision.
    stored = item("CISA Adds One Known Exploited Vulnerability to Catalog",
                  "CISA Alerts", credibility=0.95, body="CVE-2026-20316 added.")
    assign_story_keys([stored])
    arriving = item("Cisco warns of FMC static credential flaw exploited in zero-day attacks",
                    "BleepingComputer", body="CVE-2026-20316", days=1)
    assign_incremental([arriving], [stored])
    assert arriving.duplicate_of == stored.fingerprint


def test_incremental_clusters_within_the_arriving_batch():
    a = item("VMware fixes three critical flaws allowing auth bypass, VM escapes")
    b = item("Three Critical VMware Flaws Allow Auth Bypass, Code Execution, and VM Escape",
             "The Hacker News", days=1)
    duplicates = assign_incremental([a, b], [])
    assert a.story_key == b.story_key
    assert len(duplicates) == 1


def test_incremental_leaves_unrelated_items_as_their_own_stories():
    stored = item("Acme Bank phishing wave targets customers", "Krebs on Security")
    assign_story_keys([stored])
    arriving = item("Globex Gateway ships fix for memory corruption", "SecurityWeek")
    duplicates = assign_incremental([arriving], [stored])
    assert duplicates == []
    assert arriving.story_key and arriving.story_key != stored.story_key
    assert arriving.duplicate_of == ""


# --------------------------------------------------------------------------
# Read-time collapsing
# --------------------------------------------------------------------------

def test_collapse_returns_one_item_per_story_with_the_other_sources():
    a = item("VMware fixes three critical flaws allowing auth bypass, VM escapes")
    b = item("Three Critical VMware Flaws Allow Auth Bypass, Code Execution, and VM Escape",
             "The Hacker News", days=1)
    c = item("Unrelated phishing wave hits Acme Bank", "Krebs on Security")
    assign_story_keys([a, b, c])

    survivors, extra = collapse_duplicates([a, b, c])

    assert len(survivors) == 2
    canonical = next(s for s in survivors if s.story_key == a.story_key)
    assert extra[canonical.fingerprint] == ["The Hacker News"] or extra[
        canonical.fingerprint
    ] == ["BleepingComputer"]
    assert c.fingerprint in {s.fingerprint for s in survivors}


def test_collapse_preserves_caller_ordering():
    a = item("Story A about Acme Portal credentials")
    b = item("Story B about Globex Gateway memory", "The Hacker News", days=1)
    c = item("Story C about Initech Router firmware", "SecurityWeek", days=2)
    assign_story_keys([a, b, c])
    ordered = [c, a, b]
    survivors, _ = collapse_duplicates(ordered)
    assert [s.fingerprint for s in survivors] == [c.fingerprint, a.fingerprint, b.fingerprint]


def test_items_without_story_keys_each_survive():
    # Everything ingested before clustering existed has an empty key. Those
    # must degrade to "one story each", never collapse into one bucket.
    legacy = [item(f"Legacy story number {n}", days=-n) for n in range(4)]
    assert all(i.story_key == "" for i in legacy)
    survivors, extra = collapse_duplicates(legacy)
    assert len(survivors) == 4
    assert extra == {}


def test_collapse_prefers_a_renderable_member():
    a = item("VMware fixes three critical flaws allowing auth bypass, VM escapes",
             credibility=0.9)
    b = item("Three Critical VMware Flaws Allow Auth Bypass, Code Execution, and VM Escape",
             "The Hacker News", credibility=0.5, days=1)
    assign_story_keys([a, b])
    survivors, _ = collapse_duplicates(
        [a, b], prefer=lambda i: i.fingerprint == b.fingerprint,
    )
    assert [s.fingerprint for s in survivors] == [b.fingerprint]


# --------------------------------------------------------------------------
# Storage round-trip
# --------------------------------------------------------------------------

def test_story_fields_survive_a_storage_round_trip():
    original = item("Acme Portal authentication bypass exploited")
    original.story_key = "s:abc123"
    original.duplicate_of = "deadbeefdeadbeef"
    restored = NewsItem.from_storage_dict(original.to_storage_dict())
    assert restored.story_key == "s:abc123"
    assert restored.duplicate_of == "deadbeefdeadbeef"


def test_storage_dicts_written_before_clustering_load_with_empty_defaults():
    payload = item("Legacy item").to_storage_dict()
    payload.pop("story_key")
    payload.pop("duplicate_of")
    restored = NewsItem.from_storage_dict(payload)
    assert restored.story_key == ""
    assert restored.duplicate_of == ""


# --------------------------------------------------------------------------
# Cost of the read-time collapse
# --------------------------------------------------------------------------

def test_collapse_does_not_probe_single_source_stories():
    """`prefer` is backed by the AI cache, which is a Postgres round-trip.

    Calling it for every item turned one feed request into hundreds of
    queries and made /posts roughly five times slower than before story
    clustering existed. Most stories are single-source, and a group of one
    has nothing to choose between, so those must not be probed at all.
    """
    singles = [
        item("Acme Bank phishing wave targets mobile customers", "Krebs on Security"),
        item("Globex Gateway ships fix for memory corruption", "SecurityWeek", days=-1),
        item("Initech Router firmware leaks admin credentials", "DarkReading", days=-2),
        item("Umbrella Cloud console exposed without authentication", "SC Media", days=-3),
        item("Soylent CMS plugin abused to plant webshells", "The Hacker News", days=-4),
        item("Tyrell Robotics ransomware halts assembly lines", "InfoSecurity Magazine", days=-5),
    ]
    pair_a = item("VMware fixes three critical flaws allowing auth bypass, VM escapes")
    pair_b = item(
        "Three Critical VMware Flaws Allow Auth Bypass, Code Execution, and VM Escape",
        "The Hacker News", days=1,
    )
    items = [*singles, pair_a, pair_b]
    assign_story_keys(items)

    probed: list[str] = []

    def prefer(i: NewsItem) -> bool:
        probed.append(i.fingerprint)
        return True

    collapse_duplicates(items, prefer=prefer)

    # Only the two members of the one multi-source story may be probed.
    assert set(probed) <= {pair_a.fingerprint, pair_b.fingerprint}
    assert len(probed) <= 2


def test_collapse_without_prefer_never_probes():
    items = [
        item("Acme Bank phishing wave targets mobile customers", "Krebs on Security"),
        item("Globex Gateway ships fix for memory corruption", "SecurityWeek", days=-1),
        item("Initech Router firmware leaks admin credentials", "DarkReading", days=-2),
    ]
    assign_story_keys(items)
    survivors, _ = collapse_duplicates(items)
    assert len(survivors) == 3
