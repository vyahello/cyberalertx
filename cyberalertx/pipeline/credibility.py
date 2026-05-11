"""Source credibility analysis (rule-based v1).

Contract:
    analyze_credibility(item, *, batch=None) -> (tier, score)
    analyze_all(items)                       -> mutates items in place

Three signals feed the score:

  1. Base reputation (registry lookup).
     `SOURCE_PROFILES` maps source name → static credibility profile. Curated
     by hand for known outlets; anything missing falls to `DEFAULT_PROFILE`
     (unverified, score 0.35). To trust a new feed you add one entry.

  2. Sensationalism penalty.
     Clickbait wording ("shocking truth", "you won't believe…", "exclusive:")
     subtracts from the base. Capped so even very breathless writing can't
     drag a respected outlet below `verified`.

  3. Corroboration bonus.
     When this item's headline is similar to items from OTHER trusted sources
     in the same batch, we add up to +0.15. The mechanic mirrors the ranker's
     cross-source bonus but here we only count *trusted* sources — a swarm of
     unverified blogs reposting the same rumor doesn't lift credibility.

Why this is its own module (not folded into `audience`/`category`):
  Credibility is a per-source concern with its own registry lifecycle
  (an analyst can audit & retune `SOURCE_PROFILES` without touching feed
  URLs). The analyzer is a pure function of (item + batch) → (tier, score),
  so swapping it for an ML version later is one line in the orchestrator.

Where AI plugs in:
  Replace `analyze_credibility()` (or wrap it) with a classifier that scores
  textual confidence cues — hedging language, named-sourcing density,
  presence/absence of CVE IDs, vendor confirmation, etc. The orchestrator
  call site stays identical. Cascade option: run rules first, then call the
  AI only on items at the `unverified ↔ verified` boundary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from ..models import NewsItem

# Tier values are part of the public output schema — keep them stable.
TIER_TRUSTED = "trusted"
TIER_VERIFIED = "verified"
TIER_UNVERIFIED = "unverified"

_TIER_THRESHOLDS = (
    (0.70, TIER_TRUSTED),
    (0.40, TIER_VERIFIED),
)
# Anything below the lowest threshold → unverified.


@dataclass(frozen=True)
class SourceProfile:
    """Static credibility profile for a known source.

    `base_score` is the starting credibility before per-item adjustments.
    `tier` is the *declared* tier (what we believe about the publisher
    in general). The final per-item tier comes from the computed score.
    """
    base_score: float
    tier: str


# Hand-curated registry. To add or retune a source, edit this dict — the
# rest of the codebase reads from it via name lookup. Source NAMES must match
# the `SourceConfig.name` in `config.py`.
SOURCE_PROFILES: Mapping[str, SourceProfile] = {
    # Official advisories — government / CERT — highest base trust.
    "CISA Alerts":              SourceProfile(base_score=0.95, tier=TIER_TRUSTED),
    "CISA Advisories":          SourceProfile(base_score=0.95, tier=TIER_TRUSTED),
    "US-CERT":                  SourceProfile(base_score=0.95, tier=TIER_TRUSTED),
    "NCSC":                     SourceProfile(base_score=0.93, tier=TIER_TRUSTED),
    # Established cybersecurity journalism / vendor research.
    "Krebs on Security":        SourceProfile(base_score=0.90, tier=TIER_TRUSTED),
    "BleepingComputer":         SourceProfile(base_score=0.85, tier=TIER_TRUSTED),
    "The Hacker News":          SourceProfile(base_score=0.82, tier=TIER_TRUSTED),
    "Securelist (Kaspersky)":   SourceProfile(base_score=0.85, tier=TIER_TRUSTED),
    "Mandiant":                 SourceProfile(base_score=0.88, tier=TIER_TRUSTED),
    "Microsoft Security":       SourceProfile(base_score=0.88, tier=TIER_TRUSTED),
    "DarkReading":              SourceProfile(base_score=0.78, tier=TIER_TRUSTED),
    "SecurityWeek":             SourceProfile(base_score=0.75, tier=TIER_TRUSTED),
    # Mid-tier — generally reliable, more aggregated content.
    "InfoSecurity Magazine":    SourceProfile(base_score=0.62, tier=TIER_VERIFIED),
    "SC Media":                 SourceProfile(base_score=0.60, tier=TIER_VERIFIED),
    "Threatpost":               SourceProfile(base_score=0.58, tier=TIER_VERIFIED),
    # --- Ukrainian sources ---
    # Established UA tech publications. `verified` rather than `trusted`
    # because cyber coverage is one beat among many for them.
    "itc.ua":                   SourceProfile(base_score=0.66, tier=TIER_VERIFIED),
    "ain.ua":                   SourceProfile(base_score=0.62, tier=TIER_VERIFIED),
    "dev.ua":                   SourceProfile(base_score=0.60, tier=TIER_VERIFIED),
    # CERT-UA reserved for the day they publish an RSS feed:
    # "CERT-UA":                SourceProfile(base_score=0.92, tier=TIER_TRUSTED),
}

# Default for any source we haven't profiled. The unverified default is
# intentional — we want new feeds to earn their tier explicitly, not get
# automatic trust by being added to the feed list.
DEFAULT_PROFILE = SourceProfile(base_score=0.35, tier=TIER_UNVERIFIED)


# Clickbait / sensationalism wording. Each hit subtracts 0.10 from the score,
# capped at -0.30 so even very breathless writing can't single-handedly drop
# CISA below `verified`.
SENSATIONAL_PHRASES: frozenset[str] = frozenset({
    "shocking", "shocking truth", "shocking discovery",
    "you won't believe", "you wont believe", "you won't guess",
    "unbelievable", "mind-blowing", "mind blowing", "jaw-dropping",
    "explosive", "bombshell", "stunning revelation",
    "secrets revealed", "secret revealed",
    "doomsday", "apocalypse", "armageddon",
    "everything you need to know",
    "click here", "must read", "must-read",
    "you need to read this",
})

# Cross-source corroboration tuning. Mirrors the ranker's logic but only
# counts *trusted* sources — a hundred blogs reposting a rumor shouldn't lift
# credibility.
_CORROBORATION_MAX_BONUS = 0.15
_CORROBORATION_PER_SOURCE = 0.05
_CORROBORATION_JACCARD = 0.25
_CORROBORATION_MIN_SHARED_TOKENS = 2

_PENALTY_PER_HIT = 0.10
_MAX_PENALTY = 0.30

_TOKEN_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*", flags=re.UNICODE)
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with",
    "is", "are", "was", "were", "be", "been", "by", "as", "at", "from",
    "that", "this", "it", "its", "new", "more", "than", "into", "after",
})


def _title_tokens(title: str) -> set[str]:
    return {
        t.lower()
        for t in _TOKEN_RE.findall(title)
        if t.lower() not in _STOPWORDS and len(t) > 2
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _tier_for(score: float) -> str:
    for threshold, tier in _TIER_THRESHOLDS:
        if score >= threshold:
            return tier
    return TIER_UNVERIFIED


def profile_for(source_name: str) -> SourceProfile:
    """Public helper — callers can read declared profiles without going
    through the analyzer."""
    return SOURCE_PROFILES.get(source_name, DEFAULT_PROFILE)


def _sensationalism_penalty(text_lower: str) -> float:
    hits = sum(1 for phrase in SENSATIONAL_PHRASES if phrase in text_lower)
    return min(_MAX_PENALTY, hits * _PENALTY_PER_HIT)


def _corroboration_bonus(
    target: NewsItem,
    target_tokens: set[str],
    batch: Sequence[NewsItem],
) -> float:
    if not batch or not target_tokens:
        return 0.0
    corroborating_sources: set[str] = set()
    for other in batch:
        if other is target or other.source == target.source:
            continue
        # Only TRUSTED corroborators count — see module docstring.
        other_profile = SOURCE_PROFILES.get(other.source, DEFAULT_PROFILE)
        if other_profile.tier != TIER_TRUSTED:
            continue
        other_tokens = _title_tokens(other.title)
        shared = target_tokens & other_tokens
        if len(shared) < _CORROBORATION_MIN_SHARED_TOKENS:
            continue
        if _jaccard(target_tokens, other_tokens) >= _CORROBORATION_JACCARD:
            corroborating_sources.add(other.source)
    return min(_CORROBORATION_MAX_BONUS, len(corroborating_sources) * _CORROBORATION_PER_SOURCE)


def analyze_credibility(
    item: NewsItem,
    *,
    batch: Optional[Sequence[NewsItem]] = None,
) -> Tuple[str, float]:
    """Pure function. Same `(item, batch)` always yields the same `(tier, score)`.

    Pass `batch` when calling from the pipeline so the corroboration bonus can
    fire; omit it for unit tests / one-off scoring (corroboration = 0).
    """
    profile = SOURCE_PROFILES.get(item.source, DEFAULT_PROFILE)
    text_lower = f"{item.title}\n{item.raw_content}".lower()

    penalty = _sensationalism_penalty(text_lower)
    target_tokens = _title_tokens(item.title)
    bonus = _corroboration_bonus(item, target_tokens, batch or [])

    score = max(0.0, min(1.0, profile.base_score - penalty + bonus))
    return _tier_for(score), score


def analyze_for_item(item: NewsItem, *, batch: Optional[Sequence[NewsItem]] = None) -> NewsItem:
    """In-place enrichment: assign source_tier + source_credibility_score."""
    tier, score = analyze_credibility(item, batch=batch)
    item.source_tier = tier
    item.source_credibility_score = score
    return item


def analyze_all(items: Iterable[NewsItem]) -> List[NewsItem]:
    """Run credibility analysis over a whole batch.

    Materializes `items` once so each call can see all peers (needed for
    corroboration bonus).
    """
    items_list = list(items)
    for item in items_list:
        analyze_for_item(item, batch=items_list)
    return items_list


__all__ = [
    "SourceProfile",
    "SOURCE_PROFILES",
    "DEFAULT_PROFILE",
    "SENSATIONAL_PHRASES",
    "TIER_TRUSTED",
    "TIER_VERIFIED",
    "TIER_UNVERIFIED",
    "analyze_credibility",
    "analyze_for_item",
    "analyze_all",
    "profile_for",
]
