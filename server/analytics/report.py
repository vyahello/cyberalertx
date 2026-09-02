"""Fixed-width terminal rendering of an analytics `Report`.

Turns the `Report` dataclass built by `aggregate.py` into one string, in the
exact section order and with the exact heading text of the contract's section F.
This module counts nothing and decides nothing: every number it prints was
already computed, suppressed or labelled upstream, and every honesty rule it
appears to enforce (percentages withheld below the sample floor, `+N more`
tails, `unknown` kept in its natural rank position) is really just faithful
rendering of what `aggregate.py` put in the `Row`, `Table` and `Coverage`
objects. If a share is `None` here, it stays blank here.

Three rendering hazards are handled up front, because each of them fails at the
very end of a long run, after all the parsing work is already done:

  * A block glyph written to a terminal whose encoding is not UTF-8 raises
    `UnicodeEncodeError` and kills the process. `supports_unicode` probes the
    stream and `render` folds its whole output down to ASCII when the answer is
    no, so the report degrades into hashes and dashes instead of a traceback.
  * Colour on a light terminal. Only the eight basic ANSI colours plus bold and
    dim are used, so the terminal's own theme decides the actual shade, and
    every meaning colour carries is also carried by text or position — piping
    the report through `less` or into a file loses nothing but the paint.
  * Bars scaled to the column total rather than to the largest row, which turns
    every row of a long-tailed distribution into an indistinguishable stub.
    `render_bar` scales to the table maximum and resolves to 1/8 of a cell,
    because with a 24-cell bar whole blocks quantise at roughly 4% and all the
    small rows would otherwise render identically.

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
import logging
import os
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Sequence, TextIO

from .aggregate import (
    Coverage,
    Headline,
    Heatmap,
    LatencyStats,
    Matrix,
    Report,
    SecurityNoise,
    Series,
    Table,
)
from .sessionize import Ledger

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

logger = logging.getLogger("analytics.report")

# --------------------------------------------------------------------------
# Glyphs. Every non-ASCII character this module can emit appears in _ASCII_FOLD
# below, so the ASCII fallback is total rather than best-effort.
# --------------------------------------------------------------------------

_BAR_FULL = "█"                                    # full block
_BAR_PARTIALS = ("", "▏", "▎", "▍",      # 1/8 .. 7/8
                 "▌", "▋", "▊", "▉")
_SPARK = "▁▂▃▄▅▆▇█"
_SPARK_ASCII = "_.-:=+*#"
_SHADES = ("·", "░", "▒", "▓", _BAR_FULL)
_SHADES_ASCII = (".", ":", "+", "#", "@")
_RULE = "━"
_RULE_ASCII = "="

_ASCII_FOLD = str.maketrans({
    "━": "=", "─": "-", "│": "|",
    "█": "#", "▓": "#", "▒": "+", "░": ":", "·": ".",
    "▏": "=", "▎": "=", "▍": "=", "▌": "=",
    "▋": "=", "▊": "=", "▉": "=",
    "▁": "_", "▂": ".", "▃": "-", "▄": ":",
    "▅": "=", "▆": "+", "▇": "*",
    "—": "-", "–": "-", "−": "-", "→": "->",
    "←": "<-", "…": "...", "×": "x",
    "▸": ">", "▲": "^", "±": "+/-", "≥": ">=",
    "≤": "<=", "’": "'", "“": '"', "”": '"',
    " ": " ", "•": "*",
})

# Reasons a headline metric is missing. `Headline` carries the value or None;
# the *why* is a property of the range, and lives in Coverage.dimensions_absent.
# Kept here rather than in aggregate because these are display strings.
_SUPPRESSION_REASONS: dict[str, str] = {
    "visitor": "legacy logs record Cloudflare edge IPs, not visitors",
    "country": "no CF-IPCountry header in the legacy format",
    "language": "no Accept-Language in the legacy format",
    "client_hints": "no client hints in the legacy format",
    "rsc": "no Next-Router-Prefetch header in the legacy format",
    "timing": "no request/upstream timing in the legacy format",
    "host": "the legacy format logs no $host",
}

# Trailing annotations for the data-quality ledger. Keyed by a substring of the
# label that `Ledger.steps()` produces, so a wording tweak upstream degrades to
# "no annotation" rather than to a wrong one.
_LEDGER_NOTES: tuple[tuple[str, str], ...] = (
    ("direct-to-origin", "never traversed Cloudflare"),
    ("forged", "claimed a crawler, came direct"),
    ("scanner", "see security appendix"),
    ("health", "/healthz wears a browser UA"),
    ("own publishing", "the site's own posts"),
    ("unfurl", "someone pasted a link"),
    ("reach", "someone pasted a link"),
    ("feed readers", "subscribers, not visits"),
    ("declared bots", "see automated appendix"),
    ("suspected automation", "browser UA, zero assets, at volume"),
    ("prefetch", "the locale switcher"),
)

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Section headings, verbatim from section F. Both renderers import these, so
# the terminal and HTML reports cannot drift apart.
H_COVERAGE = "DATA COVERAGE"
H_QUALITY = "DATA QUALITY"
H_GLANCE = "AUDIENCE AT A GLANCE"
H_TRAFFIC = "TRAFFIC OVER TIME"
H_ALLTIME = "ALL-TIME SUMMARY"
H_COUNTRY = "COUNTRY"
H_LANGUAGE = "BROWSER LANGUAGE × EDITION READ"
H_ACQUISITION = "ACQUISITION"
H_DEVICE = "DEVICE, OS & BROWSER"
H_CONTENT = "CONTENT"
H_WHEN = "WHEN THEY READ"
H_HEALTH = "TECHNICAL HEALTH"
H_AUTOMATED = "AUTOMATED TRAFFIC"
H_SECURITY = "SECURITY NOISE"
H_NOTES = "NOTES"

_BOT_FRAMING = (
    "These are X% of requests reaching the origin, not X% of traffic "
    "— Cloudflare's managed rules (and Bot Fight Mode, if enabled) drop "
    "the worst before it ever gets here."
)

_MIN_WIDTH = 80
_MAX_WIDTH = 120
_LABEL_MAX = 22
_BAR_MAX = 28


# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Palette:
    """ANSI codes, or empty strings when colour is off.

    Only the eight basic colours plus bold and dim. The basic set is remapped by
    the user's terminal theme, so it stays legible on light *and* dark
    backgrounds; hardcoded truecolour greys are the classic "invisible on a
    light terminal" bug.
    """

    reset: str = ""
    bold: str = ""
    dim: str = ""
    red: str = ""
    yellow: str = ""
    green: str = ""
    blue: str = ""
    cyan: str = ""
    magenta: str = ""

    @classmethod
    def plain(cls) -> "Palette":
        """The no-colour palette: every code is the empty string."""
        return cls()

    @classmethod
    def ansi(cls) -> "Palette":
        """The eight basic ANSI colours plus bold and dim."""
        return cls(
            reset="\033[0m",
            bold="\033[1m",
            dim="\033[2m",
            red="\033[31m",
            yellow="\033[33m",
            green="\033[32m",
            blue="\033[34m",
            cyan="\033[36m",
            magenta="\033[35m",
        )

    @property
    def enabled(self) -> bool:
        """True when this palette actually emits escape codes."""
        return bool(self.reset)

    def paint(self, text: str, code: str) -> str:
        """Wrap `text` in `code`, or return it untouched when colour is off."""
        if not code or not self.reset:
            return text
        return f"{code}{text}{self.reset}"


# --------------------------------------------------------------------------
# Capability probes
# --------------------------------------------------------------------------


def supports_color(stream: TextIO) -> bool:
    """Decide whether ANSI colour is safe on `stream`.

    False when the stream is not a TTY, when NO_COLOR is set (by PRESENCE, any
    value, per no-color.org), or when TERM is `dumb`. The caller's --no-color
    and --color flags are applied on top of this by `render`.
    """
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    try:
        return bool(stream.isatty())
    except Exception:  # pragma: no cover - exotic stream objects
        return False


def supports_unicode(stream: TextIO) -> bool:
    """Decide whether block glyphs can be written to `stream` without raising.

    Writing `█` to a POSIX-locale terminal raises UnicodeEncodeError and
    kills the script at the very end, after every log line has already been
    parsed. This guard is mandatory, not cosmetic.
    """
    encoding = getattr(stream, "encoding", None) or ""
    if not encoding:
        return False
    normalised = encoding.lower().replace("-", "").replace("_", "")
    if normalised.startswith("utf"):
        return True
    # Some terminals report a codec that happens to cover the glyphs anyway.
    try:
        _BAR_FULL.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def terminal_width(fallback: int = 100) -> int:
    """Usable report width, clamped to [80, 120].

    300-character bars on a maximised terminal are harder to read, not easier:
    the eye cannot compare two rows whose difference is spread across half a
    metre of screen.
    """
    try:
        columns = shutil.get_terminal_size(fallback=(fallback, 40)).columns
    except Exception:  # pragma: no cover - no controlling terminal
        columns = fallback
    return max(_MIN_WIDTH, min(_MAX_WIDTH, columns))


# --------------------------------------------------------------------------
# Formatting primitives
# --------------------------------------------------------------------------


def format_int(n: int) -> str:
    """Space-separated thousands, e.g. '412 880'. Never locale-dependent."""
    return f"{n:,}".replace(",", " ")


def format_share(share: float | None) -> str:
    """'(41.2%)', or '' when statistical honesty forbids a percentage."""
    if share is None:
        return ""
    return f"({share * 100:.1f}%)"


def format_duration(seconds: float) -> str:
    """'41s', '3m 41s', '1h 04m'. Rounds down to whole seconds."""
    total = int(max(0.0, seconds))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60:02d}s"
    return f"{total // 3600}h {(total % 3600) // 60:02d}m"


def format_bytes(n: int) -> str:
    """Human byte size with a binary base, e.g. '412.8 MB'."""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"  # pragma: no cover - unreachable


def format_seconds(value: float | None) -> str:
    """Latency in seconds with millisecond resolution, or an em dash."""
    if value is None:
        return "—"
    if value < 1:
        return f"{value * 1000:.0f}ms"
    return f"{value:.2f}s"


def _dash(value: object) -> str:
    """Render an absent number as an em dash rather than as a misleading zero."""
    if value is None:
        return "—"
    if isinstance(value, int):
        return format_int(value)
    return str(value)


def _truncate(text: str, width: int) -> str:
    """Clip `text` to `width` cells, marking the clip with an ellipsis."""
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


def _wrap(text: str, width: int, *, indent: str = "  ", hanging: str | None = None) -> list[str]:
    """Wrap prose to `width`, with an optional deeper continuation indent."""
    subsequent = hanging if hanging is not None else indent
    body_width = max(20, width - max(len(indent), len(subsequent)))
    lines = textwrap.wrap(text, width=body_width) or [""]
    out = [indent + lines[0]]
    out.extend(subsequent + line for line in lines[1:])
    return out


def _unit(denominator_label: str) -> str:
    """'by session' -> 'sessions'. Used by the `+N more` truncation line.

    A denominator often carries a parenthetical qualifier that belongs in the
    heading but not in a plural noun — 'by request (browser UA with a referer)'
    has to become 'requests', not 'request (browser ua with a referer)s'. So the
    qualifier is dropped and only the head noun is pluralised, and the case of
    the original is preserved so 'UA' does not become 'ua'.
    """
    label = (denominator_label or "").strip()
    lowered = label.lower()
    for prefix in ("by distinct ", "by "):
        if lowered.startswith(prefix):
            label = label[len(prefix):]
            break
    # Drop a trailing '(...)' qualifier, plus anything after an em dash or comma.
    label = re.sub(r"\s*\(.*$", "", label)
    label = re.split(r"\s+[—-]\s+|,|\s+per\s+", label)[0]
    label = label.strip()
    if not label:
        return "rows"
    if label.endswith("s"):
        return label
    # Only a short noun phrase is safe to pluralise by suffix. Anything longer is
    # a description rather than a count noun, and 'max subscribers reported' + 's'
    # is worse than leaving it alone.
    if len(label.split()) > 2:
        return label
    return label + "s"


def _heading(text: str, palette: Palette, *, width: int) -> list[str]:
    """A section heading: blank line, bold uppercase title."""
    return ["", palette.paint(text, palette.bold)]


def _note_lines(notes: Sequence[str], palette: Palette, *, width: int,
                colour: str = "") -> list[str]:
    """Footnote lines under a table, prefixed '!' and wrapped."""
    out: list[str] = []
    for note in notes:
        if not note:
            continue
        wrapped = _wrap(f"! {note}", width, indent="    ", hanging="      ")
        out.extend(palette.paint(line, colour) if colour else line for line in wrapped)
    return out


# --------------------------------------------------------------------------
# Bars, sparklines
# --------------------------------------------------------------------------


def render_bar(value: int, maximum: int, width: int, *, ascii_only: bool) -> str:
    """A horizontal bar scaled to the LARGEST ROW IN THE TABLE, not the total.

    Scaling to the total is the usual mistake: with a long tail, every row after
    the first becomes a one-cell stub and the chart stops carrying information.
    In Unicode mode the bar resolves to 1/8 of a cell, because with a 24-cell
    bar whole blocks quantise at roughly 4% and every small row would otherwise
    render identically. Returns an unpadded string, never wider than `width`.
    """
    if width <= 0 or maximum <= 0 or value <= 0:
        return ""
    fraction = min(1.0, value / maximum)
    if ascii_only:
        cells = fraction * width
        full = int(cells)
        remainder = cells - full
        bar = "#" * full + ("=" if remainder >= 0.4 else "")
        return bar or "="
    eighths = int(round(fraction * width * 8))
    full, remainder = divmod(eighths, 8)
    bar = _BAR_FULL * full + _BAR_PARTIALS[remainder]
    return bar or _BAR_PARTIALS[1]


def sparkline(values: Sequence[int], *, ascii_only: bool) -> str:
    """A one-line trend from a series of counts, scaled to its own maximum."""
    if not values:
        return ""
    ramp = _SPARK_ASCII if ascii_only else _SPARK
    top = max(values)
    if top <= 0:
        return ramp[0] * len(values)
    steps = len(ramp) - 1
    out = []
    for value in values:
        if value <= 0:
            out.append(ramp[0])
            continue
        idx = int(round(value / top * steps))
        out.append(ramp[max(1, min(steps, idx))])
    return "".join(out)


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


def _same_title(title: str, section: str | None) -> bool:
    """True when a table's own title merely repeats the section heading."""
    if not section:
        return False
    return " ".join(title.upper().split()) == " ".join(section.upper().split())


