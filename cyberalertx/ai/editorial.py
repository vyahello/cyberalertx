"""Editorial refinement pass — strips AI fluff and operationalizes copy.

Where this runs in the pipeline:

    AI provider  →  UA glossary cleanup  →  REFINE (this)  →  VALIDATE  →  ship

What it does:

  * Sentence-by-sentence sweep of `short_summary`, `why_it_matters`, and
    `detail_body` against AI_FLUFF_PATTERNS. Any sentence containing a
    fluff phrase is dropped. The remaining sentences re-join with spaces.

  * Item-by-item sweep of `what_to_do` and `what_not_to_do` against
    GENERIC_ADVICE_PATTERNS. Generic "improve your security posture",
    "stay vigilant", "review your security practices" entries are removed
    — they offer the reader no operational guidance.

  * Paragraph-level dedup on `detail_body`: paragraphs that overlap
    heavily with `title`, `short_summary`, or `why_it_matters` are
    dropped. Each surviving paragraph should bring new information.

What it does NOT do:

  * Rewriting. We delete; we don't paraphrase. If too much gets stripped,
    `validate_journalist_response` catches the now-empty field and falls
    back to rule_based — which by construction has no fluff.

  * Locale fall-through. UA patterns only apply to UA renders; same for
    EN. The validator's russism gate stays orthogonal.

Why a separate module:

  * The phrase lists are data, not logic — analysts can extend them
    without re-reading the orchestrator.
  * The function is a pure transform on `ThreatPostResponse` — easy to
    unit-test, easy to dry-run in isolation, easy to disable for
    debugging by skipping the call site in `generator.py`.
"""
from __future__ import annotations

import re
from typing import Iterable

from .models import ThreatPostResponse


# =========================================================================
# Fluff sentence patterns. Match WITHIN a sentence; the containing
# sentence gets dropped wholesale (we don't try to surgically remove a
# fluff phrase mid-sentence — too easy to leave a grammatically broken
# fragment behind).
# =========================================================================

AI_FLUFF_PATTERNS_EN: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bstay\s+vigilant\b",
        r"\bremain\s+vigilant\b",
        r"\bremain\s+cautious\b",
        r"\bremain\s+aware\b",
        r"\bin\s+today'?s\s+(?:digital|evolving|complex|connected)\s+(?:landscape|world|environment|age)\b",
        r"\bever[- ]evolving\s+(?:threat\s+)?landscape\b",
        r"\bcybersecurity\s+is\s+(?:more\s+)?important(?:\s+than\s+ever)?\b",
        r"\bhighlights?\s+the\s+(?:importance|need|critical(?:ity|\s+nature))\b",
        r"\bunderscores?\s+the\s+(?:importance|need)\b",
        r"\bproactive\s+(?:steps?|measures?|approach)\s+to\b",
        r"\bserves?\s+as\s+a\s+reminder\b",
        r"\b(?:good|strong|proper)\s+cyber\s+hygiene\b",
        r"\brobust\s+security\s+posture\b",
        r"\bessential\s+to\s+(?:maintain|protect|safeguard)\b",
        r"\bin\s+the\s+current\s+threat\s+environment\b",
        r"\bbe\s+(?:more\s+)?cautious\s+(?:of|about|when)\b",
        r"\bthis\s+(?:incident\s+)?(?:emphasizes|reinforces|reminds)\b",
        # Significance inflation — "this is a testament/pivotal/watershed
        # moment in [X]". Brief format never needs these; they signal the
        # model is editorializing instead of reporting.
        r"\btestament\s+to\s+",
        r"\bpivotal\s+moment\b",
        r"\bwatershed\s+moment\b",
        r"\bindelible\s+mark\b",
        r"\bsea\s+change\b",
        r"\bmark(?:s|ed)?\s+a\s+(?:significant|pivotal|major)\s+(?:shift|moment|turning)\b",
        # Persuasive authority tropes — sentence openers that promise depth
        # but never deliver any. A brief reports; it doesn't pontificate.
        r"\bat\s+its\s+core,?\s",
        r"\bthe\s+real\s+question\s+is\b",
        r"\bthe\s+heart\s+of\s+the\s+matter\b",
        r"\bwhat\s+really\s+matters\s+is\b",
        # Generic positive conclusions — defaultsy hopium endings that
        # show up when the model has nothing concrete left to say.
        r"\bthe\s+future\s+looks\s+bright\b",
        r"\bexciting\s+times\s+(?:lie\s+)?ahead\b",
        r"\bstep\s+in\s+the\s+right\s+direction\b",
        r"\bonly\s+time\s+will\s+tell\b",
        # Knowledge-cutoff disclaimers — leak when the model is unsure
        # about facts. We'd rather drop the sentence than ship the hedge.
        r"\bas\s+of\s+my\s+(?:last\s+)?(?:training|knowledge|update)\b",
        r"\bbased\s+on\s+(?:the\s+)?available\s+information\b",
        r"\bwhile\s+specific\s+details\s+are\s+limited\b",
        # Chatbot artifacts — leak when the model thinks it's chatting,
        # not writing copy. Almost never legitimate inside a threat brief.
        r"\bI\s+hope\s+this\s+helps\b",
        r"\b(?:certainly|of\s+course)!",
        r"\bgreat\s+question\b",
        r"\blet\s+me\s+know\s+if\b",
        r"\bwithout\s+further\s+ado\b",
    )
)

