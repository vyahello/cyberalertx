"""Semantic validation for AI-generated ThreatPost responses.

Pydantic (in `ai/models.py`) already catches *structural* problems —
wrong types, missing required fields, integer out of range. This module
catches *quality* problems that pass schema validation but produce a
post no human would publish:

  * empty fields after strip (e.g. title is whitespace, summary is "")
  * the AI repeated the article title inside the summary
  * `what_to_do` / `what_not_to_do` contain duplicates (different items
    that say the same thing)
  * the AI dropped into clichés ("evolving threat landscape", "robust
    posture", "leverages cutting-edge")
  * the threat_level / category labels are outside the canonical enums

When any check fails we raise `ValidationFailure`; the generator catches
and falls back to the rule-based renderer. The validator is intentionally
strict: a malformed AI render is worse than a deterministic rule-based
render, because the latter at least reads coherently.

Why this lives in its own module:
  * easy to unit-test without a live API
  * easy to extend a new bad-pattern detector without touching generator.py
  * the bad-phrase list is data, not control flow — analysts can iterate
    on it without re-reading the orchestrator
"""
from __future__ import annotations

import re
from typing import Hashable, Iterable, TypeVar

from .models import ThreatPostResponse

_H = TypeVar("_H", bound=Hashable)

# Token regex for n-gram extraction. Cyrillic + Latin words, hyphenated
# compounds preserved (so "zero-day" is one token, not two).
_NGRAM_TOKEN_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*", flags=re.UNICODE)

# Editorial transformation threshold. A summary or why_it_matters that shares
# more than this fraction of 5-gram shingles with the source body is treated
# as a near-copy — most likely the AI paraphrased rather than synthesized,
# and we'd rather ship the deterministic editorial brief instead.
NEAR_COPY_SHINGLE_RATIO: float = 0.25
NEAR_COPY_SHINGLE_N: int = 5


class ValidationFailure(ValueError):
    """Raised when an AI response fails post-parse semantic validation.

    The message names the specific check that failed so the generator's
    log line is grep-able.
    """


# Canonical enums from the product spec. Keep in sync with the docstring
# in `models.ThreatPostResponse`.
_THREAT_LEVELS = frozenset({"Critical", "High", "Medium", "Low"})

# Phrases that mark "AI sludge" — the kind of generic copy the journalist
# system prompt is engineered to prevent. Substring match, case-insensitive.
# Trip ANY of these and the response is rejected — better to fall back to
# the deterministic copy than ship one of these to a reader.
_AI_CLICHES_EN = (
    # Generic threat-landscape sludge.
    "evolving threat landscape",
    "evolving cyber threat",
    "threat landscape",
    "in today's digital",
    "in today's evolving",
    "robust security posture",
    "robust cybersecurity posture",
    "leverages cutting-edge",
    "best-in-class",
    "navigate the complex",
    # Marketing-coloured threat prose. These mark the model drifting
    # into AI-news-blog tone — exactly what the CyberAlertX brief is
    # not. Tripping any of these rejects the output; rule_based is
    # the better fallback.
    "malicious actors may leverage",
    "malicious actors can leverage",
    "cybercriminals increasingly",
    "could allow attackers to gain elevated privileges and compromise",
    "this is a classic",
    "that means access to every",
    # Generic security-hygiene filler — what_to_do entries the user
    # has flagged as worthless. If any of these appear anywhere in
    # the output we reject; the brief is supposed to give specific
    # actions, not motivational reminders.
    "stay vigilant",
    "be cautious",
    "maintain good cyber hygiene",
    "maintain cyber hygiene",
    "follow vendor recommendations",
    "follow best practices",
    "review your security posture",
    "implement defense in depth",
    "educate users",
    # Educational / essay-style framing markers — operational briefs
    # don't teach; they brief. If the model drops into textbook mode
    # these phrases are the tell.
    "let's break down",
    "it is important to note",
    "in conclusion",
    "understanding this attack",
    "in summary",
    "furthermore",
    # Chatbot self-references.
    "as an ai",
    "i cannot",
    "i'm sorry",
    "as a language model",
)
_AI_CLICHES_UK = (
    # AI sludge + chatbot disclaimers in Ukrainian.
    "у сучасному ландшафті",
    "сучасний ландшафт загроз",
    "ландшафт загроз",
    "надійна позиція з безпеки",
    "комплексний підхід",
    # Marketing-coloured threat prose in UA.
    "зловмисники все частіше",
    "зловмисники можуть використовувати",
    "класичний сценарій",
    # Generic hygiene filler in UA.
    "будьте пильними",
    "дотримуйтеся кібергігієни",
    "дотримуйтесь кібергігієни",
    "навчайте користувачів",
    "дотримуйтеся рекомендацій вендора",
    "дотримуйтесь рекомендацій вендора",
    # Educational / essay markers in UA.
    "розглянемо, як працює",
    "розглянемо як працює",
    "важливо зазначити",
    "на завершення",
    "більш того",
    "як ші",
    "як штучний інтелект",
    "я не можу",
)
# Russism stems are tracked separately in ai/uk_glossary.py so the same
# vocabulary feeds the glossary normalizer AND the response validator.


