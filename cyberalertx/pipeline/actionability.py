"""Actionability analysis (rule-based v1).

Contract:
    analyze_actionability(item, *, text=None, tokens=None)
        -> (level: str, score: float in [0, 1])

Three levels, in increasing urgency:
  * "informational"      — read-only context (research, theoretical, surveys)
  * "recommended_action" — patch/update available, user should act when convenient
  * "urgent_action"      — active exploitation / credentials at risk / fire-drill

Why a rule-based first pass:
  * deterministic — easy to test the spec examples and pin regressions
  * inspectable — when a story is mis-flagged, you can read the matched phrases
  * cheap — zero cost per item, suitable for the every-15-min hot path
  * gives the AI version a labeled baseline to evaluate against later

Where AI fits in:
  Replace `analyze_actionability()` (or wrap it as a fallback) with an LLM /
  fine-tuned classifier that returns the same `(str, float)` tuple. Recommended
  cascade: run rules first, escalate to AI only on items the rules call
  "informational" with `category in {zero-day, exploit}` (a known blind spot
  of pure keyword matching).
"""
from __future__ import annotations

import re
from typing import Iterable, List, Mapping, Tuple

from ..models import NewsItem
from .keywords import count_keyword_hits

# Phrases that strongly imply "drop everything" urgency. Each hit adds 4.0
# raw points — one is enough to clear the urgent threshold by itself.
URGENT_PHRASES: frozenset[str] = frozenset({
    # Active exploitation in the wild
    "actively exploited", "exploited in the wild", "exploit in the wild",
    "in the wild", "being exploited", "under active attack",
    "ongoing campaign", "active campaign", "mass exploitation",
    "widespread exploitation", "wormable",
    # Direct calls to action with urgency
    "enable 2fa immediately", "change password immediately",
    "patch immediately", "update immediately", "apply immediately",
    "apply patch now", "patch now",
    "emergency patch", "out-of-band patch", "out of band patch",
    "urgent patch", "act now",
    "rotate credentials", "reset password", "reset passwords",
    # Compromise in progress
    "credentials stolen", "passwords stolen", "credentials exposed",
    "accounts compromised", "2fa bypass", "session hijack",
    "session token stolen", "session tokens stolen",
})

# Phrases that imply the user should act eventually — patch available,
# recommended actions, mitigations. Each hit adds 2.0 raw points.
RECOMMENDED_PHRASES: frozenset[str] = frozenset({
    # Patch / fix / update availability (common phrasings)
    "patch available", "patches available", "patch released",
    "patch is available", "patch is now available",
    "fix available", "fix is available", "fix released",
    "update available", "update released", "update is available",
    "released a patch", "issued a patch", "released a fix",
    "issues a patch", "issues an update",
    # General recommendations
    "users should update", "users should patch", "admins should",
    "recommended to update", "recommended to patch", "we recommend",
    "it is recommended", "advised to update", "advised to patch",
    # Mitigations / workarounds
    "workaround available", "mitigation available", "temporary workaround",
    "interim mitigation", "interim guidance",
    # Scale signals that suggest broad applicability (soft push)
    "millions of users", "thousands of users", "users affected",
    "users exposed", "users at risk",
})

# Phrases that pull toward "just FYI". Each hit subtracts 1.5 raw points.
INFORMATIONAL_PHRASES: frozenset[str] = frozenset({
    # Academic / theoretical framing
    "theoretical attack", "theoretical exploit", "theoretical flaw",
    "researchers discovered", "researchers found", "researchers identified",
    "academic paper", "research paper", "research report",
    "proof of concept", "proof-of-concept",
    "demonstrated that", "demonstrated how", "demonstrate how",
    # Retrospective / industry color
    "report shows", "report finds", "study finds", "survey finds",
    "according to a report", "according to the report",
    "annual report", "industry report",
    # Pure news without an ask
    "appointed", "announces partnership", "announced partnership",
    "research blog", "case study",
})

