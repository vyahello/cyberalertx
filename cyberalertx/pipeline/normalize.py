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

import html
import re
import unicodedata
from typing import Iterable, List

from ..models import NewsItem

_WS_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(
    # All C0 / C1 control chars except \t \n \r.
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]"
)

# Article-body pollution: phrases that real-world RSS feeds inject around
# the actual content. We strip these BEFORE the AI journalist sees the
# text — both because they add noise to the rendering and because they
# inflate the near-copy plagiarism score (a 5-gram from "subscribe to
# our newsletter" can be the difference between accept and reject).
#
# Each entry is a regex. Lines, paragraphs, or trailing tails are matched.
# We use MULTILINE so each pattern can anchor to line boundaries when the
# upstream feed preserved them, and DOTALL is intentionally off so a
# pattern can't eat across paragraph breaks unexpectedly.
_JUNK_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Newsletter / subscription prompts.
    re.compile(r"(?im)^\s*subscribe(?:\s+now)?\b[^.\n]*\.?\s*$"),
    re.compile(r"(?im)\bsign\s+up\s+for\s+(?:our|the)\s+newsletter[^.\n]*\.?"),
    re.compile(r"(?im)\bjoin\s+(?:our|the)\s+newsletter[^.\n]*\.?"),
    re.compile(r"(?im)\bsubscribe\s+to\s+(?:our|the)\s+(?:newsletter|feed|rss)[^.\n]*\.?"),
    # Social sharing prompts. Variants: "Share this on FB", "Share on FB",
    # "Share this article on FB Twitter LinkedIn." — consume to end of
    # sentence so the trailing platform list goes with it.
    re.compile(r"(?im)\bshare\s+(?:this(?:\s+article|\s+story)?\s+(?:on|to|via)|on|to)\s+(?:facebook|twitter|x|linkedin|telegram|reddit|whatsapp)\b[^\n.]*"),
    re.compile(r"(?im)\bfollow\s+us\s+on\s+(?:facebook|twitter|x|linkedin|telegram|youtube)\b[^\n.]*"),
    # Read-more / clickbait callouts.
    re.compile(r"(?im)^\s*(?:read|see)\s+(?:more|also|related)\b[^.\n]*\.?\s*$"),
    re.compile(r"(?im)^\s*(?:continue\s+reading|click\s+here\s+to\s+\w+)\b[^.\n]*\.?\s*$"),
    re.compile(r"(?im)\brelated\s+(?:articles|reading|stories)\s*:[^.\n]*"),
    # Sponsorship / advertising labels.
    re.compile(r"(?im)^\s*(?:advertisement|sponsored\s+(?:content|post|by)|promoted\s+content)\b[^.\n]*\.?\s*$"),
    re.compile(r"(?im)\bthis\s+article\s+is\s+sponsored\s+by\b[^.\n]*\.?"),
    re.compile(r"(?im)\b(?:^|\W)ad(?:vertisement)?\s*:\s*[^.\n]*"),
    # Copyright / licensing tails — consume the whole line, not just up
    # to the next period (the copyright line often has multiple sentences:
    # "© 2026 News. All rights reserved.").
    re.compile(r"(?im)©\s*\d{4}[^\n]*"),
    re.compile(r"(?im)^\s*copyright\s+©?\s*\d{4}[^\n]*"),
    re.compile(r"(?im)\ball\s+rights\s+reserved\b[^.\n]*\.?"),
    # Common feed tail metadata.
    re.compile(r"(?im)^\s*tags?\s*:[^.\n]*$"),
    re.compile(r"(?im)^\s*categories?\s*:[^.\n]*$"),
    re.compile(r"(?im)^\s*filed\s+under\s*:[^.\n]*$"),
    re.compile(r"(?im)^\s*posted\s+in\b[^.\n]*\.?\s*$"),
    # Comment / discussion CTAs.
    re.compile(r"(?im)\bleave\s+a\s+comment\b[^.\n]*\.?"),
    re.compile(r"(?im)\bcomments?\s+(?:are\s+)?closed\b[^.\n]*\.?"),
    # "Image source / Photo credit" callouts.
    re.compile(r"(?im)^\s*(?:image|photo)\s+(?:source|credit)\s*:[^.\n]*$"),
    # UA-language pollution (the Ukrainian feeds we use also inject these).
    # The imperative form "Підпишіться" ends in -ься; we accept anything
    # starting with "підпишіт" followed by Cyrillic word chars, then drop
    # the rest of the sentence (the typical "...на наш Telegram-канал" tail).
    # `\w` with the UNICODE flag treats Ukrainian letters as word chars.
    re.compile(r"(?imu)\bпідпишіт\w*[^.\n]*"),
    re.compile(r"(?im)\bчитайте\s+(?:також|ще)\b[^.\n]*\.?"),
    re.compile(r"(?im)\bпов(?:'|ʼ)язан(?:і|их)\s+(?:статті|матеріали)\b[^.\n]*\.?"),
    re.compile(r"(?im)\bпоширити\s+у\s+(?:facebook|telegram|твіттер)[^.\n]*\.?"),
)

