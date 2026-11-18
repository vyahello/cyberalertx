"""Weekly roundup: the headline's own lightning bolt, drawn large across the
frame, splits it into four quadrants; each quadrant holds one item the
roundup names, as a bold line pictogram (a managed monitor for an RMM
product, a window, a browser, a fridge, a terminal prompt, a robot arm...)
with its name and what the headline says about it (0-DAY, EXPLOITED,
TAKEOVER...). Items come from the text in headline order; generic ones fill
in only when fewer than four are named. Pictograms are symbols, not screens:
no invented text, commands or interfaces. No logos."""
from __future__ import annotations

import random
import re

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, icon, vignette
from . import scene


# kind, pattern in the text, default label
_TILES: tuple[tuple[str, str, str], ...] = (
    ("rmm", r"n-able|n-central|\brmm\b|screenconnect|remote[- ]management", "RMM"),
    ("os", r"windows", "Windows"),
    ("browser", r"chrome|browser|firefox|safari", "Browser"),
    ("fridge", r"fridge|refrigerat", "Fridge"),
    ("ssh", r"sshole|\bssh\b|openssh", "SSH"),
    ("robot", r"robot", "Robots"),
    ("sites", r"hacked sites|websites|wordpress|\bsites\b", "Websites"),
    ("update", r"trusted update|update tools?|booby-trapped .{0,20}update|hijacked update", "Update"),
    ("password", r"default password|blank password|admin:admin", "Password"),
)
_FALLBACK = ("server", "browser", "os", "password")


def _pick(brief: EditorialBrief) -> list[tuple[str, str, str]]:
    """Up to four (kind, label, flag) in the order the text names them."""
    t = brief.text
    found: list[tuple[int, str, str, str]] = []
    for kind, pat, label in _TILES:
        m = re.search(pat, t)
        if not m:
            continue
        ent = next((e for e in brief.entities if re.fullmatch(pat, e.lower())), "")
        if not ent:
            ent = next((e for e in brief.entities if re.search(pat, e.lower())), "")
        word = m.group(0)
        if not ent and kind in ("os", "browser") and word.isalpha():
            ent = word.capitalize()         # the product the text names ("Windows", "Chrome")
        found.append((m.start(), kind, ent or label, _flag(t, m.start(), m.end())))
    found.sort()
    out = [(k, lab, fl) for _, k, lab, fl in found][:4]
    for k in _FALLBACK:
        if len(out) >= 4:
            break
        if all(k != o[0] for o in out):
            out.append((k, k.capitalize() if k != "os" else "OS", ""))
    return out


def _flag(t: str, a: int, b: int) -> str:
    near = t[a:b + 26]
    for pat, lab in ((r"0-days?|zero-days?", "0-DAY"), (r"exploit", "EXPLOITED"), (r"takeover", "TAKEOVER"),
                     (r"hacked", "HACKED"), (r"malware|booby", "TROJANIZED"), (r"blank", "BLANK"), (r"default", "DEFAULT"),
                     (r"open", "OPEN")):
        if re.search(pat, near):
            return lab
    return "FLAW"


# ---------------------------------------------------------------- pictograms (line art, ~220 px)

def _stroke(doc: Doc, d: str, ink: str, sw: float = 10) -> None:
    doc.path(d, stroke=ink, sw=sw)


