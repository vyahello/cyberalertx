"""`/admin/media` — Media Engine assets, read-only.

Branded cards (deterministic, rendered by the website) and editorial
illustrations (provider output, validated and stored): status, variants and
their public URLs, story association, attempts, errors, provider status and
usage. Behind the same admin gate as every /admin path. The admin CSP allows
only data: images, so variants are listed as links, not thumbnails.
"""
from __future__ import annotations

import os
from collections import Counter
from datetime import datetime
from typing import Any, Mapping, Sequence

from .ui import esc, num, page, panel, pill, tile

_TONE = {"validated": "ok", "published": "ok", "generated": "ok", "generating": "accent",
         "pending": "neutral", "skipped": "neutral", "failed": "bad"}


def _links(variants: Mapping[str, str]) -> str:
    return " · ".join(f'<a href="{esc(u)}" rel="noopener noreferrer">{esc(v)}</a>'
                      for v, u in variants.items())


def _matches(a: Any, q: str) -> bool:
    ql = q.lower()
    return (ql in a.story_key.lower() or ql in a.asset_id.lower() or q in a.members
            or any(ql in str(t).lower() for t in a.alt_text.values()))


def _regen_form(a: Any, csrf: str) -> str:
    return ('<form method="post" action="/admin/media/regenerate" class="inline-form">'
            f'<input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="story" value="{esc(a.story_key)}">'
            '<label class="confirm"><input type="checkbox" name="confirm" value="yes" required> '
            'queue a new image (may cost money on the next media run)</label>'
            '<button class="btn" type="submit">Regenerate</button></form>')


