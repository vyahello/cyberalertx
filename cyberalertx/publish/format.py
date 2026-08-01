"""Render a published ThreatPost payload into a Telegram HTML message.

We use Telegram's **HTML** parse mode rather than MarkdownV2: HTML needs only
three characters escaped (`&`, `<`, `>`) instead of MarkdownV2's ~18, so it's
far harder to produce a malformed message that Telegram rejects.

Input is the merged dict produced by `_PostService.render()` (see
api/app.py:render) — top-level shared metadata plus a `translations` sub-object
keyed by locale. We pull the requested locale's text content from there.
"""
from __future__ import annotations

import html
import re
from typing import Any

# Bare CVE identifiers (e.g. "CVE-2026-45247") that the AI writes into the
# summary / quick facts are plain text — Telegram doesn't auto-link them. We
# turn each into a link to its canonical NVD page (the URL is deterministic
# from the id, so this needs no lookup against the references array).
_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)

# Severity → leading emoji. Calm, not alarmist (matches the product's
# "alert, not alarmed" design language).
_LEVEL_EMOJI = {
    "Critical": "🔴",
    "High": "🟠",
    "Medium": "🟡",
    "Low": "🟢",
}

# Telegram hard-caps a message at 4096 chars. We aim well below and trim the
# summary if a render is unusually long.
_MAX_SUMMARY_CHARS = 600


def _esc(text: str) -> str:
    """Escape the three characters that are special in Telegram HTML mode."""
    return html.escape(text or "", quote=False)


def _linkify_cves(escaped_text: str) -> str:
    """Wrap CVE identifiers in a link to their NVD detail page.

    Runs on already-escaped text. CVE ids contain only `[A-Z0-9-]`, so they're
    untouched by HTML-escaping and safe to match/wrap here without re-escaping.
    """
    def _repl(m: re.Match[str]) -> str:
        cve = m.group(0).upper()
        return f'<a href="https://nvd.nist.gov/vuln/detail/{cve}">{m.group(0)}</a>'

    return _CVE_RE.sub(_repl, escaped_text)


def _text(raw: str) -> str:
    """Escape then linkify CVEs — the standard treatment for body text."""
    return _linkify_cves(_esc(raw))


def deep_link(base_url: str, locale: str, fingerprint: str) -> str:
    """Public detail-page URL: {base}/{locale}/threat/{fingerprint}."""
    return f"{base_url.rstrip('/')}/{locale}/threat/{fingerprint}"


# Scripts that should never appear in either of our locales. The existing
# language validator compares Cyrillic against Latin counts, so a stray CJK
# or Arabic run scores as neither and slips through — a real cached post
# carries "攻擊穿過автентифікацію" in its quick facts. Nothing we publish is
# ever legitimately in these blocks.
_FOREIGN_SCRIPT_RE = re.compile(
    "["
    "一-鿿"   # CJK unified ideographs
    "぀-ヿ"   # Hiragana + Katakana
    "가-힯"   # Hangul
    "؀-ۿ"   # Arabic
    "֐-׿"   # Hebrew
    "ऀ-ॿ"   # Devanagari
    "]"
)


def quality_problem(payload: dict[str, Any], *, locale: str) -> str | None:
    """Return a reason string if this post shouldn't be published, else None.

    A pre-send gate that runs BEFORE formatting. The render path already drops
    wrong-script *titles* per locale, but not summaries — and a stale cache
    entry can still carry an English body on a UA-target render. We re-check
    both here so a half-translated card never reaches the channel.

    Every field the MESSAGE actually renders is checked, not a sample. That
    distinction caused a real defect: `render_message` leads with
    `plain_summary`, while this gate used to inspect `short_summary` only, so
    a payload with a Ukrainian summary and an English plain-language line
    shipped English text to the Ukrainian channel.
    """
    content = (payload.get("translations") or {}).get(locale)
    if not content:
        return f"no '{locale}' translation"

    title = (content.get("title") or "").strip()
    if not title:
        return "empty title"

    # Local import keeps the ai → publish dependency one-way and off the hot path.
    from ..ai.validation import _wrong_script_for_language

    # Exactly the fields `render_message` puts on screen, in the order it
    # uses them.
    checked: list[tuple[str, str]] = [
        ("title", title),
        ("plain_summary", (content.get("plain_summary") or "").strip()),
        ("short_summary", (content.get("short_summary") or "").strip()),
    ]
    checked += [
        (f"what_to_do[{n}]", str(a).strip())
        for n, a in enumerate(content.get("what_to_do") or [])
        if str(a).strip()
    ]

    for field_name, text in checked:
        if not text:
            continue
        if _wrong_script_for_language(text, locale):
            return f"{field_name} in wrong script for {locale!r}"
        stray = _FOREIGN_SCRIPT_RE.search(text)
        if stray:
            return f"{field_name} contains foreign-script character {stray.group(0)!r}"

    return None