def render_table(table: Table, *, width: int, palette: Palette,
                 ascii_only: bool, section: str | None = None) -> list[str]:
    """Render one `Table`: title line, rows, tail line, warnings.

    The column layout is computed once per table so every row lines up: label
    clipped to 22 cells, count right-aligned to the widest count, the percentage
    always occupying exactly the width of '(100.0%)' whether or not it is
    printed, and the bar taking whatever is left. A suppressed table prints its
    heading and its reason and no rows at all — a suppressed dimension must
    never be mistaken for an empty one.
    """
    lines: list[str] = []
    if _same_title(table.title, section):
        lines.append(palette.paint("  " + _table_denominator(table), palette.dim))
    elif len("  " + _table_title(table)) <= width:
        lines.append(palette.paint("  " + _table_title(table), palette.bold))
    else:
        # A long denominator drops to its own line rather than running past the
        # right margin: the denominator is never dropped, only moved.
        lines.append(palette.paint("  " + table.title, palette.bold))
        lines.extend(palette.paint(line, palette.dim) for line in
                     _wrap(_table_denominator(table), width, indent="    ",
                           hanging="      "))

    if table.suppressed:
        reason = table.suppressed_reason or "not available for this range"
        lines.extend(
            palette.paint(line, palette.dim)
            for line in _wrap(f"— suppressed ({reason})", width,
                              indent="    ", hanging="      ")
        )
        lines.extend(_note_lines(table.warnings, palette, width=width,
                                 colour=palette.yellow))
        return lines

    if not table.rows:
        lines.append(palette.paint("    (no rows)", palette.dim))
        lines.extend(_note_lines(table.warnings, palette, width=width,
                                 colour=palette.yellow))
        return lines

    counts = [row.count for row in table.rows]
    maximum = max(counts) if counts else 0
    count_w = max(len(format_int(c)) for c in counts)
    label_w = min(_LABEL_MAX, max(len(row.label) for row in table.rows))
    label_w = max(label_w, 8)

    has_secondary = any(row.secondary is not None for row in table.rows)
    secondary_w = 0
    secondary_label = ""
    if has_secondary:
        secondary_w = max(
            len(format_int(row.secondary)) for row in table.rows
            if row.secondary is not None
        )
        secondary_label = next(
            (row.secondary_label for row in table.rows if row.secondary_label), ""
        ) or ""
        secondary_w = max(secondary_w, 3)
        if secondary_label:
            lines.append(palette.paint(
                "    " + " " * label_w + "  " + " " * count_w + "  " + " " * 8
                + "  " + secondary_label.rjust(secondary_w),
                palette.dim,
            ))

    fixed = 4 + label_w + 2 + count_w + 2 + 8
    if has_secondary:
        fixed += 2 + secondary_w
    bar_w = max(0, min(_BAR_MAX, width - fixed - 2))

    has_note = any(row.note for row in table.rows)
    for row in table.rows:
        label = _truncate(row.label, label_w).ljust(label_w)
        count = format_int(row.count).rjust(count_w)
        share = format_share(row.share).rjust(8)
        cells = [f"    {label}  {count}  {share}"]
        if has_secondary:
            cells.append("  " + (_dash(row.secondary)).rjust(secondary_w))
        if bar_w:
            bar = render_bar(row.count, maximum, bar_w, ascii_only=ascii_only)
            if bar:
                cells.append("  " + palette.paint(bar, palette.cyan))
        line = "".join(cells)
        if row.note and has_note and len(line) + len(row.note) + 3 <= width:
            line = line.rstrip() + palette.paint(f"   {row.note}", palette.dim)
        lines.append(line)

    if table.tail_count > 0:
        tail = (f"    +{table.tail_count} more "
                f"({format_int(table.tail_total)} {_unit(table.denominator_label)}"
                f"{', ' + format_share(table.tail_share)[1:-1] if table.tail_share is not None else ''})")
        lines.append(palette.paint(tail, palette.dim))

    lines.extend(_table_warnings(table, palette, width=width))
    return lines


