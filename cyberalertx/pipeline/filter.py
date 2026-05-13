"""Relevance filter.

Strategy (v2 — confidence scoring):
  1. Language gate — drop confidently-non-supported languages (Russian/etc.).
  2. Tokenize title + body once.
  3. Compute a weighted relevance score:
        +3 per STRONG_CYBER_TOKENS match    (unambiguous cyber term)
        +2 per MEDIUM_CYBER_TOKENS match    (strong context)
        +1 per WEAK_CYBER_TOKENS match      (cyber-adjacent / ambiguous)
        −2 per NEGATIVE_TOKENS match        (clean-tech, war, politics, etc.)
  4. Pass iff score >= RELEVANCE_THRESHOLD (default 3).

Why this beats the binary v1:
  * "вразливі мідні контакти" in a wind-turbine puff piece used to pass
    on the bare `вразлив*` stem. It now scores +1 from `вразлив*` and −2
    from `турбін*` / `бездротова зарядк*` → net −1, below threshold.
  * A real cyber story with "actively exploited zero-day" scores +6 from
    two strong matches alone — comfortably above threshold even when the
    text incidentally mentions a non-cyber topic.
  * The 3-point threshold means a single ambiguous "password" mention
    can't carry a story; you need either one strong cyber term, or two
    converging medium/weak signals.

This is intentionally a pure function on text — no I/O, easy to unit test,
and easy to swap for an ML classifier later (preserve the
`(item) -> bool` contract).
"""
from __future__ import annotations

import re
from typing import Iterable, List

from ..models import NewsItem
from .keywords import (
    MEDIUM_CYBER_TOKENS,
    NEGATIVE_TOKENS,
    RELEVANCE_THRESHOLD,
    STRONG_CYBER_TOKENS,
    WEAK_CYBER_TOKENS,
    count_keyword_hits,
)

_WORD_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*", flags=re.UNICODE)

# Languages we explicitly reject. "other" = detector saw Cyrillic without
# Ukrainian markers (Russian/Bulgarian/Serbian). We do NOT include "unknown"
# here: that's "too short to tell" and shows up on legitimate short
# headlines plus unit-test fixtures that bypass normalize.
_REJECTED_LANGUAGES = frozenset({"other"})


def _tokenize(item: NewsItem) -> tuple[str, set[str]]:
    text = f"{item.title} \n {item.raw_content}".lower()
    tokens = set(_WORD_RE.findall(text))
    return text, tokens


def relevance_score(item: NewsItem) -> int:
    """Compute the weighted relevance score for an item.

    Public so callers (debugging, telemetry, future ranker tweaks) can
    inspect why an article was kept or dropped without re-running the
    filter logic by hand.
    """
    text, tokens = _tokenize(item)
    strong = count_keyword_hits(STRONG_CYBER_TOKENS, text, tokens)
    medium = count_keyword_hits(MEDIUM_CYBER_TOKENS, text, tokens)
    weak = count_keyword_hits(WEAK_CYBER_TOKENS, text, tokens)
    negative = count_keyword_hits(NEGATIVE_TOKENS, text, tokens)
    return (3 * strong) + (2 * medium) + weak - (2 * negative)


def is_relevant(item: NewsItem) -> bool:
    """Return True iff the item is a real cybersecurity story.

    Two gates:
      1. Language — silently reject Russian/etc. (we serve en+uk only).
      2. Relevance score — must clear `RELEVANCE_THRESHOLD`.
    """
    if item.language in _REJECTED_LANGUAGES:
        return False
    return relevance_score(item) >= RELEVANCE_THRESHOLD


def filter_relevant(items: Iterable[NewsItem]) -> List[NewsItem]:
    return [i for i in items if is_relevant(i)]


__all__ = [
    "is_relevant",
    "filter_relevant",
    "relevance_score",
]
