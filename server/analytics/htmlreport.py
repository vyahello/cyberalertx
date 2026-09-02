"""Self-contained HTML rendering of an analytics `Report`.

Produces one complete HTML document as a string: inline `<style>`, inline
`<svg>`, no `<script>`, no `<link>`, no web fonts, no images, no `@import`, and
therefore **zero network requests at view time**. That is a hard requirement,
not a preference — the file is written to `data/analytics/report.html` on a box
that has no business phoning anywhere, it is opened with `file://`, and it must
render identically on a laptop with the network unplugged.

The document mirrors the terminal report exactly: the same section order and
heading text from section F, the same coverage banner, the same suppressed
messages with the same reasons. A number that the terminal declines to print
is declined here too. Anything the two renderers disagree about is a bug in one
of them, which is why both import the heading constants from `report.py`
instead of spelling them out twice.

Charts are built from primitives the browser already has: bars are a `<div>`
with a percentage width, the trend is an inline SVG path, the heatmap is a
`<table>` of shaded cells. Light and dark are handled with
`prefers-color-scheme` over CSS custom properties, and `color-scheme: light
dark` so the scrollbars and form chrome follow.

SCOPE: reads only cyberalertx's own dedicated log plus the shared legacy
archive, filtered to the cyberalertx vhost. The three other vhosts on this
box keep writing to /var/log/nginx/access.log untouched, and nothing here
writes to any log file, ever.

PRIVACY: nothing leaves the box. No network calls at runtime, no third-party
analytics, no dependency outside the stdlib. Raw IPs are never persisted or
printed — only salted hashes, with the salt rotated daily and retained 14 days.
"""
from __future__ import annotations

import bisect
import html
import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable, Sequence

from . import REPO_ROOT
from .aggregate import (
    Coverage,
    Heatmap,
    LatencyStats,
    Matrix,
    Report,
    SecurityNoise,
    Series,
    Table,
)
from .report import (
    H_ACQUISITION,
    H_ALLTIME,
    H_AUTOMATED,
    H_CONTENT,
    H_COUNTRY,
    H_COVERAGE,
    H_DEVICE,
    H_GLANCE,
    H_HEALTH,
    H_LANGUAGE,
    H_NOTES,
    H_QUALITY,
    H_SECURITY,
    H_TRAFFIC,
    H_WHEN,
    _BOT_FRAMING,
    _SUPPRESSION_REASONS,
    _WEEKDAYS,
    effective_tz_name,
    _heatmap_cuts,
    _ledger_note,
    _unit,
    format_bytes,
    format_duration,
    format_int,
    format_seconds,
    format_share,
)
from .sessionize import Ledger

logger = logging.getLogger("analytics.htmlreport")

_HEATMAP_LEVELS = 5


def escape(value: object) -> str:
    """HTML-escape any value, quotes included.

    Ukrainian article titles must survive intact, so the document is UTF-8 and
    nothing is escaped to ASCII entities — only the five characters that would
    otherwise change the document's structure.
    """
    return html.escape(str(value), quote=True)


# --------------------------------------------------------------------------
# Stylesheet. Kept as a plain string (not an f-string) so CSS braces stay CSS.
# --------------------------------------------------------------------------

