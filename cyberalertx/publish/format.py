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

# Telegram slices. Three actions, not two: nearly every cached post carries
# three after hygiene and the median rendered message is ~826 chars — 20% of
# Telegram's 4096 cap — so cutting the third bought nothing and cost the 4G/5G
# post its only consumer-usable step ("Увімкніть Wi-Fi Calling…").
_MAX_CHECKS = 2
_MAX_ACTIONS = 3
_MAX_AVOID = 2
_MAX_AUDIENCE = 3

# `short_summary` opens with a source-attribution clause by contract
# (templates.py). The message already names the outlet on its own line, so
# pasting the clause into the body says it twice and buries the fact three
# words deep. Deliberately conservative — it strips only a leading
# "<outlet> повідомляє:" up to a COLON. A summary like "The Hacker News
# повідомляє про хвилю атак … Афганістану," is left alone on purpose: there
# the "про …" clause carries real content, and a greedy variant amputated it.
_ATTR_LEAD: dict[str, re.Pattern[str]] = {
    "ua": re.compile(
        r"^[^:»]{2,45}?\s*\b(?:повідомля\w+|попереджа\w+|пише|пишуть"
        r"|зазнача\w+|переказу\w+|розповіда\w+|наводить)"
        r"\s*(?:про\s+|що\s+)?:\s+",
        re.IGNORECASE,
    ),
    "en": re.compile(
        r"^[^:]{2,45}?\s*\b(?:reports?|reported|warns?|warned|says?|writes?)"
        r"\s*(?:that\s+|on\s+|about\s+)?:\s+",
        re.IGNORECASE,
    ),
}

_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9.+_-]*[A-Za-z0-9]")
_DIGIT_RE = re.compile(r"[0-9]")
_OUTLET_TOKENS: frozenset[str] = frozenset({
    "bleepingcomputer", "cisa", "securelist", "kaspersky", "the", "hacker",
    "news", "krebs", "dev.ua", "itc.ua", "ain.ua", "cert-ua", "certua",
})


def _bullets(values: Any, limit: int) -> list[str]:
    return [str(v).strip() for v in (values or []) if str(v).strip()][:limit]


def _strip_attribution(text: str, locale: str) -> str:
    """Drop a leading "<outlet> повідомляє:" clause, restoring sentence case.

    Returns `text` unchanged when stripping would leave too little to be a
    sentence — a summary that is *only* an attribution clause is better shown
    whole than shown empty.
    """
    pattern = _ATTR_LEAD.get(locale, _ATTR_LEAD["en"])
    match = pattern.match(text)
    if match is None:
        return text
    out = text[match.end():].strip()
    if len(out) < 40:
        return text
    return out[0].upper() + out[1:] if out[:1].islower() else out


def _anchor_tokens(text: str) -> set[str]:
    """Product / actor names in a string. Outlet names are attribution, not a
    fact about the threat, so they never justify a second paragraph."""
    return {
        m.group(0).lower() for m in _LATIN_RUN.finditer(text or "")
        if len(m.group(0)) >= 2 and m.group(0).lower() not in _OUTLET_TOKENS
    }