def _stripped(value: str | None) -> str:
    return (value or "").strip()


def _normalize_for_dup_check(value: str) -> str:
    """Lowercase + collapse whitespace + strip terminal punctuation.

    Two recommendations that differ only in trailing period or a single
    inserted space are still duplicates as far as the reader is concerned.
    """
    out = re.sub(r"\s+", " ", value).strip().lower()
    return out.rstrip(".!?…")


def _has_duplicates(items: Iterable[str]) -> bool:
    seen: set[str] = set()
    for item in items:
        norm = _normalize_for_dup_check(item)
        if not norm:
            continue
        if norm in seen:
            return True
        seen.add(norm)
    return False


def _contains_any(text_lower: str, phrases: tuple[str, ...]) -> str | None:
    for phrase in phrases:
        if phrase in text_lower:
            return phrase
    return None


# Unicode code-point ranges we allow in Ukrainian output:
#   * basic Latin (ASCII letters, digits, punctuation)
#   * Latin-1 Supplement / Extended (for occasional brand names)
#   * Cyrillic block and Ukrainian-specific letters
#   * General punctuation, currency, math symbols (em-dash, em-arrow, ≥, …)
# Anything outside these is treated as a foreign-script hallucination.
def _is_allowed_in_ua(ch: str) -> bool:
    cp = ord(ch)
    return (
        cp < 0x0080                          # ASCII
        or 0x00A0 <= cp <= 0x024F            # Latin-1 + Extended-A/B
        or 0x0300 <= cp <= 0x036F            # Combining diacritics
        or 0x0400 <= cp <= 0x04FF            # Cyrillic
        or 0x2000 <= cp <= 0x206F            # General Punctuation
        or 0x2070 <= cp <= 0x209F            # Superscripts / subscripts
        or 0x20A0 <= cp <= 0x20CF            # Currency
        or 0x2190 <= cp <= 0x21FF            # Arrows
        or 0x2200 <= cp <= 0x22FF            # Math
        or 0x2500 <= cp <= 0x257F            # Box drawing (occasional in ASCII art)
        or 0x2600 <= cp <= 0x26FF            # Misc symbols
        or 0x2700 <= cp <= 0x27BF            # Dingbats
    )


def _first_foreign_script_char(text: str) -> str | None:
    """Return the first character outside the allowed UA character set,
    or None. Used by the validator to reject AI output with hallucinated
    CJK / Arabic / Hangul characters."""
    for ch in text or "":
        if not _is_allowed_in_ua(ch):
            return ch
    return None


# Minimum share of Cyrillic-vs-Latin letters required for a UA-targeted
# field to be considered "actually written in Ukrainian". Brand-name-
# heavy headlines like "Microsoft закриває уразливість у Windows" sit
# around 60-65% Cyrillic, so 30% is a forgiving threshold that still
# rejects a fully-English headline the AI forgot to translate
# (e.g. "TrickMo Android banking trojan uses TON blockchain").
_TARGET_LANGUAGE_MIN_RATIO: float = 0.30
# Fields shorter than this (in letters) skip the language check —
# acronyms like "CVE-2026-1234 RCE" carry no language signal at all,
# and forcing them to translate would just produce noise.
_TARGET_LANGUAGE_MIN_LETTERS: int = 4


def _letter_counts(text: str) -> tuple[int, int]:
    """Return (cyrillic_letters, latin_letters) in `text`. Counts code
    points by Unicode block; digits / punctuation / symbols are ignored."""
    cyrillic = latin = 0
    for ch in text or "":
        cp = ord(ch)
        if 0x0400 <= cp <= 0x04FF:
            cyrillic += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z") or 0x00C0 <= cp <= 0x024F:
            latin += 1
    return cyrillic, latin