AI_FLUFF_PATTERNS_UA: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"важливо\s+(?:залишатися|бути|зберігати)\s+пильн",
        r"у\s+сучасному\s+(?:цифровому|складному|стрімкому)\s+(?:світі|просторі|середовищі)",
        r"у\s+сучасному\s+ландшафті\s+загроз",
        r"важливіст(?:ь|ю)\s+кібербезпек",
        r"користувачам\s+(?:варто|необхідно|слід|потрібно)\s+бути\s+(?:уважн|обережн|пильн)",
        r"необхідно\s+(?:зберігати|підтримувати|зміцнювати)\s+пильність",
        r"підкреслює\s+(?:важливість|необхідність|критичність)",
        r"наголошує\s+на\s+важливост",
        r"кіберг(?:і|и)гієн",
        r"служить\s+нагадуванням",
        r"посилює\s+необхідність",
        r"(?:гарн|надійн)а\s+позиція\s+(?:з\s+)?безпек",
        # Significance inflation
        r"(?:знаковий|поворотний|переломний)\s+момент",
        r"віхов(?:ий|а|е)\s+(?:момент|подія)",
        r"справжн(?:ій|я)\s+(?:прорив|злам)",
        # Persuasive authority tropes
        r"по\s+суті,",
        r"справжн(?:є|е)\s+питання",
        r"у\s+самому\s+центрі\s+питання",
        # Generic positive conclusions
        r"майбутнє\s+виглядає\s+(?:яскрав|обнадійлив)",
        r"крок\s+у\s+правильному\s+напрямку",
        r"час\s+покаже",
        # Cutoff disclaimers (mostly translates from EN model output)
        r"станом\s+на\s+(?:моє\s+)?останнє\s+(?:оновлення|навчання)",
        r"на\s+основі\s+доступної\s+інформації",
        # Chatbot artifacts
        r"сподіваю(?:сь|ся),?\s+це\s+допоможе",
        r"звичайно!",
        r"чудове\s+питання",
        r"без\s+зайвих\s+слів",
    )
)


# =========================================================================
# Generic-advice patterns for action items. An entry matching ANY of these
# is dropped from what_to_do / what_not_to_do because it tells the reader
# to "be careful" instead of telling them what to actually DO.
# =========================================================================

GENERIC_ADVICE_PATTERNS_EN: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bimprove\s+(?:your\s+)?security\s+posture\b",
        r"\b(?:maintain|practice|ensure)\s+(?:good\s+)?(?:cyber\s+)?hygiene\b",
        r"\bstay\s+safe\s+online\b",
        r"\bstay\s+vigilant\b",
        r"\bremain\s+(?:vigilant|cautious|aware)\b",
        r"\bbe\s+(?:more\s+)?cautious\b",
        r"\bconsider\s+implementing\b",
        r"\bevaluate\s+your\s+security\b",
        r"\breview\s+your\s+security\s+practices?\b",
        r"\bexercise\s+caution\b",
        r"\btake\s+proactive\s+steps?\b",
        r"\bstrengthen\s+(?:your\s+)?(?:overall\s+)?security\s+posture\b",
        r"\bensure\s+(?:strong\s+)?security\s+measures\b",
        r"\bbe\s+aware\s+of\s+phishing\s+attempts\b",  # captain obvious
    )
)

