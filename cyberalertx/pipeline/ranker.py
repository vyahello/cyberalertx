"""Threat scoring.

`threat_score` is a 0..100 float combining four independent signals:

    score = clip( base_keyword + severity_boost ) * recency_factor + cross_source_bonus

  * base_keyword     — how many relevance words appear (capped, log-shaped)
  * severity_boost   — multiplied per "critical / RCE / actively exploited" hit
  * recency_factor   — exponential decay with configurable half-life (newer = hotter)
  * cross_source_bonus — +N if multiple distinct sources cover the same topic.
                        Topic similarity = Jaccard on title tokens (cheap and
                        good-enough; we can swap for embeddings later).

The whole module is a pure function over (items, now). No I/O, fully testable.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Iterable, List, Sequence

from ..config import SETTINGS
from ..models import NewsItem
from .keywords import RELEVANCE_KEYWORDS, SEVERITY_WEIGHTS

_WORD_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*", flags=re.UNICODE)
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with",
    "is", "are", "was", "were", "be", "been", "by", "as", "at", "from",
    "that", "this", "it", "its", "new", "more", "than", "into", "after",
})


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2}


def _keyword_component(text: str, tokens: set[str]) -> float:
    hits = 0
    for kw in RELEVANCE_KEYWORDS:
        if " " in kw or "-" in kw:
            if kw in text:
                hits += 1
        elif kw in tokens:
            hits += 1
    # log curve so a story doesn't run away just by spamming "breach breach breach"
    return 15.0 * math.log1p(hits)


def _severity_component(text: str) -> float:
    total = 0.0
    for phrase, weight in SEVERITY_WEIGHTS.items():
        if phrase in text:
            total += weight
    return total * 4.0  # turn each unit of severity into ~4 score points


def _recency_factor(published_at: datetime, now: datetime, half_life_hours: float) -> float:
    """Exponential decay: factor=1.0 at t=0, 0.5 at one half-life, ~0.06 at 4x.

    Floor at 0.2 so a critical 5-day-old CVE still ranks visibly higher than
    a brand-new corporate puff piece that slipped through.
    """
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - published_at).total_seconds() / 3600.0)
    factor = math.pow(0.5, age_hours / max(half_life_hours, 0.1))
    return max(factor, 0.2)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cross_source_bonus(
    target: NewsItem,
    target_tokens: set[str],
    all_items: Sequence[tuple[NewsItem, set[str]]],
    similarity_threshold: float = 0.2,
    min_shared_tokens: int = 2,
) -> float:
    """Bonus for stories that show up across multiple feeds.

    We count distinct *sources* (not items) that report a similar headline.
    Two-pronged match: Jaccard >= threshold AND at least N shared distinctive
    tokens. The shared-token floor is what kills false positives from a
    single common word (e.g. two unrelated stories that both mention "phishing").
    """
    corroborating_sources: set[str] = set()
    for other, other_tokens in all_items:
        if other is target:
            continue
        if other.source == target.source:
            continue
        shared = target_tokens & other_tokens
        if len(shared) < min_shared_tokens:
            continue
        if _jaccard(target_tokens, other_tokens) >= similarity_threshold:
            corroborating_sources.add(other.source)
    n = len(corroborating_sources)
    if n == 0:
        return 0.0
    return 20.0 * (1.0 - math.exp(-0.6 * n))


def score_items(
    items: Iterable[NewsItem],
    *,
    now: datetime | None = None,
    half_life_hours: float | None = None,
) -> List[NewsItem]:
    """Assign `threat_score` to every item in-place AND return them, sorted desc."""
    now = now or datetime.now(timezone.utc)
    half_life = half_life_hours if half_life_hours is not None else SETTINGS.recency_half_life_hours

    items_list = items if isinstance(items, list) else list(items)
    precomputed: List[tuple[NewsItem, set[str], str]] = []
    for item in items_list:
        text = f"{item.title} \n {item.raw_content}".lower()
        precomputed.append((item, _tokens(item.title), text))

    similarity_pool: List[tuple[NewsItem, set[str]]] = [
        (it, toks) for (it, toks, _) in precomputed
    ]

    for item, title_tokens, text in precomputed:
        body_tokens = _tokens(text)
        base = _keyword_component(text, body_tokens)
        severity = _severity_component(text)
        recency = _recency_factor(item.published_at, now, half_life)
        bonus = _cross_source_bonus(item, title_tokens, similarity_pool)
        raw = (base + severity) * recency + bonus
        item.threat_score = max(0.0, min(100.0, raw))

    items_list.sort(key=lambda i: i.threat_score, reverse=True)
    return items_list
