"""HTML for the editor's feedback page at `/admin/feedback`.

Same house rules as `server/analytics/htmlreport.py`: one self-contained
document, inline CSS, no script, no external request, light and dark from
`prefers-color-scheme`. It is a reading surface for one person, so it is a
plain page that loads instantly on a phone rather than a dashboard.

Ordering is the point of the page: posts with the most 👎 come first, because
the editor opens it to find what needs fixing, not to admire what worked.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Callable

from ..feedback import FeedbackSummary

#: How each follow-up reason reads to the editor.
REASON_LABELS: dict[str, str] = {
    "too_vague": "Too vague",
    "too_technical": "Too technical",
    "incorrect": "Inaccurate",
    "not_relevant": "Not relevant to them",
}

TitleLookup = Callable[[str, str], str]

_CSS = """
:root{color-scheme:light dark;--bg:#f7f8fa;--card:#fff;--fg:#14171c;--muted:#5d6573;
--line:#e3e6eb;--up:#16794a;--down:#b42318;--accent:#0e7490}
@media (prefers-color-scheme:dark){:root{--bg:#0e1116;--card:#161b22;--fg:#e6e9ee;
--muted:#9aa3b2;--line:#262d38;--up:#4ade80;--down:#f87171;--accent:#22d3ee}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:32px 0 10px;
text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.sub{color:var(--muted);font-size:13px;margin:0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.tile b{display:block;font-size:24px;font-variant-numeric:tabular-nums}
.tile span{color:var(--muted);font-size:13px}
.up{color:var(--up)}.down{color:var(--down)}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
tr:last-child td{border-bottom:0}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.bar{height:8px;border-radius:4px;background:var(--line);overflow:hidden;min-width:80px}
.bar i{display:block;height:100%;background:var(--down)}
.empty{background:var(--card);border:1px dashed var(--line);border-radius:10px;padding:28px;
text-align:center;color:var(--muted)}
.tag{display:inline-block;font-size:12px;padding:1px 8px;border-radius:999px;border:1px solid var(--line);
color:var(--muted)}
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _pct(rate: float | None) -> str:
    return "—" if rate is None else f"{round(rate * 100)}%"


def _when(stamp: str) -> str:
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return _esc(stamp)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _post_link(post_id: str, locale: str, title_for: TitleLookup) -> str:
    title = title_for(post_id, locale) or post_id
    return (f'<a href="/{_esc(locale)}/threat/{_esc(post_id)}" target="_blank" '
            f'rel="noopener">{_esc(title)}</a>')


def render_feedback_page(
    summary: FeedbackSummary,
    *,
    title_for: TitleLookup,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    parts: list[str] = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="robots" content="noindex,nofollow">',
        f"<title>Reader feedback · CyberAlertX</title><style>{_CSS}</style></head>",
        "<body><main>",
        "<h1>Reader feedback</h1>",
        f'<p class="sub">Answers to “Was this helpful?” on every post. '
        f"Generated {_esc(now.strftime('%Y-%m-%d %H:%M UTC'))}.</p>",
    ]

    if not summary.posts:
        parts.append('<p class="empty" style="margin-top:24px">No feedback yet. '
                     "Votes appear here as soon as readers use the 👍 / 👎 "
                     "buttons under a post.</p></main></body></html>")
        return "".join(parts)

    locales = " · ".join(
        f"{_esc(loc.upper())}: <span class=up>{u}</span> / <span class=down>{d}</span>"
        for loc, (u, d) in sorted(summary.by_locale.items())
    )
    parts.append(
        '<div class="tiles">'
        f'<div class="tile"><b class="up">{summary.up}</b><span>👍 helpful</span></div>'
        f'<div class="tile"><b class="down">{summary.down}</b><span>👎 not helpful</span></div>'
        f'<div class="tile"><b>{_pct(summary.helpful_rate)}</b><span>helpful rate</span></div>'
        f'<div class="tile"><b>{summary.votes_last_7d}</b><span>votes, last 7 days</span></div>'
        "</div>"
        f'<p class="sub" style="margin-top:10px">By channel — {locales}</p>'
    )

    if summary.reasons:
        biggest = max(summary.reasons.values())
        parts.append("<h2>Why readers said no</h2><div class=wrap><table>")
        for reason, count in summary.reasons.most_common():
            width = round(100 * count / biggest)
            parts.append(
                f"<tr><td>{_esc(REASON_LABELS.get(reason, reason))}</td>"
                f'<td style="width:50%"><div class=bar><i style="width:{width}%"></i></div></td>'
                f"<td class=n>{count}</td></tr>"
            )
        parts.append("</table></div>")

    parts.append(
        "<h2>Posts — most 👎 first</h2><div class=wrap><table>"
        "<tr><th>Post</th><th>Lang</th><th class=n>👍</th><th class=n>👎</th>"
        "<th class=n>Helpful</th><th>Top reason</th><th>Last vote</th></tr>"
    )
    for post in summary.posts:
        top = post.reasons.most_common(1)
        reason = (f'<span class=tag>{_esc(REASON_LABELS.get(top[0][0], top[0][0]))}'
                  f" · {top[0][1]}</span>") if top else ""
        parts.append(
            f"<tr><td>{_post_link(post.id, post.locale, title_for)}</td>"
            f"<td>{_esc(post.locale.upper())}</td>"
            f"<td class='n up'>{post.up}</td><td class='n down'>{post.down}</td>"
            f"<td class=n>{_pct(post.helpful_rate)}</td><td>{reason}</td>"
            f"<td class=n>{_esc(_when(post.last_at))}</td></tr>"
        )
    parts.append("</table></div>")

    if summary.recent_down:
        parts.append("<h2>Recent 👎</h2><div class=wrap><table>"
                     "<tr><th>When</th><th>Post</th><th>Lang</th><th>Reason</th></tr>")
        for rec in summary.recent_down:
            given = str(rec.get("reason") or "")
            label = _esc(REASON_LABELS.get(given, given)) if given else (
                '<span class=sub>none given</span>')
            parts.append(
                f"<tr><td class=n>{_esc(_when(str(rec.get('timestamp', ''))))}</td>"
                f"<td>{_post_link(str(rec.get('id', '')), str(rec.get('locale', '')), title_for)}</td>"
                f"<td>{_esc(str(rec.get('locale', '')).upper())}</td><td>{label}</td></tr>"
            )
        parts.append("</table></div>")

    parts.append("</main></body></html>")
    return "".join(parts)


__all__ = ["REASON_LABELS", "render_feedback_page"]