GENERIC_ADVICE_PATTERNS_UA: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"будьте\s+(?:обережн|пильн|уважн)",
        r"залишайтеся\s+(?:пильн|обережн|уважн)",
        r"дотримуйтеся\s+(?:правил\s+)?кіберг(?:і|и)гієн",
        r"перегляньте\s+практики\s+безпек",
        r"посил(?:ьте|юйте)\s+(?:свій\s+)?захист",
        r"будьте\s+уваж(?:ні|ним)\s+(?:до|щодо|з)\s+фішинг",  # "be aware of phishing"
        r"оцініть\s+стан\s+безпек",
        r"вживайте\s+проактивних\s+заходів",
        r"забезпечте\s+належний\s+рівень\s+безпек",
    )
)


# =========================================================================
# Sentence / paragraph splitting + word overlap helpers.
# =========================================================================

# Word-level tokenizer — preserves Ukrainian + Latin. Used for both
# sentence splits and paragraph similarity.
_WORD_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)

# Cheap stopword sets so paragraph similarity doesn't get inflated by
# common articles / prepositions. Tight lists — we only need to suppress
# the highest-frequency function words.
_STOPWORDS_EN = frozenset({
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "by", "as", "at", "from",
    "that", "this", "it", "its", "their", "they", "with", "into", "after",
    "before", "than", "then", "if", "when", "while", "have", "has", "had",
})
_STOPWORDS_UA = frozenset({
    "і", "й", "та", "у", "в", "на", "з", "із", "за", "до", "від", "по",
    "що", "як", "це", "цей", "ця", "цьому", "така", "такий", "так",
    "не", "ні", "або", "чи", "але", "бо", "тому", "коли", "де", "хто",
    "які", "який", "яка", "якого", "якій", "був", "була", "було", "буде",
})

# Sentence delimiters. We keep these tight — overly-aggressive splitting
# fragments legitimate technical phrases like "ver. 12.4 was released".
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZА-ЯЇІЄҐ])")


