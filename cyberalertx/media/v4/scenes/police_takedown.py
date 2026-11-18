"""Law enforcement takes criminal infrastructure offline. The subject is the
seized hardware itself: a dark server rack (every status light off) taped
off with barrier tape, the operations it served hanging from it on evidence
tags. The tags carry only what the headline names (malware or operation
names as plain text, and a seized count when the headline gives one).

No agency, seal, badge or jurisdiction is drawn; the only banner word is
the generic SEIZED."""
from __future__ import annotations

import math
import random
import re
from typing import Callable

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene
from ._editorial import fit_size, headline_main, product_groups

_TAPE = "#F2B705"
_TAPE_INK = "#14161A"
_TAG = ("#E9D3A1", "#D6B977")
_TAG_INK = "#2A2116"
# Headline words that are not what was seized.
_NOT_SEIZED = {"Police", "Operation Endgame", "Operation", "Endgame", "Europol", "FBI", "Servers", "Logins",
               "Stolen", "Seizes", "Takes", "Down", "Dismantle", "Takedown"}


def _seized_names(brief: EditorialBrief) -> list[str]:
    out = []
    for g in product_groups(brief):
        if g in _NOT_SEIZED or g.split()[0] in {"Police", "Operation", "Europol"}:
            continue
        out.append(g)
    return out[:4]


def _headline_count(brief: EditorialBrief) -> tuple[str, str]:
    """(figure, what) when the headline itself states a seized count
    ("Seizes 6.4M Stolen Logins"); figures from `brief.facts` first."""
    for key, what in (("accounts", "accounts"), ("records", "records")):
        if brief.facts.get(key):
            return str(brief.facts[key]), what
    m = re.search(r"seiz\w*\s+(?:about\s+|over\s+|nearly\s+)?(\d+(?:[.,]\d+)?\s?(?:m|k|b|million|billion)?)\s+"
                  r"(?:stolen\s+)?(logins|credentials|accounts|passwords|domains|servers)", headline_main(brief.text))
    if not m:
        return "", ""
    fig = m.group(1).replace(" ", "").upper().replace("MILLION", "M").replace("BILLION", "B")
    what = ("stolen " if "stolen" in m.group(0) else "") + m.group(2)
    return fig, what


# ---------------------------------------------------------------- props