_CSS = """
:root {
  color-scheme: light dark;
  --bg: #fbfbfa;
  --panel: #ffffff;
  --ink: #1b1b1a;
  --ink-soft: #55554f;
  --ink-faint: #86867c;
  --rule: #e3e2dc;
  --rule-soft: #eeeee9;
  --accent: #2f6f5e;
  --accent-soft: #d8e8e2;
  --warn: #8a5a12;
  --warn-soft: #f8ecd6;
  --bad: #9c2f2f;
  --bad-soft: #f8dede;
  --bar: #3d8a75;
  --bar-soft: #e6efec;
  --hm0: #f2f1ec;
  --hm1: #d9e7e1;
  --hm2: #accfc3;
  --hm3: #74b09d;
  --hm4: #3f8d75;
  --hm5: #1f6552;
  --shadow: 0 1px 2px rgba(20, 20, 18, .05), 0 8px 24px rgba(20, 20, 18, .04);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14151a;
    --panel: #1b1d23;
    --ink: #e9e9e4;
    --ink-soft: #b0b0a8;
    --ink-faint: #7d7e78;
    --rule: #2c2f37;
    --rule-soft: #23262d;
    --accent: #7fd0b6;
    --accent-soft: #22362f;
    --warn: #e0b163;
    --warn-soft: #352c19;
    --bad: #e08585;
    --bad-soft: #3a2222;
    --bar: #52a68d;
    --bar-soft: #232a28;
    --hm0: #22252b;
    --hm1: #24382f;
    --hm2: #2c5445;
    --hm3: #37765f;
    --hm4: #46997c;
    --hm5: #6fc4a6;
    --shadow: 0 1px 2px rgba(0, 0, 0, .3), 0 8px 24px rgba(0, 0, 0, .25);
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue",
        "Noto Sans", Arial, sans-serif;
  font-variant-numeric: tabular-nums;
}
main { max-width: 1040px; margin: 0 auto; padding: 40px 24px 96px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

.masthead { border-bottom: 2px solid var(--ink); padding-bottom: 18px; margin-bottom: 8px; }
.masthead h1 { font-size: 27px; line-height: 1.2; margin: 0 0 10px; letter-spacing: -.015em; }
.masthead .meta { color: var(--ink-soft); font-size: 14px; margin: 2px 0; }
.masthead .meta b { color: var(--ink); font-weight: 600; }
.flag {
  display: inline-block; margin-top: 12px; padding: 6px 11px; border-radius: 6px;
  background: var(--warn-soft); color: var(--warn); font-size: 13px; font-weight: 600;
}

.toc { margin: 22px 0 0; font-size: 13.5px; color: var(--ink-faint); }
.toc a { color: var(--ink-soft); }
.toc span { color: var(--rule); margin: 0 7px; }

section { margin-top: 46px; scroll-margin-top: 16px; }
section > h2 {
  font-size: 12.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  color: var(--ink-faint); margin: 0 0 4px; padding-bottom: 8px;
  border-bottom: 1px solid var(--rule);
}
section > h2 .den { float: right; letter-spacing: .02em; text-transform: none;
  font-weight: 500; color: var(--ink-faint); }
h3 { font-size: 15px; font-weight: 600; margin: 26px 0 10px; color: var(--ink); }
h3 .den { font-weight: 400; color: var(--ink-faint); font-size: 13px; margin-left: 6px; }

.banner {
  background: var(--panel); border: 1px solid var(--rule); border-radius: 8px;
  padding: 14px 16px; font-size: 14px; color: var(--ink-soft); box-shadow: var(--shadow);
}
.banner p { margin: 0 0 4px; }
.banner p:last-child { margin-bottom: 0; }
.banner b { color: var(--ink); font-weight: 600; }

.tldr {
  margin-top: 18px; padding: 15px 18px; border-left: 3px solid var(--accent);
  background: var(--accent-soft); border-radius: 0 8px 8px 0;
  font-size: 16px; line-height: 1.5; color: var(--ink);
}

.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(184px, 1fr));
  gap: 12px; margin-top: 6px; }
.stat { background: var(--panel); border: 1px solid var(--rule); border-radius: 8px;
  padding: 14px 16px; box-shadow: var(--shadow); }
.stat .k { font-size: 11.5px; letter-spacing: .06em; text-transform: uppercase;
  color: var(--ink-faint); }
.stat .v { font-size: 26px; font-weight: 650; letter-spacing: -.02em; margin-top: 4px;
  line-height: 1.15; }
.stat .sub { font-size: 12.5px; color: var(--ink-soft); margin-top: 3px; }
.stat.muted .v { font-size: 14px; font-weight: 500; color: var(--ink-faint);
  line-height: 1.4; letter-spacing: 0; }

table.data { width: 100%; border-collapse: collapse; font-size: 14px; }
table.data th {
  text-align: left; font-weight: 500; font-size: 11.5px; letter-spacing: .06em;
  text-transform: uppercase; color: var(--ink-faint); padding: 0 8px 6px 0;
  border-bottom: 1px solid var(--rule);
}
table.data th.num, table.data td.num { text-align: right; white-space: nowrap; }
table.data td { padding: 6px 8px 6px 0; border-bottom: 1px solid var(--rule-soft);
  vertical-align: middle; }
table.data tr:last-child td { border-bottom: 0; }
table.data td.label { max-width: 340px; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
table.data td.share { color: var(--ink-soft); width: 68px; }
table.data td.note { color: var(--ink-faint); font-size: 12.5px; }
table.data td.barcell { width: 34%; padding-right: 0; }
.bar { background: var(--bar-soft); border-radius: 3px; height: 9px; overflow: hidden; }
.bar > i { display: block; height: 100%; background: var(--bar); border-radius: 3px; }
.tail { color: var(--ink-faint); font-size: 13px; margin: 8px 0 0; }

.suppressed {
  border: 1px dashed var(--rule); border-radius: 8px; padding: 12px 15px;
  color: var(--ink-faint); font-size: 14px; background: var(--rule-soft);
}
.suppressed b { color: var(--ink-soft); }
ul.notes { list-style: none; margin: 10px 0 0; padding: 0; font-size: 13px;
  color: var(--ink-soft); }
ul.notes li { position: relative; padding-left: 18px; margin-bottom: 5px; }
ul.notes li::before { content: "!"; position: absolute; left: 4px; color: var(--warn);
  font-weight: 700; }
ul.notes li.plain::before { content: "\\2022"; color: var(--ink-faint); font-weight: 400; }
ul.notes li.bad::before { color: var(--bad); }
ul.notes li.bad { color: var(--bad); }

.ledger { width: 100%; border-collapse: collapse; font-size: 14px; }
.ledger td { padding: 5px 8px 5px 0; border-bottom: 1px solid var(--rule-soft); }
.ledger td.sign { width: 16px; color: var(--ink-faint); text-align: center; }
.ledger td.num { text-align: right; white-space: nowrap; }
.ledger td.share { text-align: right; color: var(--ink-soft); width: 68px; }
.ledger td.why { color: var(--ink-faint); font-size: 12.5px; }
.ledger td.barcell { width: 26%; }
.ledger tr.total td { border-bottom: 2px solid var(--rule); font-weight: 600; }
.ledger tr.result td { font-weight: 700; border-top: 2px solid var(--ink);
  border-bottom: 0; padding-top: 9px; }

figure.chart { margin: 0 0 18px; background: var(--panel); border: 1px solid var(--rule);
  border-radius: 8px; padding: 16px 16px 10px; box-shadow: var(--shadow); }
figure.chart svg { display: block; width: 100%; height: auto; }
figure.chart figcaption { font-size: 12.5px; color: var(--ink-faint); margin-top: 8px; }
.spark { display: inline-block; vertical-align: middle; width: 180px; height: 26px; }

table.heat { border-collapse: separate; border-spacing: 2px; font-size: 12px;
  margin-top: 4px; }
table.heat th { font-weight: 500; color: var(--ink-faint); font-size: 11px;
  padding: 0 6px 0 0; text-align: right; white-space: nowrap; }
table.heat thead th { text-align: center; padding: 0 0 3px; }
table.heat td { width: 22px; height: 20px; border-radius: 3px; background: var(--hm0); }
table.heat td.l1 { background: var(--hm1); }
table.heat td.l2 { background: var(--hm2); }
table.heat td.l3 { background: var(--hm3); }
table.heat td.l4 { background: var(--hm4); }
table.heat td.l5 { background: var(--hm5); }
table.heat td.pub { background: transparent; color: var(--accent); text-align: center;
  font-size: 11px; line-height: 1; height: 14px; }
.heatwrap { overflow-x: auto; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; align-items: center;
  font-size: 12.5px; color: var(--ink-soft); margin-top: 12px; }
.legend .sw { display: inline-block; width: 14px; height: 14px; border-radius: 3px;
  vertical-align: -3px; margin-right: 5px; }

.kv { font-size: 14px; }
.kv div { display: flex; gap: 14px; padding: 5px 0;
  border-bottom: 1px solid var(--rule-soft); }
.kv div:last-child { border-bottom: 0; }
.kv .k { flex: 0 0 300px; color: var(--ink-soft); }
.kv .v { font-weight: 600; white-space: nowrap; }
.kv .x { color: var(--ink-faint); font-weight: 400; }

footer { margin-top: 56px; padding-top: 20px; border-top: 1px solid var(--rule);
  font-size: 13px; color: var(--ink-faint); }
footer ul { list-style: none; margin: 0 0 14px; padding: 0; }
footer li { padding-left: 16px; position: relative; margin-bottom: 6px; }
footer li::before { content: "\\2022"; position: absolute; left: 2px; }

@media (max-width: 620px) {
  main { padding: 24px 14px 64px; }
  table.data td.barcell, table.data td.note { display: none; }
  .kv .k { flex: 0 0 160px; }
}
@media print {
  body { background: #fff; }
  section { break-inside: avoid; }
  .toc { display: none; }
}
"""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _pct(share: float | None) -> str:
    """'41.2%' or an em dash — the same withholding rule as the terminal."""
    if share is None:
        return "<span class=\"x\">—</span>"
    return f"{share * 100:.1f}%"