def _adds_anchor(candidate: str, baseline: str) -> bool:
    """True when `candidate` names a product, an actor or a number that
    `baseline` does not — the test for whether a second paragraph carries
    information rather than repeating the first."""
    if _anchor_tokens(candidate) - _anchor_tokens(baseline):
        return True
    return bool(_DIGIT_RE.search(candidate)) and not _DIGIT_RE.search(baseline)


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
    checked += [
        (f"what_not_to_do[{n}]", str(a).strip())
        for n, a in enumerate(content.get("what_not_to_do") or [])
        if str(a).strip()
    ][:_MAX_AVOID]
    checked += [
        (f"am_i_affected[{n}]", str(a).strip())
        for n, a in enumerate(content.get("am_i_affected") or [])
        if str(a).strip()
    ][:_MAX_CHECKS]
    # `affected_users` is DELIBERATELY not checked. Its entries are 3-6-word
    # labels like "Адміни TeamCity On-Premises", where the Latin product name
    # pushes the script ratio past `_TARGET_LANGUAGE_MIN_RATIO`. A large share
    # of cached UA posts would be blocked from the channel by a gate that is
    # meant to catch untranslated bodies, not product names.

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
        "affects": "Who this affects",
        "do": "What to do",
        "avoid": "What not to do",
        "reported_by": "Also reported by",
        "source": "Source",
        "already": "If you're already affected",
    },
    "ua": {
        "read_more": "Читати більше",
        "more_analysis": "Читати більше — розбір і деталі",
        "more_severity": "Читати більше — чому саме такий рівень",
        "more_sources": "Читати більше — на чому це ґрунтується",
        "check": "Перевірте, чи це вас стосується",
        "affects": "Кого це стосується",
        "do": "Що робити",
        "avoid": "Чого не робити",
        "reported_by": "Також повідомили",
        "source": "Джерело",
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

    Critical always. `urgent_action` only when the severity agrees — that flag
    is a keyword score over the ENGLISH source article
    (pipeline/actionability.py) and a single "in the wild" clears the
    threshold, so it pushed a Medium post whose first action read "Звичайним
    абонентам робити нічого не треба". A push that opens with "nothing to do"
    teaches people to mute the channel, and a muted channel cannot deliver the
    one alert that needed to interrupt someone's day.
    """
    level = payload.get("threat_level")
    return level == "Critical" or (
        payload.get("actionability_level") == "urgent_action"
        and level == "High"
    )


def _hashtags(payload: dict[str, Any]) -> str:
    """Build the trailing hashtag line: urgency, category, platforms."""
    tags: list[str] = []

    # First, so `_MAX_HASHTAGS` can never slice it off: a post carrying three
    # platforms plus a category tag would otherwise lose it. Gated by `notify`
    # so the tag and the push never disagree with each other or with the body.
    if payload.get("actionability_level") == "urgent_action" and notify(payload):
        tags.append("urgent")

    category = str(payload.get("category", "")).lower()
    if category in _CATEGORY_TAG:
        tags.append(_CATEGORY_TAG[category])

    for platform in payload.get("affected_platforms") or []:
        slug = re.sub(r"[^0-9A-Za-z]+", "", str(platform))
        if slug and slug.lower() not in tags:
            tags.append(slug)

    return " ".join(f"#{t}" for t in tags[:_MAX_HASHTAGS])


def render_message(payload: dict[str, Any], *, locale: str, base_url: str) -> str:
    """Build the HTML message body for one post in one locale.

    The skeleton is fixed so a returning subscriber learns where to look:

        <severity emoji> <b>Headline</b>

        Plain-language explanation of what happened.

        The specifics: named product, named actor, the numbers.

        🔎 Check if this affects you       (or 👥 Who this affects)
        • self-check step

        ✅ What to do
        • action
        • action
        • action

        ⛔ What not to do
        • anti-pattern

        🆘 If you're already affected
        • recovery step

        Also reported by BleepingComputer, CISA
        Source: The Hacker News
        🔗 Read more — full analysis and the facts
        #vulnerability #Windows

    Sections are omitted rather than padded when the post has no content for
    them, so a thin advisory produces a short post instead of a scaffold of
    empty headings.

    The check heading has exactly three outcomes and never a fourth: real
    self-checks, else the audience, else nothing. We never print a heading
    that promises a check and then withholds one.

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

    # Plain language first, then the specifics. `plain_summary` is written for
    # a non-technical reader and, on the overwhelming majority of cached posts,
    # it names no product and no number while `short_summary` does. The message
    # used to render the plain line alone, so a subscriber read "хакери
    # зламують сервери компаній через популярну програмну складову" where the
    # cache already held the named library and the exploitation status.
    plain = (content.get("plain_summary") or "").strip()
    short = (content.get("short_summary") or "").strip()
    summary = plain or short
    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[: _MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    detail = ""
    if plain and short and _adds_anchor(short, plain):
        detail = _strip_attribution(short, locale)
        if len(detail) > _MAX_SUMMARY_CHARS:
            detail = ""

    level = payload.get("threat_level", "Low")
    emoji = _LEVEL_EMOJI.get(level, "⚪")

    fingerprint = payload.get("id", "")
    link = deep_link(base_url, locale, fingerprint)

    lines: list[str] = [f"{emoji} <b>{_text(title)}</b>"]
    if summary:
        lines.append("")
        lines.append(_text(summary))
    if detail:
        lines.append("")
        lines.append(_text(detail))

    # "Does this affect me?" is the first question a non-expert has. Three
    # outcomes, never a fourth:
    #   * real self-checks                → print them under the check heading
    #   * none, but we know the audience  → print the audience
    #   * neither                         → print nothing
    # We never print a heading that promises a check and then withholds one.
    # `affected_users` is populated on every cached post with specific labels;
    # `who_should_care` is NOT usable here — it collapses to the string
    # "Фахівці з кібербезпеки" on a large share of the posts this branch serves.
    checks = _bullets(content.get("am_i_affected"), _MAX_CHECKS)
    if checks:
        lines.append("")
        lines.append(f"🔎 <b>{_text(copy['check'])}</b>")
        lines.extend(f"• {_text(c)}" for c in checks)
    else:
        audience = _bullets(content.get("affected_users"), _MAX_AUDIENCE)
        if audience:
            lines.append("")
            lines.append(f"👥 <b>{_text(copy['affects'])}</b>")
            lines.extend(f"• {_text(a)}" for a in audience)

    actions = _bullets(content.get("what_to_do"), _MAX_ACTIONS)
    if actions:
        lines.append("")
        lines.append(f"✅ <b>{_text(copy['do'])}</b>")
        lines.extend(f"• {_text(a)}" for a in actions)

    # Anti-patterns. Present on every cached post and rendered on none of them
    # until now, which meant the channel never carried the single most
    # protective sentence in a breach post ("Не переходьте за посиланнями з
    # листів про цей витік").
    avoid = _bullets(content.get("what_not_to_do"), _MAX_AVOID)
    if avoid:
        lines.append("")
        lines.append(f"⛔ <b>{_text(copy['avoid'])}</b>")
        lines.extend(f"• {_text(a)}" for a in avoid)

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
    corroborating = _bullets(payload.get("corroborating_sources"), 3)
    if corroborating:
        lines.append(
            f"{_text(copy['reported_by'])} {_text(', '.join(corroborating))}"
        )

    # Attribution. The comment that used to sit here said the AI summary
    # already names the outlet — true of `short_summary` but the message leads
    # with `plain_summary`, whose contract forbids an attribution clause, and
    # the link preview is pinned to our own deep link. Printed only when the
    # rendered body does not already carry the name, so a summary that opens
    # "BleepingComputer повідомляє про…" is not repeated.
    source = str(payload.get("source") or "").strip()
    if source and source.lower() not in "\n".join(lines).lower():
        lines.append(f"{_text(copy['source'])}: {_text(source)}")

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
