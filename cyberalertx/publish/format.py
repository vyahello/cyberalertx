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

# Max quick facts to surface — keep the message scannable, not a wall.
_MAX_QUICK_FACTS = 2

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


def quality_problem(payload: dict, *, locale: str) -> str | None:
    """Return a reason string if this post shouldn't be published, else None.

    A pre-send gate that runs BEFORE formatting. The render path already drops
    wrong-script *titles* per locale, but not summaries — and a stale cache
    entry can still carry an English body on a UA-target render. We re-check
    both here so a half-translated card never reaches the channel.

    Checks (cheap, deterministic):
      * the requested locale has a translation with a non-empty title
      * neither the title nor the summary is in the wrong script for the locale
    """
    content = (payload.get("translations") or {}).get(locale)
    if not content:
        return f"no '{locale}' translation"

    title = (content.get("title") or "").strip()
    if not title:
        return "empty title"

    # Local import keeps the ai → publish dependency one-way and off the hot path.
    from ..ai.validation import _wrong_script_for_language

    if _wrong_script_for_language(title, locale):
        return f"title in wrong script for {locale!r}"

    summary = (content.get("short_summary") or "").strip()
    if summary and _wrong_script_for_language(summary, locale):
        return f"summary in wrong script for {locale!r}"

    return None


def render_message(payload: dict, *, locale: str, base_url: str) -> str:
    """Build the HTML message body for one post in one locale.

    Raises KeyError/ValueError if the payload lacks the requested locale's
    translation — the caller treats that as "skip this post" (degrade-and-log).
    """
    translations = payload.get("translations") or {}
    content = translations.get(locale)
    if not content:
        raise ValueError(f"payload has no '{locale}' translation")

    title = (content.get("title") or "").strip()
    summary = (content.get("short_summary") or "").strip()
    if not title:
        raise ValueError("payload translation has no title")
    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[: _MAX_SUMMARY_CHARS - 1].rstrip() + "…"

    level = payload.get("threat_level", "Low")
    emoji = _LEVEL_EMOJI.get(level, "⚪")

    fingerprint = payload.get("id", "")
    link = deep_link(base_url, locale, fingerprint)
    read_more = "Читати більше" if locale == "ua" else "Read more"

    lines: list[str] = [f"{emoji} <b>{_text(title)}</b>"]
    if summary:
        lines.append("")
        lines.append(_text(summary))

    facts = [f for f in (content.get("quick_facts") or []) if f][:_MAX_QUICK_FACTS]
    if facts:
        lines.append("")
        lines.extend(f"• {_text(str(f))}" for f in facts)

    # Footer: read-more link + source attribution. The source name is a brand
    # (BleepingComputer, CISA, itc.ua) — no translation, just a middot so the
    # reader knows who reported it.
    footer = f'🔗 <a href="{_esc(link)}">{read_more}</a>'
    source = (payload.get("source") or "").strip()
    if source:
        footer += f" · {_esc(source)}"
    lines.append("")
    lines.append(footer)

    return "\n".join(lines)


__all__ = ["render_message", "deep_link", "quality_problem"]
