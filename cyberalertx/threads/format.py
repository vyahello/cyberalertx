"""Threads-native post text, built from the edition's own fields.

Not the Telegram message: no HTML, no emoji severity marker, no headed action
block, no hashtag row. A Threads post reads as a short standalone note:

    <the edition's headline>

    <plain-language explanation>
    <the specific technical fact, when it adds a name, number or identifier>

    <why it matters>                       (when there is room)
    What to do: <first action>             (when the story has one)

    Source: <outlet>                       (always; the attribution)
    <link to the CyberAlertX article>

Every sentence comes from the edition the editorial pipeline already wrote
and validated in that language — UA posts are built from the UA edition, not
translated from the EN post. Nothing is invented: no urgency words, no
recommendations the edition does not contain.

Limits (official docs, Nov 2026): 500 characters, emojis counted as their
UTF-8 byte length; at most 5 links; one topic tag per post (sent as the
`topic_tag` parameter, not in the text). When the text is too long, whole
blocks are dropped in a fixed order — why it matters first, then the
technical fact or the action (the fact is kept longer when it carries a CVE
id, version or count); only then is the explanation shortened, at a sentence or word
boundary, so URLs and identifiers like CVE-2026-1234 are never cut. Headline,
source line and link are always kept.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..publish.format import _OUTLET_TOKENS, _actions, _is_claim, _is_near_duplicate

TEXT_LIMIT = 500
#: Editorial target: optional blocks are dropped above this; 500 stays the hard limit.
TEXT_TARGET = 450
LINK_LIMIT = 5
_URL_RE = re.compile(r"https?://\S+")
_TAG_RE = re.compile(r"<[^>]+>")

_LEAD = {
    "en": re.compile(r"^(?:[A-Z][\w.&'-]*\s+){1,3}(?:reports?|reported|says|said|warns|warned|writes)"
                     r"(?:\s+that)?[:,]?\s+"),
    "ua": re.compile(r"^(?:\S+\s+){1,3}(?:повідомля\w+|пише|пишуть|зазнача\w+|попереджа\w+)"
                     r"(?:,?\s+що|\s+про)?[:,]?\s+", re.IGNORECASE),
}
_HARD_ID = re.compile(r"\bCVE-\d{4}-\d{4,}\b|\b\d+(?:[.,]\d+)*\b")
_WORD = re.compile(r"[\w][\w.&'-]*")

_SOURCE_LABEL = {"en": "Source", "ua": "Джерело"}
_ACTION_LABEL = {"en": "What to do:", "ua": "Що зробити:"}
#: One topic tag per post (1–50 chars, no "." or "&").
TOPIC_TAG = {"en": "Cybersecurity", "ua": "Кібербезпека"}
#: Evidence qualifiers, never dropped: a claim or a suspicion is not a fact.
_CLAIM_LINE = {"en": "Unconfirmed: this is the attackers' own claim.",
               "ua": "Не підтверджено: це заява самих зловмисників."}
_SUSPECTED_LINE = {"en": "Exploitation is suspected, not confirmed.",
                   "ua": "Атаки підозрюють, але не підтвердили."}


def _emoji(ch: str) -> bool:
    o = ord(ch)
    return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or o in (0xFE0F, 0x200D)


def threads_length(text: str) -> int:
    """Characters as Threads counts them: emojis by UTF-8 byte length."""
    return sum(len(c.encode("utf-8")) if _emoji(c) else 1 for c in text)


def _strip_lead(text: str, locale: str) -> str:
    """Drop a leading "<Outlet> reports (that)" clause; the article page attributes."""
    m = _LEAD.get(locale, _LEAD["en"]).match(text)
    if not m or len(text) - m.end() < 40:
        return text
    rest = text[m.end():]
    return rest[0].upper() + rest[1:]


def _specifics(text: str) -> set[str]:
    """Names, acronyms, numbers and identifiers — not ordinary words, not outlets.

    A capitalised word counts unless it starts a sentence; anything with a
    digit counts. Works for UA too: Latin product names and Cyrillic proper
    nouns are capitalised mid-sentence."""
    out: set[str] = set()
    start = True
    for m in _WORD.finditer(text):
        w = m.group(0).rstrip(".")
        sentence_start = start
        start = m.group(0).endswith(".")
        if w.lower() in _OUTLET_TOKENS:
            continue
        if any(ch.isdigit() for ch in w) or (w[:1].isupper() and not sentence_start) or (len(w) > 1 and w.isupper()):
            out.add(w.lower())
    return out


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", str(value or ""))).strip()


def _shorten(text: str, budget: int) -> str:
    """Whole sentences if possible, else whole words, + "…"; never mid-token."""
    if threads_length(text) <= budget:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for s in sentences:
        candidate = f"{out} {s}".strip()
        if threads_length(candidate) > budget:
            break
        out = candidate
    if out:
        return out
    words, out = text.split(), ""
    for w in words:
        candidate = f"{out} {w}".strip()
        if threads_length(candidate + "…") > budget:
            break
        out = candidate
    return (out.rstrip(",;:—–- ") + "…") if out else ""


@dataclass
class ThreadsPost:
    text: str
    topic_tag: str
    dropped: list[str]


class ThreadsContentError(ValueError):
    pass


def render_post(payload: dict[str, Any], *, locale: str, url: str) -> ThreadsPost:
    c = (payload.get("translations") or {}).get(locale) or {}
    title = _clean(c.get("title"))
    if not title:
        raise ThreadsContentError(f"no {locale} headline")
    if not url.startswith("https://"):
        raise ThreadsContentError("article URL must be https")
    plain = _clean(c.get("plain_summary"))
    short = _clean(c.get("short_summary"))
    explain = plain or short
    # The specific fact earns its place only with a name, number or identifier
    # the headline and explanation lack — an outlet name ("BleepingComputer
    # reports") does not count; the article page carries the attribution.
    fact = _strip_lead(short, locale) if plain and short else ""
    if fact and (not (_specifics(fact) - _specifics(f"{title}. {plain}"))
                 or _is_near_duplicate(fact, [plain, title])):
        fact = ""
    why = _clean(c.get("why_it_matters"))
    if why and _is_near_duplicate(why, [explain, fact, title]):
        why = ""
    # Only when the story justifies an action, and never off-topic advice
    # (same rules as the Telegram post).
    actions = [_clean(a) for a in _actions(payload, c)]
    action = f"{_ACTION_LABEL.get(locale, _ACTION_LABEL['en'])} {actions[0]}" if actions else ""
    qualifier = ""
    if _is_claim(c):
        qualifier = _CLAIM_LINE.get(locale, _CLAIM_LINE["en"])
    elif (payload.get("evidence") or {}).get("exploitation") == "suspected":
        qualifier = _SUSPECTED_LINE.get(locale, _SUSPECTED_LINE["en"])

    # Attribution is never dropped: a standalone post must say whose reporting
    # it relays (the outlet name was stripped from the fact sentence above).
    outlet = _clean(payload.get("source"))
    source_line = f"{_SOURCE_LABEL.get(locale, _SOURCE_LABEL['en'])}: {outlet}" if outlet else ""
    blocks: dict[str, str] = {"explain": explain, "fact": fact, "why": why, "action": action}
    dropped: list[str] = []

    def assemble() -> str:
        body = " ".join(x for x in (blocks["explain"], blocks["fact"]) if x)
        parts = [title, body, qualifier, blocks["why"], blocks["action"], source_line, url]
        return "\n\n".join(p for p in parts if p)

    def links(text: str) -> int:
        return len(set(_URL_RE.findall(text)))

    # A fact carrying a hard identifier (CVE, version, count) outranks the
    # action; otherwise the reader is better served by what to do.
    order = ("why", "action", "fact") if fact and _HARD_ID.search(fact) else ("why", "fact", "action")
    for name in order:
        text = assemble()
        if threads_length(text) <= TEXT_TARGET and links(text) <= LINK_LIMIT:
            break
        if blocks[name]:
            blocks[name] = ""
            dropped.append(name)
    text = assemble()
    if threads_length(text) > TEXT_LIMIT and blocks["explain"]:
        fixed = threads_length("\n\n".join([title, "", *([qualifier] if qualifier else []),
                                              *([source_line] if source_line else []), url]))
        blocks["explain"] = _shorten(blocks["explain"], TEXT_LIMIT - fixed)
        dropped.append("explain (shortened)" if blocks["explain"] else "explain")
        text = assemble()
    if threads_length(text) > TEXT_LIMIT:
        raise ThreadsContentError("headline and link alone exceed the Threads limit")
    if links(text) > LINK_LIMIT:
        raise ThreadsContentError("more than 5 links")
    return ThreadsPost(text=text, topic_tag=TOPIC_TAG.get(locale, TOPIC_TAG["en"]), dropped=dropped)


__all__ = ["LINK_LIMIT", "TEXT_LIMIT", "TEXT_TARGET", "TOPIC_TAG", "ThreadsContentError", "ThreadsPost", "render_post",
           "threads_length"]
