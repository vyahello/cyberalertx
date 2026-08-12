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


# ===========================================================================
# Calque / anglicism table — English syntax and vocabulary wearing Ukrainian
# letters. Orthogonal to GLOSSARY above: that one catches Russian, this one
# catches machine-translated English, which is the dominant failure mode
# because the overwhelming majority of live UA posts are written from an
# English source article.
#
# ONLY morphologically safe stem swaps live here: the replacement must share
# gender and declension class with the source, so every inflected form stays
# grammatical. Defects that need the sentence rebuilt (нанизування іменників,
# «дозволяє + віддієслівний іменник», пасив, порядок слів) are prompt rules,
# not substitutions — see `_SHARED_RULES_UK` in templates.py.
# ===========================================================================

CALQUE_GLOSSARY: Mapping[str, str] = {
    # Non-words: Ukrainian forms no participle from "патч".
    "непропатчен": "неоновлен",
    "незапатчен":  "неоновлен",
    "пропатчен":   "виправлен",
    "запатчен":    "виправлен",
    "патчен":      "виправлен",
    # Half-translated Russian «межсетевой экран».
    "міжсітьов":   "мережев",
    # Both are in SUM-11; the product ships one. Does NOT touch
    # "уражати/ураження" — different stem, different first three letters.
    "уразлив":     "вразлив",
    # «Угрупування» is the process noun (the act of grouping); a threat actor
    # is «угруповання». The wrong form is currently the majority form.
    "угрупуван":   "угрупован",
    # Anglicism with a living equivalent; same gender, same declension.
    "афіліат":     "партнер",
}

_CALQUE_STEMS: tuple[tuple[str, str], ...] = tuple(
    sorted(CALQUE_GLOSSARY.items(), key=lambda kv: -len(kv[0]))
)

# ===========================================================================
# Exact-form replacements, for terms where a stem swap would break grammar.
#
# «Вада» is not a cybersecurity term. In Ukrainian it is a defect in the
# everyday or medical sense — вада серця, вада конструкції — and reads wrong
# for a software flaw an attacker exploits. The term is «вразливість».
#
# This cannot go in CALQUE_GLOSSARY: that table swaps stems and keeps the
# suffix, which only works when both words share a declension class. These
# two do not. «Вада» is 1st declension (вада, вади, ваду, вадою), while
# «вразливість» is 3rd (вразливість, вразливості, вразливістю), and the
# genitive plural is irregular against it — «398 вад» becomes «398
# вразливостей», not «398 вразливостей» by any suffix rule. So every form is
# mapped explicitly.
#
# Both nouns are feminine, so adjectives, pronouns and past-tense verbs
# agreeing with them stay correct: «критична вада» → «критична вразливість»,
# «цю ваду» → «цю вразливість».
#
# Whole-word matching only — «Вадим» must never become «Вразливістьм».
# ===========================================================================

TERM_FORMS: Mapping[str, str] = {
    "вада":   "вразливість",    # nom sg
    "вади":   "вразливості",    # gen sg / nom pl / acc pl
    "ваді":   "вразливості",    # dat sg / loc sg
    "ваду":   "вразливість",    # acc sg
    "вадою":  "вразливістю",    # instr sg
    "вад":    "вразливостей",   # gen pl
    "вадам":  "вразливостям",   # dat pl
    "вадами": "вразливостями",  # instr pl
    "вадах":  "вразливостях",   # loc pl
}

# Replacing the noun can leave a preposition Ukrainian euphony rejects: «в
# ваді» is unremarkable, but «в вразливості» stacks в+вр. The rule is «у»
# before a consonant cluster. Case is carried over so a mid-sentence «в»
# does not come back capitalised.
_V_BEFORE_CLUSTER = re.compile(r"\b([Вв])(\s+вразлив\w+)")


def _fix_euphony(text: str) -> str:
    return _V_BEFORE_CLUSTER.sub(
        lambda m: ("У" if m.group(1).isupper() else "у") + m.group(2), text,
    )

# Collocations a single-word swap cannot reach. Applied BEFORE the stem pass
# and keyed on the ORIGINAL wording, so a legitimate «мережевий захист»
# (network protection in general) is never turned into «мережевий екран»
# (firewall).
CALQUE_PHRASES: Mapping[str, str] = {
    "маловисокопривілейований користувач AD":
        "звичайний обліковий запис Active Directory",
    "міжсітьовим бар'єром": "мережевим екраном",
    "міжсітьових бар'єрів": "мережевих екранів",
    "міжсітьовим захистом": "мережевим екраном",
    "міжсітьових захистів": "мережевих екранів",
}


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


def _normalize_calque_word(word: str) -> str:
    """Longest-match-first stem swap for one Cyrillic word.

    Same contract as `_normalize_one`: the suffix is preserved so every
    inflected form survives, and the first letter's case is carried over.
    """
    lower = word.lower()
    # Exact forms win over stems: these are the terms whose replacement does
    # not share a declension class, so suffix-preserving substitution would
    # produce a non-word.
    exact = TERM_FORMS.get(lower)
    if exact is not None:
        return exact[0].upper() + exact[1:] if word[0].isupper() else exact
    for stem, replacement in _CALQUE_STEMS:
        if lower.startswith(stem):
            tail = word[len(stem):]
            if word[0].isupper():
                replacement = replacement[0].upper() + replacement[1:]
            return replacement + tail
    return word


def normalize_ukrainian_calques(text: str) -> str:
    """Sweep `text` through the phrase table, then the calque stem table.

    Idempotent, and safe to call on text that has already been through
    `normalize_ukrainian` — the two tables share no stems.
    """
    if not text or not isinstance(text, str):
        return text
    for source, target in CALQUE_PHRASES.items():
        text = text.replace(source, target)
    text = _WORD_RE.sub(lambda m: _normalize_calque_word(m.group(1)), text)
    return _fix_euphony(text)


def normalize_ukrainian_calque_fields(values: object) -> object:
    """Recursive variant — walks dicts/lists, normalizes every string."""
    if isinstance(values, str):
        return normalize_ukrainian_calques(values)
    if isinstance(values, list):
        return [normalize_ukrainian_calque_fields(v) for v in values]
    if isinstance(values, dict):
        return {k: normalize_ukrainian_calque_fields(v) for k, v in values.items()}
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
    "CALQUE_GLOSSARY",
    "CALQUE_PHRASES",
    "GLOSSARY",
    "RUSSISM_STEMS",
    "normalize_ukrainian",
    "normalize_ukrainian_calque_fields",
    "normalize_ukrainian_calques",
    "normalize_ukrainian_fields",
    "has_russism",
]
