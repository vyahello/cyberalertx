"""Shared shell and components for the /admin pages.

Server-rendered HTML with inline CSS and no JavaScript. That is a security
property as much as a style choice: the pages carry a CSP of
`script-src 'none'`, so even if escaping ever failed somewhere, injected
script could not run. Everything that looks interactive — tabs, gauges, bars
— is plain links, CSS and inline SVG.

The look follows the public site: graphite surfaces and the calm cyan accent,
dark by default, with a light variant for `prefers-color-scheme: light`.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

Tone = str  # "ok" | "warn" | "bad" | "accent" | "neutral"

NAV: tuple[tuple[str, str, str], ...] = (
    ("overview", "Overview", "/admin/"),
    ("feedback", "Feedback", "/admin/feedback"),
    ("quality", "Quality", "/admin/metrics"),
    ("sources", "Sources", "/admin/sources"),
)

#: Sent on every admin HTML page. No script may run; styles and images are
#: inline only; nothing may embed the page or receive a referrer from it.
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

_CSS = """
:root{--bg:#0e1116;--surface:#151a21;--surface-2:#1b212a;--line:#252c36;--text:#e6e9ee;
--muted:#98a2b3;--faint:#6b7383;--accent:#06b6d4;--ok:#34d399;--warn:#fbbf24;--bad:#f87171;
--ok-bg:rgba(52,211,153,.12);--warn-bg:rgba(251,191,36,.12);--bad-bg:rgba(248,113,113,.12);
--accent-bg:rgba(6,182,212,.12);color-scheme:dark}
@media (prefers-color-scheme:light){:root{--bg:#f6f7f9;--surface:#fff;--surface-2:#f1f3f6;
--line:#e2e6ec;--text:#111418;--muted:#5b6472;--faint:#8a93a2;--accent:#0891b2;--ok:#059669;
--warn:#b45309;--bad:#dc2626;--ok-bg:rgba(5,150,105,.1);--warn-bg:rgba(180,83,9,.1);
--bad-bg:rgba(220,38,38,.1);--accent-bg:rgba(8,145,178,.1);color-scheme:light}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 88%,transparent);
backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.top .in{max-width:1180px;margin:0 auto;padding:0 20px;display:flex;align-items:center;gap:20px;height:56px}
.brand{font-weight:650;letter-spacing:-.01em;color:var(--text);white-space:nowrap}
.brand span{margin-left:8px;font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
color:var(--accent);background:var(--accent-bg);padding:2px 8px;border-radius:999px}
nav{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;flex:1}nav::-webkit-scrollbar{display:none}
nav a{color:var(--muted);padding:7px 12px;border-radius:8px;white-space:nowrap;font-weight:500}
nav a:hover{color:var(--text);background:var(--surface-2);text-decoration:none}
nav a[aria-current=page]{color:var(--text);background:var(--surface-2);box-shadow:inset 0 -2px 0 var(--accent)}
.site{color:var(--muted);white-space:nowrap;font-size:13px}
main{max-width:1180px;margin:0 auto;padding:28px 20px 64px}
.head{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:22px}
h1{font-size:24px;line-height:1.2;margin:0;letter-spacing:-.02em}
.sub{color:var(--muted);margin:6px 0 0;max-width:72ch}
.meta{color:var(--faint);font-size:12px;display:flex;gap:14px;align-items:center}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.cols{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));margin-top:14px;align-items:start}
.tile{display:block;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;
color:var(--text);position:relative;transition:border-color .15s}
a.tile:hover{border-color:color-mix(in srgb,var(--accent) 45%,var(--line));text-decoration:none}
.tile .k{color:var(--muted);font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
display:flex;align-items:center;gap:8px}
.tile .v{font-size:28px;font-weight:650;letter-spacing:-.02em;margin-top:8px;font-variant-numeric:tabular-nums;
display:flex;align-items:center;gap:12px}
.tile .s{color:var(--muted);font-size:13px;margin-top:4px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--faint);flex:none}
.dot.ok{background:var(--ok);box-shadow:0 0 0 3px var(--ok-bg)}.dot.warn{background:var(--warn);box-shadow:0 0 0 3px var(--warn-bg)}
.dot.bad{background:var(--bad);box-shadow:0 0 0 3px var(--bad-bg)}.dot.accent{background:var(--accent)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.panel>h2{margin:0;padding:14px 18px;font-size:13px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
color:var(--muted);border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px}
.panel>h2 small{text-transform:none;letter-spacing:0;font-weight:500;color:var(--faint)}
.panel .body{padding:16px 18px}
.full{margin-top:14px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:10px 18px;border-bottom:1px solid var(--line);vertical-align:middle}
th{color:var(--faint);font-weight:600;font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;white-space:nowrap;
background:var(--surface-2)}
tr:last-child td{border-bottom:0}tbody tr:hover td{background:color-mix(in srgb,var(--surface-2) 60%,transparent)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:2px 9px;border-radius:999px;
white-space:nowrap;background:var(--surface-2);color:var(--muted)}
.pill.ok{background:var(--ok-bg);color:var(--ok)}.pill.warn{background:var(--warn-bg);color:var(--warn)}
.pill.bad{background:var(--bad-bg);color:var(--bad)}.pill.accent{background:var(--accent-bg);color:var(--accent)}
.meter{height:6px;border-radius:999px;background:var(--surface-2);overflow:hidden;min-width:70px}
.meter i{display:block;height:100%;border-radius:999px;background:var(--accent)}
.meter i.ok{background:var(--ok)}.meter i.warn{background:var(--warn)}.meter i.bad{background:var(--bad)}
.stack{display:flex;height:12px;border-radius:999px;overflow:hidden;background:var(--surface-2);gap:2px}
.stack i{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:12px;color:var(--muted);font-size:13px}
.legend b{color:var(--text);font-variant-numeric:tabular-nums;margin-left:4px}
.legend span{display:inline-flex;align-items:center;gap:7px}
.sw{width:10px;height:10px;border-radius:3px;display:inline-block}
.rows{display:grid;gap:12px}
.row{display:grid;grid-template-columns:minmax(120px,1fr) 2fr auto;align-items:center;gap:14px}
.row .lbl{color:var(--text)}.row .num{font-variant-numeric:tabular-nums;color:var(--muted);min-width:3ch;text-align:right}
.alerts{list-style:none;margin:0;padding:0}
.alerts li{display:flex;gap:12px;align-items:flex-start;padding:12px 18px;border-bottom:1px solid var(--line)}
.alerts li:last-child{border-bottom:0}.alerts .dot{margin-top:6px}.alerts li>div{min-width:0;flex:1}
.alerts p{margin:0}.alerts small{color:var(--muted);display:block;margin-top:2px}.alerts small .trunc{display:inline-block;max-width:100%;vertical-align:bottom}.alerts p .trunc{max-width:100%}
.empty{color:var(--muted);padding:26px 18px;text-align:center}
.banner{display:flex;gap:12px;align-items:flex-start;padding:12px 16px;border-radius:12px;margin-bottom:16px;
border:1px solid var(--line);background:var(--surface)}
.banner.warn{border-color:color-mix(in srgb,var(--warn) 40%,var(--line));background:var(--warn-bg)}
.banner.bad{border-color:color-mix(in srgb,var(--bad) 40%,var(--line));background:var(--bad-bg)}
.banner .dot{margin-top:6px}.banner p{margin:0}
time{white-space:nowrap}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
.trunc{max-width:52ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block}.cols .trunc{max-width:28ch}
.ring{flex:none}
footer{color:var(--faint);font-size:12px;margin-top:28px}
@media (max-width:640px){
.top .in{flex-wrap:wrap;height:auto;gap:4px 12px;padding:10px 14px 0}
.site{display:none}nav{order:3;flex-basis:100%;padding-bottom:8px;margin:0 -6px}
main{padding:18px 14px 48px}h1{font-size:21px}.head{margin-bottom:16px}
.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.tile{padding:13px 14px}.tile .k{font-size:11px}.tile .v{font-size:22px;gap:8px;margin-top:6px}
.tile .s{font-size:12px}.ring{width:34px;height:34px}
.cols{grid-template-columns:1fr}
th,td{padding:9px 12px}.panel>h2,.panel .body{padding-left:14px;padding-right:14px}
.alerts li{padding-left:14px;padding-right:14px}.row{grid-template-columns:1fr auto}
.row .meter{grid-column:1/-1;order:3}.hide-xs{display:none}.trunc{max-width:38vw}
th,td{padding:8px 9px}.cell-meter{min-width:64px!important}.cols .trunc{max-width:38vw}}
@media (max-width:1100px){.hide-sm{display:none}th,th.n{white-space:normal}}
"""


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def pct(rate: float | None, digits: int = 0) -> str:
    if rate is None:
        return "—"
    return f"{rate * 100:.{digits}f}%"


def num(value: int | float) -> str:
    return f"{value:,}".replace(",", " ")


def parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def ago(value: object, now: datetime, *, missing: str = "never") -> str:
    """'3 min ago' with the exact UTC time in a tooltip."""
    when = parse_time(value)
    if when is None:
        return f'<span style="color:var(--faint)">{esc(missing)}</span>'
    seconds = (now - when).total_seconds()
    if seconds < 0:
        text = "just now"
    elif seconds < 90:
        text = "just now"
    elif seconds < 3600:
        text = f"{int(seconds // 60)} min ago"
    elif seconds < 48 * 3600:
        text = f"{int(seconds // 3600)} h ago"
    else:
        text = f"{int(seconds // 86400)} d ago"
    exact = when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f'<time datetime="{esc(when.isoformat())}" title="{exact}">{text}</time>'


def tone_for_rate(rate: float | None, *, good: float, fair: float) -> Tone:
    if rate is None:
        return "neutral"
    return "ok" if rate >= good else "warn" if rate >= fair else "bad"


def ring(rate: float | None, tone: Tone = "accent", size: int = 44) -> str:
    """A circular gauge. Pure SVG, so it survives the no-script CSP."""
    r = (size - 6) / 2
    circumference = 2 * 3.14159265 * r
    filled = 0.0 if rate is None else max(0.0, min(1.0, rate)) * circumference
    colour = {"ok": "var(--ok)", "warn": "var(--warn)", "bad": "var(--bad)"}.get(tone, "var(--accent)")
    c = size / 2
    return (
        f'<svg class="ring" width="{size}" height="{size}" viewBox="0 0 {size} {size}" aria-hidden="true">'
        f'<circle cx="{c}" cy="{c}" r="{r:.2f}" fill="none" stroke="var(--surface-2)" stroke-width="5"/>'
        f'<circle cx="{c}" cy="{c}" r="{r:.2f}" fill="none" stroke="{colour}" stroke-width="5" '
        f'stroke-linecap="round" stroke-dasharray="{filled:.2f} {circumference:.2f}" '
        f'transform="rotate(-90 {c} {c})"/></svg>'
    )


def meter(fraction: float | None, tone: Tone = "accent") -> str:
    width = 0 if fraction is None else round(max(0.0, min(1.0, fraction)) * 100, 1)
    cls = f' class="{tone}"' if tone in ("ok", "warn", "bad") else ""
    return f'<div class="meter"><i{cls} style="width:{width}%"></i></div>'


def pill(text: str, tone: Tone = "neutral") -> str:
    return f'<span class="pill {esc(tone)}">{esc(text)}</span>'


def dot(tone: Tone) -> str:
    return f'<span class="dot {esc(tone)}" aria-hidden="true"></span>'


def tile(label: str, value: str, sub: str = "", *, tone: Tone = "", href: str = "",
         visual: str = "") -> str:
    """A KPI tile. `value` and `sub` are trusted HTML built by the caller."""
    head = f'<div class="k">{dot(tone) if tone else ""}{esc(label)}</div>'
    body = f'<div class="v">{visual}{value}</div>' + (f'<div class="s">{sub}</div>' if sub else "")
    if href:
        return f'<a class="tile" href="{esc(href)}">{head}{body}</a>'
    return f'<div class="tile">{head}{body}</div>'


def panel(title: str, body: str, *, aside: str = "", padded: bool = True, cls: str = "") -> str:
    """`body` and `aside` are trusted HTML."""
    aside_html = f"<small>{aside}</small>" if aside else ""
    inner = f'<div class="body">{body}</div>' if padded else body
    return f'<section class="panel {cls}"><h2>{esc(title)}{aside_html}</h2>{inner}</section>'


@dataclass(frozen=True)
class Segment:
    label: str
    value: int
    colour: str


def stack(segments: Sequence[Segment]) -> str:
    total = sum(s.value for s in segments) or 1
    bars = "".join(
        f'<i style="width:{100 * s.value / total:.2f}%;background:{s.colour}" '
        f'title="{esc(s.label)}: {s.value}"></i>'
        for s in segments if s.value
    )
    legend = "".join(
        f'<span><i class="sw" style="background:{s.colour}"></i>{esc(s.label)}'
        f"<b>{num(s.value)}</b><span style=\"color:var(--faint)\">{pct(s.value / total)}</span></span>"
        for s in segments
    )
    return f'<div class="stack" role="img" aria-label="breakdown">{bars}</div><div class="legend">{legend}</div>'


def bar_rows(rows: Iterable[tuple[str, int]], *, tone: Tone = "accent") -> str:
    """Labelled horizontal bars scaled to the largest value."""
    items = [(label, value) for label, value in rows]
    if not items:
        return '<p class="empty">Nothing recorded.</p>'
    biggest = max(v for _, v in items) or 1
    return '<div class="rows">' + "".join(
        f'<div class="row"><span class="lbl">{esc(label)}</span>{meter(v / biggest, tone)}'
        f'<span class="num">{num(v)}</span></div>'
        for label, v in items
    ) + "</div>"


def page(
    *,
    active: str,
    title: str,
    subtitle: str,
    body: str,
    now: datetime,
    json_href: str = "",
) -> str:
    """The full document. `body` is trusted HTML assembled from escaped parts."""
    nav = "".join(
        f'<a href="{href}"{" aria-current=page" if key == active else ""}>{esc(label)}</a>'
        for key, label, href in NAV
    )
    meta = f'<span>Updated {esc(now.astimezone(timezone.utc).strftime("%H:%M UTC"))}</span>'
    if json_href:
        meta += f'<a href="{esc(json_href)}">JSON</a>'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">'
        f"<title>{esc(title)} · CyberAlertX admin</title><style>{_CSS}</style></head><body>"
        f'<header class="top"><div class="in"><a class="brand" href="/admin/">CyberAlertX<span>Admin</span></a>'
        f'<nav aria-label="Admin sections">{nav}</nav>'
        f'<a class="site" href="/" target="_blank" rel="noopener noreferrer">View site ↗</a></div></header>'
        f'<main><div class="head"><div><h1>{esc(title)}</h1><p class="sub">{subtitle}</p></div>'
        f'<div class="meta">{meta}</div></div>{body}</main></body></html>'
    )


__all__ = [
    "CSP", "NAV", "Segment", "ago", "bar_rows", "dot", "esc", "meter", "num", "page",
    "panel", "parse_time", "pct", "pill", "ring", "stack", "tile", "tone_for_rate",
]