# Per-locale message furniture. Kept in one table so the two channels stay
# structurally identical and a reader switching between them recognizes the
# same skeleton.
_COPY: dict[str, dict[str, str]] = {
    "en": {
        "read_more": "Read more",
        # Named payoffs for the link. The message already carries the
        # summary, the checks and the actions, so a bare "Read more" asks
        # for a tap without saying what is on the other side. Each of these
        # is only used when the post actually has that content.
        "more_analysis": "Read more — full analysis and the facts",
        "more_severity": "Read more — why it's rated this way",
        "more_sources": "Read more — the reporting behind this",
        "check": "Check if this affects you",
        "do": "What to do",
        "reported_by": "Also reported by",
        "already": "If you're already affected",
    },
    "ua": {
        "read_more": "Читати більше",
        "more_analysis": "Читати більше — розбір і деталі",
        "more_severity": "Читати більше — чому саме такий рівень",
        "more_sources": "Читати більше — на чому це ґрунтується",
        "check": "Перевірте, чи це вас стосується",
        "do": "Що робити",
        "reported_by": "Також повідомили",
        "already": "Якщо вас це вже зачепило",
    },
}


def _read_more_label(
    payload: dict[str, Any], content: dict[str, Any], copy: dict[str, str],
) -> str:
    """Pick the link label that names what the detail page actually adds.

    Ordered by how much the extra content is worth to a reader who has just
    finished the message: the analysis is the biggest payoff, then the
    severity rationale, then the corroborating reporting. Falls back to a
    plain "Read more" when the post has none of them, so the label never
    promises something the page does not have.
    """
    if str(content.get("detail_body") or "").strip():
        return copy.get("more_analysis", copy["read_more"])
    if str(content.get("severity_reason") or "").strip():
        return copy.get("more_severity", copy["read_more"])
    if payload.get("corroborating_sources"):
        return copy.get("more_sources", copy["read_more"])
    return copy["read_more"]

# Hashtags make a post findable inside Telegram's own search and let readers
# follow one theme across the channel. Only a small curated set — a wall of
# tags reads as spam and dilutes the ones that matter.
_CATEGORY_TAG = {
    "phishing": "phishing",
    "ransomware": "ransomware",
    "vulnerability": "vulnerability",
    "breach": "breach",
    "data leak": "dataleak",
    "exploit": "exploit",
    "zero-day": "zeroday",
    "malware": "malware",
    "spyware": "spyware",
    "scam": "scam",
    "botnet": "botnet",
    "social engineering": "socialengineering",
}

_MAX_HASHTAGS = 4


def notify(payload: dict[str, Any]) -> bool:
    """Should this post buzz subscribers' phones?

    Only Critical severity or an explicit urgent action. Everything else is
    sent silently. A channel that pushes a notification for every routine
    advisory gets muted, and a muted channel cannot deliver the one alert
    that actually needed to interrupt someone's day.
    """
    return (
        payload.get("threat_level") == "Critical"
        or payload.get("actionability_level") == "urgent_action"
    )


def _hashtags(payload: dict[str, Any]) -> str:
    """Build the trailing hashtag line: category, platforms, CVE ids."""
    tags: list[str] = []
    category = str(payload.get("category", "")).lower()
    if category in _CATEGORY_TAG:
        tags.append(_CATEGORY_TAG[category])

    for platform in payload.get("affected_platforms") or []:
        slug = re.sub(r"[^0-9A-Za-z]+", "", str(platform))
        if slug and slug.lower() not in tags:
            tags.append(slug)

    if payload.get("actionability_level") == "urgent_action":
        tags.append("urgent")

    return " ".join(f"#{t}" for t in tags[:_MAX_HASHTAGS])


