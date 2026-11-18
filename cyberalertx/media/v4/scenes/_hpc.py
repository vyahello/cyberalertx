"""Shared pieces of the supercomputer scenes (`hpc_hall`, `hpc_drawn`).

The annotation is a news graphic, not a crime-scene marker: no bracket on a
rack, nothing that suggests where in the hall (or that physically) anything
happened. What the sources state is shown as type:

* an account figure from `brief.facts` (and only from there), set large, with
  a row of person tokens scaled from it: each token stands for a round number
  of accounts that divides the figure exactly (4,000 = 40 x 100), with the
  legend "= 100 accounts". If no such unit exists, the type carries the
  figure alone. Tokens stay separate shapes at feed size (176 px);
* otherwise the machine's stated state: taken offline, or a security breach.
"""
from __future__ import annotations

import math
import re

from ..brief import EditorialBrief
from ..kit import H, Doc, f, icon
from .. import type as T

_OFFLINE = re.compile(r"offline|offlline|shut down|вимкн|відключ")
_ACCOUNTS = re.compile(r"accounts|обліков")
_BREACH = re.compile(r"breach|hack|cyberattack|intrusion|злам|атак")

#: Accounts per token, in order of preference, and the token counts that
#: stay legible as separate shapes at feed size.
_UNITS = (100, 1000, 50, 500, 10, 5000, 10000, 1)
_MIN_TOKENS, _MAX_TOKENS = 12, 60


def mode(brief: EditorialBrief) -> str:
    """'accounts', 'offline' or 'breach': mirrors brief.alt_text's choice."""
    if brief.facts.get("accounts") or _ACCOUNTS.search(brief.text):
        return "accounts"
    return "offline" if _OFFLINE.search(brief.text) else "breach"


def stated(brief: EditorialBrief) -> str:
    """What the drawn hall may annotate: 'accounts' only with a figure in
    `brief.facts`, 'offline' or 'breach' only when the text says so; '' when
    the sources state none of these (the hall is then shown unannotated)."""
    if brief.facts.get("accounts"):
        return "accounts"
    if _OFFLINE.search(brief.text):
        return "offline"
    if _BREACH.search(brief.text) or brief.status in ("compromise", "exploited", "confirmed"):
        return "breach"
    return ""


def account_label(brief: EditorialBrief) -> str:
    n = brief.facts.get("accounts")
    if not n:
        return ""
    return f"{n}+" if brief.facts.get("accounts_plus") else str(n)


def account_count(brief: EditorialBrief) -> int:
    """The stated count as an integer when it is a plain number (no 'M'/'K'
    scale word); else 0."""
    n = str(brief.facts.get("accounts") or "")
    if not re.fullmatch(r"\d{1,3}(?:[ ,.]\d{3})*|\d+", n):
        return 0
    return int(re.sub(r"\D", "", n))


def token_scale(n: int) -> tuple[int, int]:
    """(tokens, accounts per token) for a count `n`, using the first unit
    that divides `n` exactly into a legible number of tokens; (0, 0) when
    none does (the figure is then shown as type only)."""
    for unit in _UNITS:
        if n > 0 and n % unit == 0 and _MIN_TOKENS <= n // unit <= _MAX_TOKENS:
            return n // unit, unit
    return 0, 0


def person(doc: Doc, cx: float, top: float, h: float, color: str) -> None:
    """A filled person token (head + shoulders), `h` tall."""
    r = h * 0.23
    doc.circle(cx, top + r, r, color)
    w = h * 0.40
    y0 = top + h * 0.52
    doc.path(f"M{f(cx - w)} {f(top + h)}V{f(y0 + w * 0.55)}Q{f(cx - w)} {f(y0)} {f(cx)} {f(y0)}"
             f"Q{f(cx + w)} {f(y0)} {f(cx + w)} {f(y0 + w * 0.55)}V{f(top + h)}Z", fill=color)


