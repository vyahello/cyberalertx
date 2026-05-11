"""Unicode normalization + language detection.

Why this is its own stage (not folded into the source layer):
  * keeps RSS-parsing concerns separate from text-hygiene concerns
  * downstream stages (filter, ranker, categorizer) all assume normalized text
  * lets us insert an AI translator here later without touching anything else

What "safe text" means here:
  1. Decoded as Python str (the source layer already did this via httpx).
  2. NFC-normalized — so "café" composed-vs-decomposed compare equal.
  3. Unpaired surrogates removed — these can sneak in from malformed feeds
     and crash json.dumps later.
  4. Control chars stripped except for whitespace (tab/newline/CR).
  5. Whitespace collapsed.

Language detection is intentionally deterministic and dependency-free.
The supported set is {en, uk}; anything else returns "other" (or "unknown"
for too-short input). Swap in `langdetect` / `lingua` / a model when you need
broader coverage — the contract is `detect_language(text) -> str`.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List

from ..models import NewsItem

_WS_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(
    # All C0 / C1 control chars except \t \n \r.
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]"
)

# Unicode block ranges we care about.
_CYRILLIC_RANGE = (0x0400, 0x04FF)
_LATIN_BASIC = (0x0041, 0x007A)

# Letters that exist in Ukrainian but NOT in most other Cyrillic-using
# languages — used to confirm Cyrillic text is Ukrainian.
_UKRAINIAN_ONLY = frozenset("їєґіЇЄҐІ")


def safe_text(value: str) -> str:
    """Make any incoming string safe for downstream text processing.

    Idempotent and total — never raises. A non-string input returns "".
    """
    if not isinstance(value, str):
        return ""
    # NFC composes "e + ́" → "é" so equality and substring search behave.
    try:
        text = unicodedata.normalize("NFC", value)
    except (TypeError, ValueError):
        text = value
    # Strip unpaired surrogates that some malformed feeds inject.
    text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    text = _CTRL_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def detect_language(text: str) -> str:
    """Return one of: 'en', 'uk', 'other', 'unknown'.

    Heuristic:
      * Latin-dominant script → 'en' (we don't target other Latin languages).
      * Cyrillic-dominant + Ukrainian-only letters (ї/є/ґ/і) → 'uk'.
      * Cyrillic-dominant without Ukrainian markers → 'other'. We don't
        claim to identify Russian/Bulgarian/Serbian/etc. — anything that's
        not confidently Ukrainian falls into 'other'.
      * Too short / no letters → 'unknown'.
    """
    if not text:
        return "unknown"
    cyrillic = 0
    latin = 0
    for ch in text:
        cp = ord(ch)
        if _CYRILLIC_RANGE[0] <= cp <= _CYRILLIC_RANGE[1]:
            cyrillic += 1
        elif ch.isalpha() and cp < 0x0080:
            latin += 1
    letters = cyrillic + latin
    if letters < 4:
        return "unknown"
    if cyrillic / letters < 0.3:
        return "en"
    if any(c in _UKRAINIAN_ONLY for c in text):
        return "uk"
    return "other"


def normalize_item(item: NewsItem) -> NewsItem:
    """In-place enrichment: clean text + populate language fields.

    Idempotent: running twice yields the same result.
    """
    item.title = safe_text(item.title)
    item.raw_content = safe_text(item.raw_content)
    # Detect on title+content; title alone is often too short to be reliable.
    detected = detect_language(f"{item.title}\n{item.raw_content}")
    item.language = detected
    if item.original_language in ("", "unknown"):
        item.original_language = detected
    return item


def normalize_all(items: Iterable[NewsItem]) -> List[NewsItem]:
    return [normalize_item(i) for i in items]