def _num(value: int | None) -> str:
    """A formatted integer, or an em dash for an honestly absent one."""
    return format_int(value) if value is not None else "—"


def _bar(value: int, maximum: int) -> str:
    """A pure-CSS bar scaled to the largest row, never to the total."""
    if maximum <= 0 or value <= 0:
        return ""
    width = max(1.0, min(100.0, value / maximum * 100.0))
    return f'<div class="bar"><i style="width:{width:.2f}%"></i></div>'


def _notes_list(notes: Iterable[str], *, plain: bool = False,
                bad: Sequence[str] = ()) -> str:
    """Footnotes under a section, in the same words as the terminal."""
    items = [n for n in notes if n]
    if not items:
        return ""
    bad_set = set(bad)
    rows = "".join(
        f'<li class="{"bad" if n in bad_set else ("plain" if plain else "")}">'
        f"{escape(n)}</li>"
        for n in items
    )
    return f'<ul class="notes">{rows}</ul>'


def _suppressed(reason: str | None) -> str:
    """The one shape a suppressed dimension is allowed to take. Never a zero."""
    text = reason or "not available for this range"
    return (f'<div class="suppressed"><b>Suppressed.</b> {escape(text)} '
            "— reported as unavailable rather than estimated.</div>")


def _section(anchor: str, heading: str, body: str, *, denominator: str = "") -> str:
    """One `<section>` with the exact heading text from section F."""
    den = f'<span class="den">{escape(denominator)}</span>' if denominator else ""
    return (f'<section id="{escape(anchor)}"><h2>{escape(heading)}{den}</h2>'
            f"{body}</section>")


def _stat(key: str, value: str, sub: str = "", *, muted: bool = False) -> str:
    """One headline tile. `muted` is how a suppressed metric shows its reason."""
    cls = "stat muted" if muted else "stat"
    sub_html = f'<div class="sub">{escape(sub)}</div>' if sub else ""
    return (f'<div class="{cls}"><div class="k">{escape(key)}</div>'
            f'<div class="v">{escape(value)}</div>{sub_html}</div>')


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