def render_media(assets: Sequence[Any], usage: Sequence[Mapping[str, Any]], *, now: datetime, q: str = "",
                 csrf: str = "", notice: str = "", error: str = "") -> str:
    provider = (os.getenv("CYBERALERTX_IMAGE_PROVIDER") or "none").strip().lower()
    all_assets = list(assets)
    if q:
        assets = [a for a in assets if _matches(a, q)]
    cards = [a for a in assets if a.asset_type == "branded_card"]
    illus = [a for a in assets if a.asset_type == "editorial_illustration"]
    last_ok = max((u.get("at", "") for u in usage if u.get("ok")), default="")
    by_status = Counter(a.status for a in illus)
    ok_calls = sum(1 for u in usage if u.get("ok"))
    cost = sum(float(u.get("cost_usd") or 0) for u in usage)

    tiles = "".join([
        tile("Branded cards", num(len(cards)), f"{num(len({a.story_key for a in cards}))} stories",
             tone="ok" if cards else "neutral"),
        tile("Illustrations", num(by_status.get("validated", 0) + by_status.get("published", 0)),
             " · ".join(f"{esc(k)} {v}" for k, v in sorted(by_status.items())) or "none",
             tone="ok" if illus else "neutral"),
        tile("Image provider", "not configured" if provider == "none" else esc(provider),
             "branded cards only — by design, not a failure" if provider == "none"
             else f"last success {esc(last_ok[:16]) or 'never'}",
             tone="neutral" if provider == "none" else "ok"),
        tile("Provider calls", num(len(usage)), f"{ok_calls} ok · ${cost:.2f} recorded"),
    ])

    def illus_row(a: Any) -> str:
        err = f"<br><small>{esc(a.last_error)}</small>" if a.last_error else ""
        return (f"<tr><td>{pill(a.status, _TONE.get(a.status, 'neutral'))}</td>"
                f"<td><code>{esc(a.story_key)}</code><br><small>{esc(len(a.members))} articles</small></td>"
                f"<td>{esc(a.width)}×{esc(a.height)} {esc(a.mime_type)}<br>"
                f"<small>{esc(a.generation_model or a.source)} · prompt {esc(a.prompt_version)}</small></td>"
                f"<td class=num>{esc(a.attempts)}</td><td>{_links(a.variants) or '—'}{err}</td>"
                f"<td><small>{esc(a.updated_at)}</small>"
                + (f"<br>{_regen_form(a, csrf)}" if csrf and provider != "none" and a.status in ("validated", "failed", "published") else "")
                + "</td></tr>")

    illus_html = (
        "<table><thead><tr><th>status</th><th>story</th><th>source</th><th>attempts</th>"
        "<th>variants / error</th><th>updated</th></tr></thead><tbody>"
        + "".join(illus_row(a) for a in sorted(illus, key=lambda a: a.updated_at, reverse=True)[:100])
        + "</tbody></table>"
    ) if illus else ('<p class="empty">No illustrations. '
                     + ("No image provider is configured (<code>CYBERALERTX_IMAGE_PROVIDER</code>), "
                        "so every story uses its branded card." if provider == "none" else
                        "None of the stories qualified yet.") + "</p>")

    def card_row(a: Any) -> str:
        return (f"<tr><td>{esc(a.locale.upper())}</td><td><code>{esc(a.members[0] if a.members else '')}</code>"
                f"<br><small>{esc(a.alt_text.get(a.locale, ''))}</small></td>"
                f"<td><code>{esc(a.content_hash)}</code></td><td>{_links(a.variants)}</td></tr>")

    card_html = (
        "<table><thead><tr><th>edition</th><th>post / alt text</th><th>hash</th>"
        "<th>variants</th></tr></thead><tbody>"
        + "".join(card_row(a) for a in sorted(cards, key=lambda a: a.updated_at, reverse=True)[:60])
        + "</tbody></table>"
    ) if cards else '<p class="empty">No cards recorded yet.</p>'

    usage_rows = "".join(
        f"<tr><td><small>{esc(u.get('at'))}</small></td><td><code>{esc(u.get('story_key'))}</code></td>"
        f"<td>{esc(u.get('provider'))} {esc(u.get('model', ''))}</td>"
        f"<td>{pill('ok', 'ok') if u.get('ok') else pill('failed', 'bad')}</td>"
        f"<td><small>{esc(u.get('error', ''))}</small></td></tr>"
        for u in list(usage)[-30:][::-1])
    usage_html = (f"<table><thead><tr><th>at</th><th>story</th><th>provider</th><th>result</th>"
                  f"<th>error</th></tr></thead><tbody>{usage_rows}</tbody></table>"
                  if usage_rows else '<p class="empty">No provider calls recorded.</p>')

    search = ('<form class="filters" method="get" action="/admin/media">'
              f'<label>Story ID, asset or headline<input type="search" name="q" value="{esc(q)}"></label>'
              '<button class="btn" type="submit">Search</button> <a href="/admin/media" style="padding:7px 4px">Reset</a>'
              + (f'<span style="color:var(--muted);font-size:13px;padding:7px 0">{len(assets)} of {len(all_assets)} records</span>' if q else "")
              + "</form>")
    banner = ""
    if notice:
        banner += f'<div class="banner"><span class="dot ok"></span><p>{esc(notice)}</p></div>'
    if error:
        banner += f'<div class="banner bad"><span class="dot bad"></span><p>{esc(error)}</p></div>'
    body = (
        banner + f'<div class="grid">{tiles}</div><div class="full">{search}</div>'
        + panel("Editorial illustrations", illus_html, padded=not illus, cls="full",
                aside="regenerate: <code>python -m cyberalertx.tools.media regenerate STORY_KEY</code>")
        + panel("Branded cards (latest 60)", card_html, padded=not cards, cls="full",
                aside="rendered on request by the website; no bytes stored")
        + panel("Provider usage", usage_html, padded=not usage_rows, cls="full")
    )
    return page(active="media", title="Media studio", body=body, now=now, json_href="/admin/media.json", query=q,
                subtitle="Cards for every eligible story, illustrations only for high-priority ones. "
                         "A failure here never blocks an article or a Telegram post.")


__all__ = ["render_media"]