def _table_title(table: Table) -> str:
    """'Device class (by session, n = 412)' — the denominator is never implicit."""
    return f"{table.title} {_table_denominator(table)}"


def _table_denominator(table: Table) -> str:
    """'(by session, n = 412)'. Printed in every heading without exception:
    sections legitimately use different denominators, and mixing them silently
    is the second most common way a report like this misleads its own author."""
    bits = []
    if table.denominator_label:
        bits.append(table.denominator_label)
    bits.append(f"n = {format_int(table.n)}")
    return f"({', '.join(bits)})"


def _table_warnings(table: Table, palette: Palette, *, width: int) -> list[str]:
    """Render the honesty footnotes `aggregate.py` attached to this table.

    This renderer deliberately derives NOTHING. The eleven honesty rules live in
    exactly one place — `aggregate.build_table` — because the contract requires a
    single helper for them, and because when this function had its own copy of
    the unknown-bias and long-tail thresholds the two implementations drifted:
    the HTML report printed the same table's unknown share as both '100%' and
    '99.9%', one from each site. Renderers choose colour; they do not restate
    statistics.
    """
    out: list[str] = []
    for warning in table.warnings:
        colour = palette.red if _is_severe_note(warning) else palette.yellow
        out.extend(_note_lines([warning], palette, width=width, colour=colour))
    return out


def _is_severe_note(note: str) -> bool:
    """Bias warnings are red; the rest are ordinary yellow caveats.

    Matched on the note's opening words rather than on a flag because `Table`
    carries notes as plain strings; keep this in step with `aggregate.py` if the
    wording there changes.
    """
    return note.startswith(("unknown is", "n = "))


def render_matrix(matrix: Matrix, *, width: int, palette: Palette,
                  section: str | None = None) -> list[str]:
    """Render the language x locale cross-tab.

    The signal is in the OFF-DIAGONALS, so the layout puts the locale columns
    side by side and adds the row total, the row's share of all sessions and the
    '-> prefers' verdict. Read the ratio *within* each row; the column totals
    answer a different and much less interesting question.
    """
    lines: list[str] = []
    if _same_title(matrix.title, section):
        lines.append(palette.paint(f"  (n = {format_int(matrix.n)})", palette.dim))
    else:
        lines.append(palette.paint(
            f"  {matrix.title} (n = {format_int(matrix.n)})", palette.bold))

    if matrix.suppressed:
        reason = matrix.suppressed_reason or "not available for this range"
        lines.extend(
            palette.paint(line, palette.dim)
            for line in _wrap(f"— suppressed ({reason})", width,
                              indent="    ", hanging="      ")
        )
        lines.extend(_note_lines(matrix.notes, palette, width=width,
                                 colour=palette.yellow))
        return lines

    if not matrix.row_labels:
        lines.append(palette.paint("    (no rows)", palette.dim))
        return lines

    label_w = max(8, min(_LABEL_MAX, max(len(l) for l in matrix.row_labels)))
    cell_w = max(6, max((len(l) for l in matrix.col_labels), default=6))
    total_w = max(5, max((len(format_int(t)) for t in matrix.row_totals), default=5))
    pref_w = max(9, max((len(p) for p in matrix.preference), default=9))

    header = (
        "    " + "language".ljust(label_w)
        + "".join(l.rjust(cell_w + 2) for l in matrix.col_labels)
        + "total".rjust(total_w + 2) + "share".rjust(10)
        + "  " + "→ prefers".ljust(pref_w)
    )
    lines.append(palette.paint(header, palette.dim))

    for idx, row_label in enumerate(matrix.row_labels):
        cells = matrix.cells[idx] if idx < len(matrix.cells) else ()
        total = matrix.row_totals[idx] if idx < len(matrix.row_totals) else 0
        share = matrix.row_shares[idx] if idx < len(matrix.row_shares) else None
        pref = matrix.preference[idx] if idx < len(matrix.preference) else ""
        line = (
            "    " + _truncate(row_label, label_w).ljust(label_w)
            + "".join(format_int(c).rjust(cell_w + 2) for c in cells)
            + format_int(total).rjust(total_w + 2)
            + format_share(share).rjust(10)
            + "  " + pref.ljust(pref_w)
        )
        lines.append(line.rstrip())

    lines.extend(_note_lines(matrix.notes, palette, width=width,
                             colour=palette.yellow))
    return lines