def _table(table: Table, *, heading_level: str = "h3") -> str:
    """Render one `Table`, honesty footnotes and all."""
    den = f"{table.denominator_label}, n = {format_int(table.n)}" \
        if table.denominator_label else f"n = {format_int(table.n)}"
    head = (f'<{heading_level}>{escape(table.title)}'
            f'<span class="den">{escape(den)}</span></{heading_level}>')

    if table.suppressed:
        return head + _suppressed(table.suppressed_reason) + _table_notes(table)
    if not table.rows:
        return head + '<div class="suppressed">No rows in this range.</div>' \
            + _table_notes(table)

    maximum = max(row.count for row in table.rows)
    has_secondary = any(row.secondary is not None for row in table.rows)
    secondary_label = next(
        (r.secondary_label for r in table.rows if r.secondary_label), ""
    ) or "secondary"
    has_note = any(row.note for row in table.rows)

    header = ["<th></th>", '<th class="num">count</th>', '<th class="num">share</th>']
    if has_secondary:
        header.insert(1, f'<th class="num">{escape(secondary_label)}</th>')
    if has_note:
        header.append("<th></th>")
    header.append("<th></th>")

    rows_html = []
    for row in table.rows:
        cells = [f'<td class="label" title="{escape(row.label)}">'
                 f"{escape(row.label)}</td>"]
        if has_secondary:
            cells.append(f'<td class="num">{_num(row.secondary)}</td>')
        cells.append(f'<td class="num">{format_int(row.count)}</td>')
        cells.append(f'<td class="num share">{_pct(row.share)}</td>')
        if has_note:
            cells.append(f'<td class="note">{escape(row.note or "")}</td>')
        cells.append(f'<td class="barcell">{_bar(row.count, maximum)}</td>')
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    tail = ""
    if table.tail_count > 0:
        share = format_share(table.tail_share)
        share_txt = f", {share[1:-1]}" if share else ""
        tail = (f'<p class="tail">+{table.tail_count} more '
                f"({format_int(table.tail_total)} "
                f"{escape(_unit(table.denominator_label))}{share_txt})</p>")

    return (head + '<table class="data"><thead><tr>' + "".join(header)
            + "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
            + tail + _table_notes(table))


def _table_notes(table: Table) -> str:
    """Render the honesty footnotes `aggregate.py` attached to this table.

    Derives nothing of its own. This function used to recompute the unknown-bias
    and long-tail notes at a different precision from `aggregate.py`, so every
    affected table carried both versions — the reader saw 'unknown is 100%' and
    'unknown is 99.9%' about the same column, one line apart. The statistics have
    one home; this decides only which of them are shown in the warning style.
    """
    notes = list(table.warnings)
    bad = [note for note in notes if note.startswith(("unknown is", "n = "))]
    return _notes_list(notes, bad=bad)


def _tables(tables: Sequence[Table]) -> str:
    """Several tables in one section, in the order section F gives them."""
    return "".join(_table(t) for t in tables if t is not None)


def _matrix(matrix: Matrix) -> str:
    """The language x locale cross-tab. The signal is in the off-diagonals."""
    head = (f"<h3>{escape(matrix.title)}"
            f'<span class="den">n = {format_int(matrix.n)}</span></h3>')
    if matrix.suppressed:
        return head + _suppressed(matrix.suppressed_reason) \
            + _notes_list(matrix.notes)
    if not matrix.row_labels:
        return head + '<div class="suppressed">No rows in this range.</div>'

    header = ["<th>language</th>"]
    header += [f'<th class="num">{escape(c)}</th>' for c in matrix.col_labels]
    header += ['<th class="num">total</th>', '<th class="num">share</th>',
               "<th>&rarr; prefers</th>"]

    rows_html = []
    for idx, label in enumerate(matrix.row_labels):
        cells = matrix.cells[idx] if idx < len(matrix.cells) else ()
        total = matrix.row_totals[idx] if idx < len(matrix.row_totals) else 0
        share = matrix.row_shares[idx] if idx < len(matrix.row_shares) else None
        pref = matrix.preference[idx] if idx < len(matrix.preference) else ""
        tds = [f'<td class="label">{escape(label)}</td>']
        tds += [f'<td class="num">{format_int(c)}</td>' for c in cells]
        tds.append(f'<td class="num">{format_int(total)}</td>')
        tds.append(f'<td class="num share">{_pct(share)}</td>')
        tds.append(f"<td>{escape(pref)}</td>")
        rows_html.append("<tr>" + "".join(tds) + "</tr>")

    return (head + '<table class="data"><thead><tr>' + "".join(header)
            + "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
            + _notes_list(matrix.notes))


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------


def _ledger(ledger: Ledger, *, total: int) -> str:
    """The composition audit as a waterfall: every subtraction, visible."""
    try:
        steps = list(ledger.steps())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("ledger.steps() failed: %s", exc)
        return '<div class="suppressed">Ledger unavailable.</div>'
    if not steps:
        return '<div class="suppressed">Ledger empty.</div>'

    maximum = max((abs(c) for _, c, _ in steps), default=0)
    last = len(steps) - 1
    rows = []
    for idx, (label, count, share) in enumerate(steps):
        if idx == 0:
            sign, cls, shown = "", "total", format_int(count)
        elif idx == last:
            sign, cls, shown = "=", "result", format_int(count)
        else:
            sign, cls, shown = "−", "", format_int(-abs(count))
        why = _ledger_note(label)
        rows.append(
            f'<tr class="{cls}"><td class="sign">{sign}</td>'
            f"<td>{escape(label)}</td>"
            f'<td class="num">{shown}</td>'
            f'<td class="share">{_pct(share)}</td>'
            f'<td class="why">{escape(why)}</td>'
            f'<td class="barcell">{_bar(abs(count), maximum)}</td></tr>'
        )
    return f'<table class="ledger"><tbody>{"".join(rows)}</tbody></table>'


# --------------------------------------------------------------------------
# Charts — inline SVG, no library, no external anything
# --------------------------------------------------------------------------


