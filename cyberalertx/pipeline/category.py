"""Cybersecurity category classification (rule-based v1).

Contract:
    classify(text) -> (category: str, confidence: float in [0, 1])

Why rule-based first:
  * deterministic — same input always yields the same label, easy to test
  * inspectable — when a story is mis-categorized, you can read the rule
  * zero cost — no model load, no network call, no GPU

How to upgrade to AI later:
  Replace `classify()` (or wrap it) with an LLM/embedding-based classifier
  that returns the same tuple shape. The orchestrator's `categorize_all()`
  call site doesn't change.

Category set is fixed by the product spec. "other" is the bucket for items
that pass the relevance filter but don't fit a named category.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Mapping, Tuple

from ..models import NewsItem
from .keywords import count_keyword_hits

# Per-category keyword vocabulary. English + a starter set of Ukrainian terms.
# Order of dict keys defines priority on ties — most specific first.
# Use trailing `*` for Slavic stems (covers case/number inflections).
CATEGORY_KEYWORDS: Mapping[str, frozenset[str]] = {
    "zero-day": frozenset({
        "zero-day", "zero day", "0-day", "0day", "zeroday",
        "нульового дня",
    }),
    "ransomware": frozenset({
        "ransomware", "ransom", "extortion", "double extortion",
        "lockbit", "blackcat", "alphv", "conti", "clop", "royal ransomware",
        "програма-вимагач", "вимагач*", "шифрувальник*",
    }),
    "spyware": frozenset({
        "spyware", "stalkerware", "surveillance", "pegasus", "predator",
        "шпигунське по", "шпигунська програма", "шпигун*",
    }),
    "botnet": frozenset({
        "botnet", "ddos", "command and control", "c2 server", "c&c server",
        "ботнет",
    }),
    "phishing": frozenset({
        "phishing", "phish", "smishing", "vishing", "spear phishing",
        "credential harvesting", "lookalike domain", "fake login",
        "фішинг*",
    }),
    "social engineering": frozenset({
        "social engineering", "pretexting", "impersonation",
        "business email compromise", "bec scam",
        "соціальна інженерія", "соцінженерія",
    }),
    "exploit": frozenset({
        "exploit", "exploited", "exploits", "exploitation",
        "remote code execution", "rce", "actively exploited",
        "експлойт*", "експлуат*",
    }),
    "vulnerability": frozenset({
        "vulnerability", "vulnerabilities", "vuln", "cve-", "flaw",
        "advisory", "advisories", "patch", "patched",
        "вразлив*", "уразлив*",
    }),
    "breach": frozenset({
        "breach", "breached", "data breach",
        "злам*",
    }),
    "data leak": frozenset({
        "data leak", "data leaks", "leaked database", "exposed database",
        "exfiltrated", "exfiltration", "stolen data", "credentials exposed",
        "витік даних", "викрадено дані", "витік",
    }),
    "malware": frozenset({
        "malware", "trojan", "rootkit", "worm", "rat", "infostealer",
        "stealer", "loader", "dropper", "backdoor",
        "шкідливе по", "шкідлива програма", "троян*", "шкідлив*",
    }),
    "scam": frozenset({
        "scam", "scams", "scammer", "fraud", "investment scam",
        "romance scam", "tech support scam",
        "шахрай*",
    }),
}

# Tokenizer that copes with hyphenated keywords (zero-day) and ascii+cyrillic.
_TOKEN_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*", flags=re.UNICODE)


def classify(text: str) -> Tuple[str, float]:
    """Return (category, confidence).

    Confidence is `winner_hits / total_hits` across all categories.
    A clean single-category match → 1.0. Mixed signals → lower.
    """
    if not text:
        return "other", 0.0
    text_lower = text.lower()
    tokens = set(_TOKEN_RE.findall(text_lower))

    scores = {
        cat: count_keyword_hits(kws, text_lower, tokens)
        for cat, kws in CATEGORY_KEYWORDS.items()
    }
    total = sum(scores.values())
    if total == 0:
        return "other", 0.0
    # Pick highest score; ties broken by the priority order baked into
    # CATEGORY_KEYWORDS dict insertion order (most-specific first).
    best_cat = max(CATEGORY_KEYWORDS.keys(), key=lambda c: scores[c])
    best_score = scores[best_cat]
    if best_score == 0:
        return "other", 0.0
    confidence = best_score / total
    return best_cat, confidence


def categorize_item(item: NewsItem) -> NewsItem:
    """In-place enrichment: assign category + category_confidence."""
    category, confidence = classify(f"{item.title}\n{item.raw_content}")
    item.category = category
    item.category_confidence = confidence
    return item


def categorize_all(items: Iterable[NewsItem]) -> List[NewsItem]:
    return [categorize_item(i) for i in items]


__all__ = [
    "CATEGORY_KEYWORDS",
    "classify",
    "categorize_item",
    "categorize_all",
]