# --------------------------------------------------------------------------
# Heatmap
# --------------------------------------------------------------------------


def render_heatmap(heatmap: Heatmap, *, ascii_only: bool, palette: Palette,
                   width: int = 100, section: str | None = None) -> list[str]:
    """Render the 7x24 weekday-by-hour grid on a QUANTILE scale.

    A linear scale on diurnal data leaves twenty of the twenty-four columns
    blank and the picture says nothing; the quantile cut points come from
    `aggregate.py` and the legend prints the real value range behind each shade,
    without which a shaded grid is decorative rather than informative.

    Publish times are drawn as a separate '^' row underneath rather than painted
    over the cells, so the audience's shape and the cron schedule's shape can be
    compared instead of one hiding the other.
    """
    lines: list[str] = []
    # render() puts the timezone in the section heading, so a title that merely
    # repeats it earns no line of its own.
    if not _same_title(heatmap.title, section):
        lines.append(palette.paint(f"  {heatmap.title} ({heatmap.tz_name})",
                                   palette.bold))

    if heatmap.suppressed:
        reason = heatmap.suppressed_reason or "not available for this range"
        lines.append(palette.paint(f"    — suppressed ({reason})", palette.dim))
        return lines

    values = heatmap.values or ()
    if not values or not any(any(row) for row in values):
        lines.append(palette.paint("    (no activity in this range)", palette.dim))
        lines.extend(_note_lines(heatmap.notes, palette, width=width,
                                 colour=palette.yellow))
        return lines

    shades = _SHADES_ASCII if ascii_only else _SHADES
    cuts = _heatmap_cuts(heatmap.thresholds, values)

    header = [" "] * 24
    for hour in range(0, 24, 3):
        label = f"{hour:02d}"
        header[hour] = label[0]
        if hour + 1 < 24:
            header[hour + 1] = label[1]
    row_totals = [sum(row) for row in values]
    total_w = max(4, max((len(format_int(t)) for t in row_totals), default=4))
    lines.append(palette.paint("        " + "".join(header) + "  "
                               + "total".rjust(total_w), palette.dim))

    peak = max(max(row) if row else 0 for row in values)
    for idx, row in enumerate(values[:7]):
        name = _WEEKDAYS[idx] if idx < len(_WEEKDAYS) else f"d{idx}"
        cells = "".join(_shade(v, cuts, shades) for v in list(row)[:24])
        total = format_int(row_totals[idx]).rjust(total_w)
        painted = palette.paint(cells, palette.green if palette.enabled else "")
        lines.append(f"    {name} {painted}  {total}")

    lines.append("")
    lines.append(palette.paint("    " + _heatmap_legend(cuts, shades, peak), palette.dim))

    if heatmap.publish_marks:
        lines.append(_publish_row(heatmap.publish_marks, palette,
                                  ascii_only=ascii_only))

    lines.extend(_note_lines(heatmap.notes, palette, width=width,
                             colour=palette.yellow))
    return lines


def _heatmap_cuts(thresholds: Sequence[int], values: Sequence[Sequence[int]]) -> tuple[int, ...]:
    """Up to four internal boundaries, giving five shade bands."""
    cuts = tuple(sorted({int(t) for t in thresholds if t and t > 0}))[:4]
    if cuts:
        return cuts
    peak = max((max(row) if row else 0 for row in values), default=0)
    if peak <= 1:
        return (1,)
    return tuple(sorted({max(1, round(peak * f)) for f in (0.15, 0.35, 0.6, 0.85)}))


def _shade(value: int, cuts: Sequence[int], shades: Sequence[str]) -> str:
    """Blank for a genuine zero; otherwise the band the value falls in."""
    if value <= 0:
        return " "
    idx = bisect.bisect_left(list(cuts), value)
    return shades[min(idx, len(shades) - 1)]


def _heatmap_legend(cuts: Sequence[int], shades: Sequence[str], peak: int) -> str:
    """'blank 0  . 1-3  : 4-9  + 10-21  # 22-48  @ 49+' — the numbers matter."""
    parts = ["blank 0"]
    low = 1
    for i, cut in enumerate(cuts):
        if i >= len(shades):
            break
        parts.append(f"{shades[i]} {low}-{cut}" if cut > low else f"{shades[i]} {low}")
        low = cut + 1
    top_idx = min(len(cuts), len(shades) - 1)
    parts.append(f"{shades[top_idx]} {low}+" if low <= peak else f"{shades[top_idx]} {low}+")
    return "scale (quantile):  " + "   ".join(parts)


def _publish_row(marks: Sequence[tuple[int, int]], palette: Palette, *,
                 ascii_only: bool) -> str:
    """Hours at which articles were published, aggregated across weekdays.

    Publishing here is a cron job, so the per-weekday detail is near-uniform and
    the aggregate row is the honest comparison: audience shape against publish
    shape. Without it the section shows the user their own schedule reflected
    back at them.
    """
    glyph = "^" if ascii_only else "▲"
    hours = {h for _, h in marks if 0 <= h < 24}
    cells = "".join(glyph if h in hours else " " for h in range(24))
    label = f"{glyph} published"
    return "    pub " + palette.paint(cells, palette.magenta) + "   " + palette.paint(
        label, palette.dim)


# --------------------------------------------------------------------------
# Series
# --------------------------------------------------------------------------


