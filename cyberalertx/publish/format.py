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


def deep_link(base_url: str, locale: str, fingerprint: str) -> str:
    """Public detail-page URL: {base}/{locale}/threat/{fingerprint}."""
    return f"{base_url.rstrip('/')}/{locale}/threat/{fingerprint}"


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

    lines: list[str] = [f"{emoji} <b>{_esc(title)}</b>"]
    if summary:
        lines.append("")
        lines.append(_esc(summary))

    facts = [f for f in (content.get("quick_facts") or []) if f][:_MAX_QUICK_FACTS]
    if facts:
        lines.append("")
        lines.extend(f"• {_esc(str(f))}" for f in facts)

    lines.append("")
    lines.append(f'🔗 <a href="{_esc(link)}">{read_more}</a>')

    return "\n".join(lines)


__all__ = ["render_message", "deep_link"]