# Cap on retained body length. Anything past this is feed pollution
# masquerading as content (long comment dumps, related-articles galleries,
# inline ads). The AI journalist only needs the lead — 3000 chars is
# generous for the kind of cyber news we ingest.
_MAX_BODY_CHARS = 3000

# Unicode block ranges we care about.
_CYRILLIC_RANGE = (0x0400, 0x04FF)
_LATIN_BASIC = (0x0041, 0x007A)

# Letters that exist in Ukrainian but NOT in most other Cyrillic-using
# languages — used to confirm Cyrillic text is Ukrainian.
_UKRAINIAN_ONLY = frozenset("їєґіЇЄҐІ")


def safe_text(value: str) -> str:
    """Make any incoming string safe for downstream text processing.

    Idempotent and total — never raises. A non-string input returns "".

    Pipeline (each step is independent and idempotent):
      1. NFC normalize so "café" composed-vs-decomposed compare equal.
      2. Decode HTML entities (`&lt;` → `<`, `&amp;` → `&`, `&#x27;` → `'`).
         RSS feeds frequently double-escape technical content like
         "Affected versions: &lt;2.9.0" — we want that to render as
         "<2.9.0" in the UI, not as literal "&lt;2.9.0".
      3. Round-trip through utf-8 to strip unpaired surrogates that some
         malformed feeds inject.
      4. Replace control chars (except \\t \\n \\r) with single space.
      5. Collapse runs of whitespace.
    """
    if not isinstance(value, str):
        return ""
    try:
        text = unicodedata.normalize("NFC", value)
    except (TypeError, ValueError):
        text = value
    # Decode HTML entities. `html.unescape` is idempotent on already-decoded
    # text — running it twice doesn't damage real `&` characters.
    text = html.unescape(text)
    text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    text = _CTRL_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def clean_article_body(text: str) -> str:
    """Strip RSS pollution before storage / AI rendering.

    Applies a list of regex sweeps to remove common feed junk: newsletter
    prompts, social-share blocks, "read more" callouts, ad markers,
    copyright tails, comment CTAs. Idempotent — running twice yields the
    same result.

    Why this is its own pass (not folded into safe_text):
      * `safe_text` is shared with `title` and other short strings where
        a "Subscribe!" CTA wouldn't appear; we don't want the regex
        sweep there.
      * Pollution patterns evolve as we add sources — keeping them in
        one labeled list makes the list auditable.
      * Cleaner input meaningfully improves AI rendering quality and
        reduces near-copy false positives in the anti-plagiarism gate.
    """
    if not text:
        return ""
    cleaned = text
    for pattern in _JUNK_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    # Collapse the whitespace introduced by removed phrases.
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    # Hard length cap — long bodies past this are pollution by definition.
    if len(cleaned) > _MAX_BODY_CHARS:
        # Trim at sentence boundary inside the budget when possible.
        cut = cleaned.rfind(". ", 0, _MAX_BODY_CHARS)
        cleaned = cleaned[: cut + 1] if cut > _MAX_BODY_CHARS * 0.75 else cleaned[:_MAX_BODY_CHARS]
    return cleaned


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
        return "ua"
    return "other"


def normalize_item(item: NewsItem) -> NewsItem:
    """In-place enrichment: clean text + populate language fields.

    Pipeline order matters:
      1. `safe_text` on title (whitespace normalization, NFC, controls).
      2. `safe_text` then `clean_article_body` on raw_content — the body
         passes through TWO sweeps because the regex sweep needs already-
         normalized whitespace to anchor reliably.
      3. Detect language AFTER cleanup so newsletter prompts in a third
         language don't poison the detector.

    Idempotent: running twice yields the same result.
    """
    item.title = safe_text(item.title)
    item.raw_content = clean_article_body(safe_text(item.raw_content))
    # Detect on title+content; title alone is often too short to be reliable.
    detected = detect_language(f"{item.title}\n{item.raw_content}")
    item.language = detected
    if item.original_language in ("", "unknown"):
        item.original_language = detected
    return item


def normalize_all(items: Iterable[NewsItem]) -> List[NewsItem]:
    return [normalize_item(i) for i in items]