def render_series(series: Series, *, width: int, ascii_only: bool,
                  palette: Palette) -> list[str]:
    """Per-bucket table plus a sparkline, plus the period-over-period block.

    Partial first and last buckets are suffixed '(partial)' and are never
    extrapolated; a bucket with no ingested data at all is '(no data)', which is
    a different statement from a zero and must not be plotted as one.
    """
    lines: list[str] = []
    if not series.points:
        lines.append(palette.paint("    (no periods in range)", palette.dim))
        return lines

    label_w = max(10, min(30, max(len(_series_label(p)) for p in series.points)))
    pv_w = max(9, max(len(format_int(p.pageviews)) for p in series.points))
    se_w = max(8, max(len(_dash(p.sessions)) for p in series.points))
    vi_w = max(8, max(len(_dash(p.visitors)) for p in series.points))
    maximum = max((p.pageviews for p in series.points if not p.hole), default=0)
    bar_w = max(0, min(_BAR_MAX,
                       width - (4 + label_w + 2 + pv_w + 2 + se_w + 2 + vi_w + 4)))

    header = ("    " + "period".ljust(label_w) + "  " + "pageviews".rjust(pv_w)
              + "  " + "sessions".rjust(se_w) + "  " + "visitors".rjust(vi_w))
    lines.append(palette.paint(header, palette.dim))

    for point in series.points:
        label = _truncate(_series_label(point), label_w).ljust(label_w)
        if point.hole:
            row = ("    " + label + "  " + "—".rjust(pv_w) + "  "
                   + "—".rjust(se_w) + "  " + "—".rjust(vi_w))
            lines.append(palette.paint(row, palette.dim))
            continue
        row = ("    " + label
               + "  " + format_int(point.pageviews).rjust(pv_w)
               + "  " + _dash(point.sessions).rjust(se_w)
               + "  " + _dash(point.visitors).rjust(vi_w))
        if bar_w:
            bar = render_bar(point.pageviews, maximum, bar_w, ascii_only=ascii_only)
            if bar:
                row += "  " + palette.paint(bar, palette.cyan)
        lines.append(row)

    spark = series.sparkline or tuple(
        p.pageviews for p in series.points if not p.hole
    )
    if spark:
        low, high = min(spark), max(spark)
        lines.append("")
        lines.append("    " + palette.paint(sparkline(spark, ascii_only=ascii_only),
                                            palette.cyan)
                     + palette.paint(f"   {format_int(low)} … {format_int(high)}"
                                     f" pageviews per {series.bucket}", palette.dim))

    if series.compare is not None:
        lines.append("")
        lines.extend(_render_comparison(series, palette))

    lines.extend(_note_lines(series.notes, palette, width=width,
                             colour=palette.yellow))
    return lines


def _series_label(point: object) -> str:
    """Bucket label with its honesty suffix."""
    label = getattr(point, "label", "") or getattr(point, "key", "")
    if getattr(point, "hole", False):
        return f"{label} (no data)"
    if getattr(point, "partial", False):
        return f"{label} (partial)"
    return str(label)


def _render_comparison(series: Series, palette: Palette) -> list[str]:
    """Current vs previous complete bucket, absolute and relative."""
    comparison = series.compare
    if comparison is None:  # pragma: no cover - guarded by caller
        return []
    lines = [palette.paint(
        f"    {comparison.current_label} vs {comparison.previous_label}"
        "   (complete periods only)", palette.dim)]
    if not comparison.metrics:
        return lines
    name_w = max(len(m[0]) for m in comparison.metrics)
    for name, current, previous, delta in comparison.metrics:
        arrow, colour = _delta_style(delta, palette)
        change = "—" if delta is None else f"{arrow}{abs(delta) * 100:.1f}%"
        lines.append(
            "    " + name.ljust(name_w)
            + "  " + format_int(previous).rjust(9)
            + " → " + format_int(current).rjust(9)
            + "  " + palette.paint(change.rjust(8), colour)
        )
    return lines


def _delta_style(delta: float | None, palette: Palette) -> tuple[str, str]:
    """Arrow and colour for a fractional change. Colour is redundant with the
    arrow, so a piped report loses nothing."""
    if delta is None:
        return "", palette.dim
    if delta > 0.001:
        return "+", palette.green
    if delta < -0.001:
        return "-", palette.yellow
    return "", palette.dim


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------


def ledger_total(ledger: Ledger, fallback: int = 0) -> int:
    """The denominator the ledger's shares are against.

    `Ledger.total_lines` is authoritative when it is filled. When it is not, the
    rows themselves sum to the total by construction, and `ParseStats.total` is
    the third fallback — a composition audit whose percentages are all blank is
    exactly the thing this section exists to prevent.
    """
    if ledger.total_lines:
        return ledger.total_lines
    try:
        steps = list(ledger.steps())
    except Exception:  # pragma: no cover - defensive
        return fallback
    for label, count, _ in steps:
        if "total" in label.lower():
            return abs(count)
    summed = sum(abs(count) for _, count, _ in steps)
    return summed or fallback


def render_ledger(ledger: Ledger, *, width: int, palette: Palette,
                  total: int | None = None) -> list[str]:
    """The composition audit: how N raw lines became M human pageviews.

    Printed before anything analytical, because it is what licenses the rest of
    the report. Every subtraction is shown with its count and its share of the
    total; a filter nobody can see is a filter nobody notices has grown to
    swallow real traffic.
    """
    try:
        steps = list(ledger.steps())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("ledger.steps() failed: %s", exc)
        return [palette.paint("    (ledger unavailable)", palette.dim)]
    if not steps:
        return [palette.paint("    (ledger empty)", palette.dim)]

    label_w = min(max(len(s[0]) for s in steps), 34)
    count_w = max(len(format_int(abs(s[1]))) for s in steps) + 1
    denominator = total if total is not None else ledger_total(ledger)

    lines: list[str] = []
    last = len(steps) - 1
    for idx, (label, count, share) in enumerate(steps):
        is_total = "total" in label.lower()
        if is_total:
            sign = " "
        elif idx == last:
            sign = "="
        else:
            sign = "−"
        shown = (format_int(count) if is_total or idx == last
                 else format_int(-abs(count)))
        if share is None and denominator:
            share = abs(count) / denominator
        line = ("    " + f"{sign} " + _truncate(label, label_w).ljust(label_w)
                + "  " + shown.rjust(count_w)
                + "  " + format_share(share).rjust(8))
        note = _ledger_note(label)
        if note and len(line) + len(note) + 6 <= width:
            line = line.rstrip() + palette.paint(f"   ← {note}", palette.dim)
        if idx == last:
            line = palette.paint(line, palette.bold)
        lines.append(line)
    return lines


def _ledger_note(label: str) -> str:
    """First matching annotation for a ledger row, or ''."""
    lowered = label.lower()
    for needle, note in _LEDGER_NOTES:
        if needle in lowered:
            return note
    return ""


# --------------------------------------------------------------------------
# Header, coverage, headline
# --------------------------------------------------------------------------


def _render_header(report: Report, palette: Palette, *, width: int) -> list[str]:
    """The four-line banner: what this is, what window, from what source."""
    rule = _RULE * width
    days = max(1, (report.until.date() - report.since.date()).days + 1)
    span = (f"{report.since:%d %b} – {report.until:%d %b %Y} "
            f"({days} day{'s' if days != 1 else ''})")
    if report.tz_fallback:
        tz_part = f"times in UTC (tzdata missing — {report.tz_name} unavailable)"
    else:
        offset = _utc_offset(report.since)
        tz_part = (f"times in {report.tz_name}"
                   if offset == report.tz_name
                   else f"times in {report.tz_name} ({offset})")

    source = _source_label(report)
    formats = ", ".join(sorted(report.formats_seen)) or "none"
    generated = f"generated {report.generated_at:%d %b %H:%M}"

    lines = [
        palette.paint(rule, palette.dim),
        palette.paint(" CyberAlertX — audience report", palette.bold),
        f" {span} · {tz_part}",
        palette.paint(f" source: {source} · format: {formats} · {generated}",
                      palette.dim),
    ]
    if report.include_bots:
        lines.append(palette.paint(
            " INCLUDING BOTS AND AGENTS — these are not audience numbers",
            palette.bold + palette.yellow))
    if report.host_filter and "all" in {h.lower() for h in report.host_filter}:
        lines.append(palette.paint(
            " HOST FILTER DISABLED — other vhosts on this box are included",
            palette.bold + palette.yellow))
    if report.hard_only:
        lines.append(palette.paint(
            " hard navigations only — soft (client-routed) pageviews excluded",
            palette.dim))
    lines.append(palette.paint(rule, palette.dim))
    return lines


