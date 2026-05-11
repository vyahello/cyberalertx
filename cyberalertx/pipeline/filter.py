"""Relevance filter.

Strategy:
  1. Tokenize title + body once, keep both raw lower-cased text (for phrase
     matches like "zero day") and a token set (for word matches).
  2. Item passes if it hits >=1 relevance keyword.
  3. Item is rejected if it also strongly matches an exclusion phrase AND its
     relevance signal is weak (only 1 relevance hit). This lets a story about
     "Acme Corp acquires SecurityCo after major breach" still pass.

This is intentionally a pure function on text — no I/O, easy to unit test,
and easy to swap for an ML classifier later.
"""
from __future__ import annotations

import re
from typing import Iterable, List

from ..models import NewsItem
from .keywords import EXCLUSION_KEYWORDS, RELEVANCE_KEYWORDS, count_keyword_hits

_WORD_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*", flags=re.UNICODE)


def _normalize(item: NewsItem) -> tuple[str, set[str]]:
    text = f"{item.title} \n {item.raw_content}".lower()
    tokens = set(_WORD_RE.findall(text))
    return text, tokens


def is_relevant(item: NewsItem) -> bool:
    text, tokens = _normalize(item)
    relevance_hits = count_keyword_hits(RELEVANCE_KEYWORDS, text, tokens)
    if relevance_hits == 0:
        return False
    exclusion_hits = count_keyword_hits(EXCLUSION_KEYWORDS, text, tokens)
    # Weak relevance + strong exclusion = corporate/IT news with a sec word
    # sprinkled on top. Drop it.
    if exclusion_hits >= 1 and relevance_hits < 2:
        return False
    return True


def filter_relevant(items: Iterable[NewsItem]) -> List[NewsItem]:
    return [i for i in items if is_relevant(i)]
