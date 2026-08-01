"""Deterministic content hygiene, applied at RENDER time.

Why this module exists at all — and why it is not part of `editorial.py`:

`editorial.py` runs once, BEFORE a post is written to the AI cache. That
makes it powerless over the posts already in the cache, and the cache is
keyed by `(fingerprint, locale)` with no prompt version in the key — so a
prompt fix never rewrites a post that already exists. At the time this was
written, 188 of 188 live posts predated the contract changes that would
have prevented the defects below.

This module runs on every render instead, which means it repairs the whole
back catalogue on the next request, for both the website and Telegram (both
read `_PostService.render()` output). It is pure, has no I/O, and never
calls a model — the API server is forbidden from doing that.

WHAT IT REMOVES

  1. Null bullets. A list item that occupies a slot under "What to do" or
     "Check if this affects you" while stating that there is nothing to do
     and nothing to check:

         "Ви звичайний абонент: діяти нічого не можете, це на боці оператора."
         "Ця новина про метод атаки. Технічної перевірки для вашого пристрою немає."
         "Нічого робити не треба, якщо ви не адмініструєте власний сервер."

     These read as an answer but carry no information, and because Telegram
     shows only the first two bullets, one of them can push out the only
     usable step in the list.

  2. Absence-as-fact. A `quick_facts` entry whose whole content is what the
     source did not say ("IOC та список жертв не оприлюднені"). A fact is
     something that is true, not something that is unknown.

     DELIBERATE EXCEPTION: an absence that changes what a defender does is
     kept. "No public PoC observed" and "Патч ще не випущено" both move the
     patch-urgency decision; "the article did not name the victims" does
     not. `_DECISION_RELEVANT_ABSENCE` encodes that distinction.

  3. Severity rationales that explain the rating by something other than
     the threat — by what the source omitted, or by the reader not needing
     to act. Those describe our sourcing, not the danger.

  4. The level restatement at the head of a severity rationale. The page
     prints "Чому рівень «Середній»" immediately above the sentence, so
     "Середній рівень, бо…" makes the reader read the label twice — and on
     3 of the 16 cached posts the restated level contradicts the badge.

WHAT IT DELIBERATELY DOES NOT REMOVE

  Exclusions that name something concrete. "Якщо ви ніколи не запускали yay
  чи paru, вас це не стосується" tells a reader to recall a specific action
  and reach a verdict, so it is a real check and it survives. The line is
  drawn at whether the reader is given anything to evaluate.

Removal is silent by design: the render layer already omits any section
whose list is empty, so a post that loses all of its checks renders without
the heading rather than with an empty one.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .uk_glossary import normalize_ukrainian_calque_fields

# ===========================================================================
# Null ACTION bullets — for `what_to_do` / `what_not_to_do`.
#
# The contract for these fields is "tell the reader to do something". A
# bullet whose main clause negates that fails the contract no matter how
# concretely the rest of it is worded, so unlike the check patterns below
# these fire regardless of any product name in the sentence: the reader is
# still not being given a step.
#
# The prompt used to ASK for these ("Якщо загроза стосується лише серверів,
# так і напишіть: «Нічого робити не треба, якщо ви не адмініструєте власний
# сервер.»"), which is why they are common in the back catalogue.
# ===========================================================================

_NULL_ACTION_UA: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        # "нічого робити не треба" and every word order it appears in.
        r"нічого\s+(?:не\s+)?(?:треба|потрібно|варто)\s+робити",
        r"робити\s+нічого\s+не\s+(?:треба|потрібно|варто)",
        r"нічого\s+робити\s+не\s+(?:треба|потрібно|варто)",
        r"(?:ніяких|жодних)\s+дій\s+не\s+(?:потрібно|треба|вимагається)",
        r"(?:прямої\s+)?ді[йї]\s+не\s+(?:потрібно|треба|вимагається)",
        r"не\s+потребу[єю]\s+(?:жодних\s+|ніяких\s+)?ді[йї]",
        # "you can do nothing, it's on the operator's side"
        r"(?:діяти\s+)?нічого\s+не\s+можете",
        r"не\s+можете\s+нічого\s+(?:зробити|вдіяти)",
        r"нічого\s+не\s+залежить\s+від\s+вас",
    )
)

_NULL_ACTION_EN: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bnothing\s+(?:to\s+do|you\s+(?:can|need\s+to)\s+do)\b",
        r"\bno\s+action\s+(?:is\s+)?(?:needed|required|necessary)\b",
        r"\byou\s+(?:don'?t|do\s+not)\s+need\s+to\s+do\s+anything\b",
        r"\bthere\s+is\s+nothing\s+you\s+can\s+do\b",
        r"\bnothing\s+for\s+(?:you|end\s+users?|consumers?)\s+to\s+do\b",
    )
)

# ===========================================================================
# Null CHECK bullets — for `am_i_affected`.
#
# The contract is "give the reader a test they can run". These patterns
# match bullets that announce there is no such test, or that reframe the
# item as being about a technique in general rather than about the reader.
#
# Note what is NOT here: a bare "вас це не стосується". An exclusion is a
# legitimate outcome of a check ("Якщо ви ніколи не запускали yay чи paru,
# вас це не стосується") and removing those would delete real answers.
# ===========================================================================

_NULL_CHECK_UA: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        # "there is no technical check for your device"
        r"перевірк[аиу][^.]{0,40}\bнема[єе]\b",
        r"\bнема[єе]\b[^.]{0,40}перевірк",
        r"перевірити\s+(?:це\s+)?немож",
        r"немож(?:ливо|на)\s+перевірити",
        r"способу\s+перевірити\s+нема",
        # meta-framing: "this news is about an attack method"
        r"^\s*(?:ця|це)\s+новина\s+про\b",
        r"^\s*йдеться\s+про\s+метод\b",
        r"це\s+(?:новина|матеріал)\s+про\s+метод",
        # powerlessness
        r"(?:діяти\s+)?нічого\s+не\s+можете",
        r"не\s+можете\s+нічого\s+(?:зробити|вдіяти|перевірити)",
        r"це\s+на\s+боці\s+(?:оператора|вендора|провайдера|постачальника|розробника)",
        # A "check" whose entire content is what the SOURCE withheld. Kept
        # separate from _ABSENCE_FACT_UA (which guards quick_facts): under a
        # heading that promises the reader a test, a gap in our sourcing
        # answers nothing. "Amgen не називала кількість постраждалих, тож
        # остаточного списку поки немає" is a fact about the article.
        r"(?:деталей|деталі|версій|індикатор\w*|списку|переліку|конкретики"
        r"|подробиць)[^.]{0,45}\bнема[єе]\b",
        r"\bне\s+(?:назвал\w+|назива\w+|навод\w+|розкрив\w*|уточнив\w*"
        r"|оприлюднил\w*)\b[^.]{0,70}\b(?:нема[єе]|поки)\b",
        # A check whose result is stated up front, so running it is pointless.
        r"нічого\s+(?:встановлювати|завантажувати|шукати|вводити)\s+не\s+"
        r"(?:треба|потрібно)",
    )
)

_NULL_CHECK_EN: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bno\s+(?:technical\s+|practical\s+|direct\s+)?(?:self-)?check\b",
        r"\bthere\s+is\s+no\s+way\s+to\s+check\b",
        r"\bnothing\s+(?:for\s+you\s+)?to\s+check\b",
        r"\bcannot\s+be\s+checked\b",
        r"^\s*this\s+(?:news|item|story)\s+is\s+about\b",
        r"\bnothing\s+you\s+can\s+(?:do|check)\b",
        r"\bhandled\s+(?:entirely\s+)?(?:by|on)\s+(?:your\s+)?(?:carrier|operator|provider|vendor)'?s?\s+side\b",
    )
)

# ===========================================================================
# Absence-as-fact — for `quick_facts`.
# ===========================================================================

_ABSENCE_FACT_UA: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bне\s+(?:назван|оприлюднен|вказан|розкрит|уточнен|наведен|повідомлен|опублікован)",
        r"\bнема[єе]\s+(?:даних|деталей|інформації|подробиць)",
        r"\bневідом(?:о|і|а)\b",
        r"\bджерело\s+не\s+",
        r"\bстаття\s+не\s+",
        r"\bпублікація\s+не\s+",
        # Bibliographic subject + bare absence. The subject must be a NAMING
        # artifact — never a world-state. That distinction is what keeps
        # "Даних про експлуатацію в атаках немає" (exploitation status) and
        # "Патч відсутній на момент атак" (fix status) alive while removing
        # "IOC та CVE відсутні" and "Технічних деталей і IOC немає".
        r"\b(?:CVE|IOC|індикатор\w*|деталі|деталей|подробиц\w+|атрибуці\w+"
        r"|перелік|переліку|список|списку|специфікаці\w+)\b"
        r"[^.]{0,45}\b(?:нема[єе]|відсутн\w+)\b",
        # Finite past tense of not-saying: the stem list above only covers
        # participles, so "Компанія не назвала кількість постраждалих" and
        # "Кількість постраждалих Amgen не назвала" both slipped through.
        r"\bне\s+назвал\w+\b",
        r"\bне\s+деталізован\w*\b",
        r"\bатрибуці\w+[^.]{0,40}\bне\s+(?:назван|оголошен|встановлен|розкрит)",
    )
)

_ABSENCE_FACT_EN: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bnot\s+(?:named|disclosed|published|specified|detailed|released|stated)\b",
        r"\bno\s+(?:details?|information|specifics?)\s+(?:were\s+|was\s+)?(?:given|provided|available)\b",
        r"\b(?:the\s+)?(?:source|article|report)\s+(?:does\s+not|did\s+not|doesn'?t|didn'?t)\b",
        r"\bunknown\b",
        r"\bunclear\b",
    )
)

# An absence that a defender acts on is intelligence, not padding. These
# override the absence patterns above: "no public PoC" and "patch not yet
# released" both change how urgently someone patches, so they stay.
_DECISION_RELEVANT_ABSENCE: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bPoC\b",
        r"proof[- ]of[- ]concept",
        r"експлойт",
        r"\bexploit",
        r"патч",
        r"\bpatch\b",
        r"виправлення",
        r"\bfix\b",
        r"оновлення",
        # "No CVE assigned yet" says the flaw is too fresh to be tracked,
        # which changes how a defender searches for it. "The report did not
        # name a CVE" is just padding, so the bare token is NOT exempt.
        r"CVE[^.]{0,25}(?:ще\s+не|не)\s+присвоєн",
        r"\bno\s+CVE\s+(?:has\s+been\s+)?assigned\b",
        r"\bCVE\s+pending\b",
        r"сканува",
        r"\bscanning\b",
        r"експлуат",
        r"exploitation",
        r"атак(?:и|ах|ується)\s+не\s+(?:зафіксован|спостеріга)",
        r"\bin\s+the\s+wild\b",
        # "The data has not been published yet, only threatened" tells a
        # worried reader the harm has not landed. That is the single most
        # decision-relevant thing a breach post can say, so it outranks the
        # absence patterns even though it is grammatically an absence.
        r"(?:дані|витік|витоку|інформаці\w*)\s+ще\s+не\b",
        r"ще\s+не\s+(?:оприлюднен|опублікован|злит|викладен)\w*",
        r"\bnot\s+yet\s+(?:leaked|published|released|posted)\b",
        # World-state absences that the bibliographic patterns below would
        # otherwise reach. "CVE відсутній, це не вразливість" is a verdict on
        # the item, not a gap in our sourcing; "Відсутня автентифікація
        # критичної функції" (CWE-306) is the vulnerability itself.
        r"це\s+не\s+вразливість",
        r"\bне\s+(?:зафіксован|виявлен|підтвердж|спостеріга|заявлен)",
        r"^\s*відсутн",
    )
)

# ===========================================================================
# Weak severity rationales — for `severity_reason`.
#
# The field's job is to name the factor that decided the rating. These match
# rationales that instead cite our sourcing, or the reader's lack of a task.
# ===========================================================================

_WEAK_SEVERITY_UA: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        # Any verb of not-saying with OUR SOURCING as the subject. The verb
        # list used to be enumerated and the model simply reached for one
        # that wasn't on it — "наслідки для конкретних жертв джерело не
        # описує" survived a full re-render because "описує" was missing.
        # The subject is what makes this a defect, not the verb, so match on
        # the subject and let the verb be anything.
        r"(?:джерело|стаття|публікація|допис|матеріал|замітка)\s+не\s+\w+",
        # Same thing with the subject trailing, which Ukrainian allows
        # freely: "деталей про жертв джерело не наводить".
        r"\bне\s+\w+(?:є|ють|ла|ло|ли|ить|ать)\s+(?:джерело|стаття|публікація)\b",
        r"деталей\s+[^.]{0,40}не\s+(?:наводить|подано|вказано|розкрито)",
        r"(?:прямої\s+)?ді[йї]\s+не\s+потрібно",
        r"(?:звичайному\s+)?користувачеві\s+[^.]{0,30}не\s+потрібно",
        r"нічого\s+робити\s+не\s+(?:треба|потрібно)",
        r"бракує\s+(?:деталей|даних|подробиць)",
    )
)

_WEAK_SEVERITY_EN: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\b(?:the\s+)?(?:source|article|report)\s+(?:does\s+not|did\s+not|doesn'?t|didn'?t)\b",
        r"\bno\s+(?:direct\s+)?action\s+(?:is\s+)?(?:needed|required)\s+for\b",
        r"\bordinary\s+users?\s+(?:do\s+not|don'?t)\s+need\b",
        r"\blacks?\s+(?:detail|specifics)\b",
        # Circular: "Critical due to the severity of the vulnerability."
        r"\bdue\s+to\s+(?:the\s+)?(?:severity|seriousness|critical(?:ity)?)\b",
    )
)

# `severity_reason` opens by restating the level in all 16 of the cached
# posts that carry it, and the UI prints the level directly above the
# sentence ("Чому рівень «Середній»: Середній рівень, бо…"). Worse, 3 of the
# 16 name a DIFFERENT level than `threat_level` — e0cbfbb17f2a64cb is rated
# Low and its sentence opens "Середній рівень, бо…". Stripping the opener
# removes the repetition and the contradiction in one pass, and — unlike
# blanking the field — keeps the otherwise-good explanations.
_LEVEL_PREFIX = re.compile(
    r"^\s*(?:критичн\w*|висок\w*|середн\w*|низьк\w*|critical|high|medium|low)"
    r"(?:\s+(?:рівень|ризик|severity|risk))?"
    r"(?:\s+(?:для\s+більшості\s+читачів|for\s+most\s+readers))?"
    r"\s*[,:—-]?\s*(?:бо|тому\s+що|через\s+те[,]?\s*що|because|since)\s+",
    re.IGNORECASE,
)

# The reader-has-no-task clause in its trailing form. `_WEAK_SEVERITY_UA`
# blanks a rationale that is ONLY this; here the clause is a tail on an
# otherwise-real explanation ("…, а виправляти має оператор, не ви"), so we
# amputate rather than discard.
_TRAILING_NO_TASK = re.compile(
    r"\s*[,;]\s*(?:а|і|та)\s+[^,;.]{0,60}?"
    r"(?:виправ\w+\s+(?:має|повинен|мусить)|це\s+на\s+боці|ставить)\s+"
    r"(?:оператор|вендор|провайдер|постачальник|розробник)\w*"
    r"(?:\s*,\s*не\s+ви)?(?=[.\s]*$)",
    re.IGNORECASE,
)


def normalize_severity_reason(text: str) -> str:
    """Strip the level restatement the UI already prints, and any trailing
    reader-has-no-task clause. Returns "" only for empty input."""
    stripped = " ".join(text.split())
    if not stripped:
        return ""
    stripped = _TRAILING_NO_TASK.sub("", stripped).strip()
    match = _LEVEL_PREFIX.match(stripped)
    if match is not None:
        stripped = stripped[match.end():].strip()
    if not stripped:
        return ""
    if not stripped.endswith((".", "!", "?")):
        stripped += "."
    return stripped[0].upper() + stripped[1:]


def _matches_any(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(p.search(text) for p in patterns)


def _patterns(
    language: str,
    ua: tuple[re.Pattern[str], ...],
    en: tuple[re.Pattern[str], ...],
) -> tuple[re.Pattern[str], ...]:
    """Return the pattern set for `language`, plus the other language's set.

    Both are checked regardless of locale. A UA render can carry an English
    sentence that leaked through the language gate, and the reverse happens
    too; neither should get a free pass on content hygiene.
    """
    return (ua + en) if language == "ua" else (en + ua)


def is_null_action(text: str, language: str = "en") -> bool:
    """True when a `what_to_do` bullet tells the reader to do nothing."""
    stripped = text.strip()
    if not stripped:
        return False
    return _matches_any(stripped, _patterns(language, _NULL_ACTION_UA, _NULL_ACTION_EN))


def is_null_check(text: str, language: str = "en") -> bool:
    """True when an `am_i_affected` bullet offers no test to run.

    An exclusion that names something the reader can recall or look at is
    NOT a null check — see the module docstring.
    """
    stripped = text.strip()
    if not stripped:
        return False
    return _matches_any(stripped, _patterns(language, _NULL_CHECK_UA, _NULL_CHECK_EN))


def is_absence_fact(text: str, language: str = "en") -> bool:
    """True when a `quick_facts` entry states only what is unknown.

    Returns False for absences that change a defender's decision (no public
    PoC, no patch yet, no exploitation observed).
    """
    stripped = text.strip()
    if not stripped:
        return False
    if _matches_any(stripped, _DECISION_RELEVANT_ABSENCE):
        return False
    return _matches_any(stripped, _patterns(language, _ABSENCE_FACT_UA, _ABSENCE_FACT_EN))


def is_weak_severity_reason(text: str, language: str = "en") -> bool:
    """True when a severity rationale explains the rating by something
    other than the threat itself."""
    stripped = text.strip()
    if not stripped:
        return False
    return _matches_any(stripped, _patterns(language, _WEAK_SEVERITY_UA, _WEAK_SEVERITY_EN))


def _clean_list(
    values: Any,
    language: str,
    predicate: Any,
) -> list[str]:
    """Drop empty and predicate-matching entries, preserving order."""
    out: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if not text or predicate(text, language):
            continue
        out.append(text)
    return out


def clean_localized_content(
    content: Mapping[str, Any], language: str,
) -> dict[str, Any]:
    """Return `content` with null bullets, absence-facts and weak severity
    rationales removed.

    Pure: the input mapping is not modified. Every other key passes through
    untouched, so this stays safe to call on a payload whose shape has since
    grown new fields.
    """
    cleaned: dict[str, Any] = dict(content)

    cleaned["am_i_affected"] = _clean_list(
        content.get("am_i_affected"), language, is_null_check,
    )
    cleaned["what_to_do"] = _clean_list(
        content.get("what_to_do"), language, is_null_action,
    )
    cleaned["what_not_to_do"] = _clean_list(
        content.get("what_not_to_do"), language, is_null_action,
    )
    # Same speech act as what_to_do — the heading promises a step. Nothing in
    # the current cache trips this; it is here so the field cannot become the
    # next place the padding lands.
    cleaned["if_already_affected"] = _clean_list(
        content.get("if_already_affected"), language, is_null_action,
    )
    cleaned["quick_facts"] = _clean_list(
        content.get("quick_facts"), language, is_absence_fact,
    )

    severity = str(content.get("severity_reason") or "").strip()
    if severity and is_weak_severity_reason(severity, language):
        # Blank rather than keep: the frontend and the Telegram renderer
        # both omit the block when it is empty, and no explanation beats a
        # misleading one.
        cleaned["severity_reason"] = ""
    else:
        cleaned["severity_reason"] = normalize_severity_reason(severity)

    # --- Ukrainian calque repair -----------------------------------------
    # The overwhelming majority of cached UA posts were written from an
    # English source article, and the generation-time guard
    # (uk_glossary.GLOSSARY) only ever policed russisms — nothing caught
    # "непропатчені сервери" or "міжсітьовий екран". Runs LAST so it also
    # reaches `severity_reason`, which the branch above rewrites from the
    # original mapping. Substitution, not deletion: the table is restricted
    # to swaps that keep gender and declension, so agreement cannot break.
    if language == "ua":
        for field in (
            "title", "plain_summary", "short_summary", "why_it_matters",
            "severity_reason", "detail_body",
            "am_i_affected", "what_to_do", "what_not_to_do",
            "if_already_affected", "quick_facts", "affected_users",
        ):
            if field in cleaned:
                cleaned[field] = normalize_ukrainian_calque_fields(cleaned[field])

    return cleaned


__all__ = [
    "clean_localized_content",
    "is_absence_fact",
    "is_null_action",
    "is_null_check",
    "is_weak_severity_reason",
    "normalize_severity_reason",
]