def effective_tz_name(report: Report) -> str:
    """The zone the numbers are actually in.

    `Report.tz_name` holds the zone that was *asked for*, so the header can name
    the one it could not find. Every other section must print the zone the
    buckets were really computed in, or the heatmap claims a Kyiv peak it built
    from UTC hours.
    """
    return "UTC" if report.tz_fallback else report.tz_name


def _utc_offset(moment: datetime) -> str:
    """'UTC+3' from a tz-aware datetime; 'UTC' when the offset is unknown."""
    offset = moment.utcoffset()
    if offset is None:
        return "UTC"
    total = int(offset.total_seconds())
    if total == 0:
        return "UTC"
    sign = "+" if total > 0 else "-"
    hours, remainder = divmod(abs(total), 3600)
    minutes = remainder // 60
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"


def _source_label(report: Report) -> str:
    """'analytics store', or the log paths actually read."""
    sources = tuple(report.sources or ())
    if not sources:
        return "unknown"
    if sources == ("<store>",):
        return "analytics store"
    if len(sources) == 1:
        return sources[0]
    return f"{len(sources)} log files"


def _render_coverage(coverage: Coverage, palette: Palette, *,
                     width: int) -> list[str]:
    """The mandatory one-line coverage banner, plus its continuation."""
    banner = (coverage.banner or "").strip()
    if not banner:
        banner = _fallback_banner(coverage)
    lines: list[str] = []
    for chunk in banner.splitlines():
        chunk = chunk.strip()
        # aggregate.py builds the banner with the section heading baked in;
        # render() has already printed that heading, so drop the repeat.
        if chunk.upper().startswith(H_COVERAGE):
            chunk = chunk[len(H_COVERAGE):].strip()
        if not chunk:
            continue
        lines.extend(_wrap(chunk, width, indent="  ", hanging="    "))
    # Only restate the gaps when aggregate.py's banner did not already name
    # them; saying it twice trains the reader to skip the line that matters.
    said = " ".join(lines).lower()
    if coverage.dimensions_absent and "unavailable" not in said:
        absent = ", ".join(sorted(coverage.dimensions_absent))
        lines.extend(_wrap(
            f"unavailable for the whole range: {absent}",
            width, indent="  ", hanging="    "))
    if coverage.dimensions_partial and "available only" not in said:
        for dim in sorted(coverage.dimensions_partial):
            first, last = coverage.dimensions_partial[dim]
            lines.extend(_wrap(
                f"{dim} available only {first} – {last}",
                width, indent="  ", hanging="    "))
    return [palette.paint(line, palette.dim) for line in lines]


def _fallback_banner(coverage: Coverage) -> str:
    """Assemble a banner when `aggregate.py` left it empty. Never omitted."""
    if coverage.first_date is None or coverage.last_date is None:
        return "no data held for this range"
    missing = len(coverage.days_missing)
    return (f"{coverage.first_date:%d %b} – {coverage.last_date:%d %b %Y} "
            f"· {coverage.days_present} days, {missing} missing")


def _render_headline(report: Report, palette: Palette, *,
                     width: int, ascii_only: bool) -> list[str]:
    """Headline numbers in two columns, then the one-line TL;DR.

    Falls back to a single column when a suppression reason is too long to sit
    beside the counts — a suppressed metric has to say *why*, and truncating the
    reason would leave the reader thinking the number was zero.
    """
    head: Headline = report.headline
    absent = report.coverage.dimensions_absent
    suffix = "(BOTS INCLUDED)" if report.include_bots else "(bots excluded)"

    left: list[tuple[str, str]] = [
        (f"visitors {suffix}", _headline_value(head.visitors, "visitor", absent)),
        ("sessions", _headline_value(head.sessions, "visitor", absent)),
        ("pageviews", format_int(head.pageviews)),
        ("  hard / soft", f"{format_int(head.pageviews_hard)} / "
                          f"{format_int(head.pageviews_soft)}"),
    ]

    right: list[tuple[str, str]] = [
        ("pages / visit", _pair(head.pages_per_visit_mean,
                                head.pages_per_visit_median)
         if head.pages_per_visit_mean is not None
         or head.pages_per_visit_median is not None
         else _headline_value(None, "visitor", absent)),
    ]
    if head.bounce_rate is not None:
        ci = f" ±{head.bounce_ci_pp:.1f}pp" if head.bounce_ci_pp is not None else ""
        right.append(("bounce rate",
                      f"{head.bounce_rate * 100:.1f}%{ci} (upper bound)"))
    else:
        right.append(("bounce rate", _headline_value(None, "visitor", absent)))
    if head.span_mean_seconds is not None or head.span_median_seconds is not None:
        span = " · ".join(part for part in (
            f"{format_duration(head.span_mean_seconds)} mean"
            if head.span_mean_seconds is not None else "",
            f"{format_duration(head.span_median_seconds)} median"
            if head.span_median_seconds is not None else "",
        ) if part)
        right.append(("measured span", f"{span}  (engaged, ≥ 2 pv)"))
    else:
        right.append(("measured span", _headline_value(None, "visitor", absent)))
    if head.engaged_sessions is not None:
        right.append(("engaged sessions", format_int(head.engaged_sessions)))
    if head.same_day_returns is not None:
        right.append(("same-day returns", format_int(head.same_day_returns)))

    left_label_w = max(len(label) for label, _ in left)
    left_value_w = max(len(value) for _, value in left)
    right_label_w = max(len(label) for label, _ in right)
    right_value_w = max(len(value) for _, value in right)
    two_column_width = (2 + left_label_w + 2 + left_value_w + 4
                        + right_label_w + 2 + right_value_w)

    lines: list[str] = []
    if two_column_width <= width:
        for i in range(max(len(left), len(right))):
            cell = " " * (2 + left_label_w + 2 + left_value_w)
            if i < len(left):
                label, value = left[i]
                cell = ("  " + label.ljust(left_label_w) + "  "
                        + value.rjust(left_value_w))
            if i < len(right):
                rlabel, rvalue = right[i]
                cell += "    " + rlabel.ljust(right_label_w) + "  " + rvalue
            lines.append(cell.rstrip())
    else:
        label_w = max(left_label_w, right_label_w)
        for label, value in left + right:
            line = "  " + label.ljust(label_w) + "  " + value
            if len(line) <= width:
                lines.append(line.rstrip())
                continue
            lines.append("  " + label)
            lines.extend(_wrap(value, width, indent="      ", hanging="        "))

    # Identity-derived rows — visitors, sessions, pages/visit, bounce, span —
    # can only be computed for the days that carry a real client IP. When that
    # is a sub-range of the window, say so here rather than only in the coverage
    # banner: otherwise 'pageviews 1 032' and 'sessions 457' sit one line apart
    # looking like one denominator, and the reader divides them.
    partial = report.coverage.dimensions_partial.get("visitor")
    if partial and head.sessions is not None:
        first, last = partial
        lines.extend(palette.paint(line, palette.dim) for line in _wrap(
            f"visitors, sessions, pages/visit, bounce and span cover "
            f"{first} – {last} only — the days with a real client IP. "
            f"pageviews covers the whole window.",
            width, indent="  ! ", hanging="    "))

    if head.tldr:
        lines.append("")
        marker = ">" if ascii_only else "▸"
        lines.extend(palette.paint(line, palette.bold)
                     for line in _wrap(f"{marker} {head.tldr}", width,
                                       indent="  ", hanging="    "))
    return lines