def _series_chart(series: Series) -> str:
    """An area-plus-line trend over the bucket series.

    Holes (buckets with nothing ingested) break the path rather than being drawn
    at zero: a gap in the data and a genuine zero are different claims, and a
    chart that renders them the same way is lying quietly.
    """
    points = [p for p in series.points]
    if not points:
        return ""
    width, height, pad = 960.0, 190.0, 26.0
    values = [0 if p.hole else p.pageviews for p in points]
    top = max(values) or 1
    step = (width - pad * 2) / max(1, len(points) - 1) if len(points) > 1 else 0.0

    def x(i: int) -> float:
        return pad + step * i if len(points) > 1 else width / 2

    def y(v: int) -> float:
        return height - pad - (v / top) * (height - pad * 2)

    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for i, point in enumerate(points):
        if point.hole:
            if current:
                segments.append(current)
                current = []
            continue
        current.append((x(i), y(point.pageviews)))
    if current:
        segments.append(current)

    paths = []
    for segment in segments:
        if len(segment) == 1:
            cx, cy = segment[0]
            paths.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.6" '
                         'fill="var(--bar)"/>')
            continue
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in segment)
        area = (d + f" L{segment[-1][0]:.1f},{height - pad:.1f}"
                f" L{segment[0][0]:.1f},{height - pad:.1f} Z")
        paths.append(f'<path d="{area}" fill="var(--bar)" opacity=".14"/>')
        paths.append(f'<path d="{d}" fill="none" stroke="var(--bar)" '
                     'stroke-width="2" stroke-linejoin="round" '
                     'stroke-linecap="round"/>')

    for i, point in enumerate(points):
        if point.partial and not point.hole:
            paths.append(
                f'<circle cx="{x(i):.1f}" cy="{y(point.pageviews):.1f}" r="3.4" '
                'fill="var(--bg)" stroke="var(--bar)" stroke-width="2"/>'
            )

    gridline = (f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" '
                f'y2="{height - pad}" stroke="var(--rule)" stroke-width="1"/>')
    label_top = (f'<text x="{pad}" y="{pad - 8}" fill="var(--ink-faint)" '
                 f'font-size="12">peak {format_int(top)} pageviews</text>')
    first = escape(points[0].label)
    last = escape(points[-1].label)
    axis = (f'<text x="{pad}" y="{height - 6}" fill="var(--ink-faint)" '
            f'font-size="12">{first}</text>'
            f'<text x="{width - pad}" y="{height - 6}" fill="var(--ink-faint)" '
            f'font-size="12" text-anchor="end">{last}</text>')

    caption = (f"{len(points)} {escape(series.bucket)} buckets; hollow markers are "
               "partial periods, gaps are periods with nothing ingested — neither "
               "is extrapolated.")
    return (f'<figure class="chart"><svg viewBox="0 0 {width:.0f} {height:.0f}" '
            f'role="img" aria-label="{escape(series.title)}" '
            'preserveAspectRatio="none" height="190">'
            + gridline + "".join(paths) + label_top + axis
            + f"</svg><figcaption>{caption}</figcaption></figure>")


def _spark_svg(values: Sequence[int]) -> str:
    """A tiny inline sparkline for the all-time strip."""
    values = [v for v in values]
    if len(values) < 2:
        return ""
    width, height = 180.0, 26.0
    top = max(values) or 1
    step = width / (len(values) - 1)
    pts = " ".join(
        f"{i * step:.1f},{height - 2 - (v / top) * (height - 4):.1f}"
        for i, v in enumerate(values)
    )
    return (f'<svg class="spark" viewBox="0 0 {width:.0f} {height:.0f}" '
            'preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="var(--bar)" '
            'stroke-width="1.6" stroke-linejoin="round"/></svg>')