def render_message(payload: dict[str, Any], *, locale: str, base_url: str) -> str:
    """Build the HTML message body for one post in one locale.

    The skeleton is fixed so a returning subscriber learns where to look:

        <severity emoji> <b>Headline</b>

        Plain-language explanation of what happened.

        🔎 Check if this affects you
        • self-check step

        ✅ What to do
        • action
        • action

        Also reported by BleepingComputer, CISA
        🔗 Read more
        #vulnerability #Windows

    Sections are omitted rather than padded when the post has no content for
    them, so a thin advisory produces a short post instead of a scaffold of
    empty headings.

    Raises KeyError/ValueError if the payload lacks the requested locale's
    translation — the caller treats that as "skip this post" (degrade-and-log).
    """
    translations = payload.get("translations") or {}
    content = translations.get(locale)
    if not content:
        raise ValueError(f"payload has no '{locale}' translation")

    title = (content.get("title") or "").strip()
    if not title:
        raise ValueError("payload translation has no title")

    copy = _COPY.get(locale, _COPY["en"])

    # Plain-language first: lead the post with the everyday-language line
    # when the post has one, falling back to the editorial summary for older
    # cached posts that predate `plain_summary`.
    summary = (
        (content.get("plain_summary") or "").strip()
        or (content.get("short_summary") or "").strip()
    )
    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[: _MAX_SUMMARY_CHARS - 1].rstrip() + "…"

    level = payload.get("threat_level", "Low")
    emoji = _LEVEL_EMOJI.get(level, "⚪")

    fingerprint = payload.get("id", "")
    link = deep_link(base_url, locale, fingerprint)

    lines: list[str] = [f"{emoji} <b>{_text(title)}</b>"]
    if summary:
        lines.append("")
        lines.append(_text(summary))

    def _bullets(values: Any, limit: int) -> list[str]:
        return [
            str(v).strip() for v in (values or []) if str(v).strip()
        ][:limit]

    # "Does this affect me?" is the first question a non-expert has, and
    # answering it inside the message means they don't need to open anything
    # to find out the answer is no.
    checks = _bullets(content.get("am_i_affected"), 2)
    if checks:
        lines.append("")
        lines.append(f"🔎 <b>{_text(copy['check'])}</b>")
        lines.extend(f"• {_text(c)}" for c in checks)

    # Actions. Two, not one: the previous single-action format frequently cut
    # the step that made the first one work (install, then reboot).
    actions = _bullets(content.get("what_to_do"), 2)
    if actions:
        lines.append("")
        lines.append(f"✅ <b>{_text(copy['do'])}</b>")
        lines.extend(f"• {_text(a)}" for a in actions)

    # Recovery path for readers who are already past the point of prevention.
    recovery = _bullets(content.get("if_already_affected"), 2)
    if recovery:
        lines.append("")
        lines.append(f"🆘 <b>{_text(copy['already'])}</b>")
        lines.extend(f"• {_text(r)}" for r in recovery)

    lines.append("")

    # Corroboration — the payoff of story clustering. "Three outlets reported
    # this" is a stronger trust signal than anything we could assert about
    # ourselves, and it is the visible reason we collapsed the duplicates.
    corroborating = [
        str(s).strip() for s in (payload.get("corroborating_sources") or [])
        if str(s).strip()
    ][:3]
    if corroborating:
        lines.append(
            f"{_text(copy['reported_by'])} {_text(', '.join(corroborating))}"
        )

    # Read-more link to our own detail page. We intentionally do NOT append the
    # original source here — it sits right after a link that points at our
    # site, which reads as if the link goes to the source. The AI summary
    # already names the outlet ("BleepingComputer повідомляє…").
    lines.append(
        f'🔗 <a href="{_esc(link)}">'
        f'{_text(_read_more_label(payload, content, copy))}</a>'
    )

    tags = _hashtags(payload)
    if tags:
        lines.append("")
        lines.append(tags)

    return "\n".join(lines)


__all__ = ["render_message", "deep_link", "quality_problem", "notify"]