def _headline_value(value: int | None, dimension: str,
                    absent: frozenset[str]) -> str:
    """A number, or the reason it is suppressed. Never a zero standing in for
    'we cannot know'."""
    if value is not None:
        return format_int(value)
    reason = _SUPPRESSION_REASONS.get(dimension)
    if reason is None:
        reason = ("not available for this range" if dimension in absent
                  else "sample too small to report honestly")
    return f"— suppressed ({reason})"


def _pair(mean: float | None, median: float | None) -> str:
    """'1.8 mean · 1.0 median', omitting whichever half is missing."""
    parts = []
    if mean is not None:
        parts.append(f"{mean:.1f} mean")
    if median is not None:
        parts.append(f"{median:.1f} median")
    return " · ".join(parts) if parts else "—"


# --------------------------------------------------------------------------
# Small sections
# --------------------------------------------------------------------------


def _render_latency(latency: LatencyStats, palette: Palette, *,
                    width: int) -> list[str]:
    """p50/p90/p99 for request and upstream time. Never a mean: one 30-second
    upstream timeout ruins a mean, and the gap between the two rows is the
    client-network story."""
    if latency.suppressed:
        reason = latency.suppressed_reason or "not available for this range"
        return [palette.paint(f"    latency — suppressed ({reason})", palette.dim)]
    lines = [
        "    " + "request time ".ljust(16)
        + f"p50 {format_seconds(latency.p50):>8}"
        + f"   p90 {format_seconds(latency.p90):>8}"
        + f"   p99 {format_seconds(latency.p99):>8}"
        + palette.paint(f"   n = {format_int(latency.n)}", palette.dim),
        "    " + "upstream time".ljust(16)
        + f"p50 {format_seconds(latency.upstream_p50):>8}"
        + f"   p90 {format_seconds(latency.upstream_p90):>8}"
        + f"   p99 {format_seconds(latency.upstream_p99):>8}",
        "    " + "bytes served ".ljust(16) + format_bytes(latency.bytes_total),
    ]
    lines.extend(_note_lines([
        "$request_time on a proxied response includes streaming to a slow client, "
        "so a mobile user on bad signal inflates it without the server being slow "
        "— the gap between request and upstream time is the client-network story."
    ], palette, width=width, colour=palette.dim))
    return lines


def _render_security(noise: SecurityNoise, palette: Palette, *,
                     width: int) -> list[str]:
    """Six lines that keep the discard filter auditable."""
    def kv(label: str, count: int, aside: str = "") -> str:
        """One fixed-width fact line; the aside is dropped if it will not fit."""
        line = "    " + label.ljust(46) + format_int(count).rjust(9)
        if aside and len(line) + len(aside) + 3 <= width:
            line += palette.paint(f"   {aside}", palette.dim)
        return line

    sources = (f"{format_int(noise.distinct_sources)} distinct sources"
               if noise.distinct_sources is not None
               else "an unknown number of sources (none stored)")
    lines = [
        *_wrap(f"noise hits {format_int(noise.total_hits)} from {sources}",
               width, indent="    ", hanging="      "),
        kv("direct-to-origin (never traversed Cloudflare)", noise.direct_to_origin,
           "someone has the origin IP"),
        kv("forged crawlers (declared, arrived outside CF)", noise.forged_crawlers),
    ]
    if noise.forged_top_uas:
        lines.extend(palette.paint(line, palette.dim) for line in _wrap(
            "claimed: " + _inline_rows(noise.forged_top_uas, 3),
            width, indent="      ", hanging="        "))
    lines.append(kv("malformed requests (raw TLS bytes, empty target)",
                    noise.malformed_requests))
    if noise.top_paths:
        lines.extend(_wrap("top probed paths: " + _inline_rows(noise.top_paths, 6),
                           width, indent="    ", hanging="      "))
    if noise.top_countries:
        lines.extend(_wrap("top source countries: "
                           + _inline_rows(noise.top_countries, 5),
                           width, indent="    ", hanging="      "))
    lines.extend(_note_lines(noise.notes, palette, width=width, colour=palette.dim))
    return lines


def _inline_rows(rows: Sequence[object], limit: int) -> str:
    """'/wp-config.php (312), /.env (288)' — a compact one-line row list."""
    parts = []
    for row in list(rows)[:limit]:
        label = getattr(row, "label", "")
        count = getattr(row, "count", 0)
        parts.append(f"{_truncate(str(label), 30)} ({format_int(int(count))})")
    return ", ".join(parts)


def _locale_mismatch_line(matrix: Matrix, palette: Palette) -> list[str]:
    """The single-figure summary of the language x locale table.

    Only computed for the two rows where a mismatch is even definable — a `de`
    browser has no German edition to prefer — and only printed once the sample
    is large enough for a headline percentage.
    """
    if matrix.suppressed or not matrix.row_labels or not matrix.col_labels:
        return []
    try:
        cols = {label.strip().strip("/").lower(): i
                for i, label in enumerate(matrix.col_labels)}
        expected = {"uk": "ua", "ua": "ua", "en": "en"}
        matched = 0
        total = 0
        for idx, raw_label in enumerate(matrix.row_labels):
            language = raw_label.strip().lower().split()[0] if raw_label.strip() else ""
            want = expected.get(language)
            if want is None or want not in cols:
                continue
            row = matrix.cells[idx]
            row_total = sum(row)
            if not row_total:
                continue
            total += row_total
            matched += row[cols[want]]
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("locale mismatch rate skipped: %s", exc)
        return []
    if total < 100:
        return []
    rate = 1.0 - (matched / total)
    return [palette.paint(
        f"    locale mismatch rate  {rate * 100:.1f}%  "
        f"({format_int(total - matched)} of {format_int(total)} sessions with a "
        "matching edition read the other one)", palette.bold)]


def _render_notes(report: Report, palette: Palette, *, width: int,
                  ascii_only: bool) -> list[str]:
    """Footer: warnings first, then the standing caveats, printed once."""
    lines: list[str] = []
    bullet = "*" if ascii_only else "•"
    for warning in report.warnings:
        lines.extend(
            palette.paint(line, palette.yellow)
            for line in _wrap(f"! {warning}", width, indent="  ", hanging="    ")
        )
    if report.warnings and report.notes:
        lines.append("")
    for note in report.notes:
        lines.extend(_wrap(f"{bullet} {note}", width, indent="  ", hanging="    "))
    return lines