def _wrong_script_for_language(text: str, language: str) -> bool:
    """True iff `text` is clearly in the wrong script for `language`.

    Decides by Cyrillic-vs-Latin letter ratio. We tolerate short / acronym-
    only strings (returns False — no signal). We tolerate brand-name-heavy
    UA headlines (Cyrillic ≥ 30% of letters is enough). We reject a fully-
    English title on a UA-target render — that's the bug we're patching.
    """
    cyrillic, latin = _letter_counts(text)
    total = cyrillic + latin
    if total < _TARGET_LANGUAGE_MIN_LETTERS:
        return False
    if language == "ua":
        return (cyrillic / total) < _TARGET_LANGUAGE_MIN_RATIO
    if language == "en":
        return (latin / total) < _TARGET_LANGUAGE_MIN_RATIO
    return False


def _shingles(text: str, n: int) -> set[tuple[str, ...]]:
    """Word-level n-gram shingle set for similarity comparison.

    Why word-level (not character):
      * Character shingles flag any shared prose ("the", "a") — too noisy.
      * Word 5-grams identify *sequences* of meaning, which is what plagiarism
        actually is.

    Lowercased; punctuation stripped via the token regex.
    """
    tokens = [t.lower() for t in _NGRAM_TOKEN_RE.findall(text)]
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a: set[_H], b: set[_H]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def near_copy_ratio(candidate: str, source: str, n: int = NEAR_COPY_SHINGLE_N) -> float:
    """Jaccard similarity of word n-gram shingles between two strings.

    Public so callers (tests, telemetry, batch-quality reports) can audit
    a specific item without re-running the full validator.
    """
    return _jaccard(_shingles(candidate, n), _shingles(source, n))


