"""Cases against alleged cybercriminals: the legal step the story reports
(acquittal, plea, extradition, sentence), set large, together with one graphic
object made from the case's own sourced figure.

No documents are drawn: no docket, no case number, no names, no seal, no
jurisdiction beyond what the headline states. Figures come from
`brief.facts` only; the step word comes from the source wording.

Variants (each has two compositions in ALTERNATIVES):
  crypto  a reported crypto amount: a chain of blocks with the gavel resting
          on it (a), or the scales of justice weighing the blocks (b);
  leak    leaked videos: the count as a wall of blank video tiles slipping out
          of their frame (a), or a film reel unspooling (b). Never game art,
          never a frame presented as real footage;
  years   a maximum sentence: one tally stroke per year (a), or the
          extradition route the source states (b);
  gavel   anything else: the gavel and the step word.
"""
from __future__ import annotations

import math
import random
import re
from typing import Callable

from .. import type as T
from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f
from . import scene
from ._camera import V3, Camera, path_of

_PAPER0, _PAPER1 = "#F2ECDF", "#E2D7C0"
_INK = "#1B2333"
_BRASS = ("#7A5A22", "#E8C46A", "#B48A3A", "#5E4416")


def _fact(brief: EditorialBrief, key: str) -> str:
    v = brief.facts.get(key)
    if not v:
        return ""
    if brief.facts.get(key + "_approx"):
        return f"~{v}"
    if brief.facts.get(key + "_plus"):
        return f"{v}+"
    return str(v)


def _verdict(text: str) -> tuple[str, str]:
    """(step word, tone) for the step the story reports, in its own wording."""
    t = text
    if re.search(r"acquit|not guilty|виправда", t):
        return "ACQUITTED", "safe"
    if re.search(r"\bclears?\b|cleared", t):
        return "CLEARED", "safe"
    if re.search(r"extradit|екстрадиц", t):
        return "EXTRADITED", "danger"
    if re.search(r"plead\w* guilty|pleads guilty|guilty plea|визна\w* провину", t):
        return "GUILTY PLEA", "danger"
    if re.search(r"sentenced|засуджен", t):
        return "SENTENCED", "danger"
    if re.search(r"convicted|found guilty", t):
        return "CONVICTED", "danger"
    if re.search(r"lawsuit|\bsues?\b|sued|подав до суду|позов", t):
        return "LAWSUIT", "accent"
    if re.search(r"indict|charged", t):
        return "CHARGED", "danger"
    if re.search(r"arrest|арешт|затрима", t):
        return "ARRESTED", "danger"
    return "IN COURT", "accent"


def _tone(doc: Doc, tone: str) -> str:
    p = doc.pal
    return p.safe if tone == "safe" else p.danger if tone == "danger" else p.accent


def _kind(brief: EditorialBrief) -> str:
    text = brief.text or ""
    if brief.facts.get("videos"):
        return "leak"
    if _fact(brief, "money") and re.search(r"crypto|ethereum|bitcoin|blockchain|криптовал", text):
        return "crypto"
    years = str(brief.facts.get("years") or "")
    if years.isdigit() and 0 < int(years) <= 60:
        return "years"
    return "gavel"