def _rack(doc: Doc, x: float, y: float, w: float, h: float, rng: random.Random) -> list[tuple[float, float]]:
    """A 42U rack in front elevation, all units dark. Returns handle points
    (where tags can be tied) down the right rail."""
    doc.shadow(x, y, w, h, 6, 1.6)
    # the rack's side panel, turned slightly away (depth)
    sd = 70
    doc.poly([(x - sd, y + 40), (x, y), (x, y + h), (x - sd, y + h - 30)],
             doc.lin([(0, "#1A1F25", 1), (1, "#262C34", 1)], 0, 0, 1, 0))
    for k in range(int(h // 60)):
        doc.line((x - sd + 12, y + 70 + k * 60), (x - 12, y + 40 + k * 60), "#11151A", 2, 0.8)
    doc.rect(x, y, w, h, doc.lin([(0, "#2B323B", 1), (1, "#161A20", 1)], 0, 0, 1, 0), 6, stroke="#0B0D10", sw=2)
    rail = 34
    for rx in (x + 10, x + w - 10 - rail):
        doc.rect(rx, y + 10, rail, h - 20, "#1D2228", 3)
        for k in range(int((h - 40) // 22)):
            doc.rect(rx + 12, y + 24 + k * 22, 10, 7, "#0C0E11", 1.5)
    inner = Box(x + 10 + rail, y + 18, w - 20 - 2 * rail, h - 36)
    doc.rect(inner.x, inner.y, inner.w, inner.h, "#0B0D10")
    kinds = ["switch", "server", "server", "storage", "server", "server", "storage", "server", "server",
             "switch", "server", "storage", "server", "server", "server", "storage"]
    yy = inner.y + 6
    i = 0
    handles: list[tuple[float, float]] = []
    while yy < inner.b - 20:
        kind = kinds[i % len(kinds)]
        uh: float = 44 if kind == "switch" else 74 if kind == "storage" else 56 if rng.random() < 0.6 else 88
        if yy + uh > inner.b - 4:
            uh = inner.b - 4 - yy
            if uh < 40:
                break
        doc.rect(inner.x - 2, yy, inner.w + 4, uh - 4, "#000", 2, opacity=0.35)
        # every light off: the operation is down
        _unit(doc, inner.x, yy, inner.w, uh - 6, kind, i)
        handles.append((inner.r - 8, yy + uh / 2))
        yy += uh
        i += 1
    # key light from the upper left across the rack face, rim on the right rail
    doc.rect(x, y, w, h, doc.lin([(0, "#FFFFFF", 0.16), (0.45, "#FFFFFF", 0.0), (1, "#000", 0.25)], 0, 0, 0.6, 1), 6)
    doc.rect(x + w - 4, y, 4, h, "#C9D3DE", opacity=0.45)
    return handles


def _unit(doc: Doc, x: float, y: float, w: float, h: float, kind: str, i: int) -> None:
    face = "#434C58" if i % 2 else "#3B434E"
    doc.rect(x, y, w, h, doc.lin([(0, face, 1), (1, "#1B2026", 1)]), 3, stroke="#0E1014", sw=1)
    doc.rect(x, y, w, 2, "#FFFFFF", opacity=0.10)
    for ex in (x + 4, x + w - 18):
        doc.rect(ex, y + 3, 14, h - 6, "#3A414B", 2)
        doc.circle(ex + 7, y + h / 2, 2.6, "#11141A")
    if kind == "switch":
        n = int((w - 120) // 24)
        for k in range(n):
            px = x + 36 + k * 24
            doc.rect(px, y + h / 2 - 8, 18, 15, "#0C0E12", 2)
    elif kind == "storage":
        n = int((w - 80) // 52)
        for k in range(n):
            px = x + 30 + k * 52
            doc.rect(px, y + 6, 46, h - 12, "#20252C", 3, stroke="#0E1014", sw=1)
            doc.rect(px + 6, y + h / 2 - 2, 34, 4, "#14171C", 2)
    else:
        for k in range(int((w * 0.42) // 10)):
            doc.rect(x + 30 + k * 10, y + 7, 5, h - 14, "#14171C", 2)
        bx = x + w * 0.56
        for k in range(3):
            doc.rect(bx + k * (w * 0.1), y + 6, w * 0.085, h - 12, "#20252C", 2, stroke="#0E1014", sw=1)
        doc.circle(x + w - 36, y + h / 2, 4, "#151820", stroke="#3D4550", sw=1.5)


def _tape(doc: Doc, x0: float, y0: float, x1: float, y1: float, hgt: float = 74, word: str = "SEIZED",
          phase: float = 0.0) -> None:
    """Barrier tape from (x0, y0) to (x1, y1) with the word repeated."""
    ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
    ln = math.hypot(x1 - x0, y1 - y0)
    with doc.g(transform=f"translate({f(x0)} {f(y0)}) rotate({ang:.2f})"):
        doc.rect(4, -hgt / 2 + 18, ln, hgt, "#000", opacity=0.45, extra=f' filter="{doc.blur(10)}"')
        doc.rect(0, -hgt / 2, ln, hgt, doc.lin([(0, "#FFD43B", 1), (0.5, _TAPE, 1), (1, "#D99A00", 1)]))
        doc.rect(0, -hgt / 2 + 6, ln, 7, _TAPE_INK)
        doc.rect(0, hgt / 2 - 13, ln, 7, _TAPE_INK)
        size = hgt * 0.46
        unit = T.measure(word, size, "ui_bold", tracking=size * 0.18) + size * 2.2
        cx = -phase * unit
        while cx < ln:
            doc.text(word, cx, T.cap_height(size, "ui_bold") / 2, size, _TAPE_INK, "ui_bold", tracking=size * 0.18)
            doc.rect(cx + unit - size * 1.45, -size * 0.18, size * 0.7, size * 0.36, _TAPE_INK, 2)
            cx += unit
        # creases
        for k in range(1, int(ln // 260) + 1):
            doc.rect(k * 260 + (k * 37) % 90, -hgt / 2, 3, hgt, "#FFFFFF", opacity=0.22)


def _tag(doc: Doc, x: float, y: float, w: float, h: float, anchor: tuple[float, float], lines: list[tuple[str, float,
         str]], rot: float) -> None:
    """A manila evidence tag tied by a string to `anchor`; `lines` = (text,
    size, font) set left-aligned."""
    ex, ey = x + 30, y + h / 2
    a = math.radians(rot)
    # string: anchor -> eyelet (rotated position)
    cx, cy = x + w / 2, y + h / 2
    rx = cx + (ex - cx) * math.cos(a) - (ey - cy) * math.sin(a)
    ry = cy + (ex - cx) * math.sin(a) + (ey - cy) * math.cos(a)
    mx, my = (anchor[0] + rx) / 2, max(anchor[1], ry) + 26
    doc.path(f"M{f(anchor[0])} {f(anchor[1])}Q{f(mx)} {f(my)} {f(rx)} {f(ry)}", stroke="#000", sw=4, opacity=0.3,
             extra=' transform="translate(2 6)"')
    doc.path(f"M{f(anchor[0])} {f(anchor[1])}Q{f(mx)} {f(my)} {f(rx)} {f(ry)}", stroke="#D9D2C3", sw=3)
    doc.circle(anchor[0], anchor[1], 6, "#D9D2C3")
    with doc.g(transform=f"rotate({rot:.2f} {f(cx)} {f(cy)})"):
        shape = (f"M{f(x + 36)} {f(y)}H{f(x + w - 8)}Q{f(x + w)} {f(y)} {f(x + w)} {f(y + 8)}V{f(y + h - 8)}"
                 f"Q{f(x + w)} {f(y + h)} {f(x + w - 8)} {f(y + h)}H{f(x + 36)}L{f(x)} {f(y + h - 30)}"
                 f"V{f(y + 30)}Z")
        doc.path(shape, fill="#000", opacity=0.45, extra=f' transform="translate(8 18)" filter="{doc.blur(9)}"')
        doc.path(shape, fill=doc.lin([(0, _TAG[0], 1), (1, _TAG[1], 1)], 0, 0, 0.3, 1))
        doc.path(shape, fill="none", stroke="#FFFFFF", sw=1.5, opacity=0.35)
        doc.circle(ex, ey, 15, "#C9A964", stroke="#A88B4C", sw=3)
        doc.circle(ex, ey, 7, "#1B1F25")
        doc.rect(x + 60, y, 6, h, "#B0915A", opacity=0.45)
        ty = y + 22
        tot = sum(T.cap_height(s, fn) for _, s, fn in lines) + 18 * (len(lines) - 1)
        ty = y + (h - tot) / 2
        for txt, s, fn in lines:
            ty += T.cap_height(s, fn)
            doc.text(txt, x + 86, ty, s, _TAG_INK, fn)
            ty += 18


# ---------------------------------------------------------------- compositions

def _comp_rack(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """A: the taped-off rack, its operations on evidence tags."""
    background(doc, light=(0.30, 0.10), floor=780)
    # backlight on the wall behind the rack: a clear silhouette at feed size
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#8FA3B8", 0.42), (0.6, "#56677A", 0.12), (1, "#000", 0)], 0.36, 0.38,
                                      0.55))
    names = _seized_names(brief)
    fig, what = _headline_count(brief)
    rx, rw = 270, 580
    handles = _rack(doc, rx, -30, rw, 880, rng)
    # floor shadow line
    doc.rect(rx - 40, 846, rw + 80, 20, "#000", 10, opacity=0.5, extra=f' filter="{doc.blur(12)}"')
    _tape(doc, -40, 250, 1640, 470, phase=0.15)
    _tape(doc, -40, 690, 1100, 520, hgt=60, phase=0.55)
    # evidence tags down the right rail
    tags: list[list[tuple[str, float, str]]] = []
    for nm in names:
        tags.append([(nm, fit_size(nm, 64, 520, "ui_bold"), "ui_bold")])
    if fig:
        tags.append([(fig, 104, "display"), (what, 34, "ui")])
    if not tags:
        tags.append([("servers", 64, "ui_bold")])
    n = len(tags)
    top, gap = 70, 34
    hs: list[float] = [190 if len(t) > 1 else 104 for t in tags]
    avail = 840 - top - gap * (n - 1)
    k = min(1.0, avail / sum(hs))
    hs = [h_ * k for h_ in hs]
    y = top + (840 - top - sum(hs) - gap * (n - 1)) / 2
    for i, (t, h_) in enumerate(zip(tags, hs)):
        hp = handles[min(len(handles) - 1, max(0, int((y + h_ / 2 - 20) / 880 * len(handles))))]
        tx = 930 + (i % 2) * 44
        rot = (-3.5 if i % 2 else 2.5) + rng.uniform(-1.0, 1.0)
        if len(t) > 1:
            t = [(t[0][0], t[0][1] * k, t[0][2]), (t[1][0], t[1][1] * max(k, 0.8), t[1][2])]
        else:
            t = [(t[0][0], t[0][1] * max(k, 0.85), t[0][2])]
        _tag(doc, tx, y, 560, h_, hp, t, rot)
        y += h_ + gap
    doc.focus = Box(150, 40, 1360, 765)
    vignette(doc, 0.5)


def _evidence_bag(doc: Doc, b: Box) -> None:
    """Clear plastic over whatever was drawn in `b` (call after the contents)."""
    d = (f"M{f(b.x)} {f(b.y + 20)}Q{f(b.x)} {f(b.y)} {f(b.x + 20)} {f(b.y)}H{f(b.r - 20)}Q{f(b.r)} {f(b.y)} "
         f"{f(b.r)} {f(b.y + 20)}L{f(b.r - 6)} {f(b.b - 30)}Q{f(b.r - 8)} {f(b.b)} {f(b.r - 36)} {f(b.b - 2)}"
         f"H{f(b.x + 30)}Q{f(b.x + 4)} {f(b.b)} {f(b.x + 6)} {f(b.b - 30)}Z")
    doc.path(d, fill=doc.lin([(0, "#E8F0F8", 0.20), (0.5, "#E8F0F8", 0.06), (1, "#E8F0F8", 0.16)], 0, 0, 1, 1))
    doc.path(d, fill="none", stroke="#EEF4FA", sw=4, opacity=0.6)
    # creases: soft specular streaks where the film folds
    for u, v, du, dv, wd in ((0.04, 0.30, 0.30, -0.10, 18), (0.55, 0.12, 0.40, 0.06, 12),
                             (0.20, 0.82, 0.35, 0.04, 14), (0.70, 0.70, 0.26, 0.16, 10)):
        x0, y0 = b.x + b.w * u, b.y + b.h * v
        doc.path(f"M{f(x0)} {f(y0)}q{f(b.w * du * 0.5)} {f(b.h * dv - 14)} {f(b.w * du)} {f(b.h * dv)}",
                 stroke="#FFFFFF", sw=wd, opacity=0.16)
    # heat-seal strip with a red tamper band
    doc.rect(b.x + 4, b.y + 18, b.w - 8, 40, "#E8EEF4", opacity=0.25)
    doc.rect(b.x + 4, b.y + 28, b.w - 8, 18, "#C7362B")
    doc.rect(b.x + 4, b.y + 34, b.w - 8, 3, "#8E1E16")


def _comp_bag(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """B: one server from the rack, sealed in an evidence bag on a steel
    bench, its label listing what was seized."""
    background(doc, light=(0.45, 0.0))
    # the bench seen from above, lit by one overhead lamp
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#5A6573", 0.55), (1, "#0E1115", 0)], 0.45, 0.42, 0.62))
    names = _seized_names(brief)
    fig, what = _headline_count(brief)
    with doc.g(transform=f"rotate({rng.uniform(-6.0, -4.0):.2f} 760 450)"):
        bag = Box(130, 150, 1300, 640)
        doc.rect(bag.x + 20, bag.y + 50, bag.w, bag.h, "#000", 24, opacity=0.55, extra=f' filter="{doc.blur(26)}"')
        # contents: a 2U server, front elevation, every light off
        sv = Box(bag.x + 70, bag.y + 100, bag.w - 140, 150)
        doc.rect(sv.x + 8, sv.y + 16, sv.w, sv.h, "#000", 4, opacity=0.5, extra=f' filter="{doc.blur(8)}"')
        _unit(doc, sv.x, sv.y, sv.w, sv.h / 2, "server", 1)
        _unit(doc, sv.x, sv.y + sv.h / 2, sv.w, sv.h / 2, "storage", 0)
        # write-on evidence label, printed on the bag
        lb = Box(bag.x + 70, sv.b + 40, 760, bag.b - sv.b - 70)
        doc.rect(lb.x, lb.y, lb.w, lb.h, "#F4F1EA", 6)
        doc.rect(lb.x, lb.y, lb.w, 76, "#C7362B", 6)
        doc.rect(lb.x, lb.y + 60, lb.w, 16, "#C7362B")
        doc.text("SEIZED", lb.x + 32, lb.y + 56, 52, "#FFFFFF", "ui_bold", tracking=9)
        rows = names or ["servers and domains"]
        ry = lb.y + 76
        rh = (lb.h - 76) / max(1, len(rows))
        for k, n in enumerate(rows):
            sz = min(56.0, rh * 0.62)
            doc.text(n, lb.x + 32, ry + rh / 2 + T.cap_height(sz, "ui_bold") / 2, sz, "#1B1F26", "ui_bold")
            if k < len(rows) - 1:
                doc.line((lb.x + 32, ry + rh), (lb.r - 32, ry + rh), "#C9C2B5", 2)
            ry += rh
        if fig:
            fx = lb.r + 50
            doc.text(fig, fx, lb.y + 120, 110, "#F2F4F7", "display")
            doc.text(what, fx + 4, lb.y + 172, 36, "#B9C2CD", "ui")
        _evidence_bag(doc, bag)
    doc.focus = Box(140, 120, 1300, 731)
    vignette(doc, 0.6)


ALTERNATIVES: dict[str, Callable[[Doc, EditorialBrief, random.Random], None]] = {"a": _comp_rack, "b": _comp_bag}


@scene("police_takedown")
def police_takedown(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    _comp_rack(doc, brief, rng)