def _series_table(series: Series) -> str:
    """The per-bucket numbers behind the chart, with the honesty suffixes."""
    if not series.points:
        return '<div class="suppressed">No periods in this range.</div>'
    rows = []
    for point in series.points:
        label = escape(point.label)
        if point.hole:
            label += ' <span class="x">(no data)</span>'
            cells = ('<td class="num">—</td><td class="num">—</td>'
                     '<td class="num">—</td>')
        else:
            if point.partial:
                label += ' <span class="x">(partial)</span>'
            cells = (f'<td class="num">{format_int(point.pageviews)}</td>'
                     f'<td class="num">{_num(point.sessions)}</td>'
                     f'<td class="num">{_num(point.visitors)}</td>')
        rows.append(f'<tr><td class="label">{label}</td>{cells}</tr>')
    return ('<table class="data"><thead><tr><th>period</th>'
            '<th class="num">pageviews</th><th class="num">sessions</th>'
            '<th class="num">visitors</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def _comparison(series: Series) -> str:
    """Period-over-period, from complete buckets only."""
    comparison = series.compare
    if comparison is None or not comparison.metrics:
        return ""
    rows = []
    for name, current, previous, delta in comparison.metrics:
        if delta is None:
            change = '<span class="x">—</span>'
        else:
            sign = "+" if delta > 0 else ("−" if delta < 0 else "")
            change = f"{sign}{abs(delta) * 100:.1f}%"
        rows.append(f'<tr><td class="label">{escape(name)}</td>'
                    f'<td class="num">{format_int(previous)}</td>'
                    f'<td class="num">{format_int(current)}</td>'
                    f'<td class="num">{change}</td></tr>')
    return ("<h3>Period over period"
            f'<span class="den">{escape(comparison.previous_label)} '
            f'&rarr; {escape(comparison.current_label)}, complete periods only'
            "</span></h3>"
            '<table class="data"><thead><tr><th>metric</th>'
            '<th class="num">previous</th><th class="num">current</th>'
            '<th class="num">change</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def _heatmap(heatmap: Heatmap) -> str:
    """7x24 shaded grid on the quantile scale, with the publish row beneath."""
    if heatmap.suppressed:
        return _suppressed(heatmap.suppressed_reason)
    values = heatmap.values or ()
    if not values or not any(any(r) for r in values):
        return '<div class="suppressed">No activity in this range.</div>'

    cuts = _heatmap_cuts(heatmap.thresholds, values)
    header = "".join(
        f'<th>{h:02d}</th>' if h % 3 == 0 else "<th></th>" for h in range(24)
    )
    body = []
    for idx, row in enumerate(values[:7]):
        name = _WEEKDAYS[idx] if idx < len(_WEEKDAYS) else f"d{idx}"
        cells = []
        for hour, value in enumerate(list(row)[:24]):
            level = _level(value, cuts)
            cells.append(f'<td class="l{level}" '
                         f'title="{name} {hour:02d}:00 — {format_int(value)}"></td>')
        body.append(f"<tr><th>{name}</th>" + "".join(cells) + "</tr>")

    pub_hours = {h for _, h in heatmap.publish_marks if 0 <= h < 24}
    pub_row = ""
    if pub_hours:
        pub_cells = "".join(
            f'<td class="pub">{"&#9650;" if h in pub_hours else ""}</td>'
            for h in range(24)
        )
        pub_row = f'<tr><th>published</th>{pub_cells}</tr>'

    swatches = []
    low = 1
    for level in range(1, min(len(cuts), _HEATMAP_LEVELS - 1) + 1):
        cut = cuts[level - 1]
        swatches.append(f'<span><i class="sw" style="background:var(--hm{level})">'
                        f"</i>{low}&ndash;{cut}</span>")
        low = cut + 1
    top_level = min(len(cuts) + 1, _HEATMAP_LEVELS)
    swatches.insert(0, '<span><i class="sw" style="background:var(--hm0)"></i>0</span>')
    swatches.append(f'<span><i class="sw" style="background:var(--hm{top_level})">'
                    f"</i>{low}+</span>")

    legend = ('<div class="legend"><b>quantile scale:</b>'
              + "".join(swatches) + "</div>")
    return ('<div class="heatwrap"><table class="heat"><thead><tr><th></th>'
            + header + "</tr></thead><tbody>" + "".join(body) + pub_row
            + "</tbody></table></div>" + legend + _notes_list(heatmap.notes))


def _level(value: int, cuts: Sequence[int]) -> int:
    """0 for a genuine zero; otherwise the shade band the value falls in."""
    if value <= 0:
        return 0
    return min(bisect.bisect_left(list(cuts), value) + 1, _HEATMAP_LEVELS)


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------


def _masthead(report: Report) -> str:
    """Who, what window, from which source, in which timezone."""
    days = max(1, (report.until.date() - report.since.date()).days + 1)
    span = (f"{report.since:%d %b} – {report.until:%d %b %Y} "
            f"({days} day{'s' if days != 1 else ''})")
    if report.tz_fallback:
        tz = f"times in UTC (tzdata missing — {report.tz_name} unavailable)"
    else:
        tz = f"times in {report.tz_name}"
    sources = tuple(report.sources or ())
    if sources == ("<store>",):
        source = "analytics store"
    elif len(sources) == 1:
        source = sources[0]
    else:
        source = f"{len(sources)} log files"
    formats = ", ".join(sorted(report.formats_seen)) or "none"

    flags = []
    if report.include_bots:
        flags.append('<div class="flag">INCLUDING BOTS AND AGENTS — these are not '
                     "audience numbers</div>")
    if report.host_filter and "all" in {h.lower() for h in report.host_filter}:
        flags.append('<div class="flag">HOST FILTER DISABLED — other vhosts on this '
                     "box are included</div>")
    if report.hard_only:
        flags.append('<div class="flag">HARD NAVIGATIONS ONLY — client-routed '
                     "pageviews excluded</div>")

    return (
        '<header class="masthead">'
        "<h1>CyberAlertX — audience report</h1>"
        f'<p class="meta"><b>{escape(span)}</b> · {escape(tz)}</p>'
        f'<p class="meta">source: {escape(source)} · format: {escape(formats)}'
        f" · generated {report.generated_at:%d %b %Y %H:%M}"
        f" · v{escape(report.tool_version)}</p>"
        + "".join(flags) + "</header>"
    )


def _toc() -> str:
    """A compact jump list — the document is long and the reader has a question."""
    entries = [
        ("coverage", "Coverage"), ("quality", "Data quality"),
        ("glance", "At a glance"), ("traffic", "Over time"),
        ("country", "Country"), ("language", "Language × edition"),
        ("acquisition", "Acquisition"), ("device", "Device"),
        ("content", "Content"), ("when", "When they read"),
        ("health", "Technical health"), ("automated", "Automated"),
        ("security", "Security noise"),
    ]
    links = '<span>·</span>'.join(
        f'<a href="#{a}">{escape(t)}</a>' for a, t in entries
    )
    return f'<nav class="toc">{links}</nav>'


def _coverage(coverage: Coverage) -> str:
    """The mandatory banner, never omitted, naming the exact gaps."""
    lines: list[str] = []
    banner = (coverage.banner or "").strip()
    if banner:
        lines.extend(banner.splitlines())
    elif coverage.first_date and coverage.last_date:
        lines.append(f"{coverage.first_date:%d %b} – {coverage.last_date:%d %b %Y} · "
                     f"{coverage.days_present} days, "
                     f"{len(coverage.days_missing)} missing")
    else:
        lines.append("no data held for this range")
    if coverage.dimensions_absent:
        lines.append("unavailable for the whole range: "
                     + ", ".join(sorted(coverage.dimensions_absent)))
    for dim in sorted(coverage.dimensions_partial):
        first, last = coverage.dimensions_partial[dim]
        lines.append(f"{dim} available only {first} – {last}")
    body = "".join(f"<p>{escape(line)}</p>" for line in lines if line.strip())
    return f'<div class="banner">{body}</div>'


def _glance(report: Report) -> str:
    """Headline tiles, then the TL;DR — the finding, surfaced not buried."""
    head = report.headline
    absent = report.coverage.dimensions_absent
    suffix = "(BOTS INCLUDED)" if report.include_bots else "(bots excluded)"

    tiles: list[str] = []
    if head.visitors is None:
        tiles.append(_stat(f"visitors {suffix}",
                           _SUPPRESSION_REASONS.get("visitor", "unavailable"),
                           "suppressed, never estimated", muted=True))
    else:
        tiles.append(_stat(f"visitors {suffix}", format_int(head.visitors)))

    tiles.append(_stat("sessions", _num(head.sessions))
                 if head.sessions is not None else
                 _stat("sessions", _SUPPRESSION_REASONS.get("visitor", "unavailable"),
                       "needs visitor identity", muted=True))
    tiles.append(_stat("pageviews", format_int(head.pageviews),
                       f"hard {format_int(head.pageviews_hard)} · "
                       f"soft {format_int(head.pageviews_soft)}"))

    if head.pages_per_visit_mean is not None or head.pages_per_visit_median is not None:
        mean = (f"{head.pages_per_visit_mean:.1f}"
                if head.pages_per_visit_mean is not None else "—")
        median = (f"{head.pages_per_visit_median:.1f} median"
                  if head.pages_per_visit_median is not None else "")
        tiles.append(_stat("pages / visit", mean, median))
    if head.bounce_rate is not None:
        ci = f"±{head.bounce_ci_pp:.1f}pp · " if head.bounce_ci_pp is not None else ""
        tiles.append(_stat("bounce rate", f"{head.bounce_rate * 100:.1f}%",
                           f"{ci}upper bound"))
    if head.span_mean_seconds is not None:
        median = (f"{format_duration(head.span_median_seconds)} median · "
                  if head.span_median_seconds is not None else "")
        tiles.append(_stat("measured span",
                           format_duration(head.span_mean_seconds),
                           f"{median}engaged visits (≥ 2 pageviews)"))
    if head.engaged_sessions is not None:
        tiles.append(_stat("engaged sessions", format_int(head.engaged_sessions)))
    if head.same_day_returns is not None:
        tiles.append(_stat("same-day returns", format_int(head.same_day_returns),
                           "cross-day identity is not computable by design"))

    if absent:
        tiles.append(_stat("not measurable in this range",
                           ", ".join(sorted(absent)),
                           "see DATA COVERAGE", muted=True))
    tldr = f'<div class="tldr">{escape(head.tldr)}</div>' if head.tldr else ""
    return f'<div class="stats">{"".join(tiles)}</div>{tldr}'


def _latency(latency: LatencyStats) -> str:
    """Percentiles only. A mean is one upstream timeout away from meaningless."""
    if latency.suppressed:
        return _suppressed(latency.suppressed_reason)
    rows = [
        ("request time", latency.p50, latency.p90, latency.p99),
        ("upstream time", latency.upstream_p50, latency.upstream_p90,
         latency.upstream_p99),
    ]
    body = "".join(
        f'<tr><td class="label">{escape(name)}</td>'
        f'<td class="num">{format_seconds(p50)}</td>'
        f'<td class="num">{format_seconds(p90)}</td>'
        f'<td class="num">{format_seconds(p99)}</td></tr>'
        for name, p50, p90, p99 in rows
    )
    note = ("$request_time on a proxied response includes streaming to a slow "
            "client, so a mobile user on bad signal inflates it without the server "
            "being slow — the gap between request and upstream time is the "
            "client-network story.")
    return ("<h3>Latency"
            f'<span class="den">n = {format_int(latency.n)} requests · '
            f"{escape(format_bytes(latency.bytes_total))} served</span></h3>"
            '<table class="data"><thead><tr><th></th><th class="num">p50</th>'
            '<th class="num">p90</th><th class="num">p99</th></tr></thead>'
            f"<tbody>{body}</tbody></table>" + _notes_list([note], plain=True))


def _security(noise: SecurityNoise) -> str:
    """Six facts that keep the discard filter auditable."""
    def line(key: str, value: str, extra: str = "") -> str:
        extra_html = f'<span class="x">{escape(extra)}</span>' if extra else ""
        return (f'<div><span class="k">{escape(key)}</span>'
                f'<span class="v">{escape(value)}</span>{extra_html}</div>')

    def inline(rows: Sequence[object], limit: int) -> str:
        return ", ".join(
            f"{getattr(r, 'label', '')} ({format_int(int(getattr(r, 'count', 0)))})"
            for r in list(rows)[:limit]
        )

    body = [
        line("noise hits", format_int(noise.total_hits),
             (f"from {format_int(noise.distinct_sources)} distinct sources"
              if noise.distinct_sources is not None
              else "from an unknown number of sources (none stored; --from-logs)")),
        line("direct-to-origin (never traversed Cloudflare)",
             format_int(noise.direct_to_origin), "someone has the origin IP"),
        line("forged crawlers (declared, arrived outside CF)",
             format_int(noise.forged_crawlers), inline(noise.forged_top_uas, 3)),
        line("malformed requests (raw TLS bytes, empty target)",
             format_int(noise.malformed_requests)),
    ]
    if noise.top_paths:
        body.append(line("top probed paths", "", inline(noise.top_paths, 6)))
    if noise.top_countries:
        body.append(line("top source countries", "", inline(noise.top_countries, 5)))
    return (f'<div class="kv">{"".join(body)}</div>'
            + _notes_list(noise.notes, plain=True))


def _footer(report: Report) -> str:
    """Warnings, then the standing caveats — printed once, never per section."""
    warnings = _notes_list(report.warnings)
    notes = "".join(f"<li>{escape(n)}</li>" for n in report.notes)
    return (f"<footer>{warnings}<ul>{notes}</ul>"
            f'<p>CyberAlertX analytics v{escape(report.tool_version)} · '
            f"rendered {report.generated_at:%d %b %Y %H:%M} · "
            "this file is self-contained and makes no network requests.</p>"
            "</footer>")


# --------------------------------------------------------------------------
# Document
# --------------------------------------------------------------------------


def render_html(report: Report) -> str:
    """One complete, self-contained HTML document as a string.

    Inline `<style>`, inline `<svg>`, no external script, link, font or image —
    zero network requests of any kind at view time. Mirrors the terminal section
    order and heading text exactly, so the two renderers cannot drift.
    """
    parts: list[str] = [_masthead(report), _toc()]

    def add(anchor: str, heading: str, body: object, *, denominator: str = "") -> None:
        """Emit a section, isolating any failure to that section alone."""
        try:
            html_body = body() if callable(body) else str(body)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("html section %s failed: %s", heading, exc)
            html_body = ('<div class="suppressed">Section unavailable: '
                         f"{escape(exc)}</div>")
        parts.append(_section(anchor, heading, html_body, denominator=denominator))

    add("coverage", H_COVERAGE, lambda: _coverage(report.coverage))
    add("quality", H_QUALITY,
        lambda: _ledger(report.ledger, total=report.ledger.total_lines),
        denominator=(f"{format_int(report.ledger.total_lines)} log lines → "
                     f"{format_int(report.headline.pageviews)} human pageviews"))
    add("glance", H_GLANCE, lambda: _glance(report),
        denominator=(f"n = {format_int(report.headline.sessions)} sessions"
                     if report.headline.sessions is not None else ""))
    add("traffic", H_TRAFFIC,
        lambda: (_series_chart(report.timeseries)
                 + _series_table(report.timeseries)
                 + _notes_list(report.timeseries.notes)
                 + _comparison(report.timeseries)),
        denominator=(f"{report.timeseries.bucket}, "
                     f"n = {format_int(report.headline.pageviews)} pageviews"))
    if report.all_time is not None:
        add("alltime", H_ALLTIME,
            lambda: (_spark_svg(report.all_time.sparkline)
                     + _series_chart(report.all_time)
                     + _series_table(report.all_time)
                     + _notes_list(report.all_time.notes)))
    add("country", H_COUNTRY, lambda: _table(report.countries))
    add("language", H_LANGUAGE,
        lambda: _matrix(report.language_locale) + _table(report.languages))
    add("acquisition", H_ACQUISITION,
        lambda: _tables([report.channels, report.campaigns, report.referrers]))
    add("device", H_DEVICE, lambda: _tables([
        report.device_types, report.vendors, report.models, report.os_families,
        report.os_versions, report.browsers, report.in_app]))
    add("content", H_CONTENT, lambda: _tables([
        report.top_articles, report.entry_pages, report.locales,
        report.broken_links, report.not_found]))
    add("when", H_WHEN, lambda: _heatmap(report.heatmap),
        denominator=f"{report.heatmap.unit}/hour, {effective_tz_name(report)}")
    add("health", H_HEALTH,
        lambda: (_table(report.status_codes) + _latency(report.latency)
                 + _table(report.slowest_routes)))
    add("automated", H_AUTOMATED,
        lambda: (_notes_list([_BOT_FRAMING], plain=True)
                 + _tables([report.bot_labels, report.bot_categories,
                            report.agent_reach, report.feed_subscribers,
                            report.suspected_automation])),
        denominator="appendix, by request")
    add("security", H_SECURITY, lambda: _security(report.security),
        denominator="appendix")
    add("notes", H_NOTES, lambda: _footer(report))

    body = "".join(parts)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>CyberAlertX — audience report</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n<main>{body}</main>\n"
        "</body>\n</html>\n"
    )


def write_html(report: Report, path: Path) -> Path:
    """Write the report to `path` atomically, returning the resolved path.

    Atomic because a half-written report opened in a browser looks like a broken
    tool: the document goes to a temporary file in the destination directory and
    is then moved into place with `os.replace`, matching the house rule in
    `json_store.py` and `metrics.py`.

    A relative path is resolved inside the repository and refused if it escapes;
    an absolute path is taken as the caller's explicit consent to write there.
    """
    target = Path(path)
    if not target.is_absolute():
        target = (REPO_ROOT / target).resolve()
        try:
            target.relative_to(REPO_ROOT)
        except ValueError:
            raise ValueError(
                f"refusing to write outside the repository: {target}. "
                "Pass an absolute path to write there deliberately."
            ) from None
    else:
        target = target.resolve()

    target.parent.mkdir(parents=True, exist_ok=True)
    document = render_html(report)

    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(target.parent),
        prefix=f".{target.name}.", suffix=".tmp", delete=False,
    )
    tmp_path = Path(handle.name)
    try:
        with handle:
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    logger.info("wrote HTML report to %s (%d bytes)", target, len(document))
    return target