# --------------------------------------------------------------------------
# The whole report
# --------------------------------------------------------------------------


def render(
    report: Report,
    *,
    color: bool | None = None,
    width: int | None = None,
    ascii_only: bool | None = None,
    stream: TextIO | None = None,
) -> str:
    """Render the whole report to a single string.

    Never writes to a file and never prints; the caller decides where the text
    goes. Never raises on any `Report` — a section that blows up is replaced by
    a visible one-line marker, because losing one table is recoverable and
    losing the whole run after a full ingest is not.
    """
    probe = stream if stream is not None else sys.stdout
    if color is None:
        color = supports_color(probe)
    if ascii_only is None:
        ascii_only = not supports_unicode(probe)
    if width is None:
        width = terminal_width()
    width = max(60, int(width))

    palette = Palette.ansi() if color else Palette.plain()
    out: list[str] = []

    def section(heading: str, body: Callable[[], list[str]]) -> None:
        """Emit a heading plus a body, isolating any failure to this section."""
        out.extend(_heading(heading, palette, width=width))
        try:
            lines = body()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("section %s failed to render: %s", heading, exc)
            lines = [palette.paint(f"    (section unavailable: {exc})", palette.red)]
        out.extend(lines)

    # F.0 header
    try:
        out.extend(_render_header(report, palette, width=width))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("header failed to render: %s", exc)
        out.append("CyberAlertX — audience report")

    # F.1 coverage — mandatory, in every report, always.
    section(H_COVERAGE, lambda: _render_coverage(report.coverage, palette, width=width))

    # F.2 data quality — first, because it licenses everything below it.
    total_lines = ledger_total(report.ledger, report.parse_stats.total)
    section(
        f"{H_QUALITY}  ─ how {format_int(total_lines)} log lines became "
        f"{format_int(report.headline.pageviews)} human pageviews",
        lambda: render_ledger(report.ledger, width=width, palette=palette,
                              total=total_lines),
    )
    if report.parse_stats.files_unreadable:
        out.extend(_note_lines(
            [f"unreadable, skipped: {path} ({reason})"
             for path, reason in report.parse_stats.files_unreadable],
            palette, width=width, colour=palette.red))

    # F.3 audience at a glance
    n_sessions = report.headline.sessions
    glance = (f"{H_GLANCE} (n = {format_int(n_sessions)} sessions)"
              if n_sessions is not None else f"{H_GLANCE}")
    section(glance, lambda: _render_headline(report, palette, width=width,
                                             ascii_only=ascii_only))

    # F.4 traffic over time
    section(
        f"{H_TRAFFIC} ({report.timeseries.bucket}, "
        f"n = {format_int(report.headline.pageviews)} pageviews)",
        lambda: render_series(report.timeseries, width=width,
                              ascii_only=ascii_only, palette=palette),
    )

    # F.5 all-time summary
    all_time = report.all_time
    if all_time is not None:
        section(H_ALLTIME,
                lambda: render_series(all_time, width=width,
                                      ascii_only=ascii_only, palette=palette))

    # F.6 country
    section(H_COUNTRY, lambda: render_table(report.countries, width=width,
                                            palette=palette,
                                            ascii_only=ascii_only,
                                            section=H_COUNTRY))

    # F.7 language x locale — the star of the report.
    def _language_block() -> list[str]:
        lines = render_matrix(report.language_locale, width=width,
                              palette=palette, section=H_LANGUAGE)
        mismatch = _locale_mismatch_line(report.language_locale, palette)
        if mismatch:
            lines.append("")
            lines.extend(mismatch)
        lines.append("")
        lines.extend(render_table(report.languages, width=width, palette=palette,
                                  ascii_only=ascii_only))
        return lines

    section(H_LANGUAGE, _language_block)

    # F.8 acquisition
    section(H_ACQUISITION, lambda: _tables(
        [report.channels, report.campaigns, report.referrers],
        width=width, palette=palette, ascii_only=ascii_only,
        section=H_ACQUISITION))

    # F.9 device, os & browser
    section(H_DEVICE, lambda: _tables(
        [report.device_types, report.vendors, report.models, report.os_families,
         report.os_versions, report.browsers, report.in_app],
        width=width, palette=palette, ascii_only=ascii_only, section=H_DEVICE))

    # F.10 content
    section(H_CONTENT, lambda: _tables(
        [report.top_articles, report.entry_pages, report.locales,
         report.broken_links, report.not_found],
        width=width, palette=palette, ascii_only=ascii_only, section=H_CONTENT))

    # F.11 when they read
    section(f"{H_WHEN} ({report.heatmap.unit}/hour, {effective_tz_name(report)})",
            lambda: render_heatmap(report.heatmap, ascii_only=ascii_only,
                                   palette=palette, width=width,
                                   section=H_WHEN))

    # F.12 technical health
    def _health_block() -> list[str]:
        lines = render_table(report.status_codes, width=width, palette=palette,
                             ascii_only=ascii_only, section=H_HEALTH)
        lines.append("")
        lines.extend(_render_latency(report.latency, palette, width=width))
        lines.append("")
        lines.extend(render_table(report.slowest_routes, width=width,
                                  palette=palette, ascii_only=ascii_only))
        return lines

    section(H_HEALTH, _health_block)

    # F.13 automated traffic
    def _automated_block() -> list[str]:
        lines = _note_lines([_BOT_FRAMING], palette, width=width, colour=palette.dim)
        lines.append("")
        lines.extend(_tables(
            [report.bot_labels, report.bot_categories, report.agent_reach,
             report.feed_subscribers, report.suspected_automation],
            width=width, palette=palette, ascii_only=ascii_only,
            section=H_AUTOMATED))
        return lines

    section(f"{H_AUTOMATED} (appendix, by request)", _automated_block)

    # F.14 security noise
    section(f"{H_SECURITY} (appendix)",
            lambda: _render_security(report.security, palette, width=width))

    # F.15 notes
    section(H_NOTES, lambda: _render_notes(report, palette, width=width,
                                           ascii_only=ascii_only))

    out.append("")
    text = "\n".join(out) + "\n"
    if ascii_only:
        text = _fold_ascii(text)
    return text


def _tables(tables: Sequence[Table], *, width: int, palette: Palette,
            ascii_only: bool, section: str | None = None) -> list[str]:
    """Render several tables into one section, blank-line separated."""
    lines: list[str] = []
    for idx, table in enumerate(tables):
        if table is None:  # pragma: no cover - defensive
            continue
        if idx:
            lines.append("")
        lines.extend(render_table(table, width=width, palette=palette,
                                  ascii_only=ascii_only, section=section))
    return lines


def _fold_ascii(text: str) -> str:
    """Make the output safe for a non-UTF-8 terminal.

    The known glyphs are transliterated to their ASCII equivalents; anything
    left over (a Ukrainian article title, say) becomes '?'. That loses
    information, and losing it is still strictly better than the
    UnicodeEncodeError that would otherwise abort the run at the last moment.
    """
    folded = text.translate(_ASCII_FOLD)
    return folded.encode("ascii", "replace").decode("ascii")