# Per-category nudges. Most categories are neutral; only the strongest
# urgency-correlated ones bump (or dampen, for "other").
CATEGORY_URGENCY_BIAS: Mapping[str, float] = {
    "zero-day": 1.5,
    "exploit": 1.0,
    "ransomware": 0.5,
    "data leak": 0.5,
    "breach": 0.3,
    "vulnerability": 0.3,
    "phishing": 0.0,
    "scam": 0.0,
    "malware": 0.3,
    "spyware": 0.5,
    "botnet": 0.0,
    "social engineering": 0.0,
    "other": -0.5,
}

# Weights + caps. Each signal class is capped at 2 hits — the goal is to
# detect *whether* the signal class is present, not let synonyms compound.
# Without the cap, "patch available" + "released a patch" + "users should
# update" (three ways to say the same thing) would push a routine update
# story into urgent territory.
#
# Tuned so:
#   * 1 URGENT phrase (raw=4)              → score 0.79 → urgent_action
#   * 1 RECOMMENDED phrase (raw=1.5)       → score 0.43 → recommended_action
#   * 2 RECOMMENDED phrases (raw=3)        → score 0.64 → recommended_action
#   * 2 INFORMATIONAL phrases (raw=-2)     → score 0    → informational
#   * no signals (raw=0)                   → score 0.21 → informational
_URGENT_WEIGHT = 4.0
_RECOMMENDED_WEIGHT = 1.5
_INFORMATIONAL_WEIGHT = -1.0
_SIGNAL_CAP = 2  # diminishing returns: third+ hit of the same class doesn't count

# Mapping raw → [0, 1]: shift so 0 raw lands at ~0.21, then divide. Clamp.
# Wider divisor + larger offset keep the category bias visible even when
# informational phrases pull the raw signal negative.
_RAW_OFFSET = 1.5
_RAW_DIVISOR = 7.0

_URGENT_THRESHOLD = 0.7   # >= 0.7  → urgent_action
_RECOMMENDED_THRESHOLD = 0.4  # >= 0.4 → recommended_action; else informational

_TOKEN_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*", flags=re.UNICODE)


def _level_from_score(score: float) -> str:
    if score >= _URGENT_THRESHOLD:
        return "urgent_action"
    if score >= _RECOMMENDED_THRESHOLD:
        return "recommended_action"
    return "informational"


def analyze_actionability(
    item: NewsItem,
    *,
    text: str | None = None,
    tokens: set[str] | None = None,
) -> Tuple[str, float]:
    """Pure function — same inputs always produce the same (level, score)."""
    if text is None:
        text = f"{item.title}\n{item.raw_content}".lower()
    if tokens is None:
        tokens = set(_TOKEN_RE.findall(text))

    urgent = min(_SIGNAL_CAP, count_keyword_hits(URGENT_PHRASES, text, tokens))
    recommended = min(_SIGNAL_CAP, count_keyword_hits(RECOMMENDED_PHRASES, text, tokens))
    informational = min(_SIGNAL_CAP, count_keyword_hits(INFORMATIONAL_PHRASES, text, tokens))
    category_bias = CATEGORY_URGENCY_BIAS.get(item.category, 0.0)

    raw = (
        urgent * _URGENT_WEIGHT
        + recommended * _RECOMMENDED_WEIGHT
        + informational * _INFORMATIONAL_WEIGHT
        + category_bias
    )
    score = max(0.0, min(1.0, (raw + _RAW_OFFSET) / _RAW_DIVISOR))
    return _level_from_score(score), score


def analyze_for_item(item: NewsItem) -> NewsItem:
    """In-place enrichment: assign actionability_level + actionability_score."""
    level, score = analyze_actionability(item)
    item.actionability_level = level
    item.actionability_score = score
    return item


def analyze_all(items: Iterable[NewsItem]) -> List[NewsItem]:
    return [analyze_for_item(i) for i in items]


__all__ = [
    "URGENT_PHRASES",
    "RECOMMENDED_PHRASES",
    "INFORMATIONAL_PHRASES",
    "CATEGORY_URGENCY_BIAS",
    "analyze_actionability",
    "analyze_for_item",
    "analyze_all",
]