def token_field(doc: Doc, x: float, y: float, cols: int, tokens: int, pitch_x: float, pitch_y: float,
                h: float, color: str) -> float:
    """`tokens` person tokens in rows of `cols`. Returns the bottom y."""
    for i in range(tokens):
        r, c = divmod(i, cols)
        person(doc, x + c * pitch_x + pitch_x / 2, y + r * pitch_y, h, color)
    return y + ((tokens + cols - 1) // cols) * pitch_y


def legend(doc: Doc, x: float, y: float, unit: int, color: str, ink: str, size: float = 26) -> None:
    """'<token> = 100 accounts' with `y` as the baseline."""
    person(doc, x + 12, y - size * 0.95, size * 1.05, color)
    doc.text(f"= {unit:,} account" + ("s" if unit != 1 else ""), x + 34, y, size, ink, "ui")


def power_glyph(doc: Doc, cx: float, cy: float, r: float, color: str, sw: float) -> None:
    """IEC power symbol (stroked)."""
    a = 0.78                      # gap half-angle (rad) at the top
    x0, y0 = cx - r * math.sin(a), cy - r * math.cos(a)
    x1, y1 = cx + r * math.sin(a), cy - r * math.cos(a)
    doc.path(f"M{f(x1)} {f(y1)}A{f(r)} {f(r)} 0 1 1 {f(x0)} {f(y0)}", stroke=color, sw=sw)
    doc.path(f"M{f(cx)} {f(cy - r * 1.18)}V{f(cy - r * 0.15)}", stroke=color, sw=sw)


def fit_size(s: str, max_w: float, size: float, font: str = "display") -> float:
    """Largest size <= `size` at which `s` fits `max_w`."""
    w = T.measure(T.supported(s, font), size, font)
    return size if w <= max_w else size * max_w / w


NAVY = "#0A1322"


def type_column(doc: Doc, brief: EditorialBrief, what: str, col: float) -> None:
    """The left column of the spread (width `col`): the stated account figure
    over its person tokens, or the stated state of the machine."""
    p = doc.pal
    doc.rect(0, 0, col, H, NAVY)
    doc.rect(col - 6, 0, 6, H, p.danger)          # the only red edge in the frame
    x0, inner = 64.0, col - 120
    if what == "accounts":
        label = account_label(brief) or "accounts"
        sz = fit_size(label, inner, 168)
        y = 92 + sz * 0.7
        doc.text(label, x0 - 6, y, sz, "#FFFFFF", "display")
        if label != "accounts":
            doc.text("accounts", x0, y + 70, 48, "#C9D3E3", "ui")
        tokens, unit = token_scale(account_count(brief))
        if tokens:
            cols = 8 if tokens > 24 else 6
            px = inner / cols
            py = min(px * 1.1, (H - 80 - (y + 130)) / ((tokens + cols - 1) // cols))
            bottom = token_field(doc, x0, y + 130, cols, tokens, px, py, min(px, py) * 0.78, p.danger)
            legend(doc, x0, min(bottom + 34, H - 40), unit, p.danger, "#A9B6CC")
        return
    state_type(doc, what, x0, 150, inner, 128)


def state_type(doc: Doc, what: str, x: float, y: float, width: float, size: float) -> None:
    """'offline' (power glyph) or 'breach' (warning glyph) as large type."""
    p = doc.pal
    word = "OFFLINE" if what == "offline" else "BREACH"
    if what == "offline":
        power_glyph(doc, x + 58, y + 64, 50, p.danger, 13)
    else:
        icon(doc, "warn", x + 58, y + 58, 120, p.danger, 3.2)
    sz = fit_size(word, width, size)
    base = y + 150 + sz * 0.7
    doc.text(word, x - 4, base, sz, "#FFFFFF", "display", tracking=2)
    if what == "offline":
        doc.text("after a security breach", x, base + 62, 36, "#A9B6CC", "ui")