def _paper(doc: Doc, light: tuple[float, float] = (0.3, 0.2)) -> None:
    doc.rect(0, 0, W, H, doc.lin([(0, _PAPER0, 1), (1, _PAPER1, 1)], 0, 0, 0.4, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FFFFFF", 0.55), (1, "#FFFFFF", 0)], light[0], light[1], 0.7))


def _fit(s: str, size: float, max_w: float, font: str = "display") -> float:
    while T.measure(s, size, font) > max_w and size > 20:
        size -= 2
    return size


def _kicker(doc: Doc, x: float, y: float, s: str, color: str) -> None:
    doc.rect(x, y - 40, 56, 7, color)
    doc.text(s, x, y, 26, doc.pal.muted, "ui_bold", tracking=3)


# ---------------------------------------------------------------- solid objects

def _cube(doc: Doc, cam: Camera, o: V3, s: float, front: str, top: str, side: str, edge: str) -> list[tuple[float, float]]:
    """A cube with its corner `o` at (left, bottom, back); camera above-left.
    Returns the projected front face (TL, TR, BR, BL)."""
    x0, y0, z0 = o
    x1, y1, z1 = x0 + s, y0 + s, z0 + s
    left = [(x0, y1, z0), (x0, y1, z1), (x0, y0, z1), (x0, y0, z0)]
    tp = [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)]
    fr = [(x0, y1, z1), (x1, y1, z1), (x1, y0, z1), (x0, y0, z1)]
    cam.poly(doc, left, side)
    cam.poly(doc, tp, top)
    pts = cam.poly(doc, fr, front)
    doc.path(path_of([pts[3], pts[0], pts[1]], closed=False), stroke=edge, sw=3, opacity=0.9)
    tps = [cam.p(q) for q in tp]
    doc.path(path_of([tps[3], tps[0], tps[1]], closed=False), stroke=edge, sw=2, opacity=0.5)
    return pts


def _link(doc: Doc, a: tuple[float, float], b: tuple[float, float], color: str, w: float) -> None:
    """Two interlocked chain links between screen points a and b."""
    ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    for k, (t, flat) in enumerate(((0.32, False), (0.68, True))):
        cx, cy = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        rx, ry = L * 0.26, (w * 0.9 if not flat else w * 0.32)
        tr = f"rotate({f(ang)} {f(cx)} {f(cy)})"
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy + 6)}" rx="{f(rx)}" ry="{f(ry)}" fill="none" stroke="#000" opacity="0.18" '
                f'stroke-width="{f(w * 0.42)}" transform="{tr}" filter="{doc.blur(4)}"/>')
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{f(rx)}" ry="{f(ry)}" fill="none" stroke="#4A5468" '
                f'stroke-width="{f(w * 0.52)}" transform="{tr}"/>')
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{f(rx)}" ry="{f(ry)}" fill="none" stroke="{color}" '
                f'stroke-width="{f(w * 0.36)}" transform="{tr}"/>')
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy - w * 0.08)}" rx="{f(rx)}" ry="{f(ry)}" fill="none" '
                f'stroke="#FFFFFF" opacity="0.45" stroke-width="{f(w * 0.1)}" transform="{tr}"/>')
        _ = k


def _gavel(doc: Doc, cx: float, cy: float, scale: float, rot: float) -> None:
    """A turned-wood gavel lying at `rot` degrees, head centred at (cx, cy)."""
    s = scale
    wood_v = doc.lin([(0, "#4A2A12", 1), (0.3, "#C08552", 1), (0.55, "#9C6436", 1), (1, "#3E220E", 1)], 0, 0, 0, 1)
    wood_h = doc.lin([(0, "#3E220E", 1), (0.32, "#C98D58", 1), (0.6, "#9C6436", 1), (1, "#3E220E", 1)], 0, 0, 1, 0)
    band = doc.lin([(0, "#6A4A18", 1), (0.35, "#F0D27E", 1), (1, "#5E4416", 1)], 0, 0, 1, 0)
    with doc.g(f"rotate({f(rot)} {f(cx)} {f(cy)})"):
        # shadow
        doc.rect(cx - 30 * s, cy + 48 * s, 360 * s, 34 * s, "#000", 16 * s, opacity=0.22,
                 extra=f' filter="{doc.blur(round(10 * s))}"')
        # handle
        doc.rect(cx + 40 * s, cy - 13 * s, 300 * s, 26 * s, wood_v, 13 * s)
        doc.rect(cx + 318 * s, cy - 17 * s, 42 * s, 34 * s, wood_v, 17 * s)
        doc.rect(cx + 50 * s, cy - 8 * s, 260 * s, 5 * s, "#FFFFFF", 3 * s, opacity=0.25)
        # head: a turned cylinder seen side-on, with its end face
        hw, hh = 190 * s, 96 * s
        doc.rect(cx - hw / 2, cy - hh / 2, hw, hh, wood_v, 14 * s)
        for bx in (cx - hw / 2 + 22 * s, cx + hw / 2 - 34 * s):
            doc.rect(bx, cy - hh / 2 - 2 * s, 12 * s, hh + 4 * s, band, 3 * s)
        doc.rect(cx - hw / 2 + 10 * s, cy - hh / 2 + 12 * s, hw - 20 * s, 9 * s, "#FFFFFF", 4 * s, opacity=0.22)
        doc.add(f'<ellipse cx="{f(cx - hw / 2)}" cy="{f(cy)}" rx="{f(16 * s)}" ry="{f(hh / 2)}" fill="{wood_h}"/>')
        doc.add(f'<ellipse cx="{f(cx - hw / 2)}" cy="{f(cy)}" rx="{f(9 * s)}" ry="{f(hh / 3.2)}" fill="none" '
                f'stroke="#3E220E" stroke-width="{f(1.5 * s)}" opacity="0.5"/>')