def validate_journalist_response(
    response: ThreatPostResponse,
    source_title: str = "",
    source_body: str = "",
    *,
    language: str | None = None,
) -> None:
    """Run all semantic checks on `response`. Raises `ValidationFailure`
    on the FIRST failing check (the message names which one).

    `source_title` and `source_body` are the article's original headline
    and body. We use the title to detect summary-echoes-title; we use the
    body to detect near-copy paraphrasing (anti-plagiarism gate).

    Order of checks: cheap-to-evaluate first so the most-likely failures
    (empty / cliché) fire before the more expensive shingle analysis.
    """
    # --- non-empty primary fields -----------------------------------------
    title = _stripped(response.title)
    if not title:
        raise ValidationFailure("empty title")
    summary = _stripped(response.short_summary)
    if not summary:
        raise ValidationFailure("empty short_summary")
    why = _stripped(response.why_it_matters)
    if not why:
        raise ValidationFailure("empty why_it_matters")

    # --- target-language gate (title + summary) --------------------------
    # The AI sometimes returns a fully-English title on a UA-target render
    # (the JSON parses, the summary is in Ukrainian, but the title slipped
    # through untranslated). The russism / foreign-script gates below don't
    # catch this — Latin is allowed in UA output for brand names. Here we
    # require the title (and the summary, defensively) to be DOMINANTLY in
    # the target script: ≥ 30% Cyrillic for UA, ≥ 30% Latin for EN.
    # Brand-name-heavy headlines still pass; fully-English headlines on a
    # UA render don't.
    if language in ("en", "ua"):
        if _wrong_script_for_language(title, language):
            raise ValidationFailure(
                f"title is not in target language {language!r}: {title[:80]!r}"
            )
        if _wrong_script_for_language(summary, language):
            raise ValidationFailure(
                f"short_summary is not in target language {language!r}"
            )

    # --- enum sanity ------------------------------------------------------
    level = _stripped(response.threat_level)
    if level not in _THREAT_LEVELS:
        raise ValidationFailure(f"hallucinated threat_level: {level!r}")

    # --- non-empty lists --------------------------------------------------
    to_do = [_stripped(s) for s in response.what_to_do if _stripped(s)]
    if not to_do:
        raise ValidationFailure("empty what_to_do list")
    affected = [_stripped(s) for s in response.affected_users if _stripped(s)]
    if not affected:
        raise ValidationFailure("empty affected_users list")

    # --- "title echoed inside summary" ------------------------------------
    # Trivial AI failure mode: short_summary is the title plus 4 filler words.
    # We detect by normalized substring containment in either direction —
    # but only when both strings are long enough that overlap isn't accidental.
    if source_title and len(source_title) >= 30:
        norm_title = _normalize_for_dup_check(source_title)
        norm_summary = _normalize_for_dup_check(summary)
        if norm_title and norm_title in norm_summary and len(norm_summary) <= len(norm_title) + 25:
            raise ValidationFailure("summary echoes title verbatim")

    # --- duplicate recommendations ---------------------------------------
    if _has_duplicates(to_do):
        raise ValidationFailure("duplicate entries in what_to_do")
    avoid = [_stripped(s) for s in response.what_not_to_do if _stripped(s)]
    if _has_duplicates(avoid):
        raise ValidationFailure("duplicate entries in what_not_to_do")

    # --- AI clichés / chatbot disclaimers / Russian grammar --------------
    blob = " ".join([
        title, summary, why,
        " ".join(to_do), " ".join(avoid),
        " ".join(affected),
    ]).lower()

    # We pick the locale-specific cliché list off of `response.language` —
    # but check BOTH lists for either locale, because the AI might leak EN
    # phrasing into a UK render or vice versa.
    cliche = _contains_any(blob, _AI_CLICHES_EN) or _contains_any(blob, _AI_CLICHES_UK)
    if cliche is not None:
        raise ValidationFailure(f"AI cliché detected: {cliche!r}")

    # --- russism gate (UA output only — checks the most common stems) ----
    # When the AI's Ukrainian reads like a machine translation from
    # Russian, we'd rather ship the deterministic glossary-clean rule-
    # based brief than the slop. The stems live in `uk_glossary.py` so
    # they're co-located with the normalization vocabulary.
    if language == "ua":
        from .uk_glossary import has_russism
        offender = has_russism(blob)
        if offender is not None:
            raise ValidationFailure(f"Russism stem in UA output: {offender!r}")

    # --- foreign-script characters (defensive) -------------------------
    # Real failure mode: AI sometimes hallucinates a CJK / Arabic / other
    # non-Latin / non-Cyrillic glyph mid-word ("від假"). The reader sees
    # an obviously-broken Ukrainian word. Reject; fall back to rule_based
    # which never invents characters.
    if language == "ua":
        offender = _first_foreign_script_char(blob)
        if offender is not None:
            raise ValidationFailure(
                f"Foreign-script character in UA output: {offender!r}"
            )

    # --- editorial fluff (defensive) -------------------------------------
    # The refinement pass should have already stripped any sentence
    # containing AI fluff. If something survived — because the AI wrapped
    # the fluff phrase in unusual punctuation, or our sentence splitter
    # didn't isolate it cleanly — we'd rather reject and fall back to
    # rule_based than ship a "stay vigilant in today's evolving threat
    # landscape" briefing.
    if language in ("en", "ua"):
        from .editorial import contains_fluff
        for field_name, field_value in (
            ("short_summary", summary),
            ("why_it_matters", why),
            ("detail_body", response.detail_body or ""),
        ):
            stuck = contains_fluff(field_value, language)
            if stuck is not None:
                raise ValidationFailure(
                    f"editorial fluff persisted in {field_name}: {stuck!r}"
                )

    # --- anti-plagiarism: near-copy of source body -----------------------
    # The journalist layer is supposed to SYNTHESIZE the article into an
    # editorial brief — not paraphrase it sentence-by-sentence. We check
    # both summary and why_it_matters against the source body. If either
    # shares more than NEAR_COPY_SHINGLE_RATIO of its 5-gram shingles
    # with the source, the model rewrote rather than re-thought; reject
    # so the generator falls back to the deterministic editorial brief
    # (which never reads the source body in the first place).
    if source_body:
        for field_name, field_value in (("short_summary", summary),
                                        ("why_it_matters", why)):
            ratio = near_copy_ratio(field_value, source_body)
            if ratio >= NEAR_COPY_SHINGLE_RATIO:
                raise ValidationFailure(
                    f"{field_name} reads as a near-copy of source "
                    f"(shingle overlap {ratio:.0%}, threshold "
                    f"{NEAR_COPY_SHINGLE_RATIO:.0%})"
                )


__all__ = [
    "ValidationFailure",
    "validate_journalist_response",
    "near_copy_ratio",
    "NEAR_COPY_SHINGLE_RATIO",
    "NEAR_COPY_SHINGLE_N",
]