def _split_sentences(text: str) -> list[str]:
    """Split on sentence-end punctuation followed by a capital letter."""
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_END_RE.split(text) if s.strip()]


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines."""
    if not text:
        return []
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def _tokens(text: str, stopwords: frozenset[str]) -> set[str]:
    return {
        t.lower()
        for t in _WORD_RE.findall(text)
        if len(t) > 2 and t.lower() not in stopwords
    }


def paragraph_overlap_ratio(a: str, b: str, *, language: str = "en") -> float:
    """Jaccard similarity of meaningful-word tokens between `a` and `b`.

    Stopwords removed so we measure content overlap, not connective-word
    overlap. Public so tests + telemetry can audit boundary cases."""
    stop = _STOPWORDS_UA if language == "ua" else _STOPWORDS_EN
    ta, tb = _tokens(a, stop), _tokens(b, stop)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# =========================================================================
# Core refinement primitives.
# =========================================================================

def strip_fluff_sentences(text: str, language: str) -> str:
    """Drop any sentence that matches an AI fluff pattern. Rejoin the
    rest with single-space separators (we don't preserve original
    inter-sentence whitespace; the reader doesn't see the difference)."""
    if not text:
        return text
    patterns = AI_FLUFF_PATTERNS_UA if language == "ua" else AI_FLUFF_PATTERNS_EN
    sentences = _split_sentences(text)
    kept = [s for s in sentences if not _matches_any(s, patterns)]
    return " ".join(kept)


def strip_generic_actions(items: Iterable[str], language: str) -> list[str]:
    """Drop entries from an action list that match generic-advice patterns.

    Returns a NEW list — never mutates the input. Order preserved among
    kept entries."""
    patterns = (
        GENERIC_ADVICE_PATTERNS_UA if language == "ua"
        else GENERIC_ADVICE_PATTERNS_EN
    )
    return [item for item in items if not _matches_any(item, patterns)]


def dedupe_detail_paragraphs(
    detail_body: str,
    *,
    against: Iterable[str],
    language: str = "en",
    threshold: float = 0.55,
) -> str:
    """Drop paragraphs that overlap heavily with any string in `against`.

    `against` typically holds title + short_summary + why_it_matters. A
    paragraph whose meaningful-word Jaccard with ANY reference exceeds
    `threshold` is dropped — detail_body should bring new information,
    not restate copy the reader already sees on the card.

    Empty result is fine — frontend hides the analysis block when
    detail_body is empty."""
    paragraphs = _split_paragraphs(detail_body)
    if not paragraphs:
        return ""
    against_list = [a for a in against if a]
    kept: list[str] = []
    for para in paragraphs:
        if any(
            paragraph_overlap_ratio(para, ref, language=language) >= threshold
            for ref in against_list
        ):
            continue
        kept.append(para)
    return "\n\n".join(kept)


def _matches_any(text: str, patterns: Iterable[re.Pattern[str]]) -> bool:
    return any(p.search(text) for p in patterns)


def contains_fluff(text: str, language: str) -> str | None:
    """Return the first matched fluff phrase, or None. Used by the
    validator as a defensive check after refinement — anything that
    slipped through the sentence-strip is a hard reject signal."""
    patterns = AI_FLUFF_PATTERNS_UA if language == "ua" else AI_FLUFF_PATTERNS_EN
    for p in patterns:
        m = p.search(text or "")
        if m:
            return m.group(0)
    return None


# =========================================================================
# Public entry point — runs over a full ThreatPostResponse.
# =========================================================================

def refine_response(response: ThreatPostResponse, language: str) -> None:
    """Apply all editorial refinements to `response` in place.

    Order matters:
      1. Strip fluff sentences from prose fields. `detail_body` keeps
         its paragraph structure (we strip per-paragraph then rejoin
         with `\\n\\n`) so step 3 can still see paragraph boundaries.
      2. Drop generic-advice items from action lists.
      3. Dedup detail_body paragraphs against title/summary/why_it_matters
         AFTER fluff-stripping so we don't dedup against fluff that's
         already been removed.

    No exceptions. If the response is structurally minimal (every field
    is fluff), the validator that follows this call catches it and the
    generator falls back to rule_based. This function's only job is
    aggressive copy-editing.
    """
    response.short_summary = strip_fluff_sentences(response.short_summary, language)
    response.why_it_matters = strip_fluff_sentences(response.why_it_matters, language)
    # detail_body: preserve `\n\n` paragraph boundaries through the
    # sentence-level strip so step 3 (dedup) still has paragraphs to
    # iterate over. Without this, fluff-strip would join everything
    # into one ungrouped run and dedup couldn't drop a single bad
    # paragraph without nuking the whole field.
    paragraphs = _split_paragraphs(response.detail_body)
    response.detail_body = "\n\n".join(
        strip_fluff_sentences(p, language) for p in paragraphs
        if strip_fluff_sentences(p, language).strip()
    )
    response.what_to_do = strip_generic_actions(response.what_to_do, language)
    response.what_not_to_do = strip_generic_actions(response.what_not_to_do, language)

    # Drop paragraphs that restate stuff the reader already sees on the card.
    response.detail_body = dedupe_detail_paragraphs(
        response.detail_body,
        against=(response.title, response.short_summary, response.why_it_matters),
        language=language,
    )


__all__ = [
    "AI_FLUFF_PATTERNS_EN",
    "AI_FLUFF_PATTERNS_UA",
    "GENERIC_ADVICE_PATTERNS_EN",
    "GENERIC_ADVICE_PATTERNS_UA",
    "refine_response",
    "strip_fluff_sentences",
    "strip_generic_actions",
    "dedupe_detail_paragraphs",
    "paragraph_overlap_ratio",
    "contains_fluff",
]
