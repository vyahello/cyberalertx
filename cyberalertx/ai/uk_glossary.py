"""Ukrainian post-generation normalization.

Two layers:

  1. **Glossary**: replace russism stems with the canonical Ukrainian
     equivalents in any AI-generated UA text. Cheap regex pass, idempotent.
     Catches the most common machine-translation tells.

  2. **Rejection vocabulary**: stems that would mark the output as
     unmistakably Russian-grammar, even after the cleanup pass. The
     validator imports `RUSSISM_STEMS` and fails the response — generator
     falls back to rule-based, which is glossary-clean by design.

Why a separate module:
  * Easy to extend by editing data, not code.
  * Pure functions, no I/O — trivial to unit-test.
  * The rule-based UA pool is hand-curated Ukrainian; the validator only
    needs to police AI output, not the rule-based fallback.
"""
from __future__ import annotations

import re
from typing import Mapping


# ===========================================================================
# Glossary — stem-based regex replacements.
#
# Pattern semantics:
#   * Each entry maps a russism *stem* (matched at word-boundary, then any
#     letters) to a Ukrainian replacement *stem*. Suffix letters are kept,
#     so "уязвимости" → "вразливості", "уязвимый" → "вразливий", etc.
#   * Case is preserved: if the source word starts with an uppercase letter,
#     the replacement does too.
#
# The list is intentionally narrow — only entries that DON'T have a clean
# Ukrainian homonym. We do NOT touch words like "система", "сервіс",
# "інформація" that are identical in both languages.
# ===========================================================================

GLOSSARY: Mapping[str, str] = {
    # Cyber-specific russisms.
    "уязвим":      "вразлив",        # уязвимость → вразливість
    "взлом":       "злам",            # взлом → злам
    "мошенн":      "шахрайн",        # мошенник → шахрайник (rough; usually replaces stem entirely)
    "мошенниче":   "шахрайство",     # мошенничество
    "учётн":       "обліков",        # учётная запись → облікова
    "учетн":       "обліков",        # учетная → облікова
    "пользовател": "користувач",
    "вредон":      "шкідлив",        # вредоносный → шкідливий
    "обнаруж":     "виявл",          # обнаружен → виявлен
    "находитс":    "перебува",       # находится → перебуває
    "являетс":     "є ",              # является → є (trailing space tightens to single word)
    "являютс":     "є ",
    "только что":  "щойно",
    "путём":       "шляхом",
    "путем":       "шляхом",
    "одной":       "однієї",
    "другой":      "іншої",
    # IT-adjacent.
    "получит":     "отрима",          # получит → отрима
    "сообщ":       "повідомл",
    "сейчас":      "зараз",
    "правильн":    "правильн",        # already correct in both — no-op kept to document
    "опасн":       "небезпечн",
    "защит":       "захист",
    "поддержк":    "підтримк",
    # Operations / DDoS-area russisms.
    "атак":        "атак",            # IDENTICAL — no-op so we don't fight false-positive
    "хищен":       "крадіжк",
    "перехват":    "перехопл",
    # Ukrainian author-tone fixes (not russisms — bad coinages that
    # creep into AI output when models invent compounds).
    "нульден":     "нульовий ден",   # "нульдень" → "нульовий день" (zero-day)
    "0-ден":       "нульовий ден",
    "0ден":        "нульовий ден",
    # Case fix: "витікам даних" (dative plural) → "витоку даних" (genitive
    # singular). The grammatically correct collocation is "[витоку] даних",
    # not "[витікам] даних".
    "витікам":     "витоку",
    "витоків":     "витоку",          # "запобігання витоків" → "запобігання витоку"
}

# Stems we never want to leave intact in UA AI output. Validation gate.
RUSSISM_STEMS: tuple[str, ...] = (
    "уязв",
    "взлом",
    "мошен",
    "учетн", "учётн",
    "являетс", "являютс",
    "обнаруж",
    "только что",
    "путем", "путём",
    "вредон",
    "находитс",
)


_WORD_RE = re.compile(
    r"\b([" + r"А-Яа-яЁёЇїІіЄєҐґ" + r"]+)\b",
    flags=re.UNICODE,
)


def _normalize_one(word: str) -> str:
    """Apply the longest matching glossary entry to a single Cyrillic word.

    Longest-match-first prevents `мошен` from intercepting `мошенниче` —
    the more specific entry wins.
    """
    lower = word.lower()
    for stem, replacement in sorted(GLOSSARY.items(), key=lambda x: -len(x[0])):
        if lower.startswith(stem):
            tail = word[len(stem):]
            # Preserve case of the first letter.
            if word and word[0].isupper() and replacement:
                replacement = replacement[0].upper() + replacement[1:]
            return replacement + tail
    return word


def normalize_ukrainian(text: str) -> str:
    """Sweep `text` through the russism glossary.

    Idempotent — running twice yields the same result (replacements are
    already Ukrainian and won't match a russism stem on the next pass).
    Returns the text unchanged when empty / non-string.
    """
    if not text or not isinstance(text, str):
        return text
    return _WORD_RE.sub(lambda m: _normalize_one(m.group(1)), text)


def normalize_ukrainian_fields(values: object) -> object:
    """Recursive variant — walks dicts/lists and normalizes every string
    encountered. Used by the generator to scrub an entire `ThreatPost`
    dict in one call before serialization."""
    if isinstance(values, str):
        return normalize_ukrainian(values)
    if isinstance(values, list):
        return [normalize_ukrainian_fields(v) for v in values]
    if isinstance(values, dict):
        return {k: normalize_ukrainian_fields(v) for k, v in values.items()}
    return values


def has_russism(text: str) -> str | None:
    """Return the first russism stem found in `text`, or None.

    Used by the AI response validator: any stem hit → reject the response,
    fall back to rule-based (which doesn't use russism vocabulary by
    construction)."""
    if not text:
        return None
    low = text.lower()
    for stem in RUSSISM_STEMS:
        if stem in low:
            return stem
    return None


__all__ = [
    "GLOSSARY",
    "RUSSISM_STEMS",
    "normalize_ukrainian",
    "normalize_ukrainian_fields",
    "has_russism",
]