def _pict(doc: Doc, kind: str, cx: float, cy: float, ink: str, mark: str) -> None:
    s = 1.0
    if kind == "rmm":            # a managed monitor with a remote-control gear
        _stroke(doc, f"M{f(cx - 110)} {f(cy - 80)}h220v140h-220ZM{f(cx - 40)} {f(cy + 100)}h80M{f(cx)} "
                     f"{f(cy + 60)}v40", ink)
        icon(doc, "gear", cx + 92, cy + 50, 110, mark, 9)
    elif kind == "os":           # a desktop window
        _stroke(doc, f"M{f(cx - 120)} {f(cy - 90)}h240v180h-240ZM{f(cx - 120)} {f(cy - 50)}h240", ink)
        for k in range(3):
            doc.circle(cx + 96 - k * 28, cy - 70, 7, mark if k == 0 else ink)
        icon(doc, "shieldx", cx, cy + 22, 92, mark, 9)
    elif kind == "browser":      # a browser window: tab, address bar
        _stroke(doc, f"M{f(cx - 120)} {f(cy - 90)}h240v180h-240ZM{f(cx - 120)} {f(cy - 40)}h240", ink)
        for k in range(3):
            doc.circle(cx - 98 + k * 22, cy - 65, 6, ink)
        doc.rect(cx - 24, cy - 78, 128, 26, "none", 13, stroke=ink, sw=6)
        icon(doc, "globe", cx, cy + 26, 92, mark, 9)
    elif kind == "fridge":       # two-door fridge
        _stroke(doc, f"M{f(cx - 75)} {f(cy - 120)}h150v240h-150ZM{f(cx - 75)} {f(cy + 10)}h150"
                     f"M{f(cx - 50)} {f(cy - 90)}v60M{f(cx - 50)} {f(cy + 34)}v50", ink)
        doc.rect(cx + 10, cy - 92, 44, 30, "none", 4, stroke=mark, sw=8)
    elif kind == "ssh":          # terminal prompt
        _stroke(doc, f"M{f(cx - 120)} {f(cy - 90)}h240v180h-240Z", ink)
        _stroke(doc, f"M{f(cx - 70)} {f(cy - 30)}l50 34l-50 34", mark, 12)
        _stroke(doc, f"M{f(cx + 0)} {f(cy + 40)}h60", mark, 12)
    elif kind == "robot":        # industrial arm
        _stroke(doc, f"M{f(cx - 100)} {f(cy + 110)}h140M{f(cx - 30)} {f(cy + 110)}v-30"
                     f"L{f(cx - 60)} {f(cy - 40)}L{f(cx + 60)} {f(cy - 90)}l30 50", ink, 14)
        for jx, jy in ((cx - 30, cy + 80), (cx - 60, cy - 40), (cx + 60, cy - 90)):
            doc.circle(jx, jy, 14, mark)
        _stroke(doc, f"M{f(cx + 72)} {f(cy - 26)}h40M{f(cx + 72)} {f(cy - 26)}v26M{f(cx + 112)} {f(cy - 26)}v26",
                ink, 9)
    elif kind == "sites":        # many pages, several flagged
        for i in range(3):
            for j in range(2):
                x, y = cx - 120 + i * 84, cy - 80 + j * 92
                hit = (i + j) % 2 == 0
                doc.rect(x, y, 70, 76, "none", 6, stroke=mark if hit else ink, sw=8)
    elif kind == "update":       # an update arriving, with a warning on it
        icon(doc, "download", cx - 20, cy, 210, ink, 10)
        icon(doc, "warn", cx + 90, cy + 70, 100, mark, 9)
    elif kind == "password":     # a password field with masked characters
        _stroke(doc, f"M{f(cx - 130)} {f(cy - 44)}h260v88h-260Z", ink)
        for k in range(5):
            doc.circle(cx - 90 + k * 40, cy, 12, mark)
    else:                        # server
        _stroke(doc, f"M{f(cx - 110)} {f(cy - 100)}h220v80h-220ZM{f(cx - 110)} {f(cy + 20)}h220v80h-220Z", ink)
        doc.circle(cx - 74, cy - 60, 10, mark)
        doc.circle(cx - 74, cy + 60, 10, ink)
    _ = s


def _bolt(doc: Doc, color: str) -> None:
    pts = [(x - 70, y) for x, y in ((985.0, -40.0), (560.0, 470.0), (780.0, 470.0), (590.0, 950.0),
                                    (1060.0, 380.0), (835.0, 380.0), (1060.0, -40.0))]
    d = "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z"
    doc.path(d, fill=color, extra=f' filter="{doc.blur(40)}"', opacity=0.35)
    doc.path(d, fill=doc.lin([(0, "#FFE08A", 1), (1, color, 1)], 0, 0, 0.3, 1))
    doc.path(d, stroke="#0A0F1A", sw=10, opacity=0.6)


@scene("weekly_recap")
def weekly_recap(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.5, 0.0))
    tiles = _pick(brief)
    _bolt(doc, p.warn)
    # quadrant anchors: pictogram centre, label origin
    # quadrants: pictogram at the left, name and flag beside it
    spots = ((40.0, 230.0), (1010.0, 230.0), (40.0, 660.0), (1010.0, 660.0))
    for (kind, label, flag), (qx, cy) in zip(tiles, spots):
        mark = p.danger if flag else p.warn
        _pict(doc, kind, qx + 140, cy, p.ink, mark)
        size = 56.0
        while size > 26 and T.measure(T.supported(label, "display"), size, "display") > 255:
            size -= 2
        lx = qx + 290
        doc.text(label, lx, cy + 4, size, p.ink, "display")
        if flag:
            fw = T.measure(flag, 26, "ui_bold", 2) + 40
            doc.rect(lx + 2, cy + 30, fw, 48, p.danger, 6)
            doc.text(flag, lx + 22, cy + 63, 26, "#FFFFFF", "ui_bold", tracking=2)
    doc.focus = Box(20, 20, 1560, 878)
    vignette(doc, 0.45)