def _brass_text(doc: Doc, s: str, x: float, y: float, size: float, anchor: str = "start") -> None:
    doc.text(s, x + 3, y + 4, size, "#000000", "display", anchor=anchor, opacity=0.25)
    doc.text(s, x, y, size, _BRASS[1], "display", anchor=anchor)


# ---------------------------------------------------------------- crypto

def _crypto_a(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """Chain of blocks, the gavel resting across it; the decision set large."""
    p = doc.pal
    _paper(doc, (0.25, 0.15))
    word, tone = _verdict(brief.text or "")
    col = _tone(doc, tone)
    money = _fact(brief, "money")

    cam = Camera(eye=(-300.0, 300.0, 820.0), target=(240.0, 40.0, 0.0), focal=1700, cx=880, cy=650)
    s_ = 170.0
    gap = 120.0
    navy = ("#1F2B40", "#3A4A68", "#111827")
    fronts = []
    for i in reversed(range(3)):
        o = (i * (s_ + gap), 0.0, -s_ / 2)
        # floor shadow
        sh = [cam.p(q) for q in ((o[0] - 10, 0.0, o[2] - 4), (o[0] + s_ + 30, 0.0, o[2] - 4),
                                 (o[0] + s_ + 30, 0.0, o[2] + s_ + 26), (o[0] - 10, 0.0, o[2] + s_ + 26))]
        doc.path(path_of(sh), fill="#3B2F1C", opacity=0.45, extra=f' filter="{doc.blur(14)}"')
        sh2 = [cam.p(q) for q in ((o[0] + 40, 0.0, o[2] - 30), (o[0] + s_ + 140, 0.0, o[2] - 30),
                                  (o[0] + s_ + 60, 0.0, o[2] + s_ + 10), (o[0] - 10, 0.0, o[2] + s_ + 10))]
        doc.path(path_of(sh2), fill="#3B2F1C", opacity=0.18, extra=f' filter="{doc.blur(26)}"')
        fr = _cube(doc, cam, o, s_, doc.lin([(0, navy[0], 1), (1, "#162033", 1)], 0, 0, 0.3, 1),
                   doc.lin([(0, navy[1], 1), (1, "#2C3A55", 1)], 0, 0, 0, 1), navy[2], "#8FA3C4")
        fronts.append(fr)
        if i > 0:
            pass
    fronts.reverse()
    # links between neighbouring blocks (mid-height of the front faces)
    for i in range(2):
        a = ((fronts[i][1][0] + fronts[i][2][0]) / 2 - 10, (fronts[i][1][1] + fronts[i][2][1]) / 2)
        b = ((fronts[i + 1][0][0] + fronts[i + 1][3][0]) / 2 + 10, (fronts[i + 1][0][1] + fronts[i + 1][3][1]) / 2)
        _link(doc, a, b, "#B9C3D3", 30)
    # the amount on the nearest block's face
    if money:
        with doc.g(cam.face((0.0, s_, s_ / 2), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (s_, s_))):
            size = _fit(money, 90, s_ - 20)
            doc.text(money, s_ / 2, s_ / 2 + T.cap_height(size, "display") / 2, size, _BRASS[1], "display",
                     anchor="middle")
    # gavel lying across the middle block
    top = cam.p((s_ + gap + s_ / 2, s_, 0.0))
    _gavel(doc, top[0] - 50, top[1] - 66, 1.3, -14)

    # the decision, large
    x = 90
    _kicker(doc, x, 130, "COURT DECISION", col)
    size = _fit(word, 150, 820)
    doc.text(word, x - 4, 150 + T.cap_height(size, "display") + 10, size, col, "display")
    doc.text("crypto heist charges" if re.search(r"heist", brief.text or "") else "crypto theft charges",
             x, 150 + T.cap_height(size, "display") + 74, 34, _INK, "ui_bold")
    doc.focus = Box(40, 40, 1520, 855)
    _ = (rng, p)


def _crypto_b(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """Scales of justice: the blocks of the case in one pan; the decision below."""
    _paper(doc, (0.5, 0.1))
    word, tone = _verdict(brief.text or "")
    col = _tone(doc, tone)
    money = _fact(brief, "money")
    brass = doc.lin([(0, _BRASS[3], 1), (0.4, _BRASS[1], 1), (0.7, _BRASS[2], 1), (1, _BRASS[0], 1)], 0, 0, 1, 0)
    brass_v = doc.lin([(0, _BRASS[1], 1), (1, _BRASS[0], 1)], 0, 0, 0, 1)
    cx = 800.0
    # column and base
    doc.add(f'<ellipse cx="{f(cx)}" cy="640" rx="210" ry="26" fill="#3B2F1C" opacity="0.25" filter="{doc.blur(12)}"/>')
    doc.path(f"M{f(cx - 170)} 636Q{f(cx)} 600 {f(cx + 170)} 636L{f(cx + 150)} 610Q{f(cx)} 585 {f(cx - 150)} 610Z",
             fill=brass)
    doc.rect(cx - 14, 150, 28, 460, brass, 6)
    doc.circle(cx, 140, 26, brass_v)
    # beam
    bl, br, by = cx - 380, cx + 380, 176.0
    doc.rect(bl, by - 9, br - bl, 18, brass_v, 9)
    doc.circle(bl, by, 13, brass_v)
    doc.circle(br, by, 13, brass_v)
    pans = []
    for px in (bl, br):
        py = 470.0
        doc.path(f"M{f(px)} {f(by)}L{f(px - 150)} {f(py)}M{f(px)} {f(by)}L{f(px + 150)} {f(py)}", stroke=_BRASS[0],
                 sw=3)
        doc.path(f"M{f(px - 170)} {f(py)}Q{f(px)} {f(py + 120)} {f(px + 170)} {f(py)}Z", fill=brass)
        doc.add(f'<ellipse cx="{f(px)}" cy="{f(py)}" rx="170" ry="16" fill="{_BRASS[2]}"/>')
        pans.append((px, py))
    # left pan: three linked blocks (flat, front view) carrying the amount
    px, py = pans[0]
    bw = 92
    for i in range(3):
        bx = px - 1.5 * bw - 12 + i * (bw + 12)
        doc.rect(bx, py - bw - 4, bw, bw, "#1F2B40", 8, stroke="#8FA3C4", sw=2)
        doc.rect(bx + 6, py - bw + 2, bw - 12, 10, "#FFFFFF", 4, opacity=0.12)
        if i < 2:
            doc.rect(bx + bw - 4, py - bw / 2 - 10, 20, 12, "none", 6, stroke="#B9C3D3", sw=4)
    if money:
        doc.text(money, px, py - bw - 40, 96, _INK, "display", anchor="middle")
    # right pan: the charges, as a blank label
    px, py = pans[1]
    doc.text("CHARGES", px, py - 30, 40, doc.pal.muted, "ui_bold", anchor="middle", tracking=4)
    # decision across the foot of the frame
    size = _fit(word, 150, 1200)
    doc.text(word, cx, 820, size, col, "display", anchor="middle", tracking=4)
    doc.focus = Box(100, 100, 1400, 788)
    _ = rng


# ---------------------------------------------------------------- leak

def _tile(doc: Doc, x: float, y: float, w: float, h: float, rot: float, shade: str) -> str:
    """A blank video tile: dark frame, play glyph, scrub bar (no picture)."""
    tr = f' transform="rotate({f(rot)} {f(x + w / 2)} {f(y + h / 2)})"' if rot else ""
    k = h / 60
    return (f'<g{tr}><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="{f(4 * k)}" fill="{shade}"/>'
            f'<path d="M{f(x + w / 2 - 7 * k)} {f(y + h / 2 - 10 * k)}v{f(20 * k)}l{f(17 * k)}-{f(10 * k)}z" '
            f'fill="#FFFFFF" opacity="0.85"/>'
            f'<rect x="{f(x + 6 * k)}" y="{f(y + h - 9 * k)}" width="{f(w - 12 * k)}" height="{f(2.2 * k)}" '
            f'fill="#FFFFFF" opacity="0.25"/></g>')


def _leak_a(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """A wall of blank video tiles, one per leaked video, slipping out of its
    frame at the corner; the count set huge."""
    p = doc.pal
    _paper(doc, (0.7, 0.1))
    word, tone = _verdict(brief.text or "")
    col = _tone(doc, tone)
    raw = str(brief.facts.get("videos") or "0").replace(",", "")
    n = int(raw) if raw.isdigit() else 0
    count = _fact(brief, "videos")
    cols = 10
    rows = max(1, min(9, math.ceil(n / cols))) if n else 9
    tw, th, g = 62.0, 38.0, 8.0
    gx, gy = 80.0, 120.0
    fw, fh = cols * (tw + g) + g, rows * (th + g) + g
    # the frame (a dark panel) and its shadow
    doc.rect(gx + 10, gy + 22, fw, fh, "#3B2F1C", 10, opacity=0.30, extra=f' filter="{doc.blur(16)}"')
    doc.rect(gx, gy, fw, fh, _INK, 10)
    shades = ("#2C3A55", "#344563", "#283650", "#3B4C6E")
    inside, falling = [], []
    total = n if n else cols * rows
    spill = min(14, max(0, total // 6))
    for i in range(total):
        r, c = divmod(i, cols)
        x, y = gx + g + c * (tw + g), gy + g + r * (th + g)
        if i >= total - spill:
            # the last tiles have slipped out of the frame and fall away
            j = i - (total - spill)
            t = (j + 0.5) / spill
            fx = gx + fw - 300 + t * 120 + (j % 3 - 1) * (70 + 150 * t) + rng.uniform(-20, 20)
            fy = gy + fh + 16 + (t ** 1.2) * 290 + rng.uniform(-14, 14)
            falling.append(_tile(doc, fx, fy, tw, th, rng.uniform(-35, 35) * (0.3 + t), shades[i % 4]))
        else:
            inside.append(_tile(doc, x, y, tw, th, 0, shades[(i * 7) % 4]))
    doc.add("".join(inside))
    # empty slots where the slipped tiles were
    for i in range(total - spill, total):
        r, c = divmod(i, cols)
        x, y = gx + g + c * (tw + g), gy + g + r * (th + g)
        doc.rect(x, y, tw, th, "none", 4, stroke="#5A6B8C", sw=1.5, extra=' stroke-dasharray="5 4"')
    doc.add('<g opacity="0.95">' + "".join(falling) + "</g>")
    # the count
    tx = gx + fw + 70
    _kicker(doc, tx, 170, "LEAKED", p.danger)
    size = _fit(count, 380, W - tx - 60)
    doc.text(count, tx - 10, 190 + T.cap_height(size, "display"), size, _INK, "display")
    doc.text("videos", tx, 190 + T.cap_height(size, "display") + 80, 64, _INK, "ui_bold")
    # the legal step, secondary
    by = 190 + T.cap_height(size, "display") + 140
    w = T.measure(word, 34, "ui_bold", 3) + 40
    doc.rect(tx, by, w, 60, "none", 6, stroke=col, sw=3)
    doc.text(word, tx + 20, by + 42, 34, col, "ui_bold", tracking=3)
    doc.focus = Box(50, 60, 1500, 844)


def _leak_b(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """A film reel unspooling a strip of blank frames across the page; the
    count set huge on the reel's side."""
    p = doc.pal
    doc.rect(0, 0, W, H, doc.lin([(0, "#1D2433", 1), (1, "#0F141E", 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FFFFFF", 0.10), (1, "#FFFFFF", 0)], 0.3, 0.35, 0.6))
    word, tone = _verdict(brief.text or "")
    col = p.danger if tone == "danger" else _tone(doc, tone)
    count = _fact(brief, "videos")
    # reel
    rx, ry, rr = 420.0, 420.0, 300.0
    doc.circle(rx + 18, ry + 30, rr, "#000", opacity=0.35)
    metal = doc.lin([(0, "#D9DEE5", 1), (0.5, "#8C95A3", 1), (1, "#C3CAD3", 1)], 0, 0, 1, 1)
    doc.circle(rx, ry, rr, metal)
    doc.circle(rx, ry, rr * 0.93, "#2A3142")
    doc.circle(rx, ry, rr * 0.80, doc.rad([(0, "#5B4A33", 1), (0.7, "#3A2F22", 1), (1, "#2A2219", 1)]))
    rings = "".join(f'<circle cx="{f(rx)}" cy="{f(ry)}" r="{f(rr * 0.80 - k * 9)}" fill="none" stroke="#000" '
                    f'opacity="0.18" stroke-width="1.5"/>' for k in range(1, 18))
    doc.add(rings)
    for k in range(3):
        a = math.radians(90 + k * 120)
        hx, hy = rx + math.cos(a) * rr * 0.52, ry + math.sin(a) * rr * 0.52
        doc.circle(hx, hy, rr * 0.2, "#151A24", stroke="#9AA3B0", sw=3)
    doc.circle(rx, ry, rr * 0.16, metal)
    doc.circle(rx, ry, rr * 0.05, "#151A24")
    # strip leaving the reel tangentially and running off to the right
    sx, sy = rx + rr * 0.78, ry + rr * 0.30
    d = f"M{f(sx)} {f(sy)}C{f(sx + 260)} {f(sy + 160)} {f(sx + 480)} {f(sy + 220)} {f(W + 60)} {f(sy + 120)}"
    sw = 120
    doc.path(d, stroke="#000", sw=sw + 8, opacity=0.35, extra=f' filter="{doc.blur(8)}"', cap="butt")
    doc.path(d, stroke="#1A1F2A", sw=sw, cap="butt")
    doc.path(d, stroke="#E7ECF3", sw=sw - 20, cap="butt", dash="6 10", opacity=0.0)
    doc.path(d, stroke="#E7ECF3", sw=8, cap="butt", dash="9 9", opacity=0.9,
             extra=' transform="translate(0 -46)"')
    doc.path(d, stroke="#E7ECF3", sw=8, cap="butt", dash="9 9", opacity=0.9,
             extra=' transform="translate(0 46)"')
    doc.path(d, stroke="#4A5670", sw=sw - 36, cap="butt", dash="88 8", opacity=1.0)
    doc.path(d, stroke="#FFFFFF", sw=sw - 36, cap="butt", dash="88 8", opacity=0.08)
    # the count
    tx = 860.0
    doc.rect(tx, 110, 56, 7, p.danger)
    doc.text("LEAKED", tx, 150, 26, "#AEB6C4", "ui_bold", tracking=3)
    size = _fit(count, 330, 700)
    doc.text(count, tx - 8, 170 + T.cap_height(size, "display"), size, "#F4F6FA", "display")
    doc.text("videos", tx + T.measure(count, size, "display") + 30, 170 + T.cap_height(size, "display"), 64,
             "#F4F6FA", "ui_bold")
    w = T.measure(word, 34, "ui_bold", 3) + 40
    doc.rect(tx, 820 - 60, w, 60, "none", 6, stroke=col, sw=3)
    doc.text(word, tx + 20, 820 - 18, 34, col, "ui_bold", tracking=3)
    doc.focus = Box(80, 60, 1460, 821)
    _ = rng


# ---------------------------------------------------------------- years

def _years_a(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """One tally stroke per year of the maximum sentence; the step set large."""
    p = doc.pal
    _paper(doc, (0.2, 0.2))
    word, tone = _verdict(brief.text or "")
    col = _tone(doc, tone)
    years = int(str(brief.facts.get("years") or "0"))
    x0, base, hgt = 90.0, 790.0, 300.0
    sw = 22.0
    step = 46.0
    gstep = 5 * step + 70
    maxw = W - 2 * x0
    while (years // 5) * gstep + (years % 5) * step > maxw and step > 20:
        step -= 2
        gstep = 5 * step + 50
    marks, cross = [], []
    for i in range(years):
        gi, k = divmod(i, 5)
        x = x0 + gi * gstep
        if k < 4:
            xx = x + k * step + rng.uniform(-3, 3)
            marks.append(f"M{f(xx)} {f(base - hgt + rng.uniform(-8, 8))}L{f(xx + rng.uniform(-6, 6))} {f(base)}")
        else:
            cross.append(f"M{f(x - 24)} {f(base - hgt * 0.22)}L{f(x + 3 * step + 26)} {f(base - hgt * 0.80)}")
    doc.path("".join(marks), stroke="#000", sw=sw, opacity=0.12, extra=' transform="translate(5 7)"')
    doc.path("".join(marks), stroke=_INK, sw=sw)
    doc.path("".join(cross), stroke=p.danger, sw=sw)
    _kicker(doc, x0, 130, "FACES UP TO", p.danger)
    doc.text(f"{years} years", x0 - 6, 150 + 112, 160, _INK, "display")
    w = T.measure(word, 64, "ui_bold", 4) + 56
    doc.rect(W - x0 - w, 150, w, 100, "none", 8, stroke=col, sw=5)
    doc.text(word, W - x0 - w + 28, 150 + 50 + T.cap_height(64, "ui_bold") / 2, 64, col, "ui_bold", tracking=4)
    doc.focus = Box(50, 60, 1500, 844)


def _years_b(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """The extradition route the source states (country names only when the
    text gives them), with the maximum sentence."""
    p = doc.pal
    _paper(doc, (0.5, 0.2))
    word, tone = _verdict(brief.text or "")
    col = _tone(doc, tone)
    years = str(brief.facts.get("years") or "")
    m = re.search(r"extradited from ([a-z]+) to (?:the )?(us|u\.s\.|united states)", brief.text or "")
    src, dst = (m.group(1).upper(), "US") if m else ("", "")
    # a faint graticule: the route is geographic, the map is not drawn
    grid = "".join(f"M0 {y}H{W}" for y in range(120, 900, 90)) + "".join(f"M{x} 0V{H}" for x in range(80, 1600, 120))
    doc.path(grid, stroke=_INK, sw=1, opacity=0.06)
    a, b = (1260.0, 640.0), (300.0, 640.0)
    ctrl = (780.0, 300.0)

    def qb(t: float) -> tuple[float, float]:
        return ((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * ctrl[0] + t * t * b[0],
                (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * ctrl[1] + t * t * b[1])

    pts = [qb(k / 40 * 0.9 + 0.05) for k in range(41)]
    d = path_of(pts, closed=False)
    doc.path(d, stroke="#000", sw=10, opacity=0.08, extra=' transform="translate(4 8)"')
    doc.path(d, stroke=col, sw=8, dash="22 16")
    tip, prev = pts[-1], pts[-3]
    ang = math.atan2(tip[1] - prev[1], tip[0] - prev[0])
    hd = 36
    doc.poly([(tip[0] + hd * 0.4 * math.cos(ang), tip[1] + hd * 0.4 * math.sin(ang)),
              (tip[0] - hd * math.cos(ang - 0.45), tip[1] - hd * math.sin(ang - 0.45)),
              (tip[0] - hd * math.cos(ang + 0.45), tip[1] - hd * math.sin(ang + 0.45))], col)
    for (x, y), lab in ((a, src), (b, dst)):
        doc.circle(x, y, 26, _PAPER0, stroke=_INK, sw=6)
        doc.circle(x, y, 10, _INK)
        if lab:
            doc.text(lab, x, y + 90, 56, _INK, "display", anchor="middle", tracking=4)
    size = _fit(word, 120, 900)
    doc.text(word, 800, 200, size, col, "display", anchor="middle")
    if years:
        doc.text(f"faces up to {years} years", 800, 290, 58, _INK, "ui_bold", anchor="middle")
    doc.focus = Box(140, 70, 1320, 742)
    _ = rng


# ---------------------------------------------------------------- generic

def _gavel_comp(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    _paper(doc, (0.6, 0.2))
    word, tone = _verdict(brief.text or "")
    col = _tone(doc, tone)
    _gavel(doc, 960, 560, 1.6, -18)
    _kicker(doc, 90, 170, "IN COURT", col)
    size = _fit(word, 140, 760)
    doc.text(word, 86, 190 + T.cap_height(size, "display"), size, col, "display")
    money = _fact(brief, "money")
    if money:
        doc.text(money, 90, 190 + T.cap_height(size, "display") + 150, 120, _INK, "display")
    doc.focus = Box(50, 60, 1500, 844)
    _ = rng


ALTERNATIVES: dict[str, Callable[[Doc, EditorialBrief, random.Random], None]] = {
    "crypto_a": _crypto_a, "crypto_b": _crypto_b,
    "leak_a": _leak_a, "leak_b": _leak_b,
    "years_a": _years_a, "years_b": _years_b,
    "gavel": _gavel_comp,
}
_SELECTED = {"crypto": _crypto_a, "leak": _leak_a, "years": _years_a, "gavel": _gavel_comp}


@scene("court_case")
def court_case(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    _SELECTED[_kind(brief)](doc, brief, rng)


def alt_for(brief: EditorialBrief) -> tuple[str, str]:
    """Alt text for the variant this scene draws (see _kind)."""
    k = _kind(brief)
    if k == "leak":
        n = str(brief.facts.get("videos", ""))
        return (f"Illustration: a wall of blank video tiles, {n + ' ' if n else ''}leaked videos, with the court "
                "outcome as a secondary note.",
                f"Ілюстрація: стіна порожніх відеокадрів, {n + ' ' if n else ''}злитих відео, з рішенням суду як "
                "другорядною позначкою.")
    if k == "crypto":
        m = str(brief.facts.get("money", ""))
        return (f"Illustration: a chain of blocks carrying the reported {m} with a gavel resting on it, and the "
                "court's decision.",
                f"Ілюстрація: ланцюг блоків із заявленою сумою {m}, на якому лежить суддівський молоток, і рішення "
                "суду.")
    if k == "years":
        y = str(brief.facts.get("years", ""))
        return (f"Illustration: {y} tally strokes for the maximum sentence of {y} years the defendant faces.",
                f"Ілюстрація: {y} рисок-позначок — максимальний строк {y} років, який загрожує обвинуваченому.")
    return ("Illustration: a judge's gavel with the stage the court case has reached.",
            "Ілюстрація: суддівський молоток і стадія, якої досягла судова справа.")
