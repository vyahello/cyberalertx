"""Audience relevance classification (rule-based v1).

Contract:
    classify_audience(item, *, text=None, tokens=None)
        -> (targets: list[str], confidence: float in [0, 1])

Why three signal types per audience (not just keywords):
  * Keywords catch explicit mentions ("npm package", "wallet drainer").
  * Affected platforms (already extracted upstream) give us strong typing —
    if `Kubernetes` is in the item, devs and sysadmins both care; if `Android`,
    mobile users care.
  * Categories give a default ("phishing" → consumers, "breach" → enterprise)
    so we still classify items where the language is vague.

Per-audience weights are *the same* — what differs is each profile's
vocabulary. That keeps tuning to one place (`AUDIENCES`).

How to upgrade to AI:
  Swap `classify_audience()` for an embedding-based scorer that returns the
  same `(list[str], float)` tuple. The orchestrator and downstream consumers
  don't change. Recommended: cascade — run the rules first, fall back to AI
  when `confidence < AI_FALLBACK_THRESHOLD`.

Score interpretation:
  `audience_relevance_score` reports the strongest single-audience score,
  so the UI can use it as a "we know who this is for" confidence and the
  `audience_targets` list as the actual filter facet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, Tuple

from ..models import NewsItem
from .keywords import count_keyword_hits

# Threshold below which an audience is NOT added to targets.
# A score of 1.5 raw points (one platform hit OR one category match) maps to
# 0.43, comfortably above. A single weak keyword (raw=1.0) maps to 0.33 — on
# the borderline. Tuned by hand against the live feed; revisit when feeding
# eval data into an AI model.
_TARGET_THRESHOLD = 0.33

_KEYWORD_WEIGHT = 1.0
_PLATFORM_WEIGHT = 1.5
_CATEGORY_WEIGHT = 1.5

_TOKEN_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*", flags=re.UNICODE)


@dataclass(frozen=True)
class AudienceProfile:
    keywords: frozenset[str] = field(default_factory=frozenset)
    platforms: frozenset[str] = field(default_factory=frozenset)
    categories: frozenset[str] = field(default_factory=frozenset)


# Audience vocabulary. Add a new audience by appending an entry — nothing else
# needs to change. Keep `categories` tight (only categories that *strongly*
# imply this audience), otherwise the same story will tag every audience.
AUDIENCES: Mapping[str, AudienceProfile] = {
    "normal_users": AudienceProfile(
        keywords=frozenset({
            "consumer", "personal data", "credit card", "online banking",
            "tax scam", "irs scam", "tech support scam", "romance scam",
            "qr code phishing", "quishing",
            "facebook account", "instagram account", "tiktok account",
            "social media account", "gift card scam",
            "google account", "apple id",
        }),
        platforms=frozenset({
            "Gmail", "Outlook", "WhatsApp", "Telegram", "Signal",
            "Banking", "Chrome", "Firefox", "Safari",
        }),
        # Most phishing/scam/social-engineering campaigns target consumers
        # by volume — corp BEC is the exception, caught via `enterprise`.
        categories=frozenset({"phishing", "scam", "social engineering"}),
    ),
    "developers": AudienceProfile(
        keywords=frozenset({
            "npm", "pypi", "rubygems", "maven", "nuget", "cargo crate",
            "supply chain", "supply-chain",
            "github", "gitlab", "bitbucket", "ci/cd", "jenkins",
            "docker image", "container image", "container vulnerability",
            "open source library", "open-source package",
            "deserialization", "prototype pollution",
            "api key leak", "leaked credentials", "secret leak", "secret scanning",
            "compiler", "vscode extension", "ide vulnerability",
            "package registry", "malicious package",
        }),
        platforms=frozenset({"Docker", "Kubernetes"}),
        categories=frozenset(),  # devs care about many categories — rely on keywords/platforms
    ),
    "sysadmins": AudienceProfile(
        keywords=frozenset({
            "vpn", "rdp", "remote desktop", "active directory", "domain controller",
            "windows server", "linux kernel", "ssh", "openssh", "patch tuesday",
            "firewall", "load balancer", "exchange server", "sharepoint",
            "ldap", "kerberos", "samba", "dns server",
            "esxi", "vsphere", "vcenter", "fortigate",
            "cisco asa", "cisco ios", "juniper", "palo alto",
        }),
        platforms=frozenset({
            "Cisco", "Fortinet", "VMware", "Kubernetes",
            "Cloud (AWS)", "Cloud (Azure)", "Cloud (GCP)",
        }),
        categories=frozenset(),
    ),
    "enterprise": AudienceProfile(
        keywords=frozenset({
            "oracle", "sap", "salesforce", "workday", "servicenow", "atlassian",
            "enterprise customer", "fortune 500", "fortune-500",
            "business email compromise", "bec attack", "bec scam",
            "ransom paid", "ransom payment", "regulatory fine", "gdpr fine",
            "sec filing", "8-k filing", "shareholder", "subsidiary",
        }),
        platforms=frozenset({"Microsoft 365"}),
        # Corp-scale breaches & leaks default to enterprise framing; the
        # consumer angle only fires when there's explicit consumer signal.
        categories=frozenset({"breach", "data leak"}),
    ),
    "mobile_users": AudienceProfile(
        keywords=frozenset({
            "smartphone", "google play", "app store", "play store",
            "stalkerware", "mobile spyware", "pegasus", "predator",
            "smishing", "sms phishing",
            "mobile banking trojan", "banking trojan",
            "zero-click", "zero click",
        }),
        platforms=frozenset({"Android", "iOS"}),
        categories=frozenset(),  # platforms already handle the auto-trigger
    ),
    "crypto_users": AudienceProfile(
        keywords=frozenset({
            "cryptocurrency", "bitcoin", "ethereum", "crypto wallet",
            "metamask", "trust wallet", "exchange hack", "defi exploit",
            "nft scam", "wallet drainer", "drainer kit",
            "phantom wallet", "ledger wallet", "trezor",
            "smart contract", "rug pull", "binance", "coinbase",
            "crypto stealer", "seed phrase",
        }),
        platforms=frozenset(),
        categories=frozenset(),
    ),
}


def _score_profile(
    profile: AudienceProfile,
    text_lower: str,
    tokens: set[str],
    platforms: Iterable[str],
    category: str,
) -> float:
    """Return a [0, 1] score for one audience profile.

    Raw signal: weighted sum of keyword hits, platform overlaps, and category
    membership. Squashed via `raw / (raw + 2)` — a logistic-ish curve that
    saturates so a "wall of keywords" doesn't pin every audience at 1.0.
    """
    keyword_hits = count_keyword_hits(profile.keywords, text_lower, tokens)
    platform_overlap = sum(1 for p in platforms if p in profile.platforms)
    category_match = 1 if category in profile.categories else 0
    raw = (
        keyword_hits * _KEYWORD_WEIGHT
        + platform_overlap * _PLATFORM_WEIGHT
        + category_match * _CATEGORY_WEIGHT
    )
    if raw <= 0:
        return 0.0
    return raw / (raw + 2.0)


def classify_audience(
    item: NewsItem,
    *,
    text: str | None = None,
    tokens: set[str] | None = None,
) -> Tuple[List[str], float]:
    """Pure function — same inputs always yield the same labels.

    `text` and `tokens` are optional precomputed inputs so callers iterating
    over many items can hoist the tokenization out of the loop.
    """
    if text is None:
        text = f"{item.title}\n{item.raw_content}".lower()
    if tokens is None:
        tokens = set(_TOKEN_RE.findall(text))

    scores = {
        name: _score_profile(profile, text, tokens, item.affected_platforms, item.category)
        for name, profile in AUDIENCES.items()
    }
    targets = sorted(name for name, score in scores.items() if score >= _TARGET_THRESHOLD)
    confidence = max(scores.values()) if targets else 0.0
    return targets, confidence


def classify_for_item(item: NewsItem) -> NewsItem:
    """In-place enrichment: populate audience_targets + audience_relevance_score."""
    targets, confidence = classify_audience(item)
    item.audience_targets = targets
    item.audience_relevance_score = confidence
    return item


def classify_all(items: Iterable[NewsItem]) -> List[NewsItem]:
    return [classify_for_item(i) for i in items]


__all__ = [
    "AUDIENCES",
    "AudienceProfile",
    "classify_audience",
    "classify_for_item",
    "classify_all",
]
