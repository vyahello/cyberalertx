"""GPU cryptomining hidden by a tampered library: a graphics card seated in a
server board, heat rising off the fin stack, and in front of it a large
conceptual load gauge with two needles: the reading the tampered library
reports (low, pale) and the card's real load (pinned high, red, ghosted).

The gauge is a visibly conceptual instrument (no numbers, no tool name, no
command output): the sources state only that the malware alters GPU usage
readings. Generic card design: no vendor logo, no product name."""
from __future__ import annotations

import math
import random

from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f
from . import scene


def _board(doc: Doc, y: float, rng: random.Random) -> None:
    """Server motherboard edge along the bottom: PCB, traces, the PCIe slot row."""
    doc.rect(0, y, W, H - y, doc.lin([(0, "#123222", 1), (1, "#0B1F15", 1)]))
    d = []
    for _ in range(46):
        x = rng.uniform(0, W)
        yy = rng.uniform(y + 40, H)
        L = rng.uniform(60, 260)
        d.append(f"M{f(x)} {f(yy)}h{f(L)}l18 18h{f(rng.uniform(30, 120))}")
    doc.path("".join(d), stroke="#2E6B47", sw=1.6, opacity=0.55)
    for _ in range(30):
        doc.circle(rng.uniform(0, W), rng.uniform(y + 30, H), 3, "#C8A951", opacity=0.5)
    # small SMD parts
    for _ in range(12):
        x, yy = rng.uniform(20, W - 40), rng.uniform(y + 70, H - 20)
        doc.rect(x, yy, 22, 11, "#1C1F22", 1)
        doc.rect(x, yy, 4, 11, "#B9BEC2")
        doc.rect(x + 18, yy, 4, 11, "#B9BEC2")


def _fan(doc: Doc, cx: float, cy: float, r: float, phase: float) -> None:
    # housing ring
    doc.circle(cx, cy, r + 14, "#0E1112")
    doc.circle(cx, cy, r + 14, "none", "#3B4246", 3)
    doc.circle(cx, cy, r + 4, doc.rad([(0, "#1D2326", 1), (1, "#0A0C0D", 1)]))
    # blades: swept, slightly blurred (spinning)
    blades = []
    n = 9
    for i in range(n):
        a0 = phase + 2 * math.pi * i / n
        a1 = a0 + 0.55
        r0, r1 = r * 0.3, r * 0.97
        p0 = (cx + r0 * math.cos(a0), cy + r0 * math.sin(a0))
        p1 = (cx + r1 * math.cos(a0 + 0.25), cy + r1 * math.sin(a0 + 0.25))
        p2 = (cx + r1 * math.cos(a1 + 0.25), cy + r1 * math.sin(a1 + 0.25))
        p3 = (cx + r0 * math.cos(a1 - 0.15), cy + r0 * math.sin(a1 - 0.15))
        c1 = (cx + r * 0.7 * math.cos(a0 + 0.05), cy + r * 0.7 * math.sin(a0 + 0.05))
        blades.append(f"M{f(p0[0])} {f(p0[1])}Q{f(c1[0])} {f(c1[1])} {f(p1[0])} {f(p1[1])}"
                      f"A{f(r1)} {f(r1)} 0 0 1 {f(p2[0])} {f(p2[1])}L{f(p3[0])} {f(p3[1])}Z")
    doc.path("".join(blades), fill="#4A5357", opacity=0.55, extra=f' filter="{doc.blur(2.5)}"')
    doc.path("".join(blades), fill="none", stroke="#6C777C", sw=1.2, opacity=0.35)
    # motion sheen
    doc.circle(cx, cy, r, doc.rad([(0.3, "#FFFFFF", 0.0), (0.85, "#FFFFFF", 0.07), (1, "#FFFFFF", 0.0)]))
    # hub (plain, no logo)
    doc.circle(cx, cy, r * 0.3, doc.rad([(0, "#2E3538", 1), (1, "#16191B", 1)], 0.4, 0.35, 0.7))
    doc.circle(cx, cy, r * 0.3, "none", "#4E575B", 2)


def _card(doc: Doc, x0: float, y0: float, L: float, Hc: float, danger: str, rng: random.Random) -> Box:
    """Dual-fan graphics card, elevation. Returns the shroud box."""
    # cast shadow onto the board
    doc.rect(x0 + 20, y0 + 40, L, Hc, "#000", 18, opacity=0.5, extra=f' filter="{doc.blur(26)}"')
    # PCIe edge connector (gold fingers) seated in the slot
    fx, fw = x0 + 70, L * 0.52
    doc.rect(fx, y0 + Hc - 6, fw, 38, "#0D3B22", 2)
    fingers = "".join(f"M{f(xx)} {f(y0 + Hc)}h5v26h-5Z" for xx in range(int(fx + 6), int(fx + fw - 6), 9))
    doc.path(fingers, fill="#D9B45A")
    # PCB edge visible below the shroud
    doc.rect(x0, y0 + Hc - 18, L - 10, 26, "#1B4D31", 3)
    # power connector + cables on the top edge, right side
    px = x0 + L - 190
    doc.path("".join(f"M{f(px + 14 + k * 18)} {f(y0 - 30)}C{f(px + 14 + k * 18)} {f(y0 - 120)} "
                     f"{f(px + 60 + k * 26)} {f(y0 - 160)} {f(px + 90 + k * 30)} {f(y0 - 320)}" for k in range(4)),
             stroke="#E1B93A", sw=6)
    doc.path("".join(f"M{f(px + 23 + k * 18)} {f(y0 - 30)}C{f(px + 23 + k * 18)} {f(y0 - 116)} "
                     f"{f(px + 72 + k * 26)} {f(y0 - 156)} {f(px + 104 + k * 30)} {f(y0 - 320)}" for k in range(4)),
             stroke="#15181A", sw=6)
    doc.rect(px, y0 - 34, 84, 40, "#202427", 4, stroke="#3B4246")
    # heatsink fin stack visible along the top (shroud open there)
    doc.rect(x0 + 30, y0 - 26, L - 70, 34, "#1A1E20", 3)
    fins = "".join(f"M{f(xx)} {f(y0 - 22)}v28" for xx in range(int(x0 + 40), int(x0 + L - 48), 7))
    doc.path(fins, stroke="#9AA4A8", sw=2.2)
    doc.rect(x0 + 30, y0 - 26, L - 70, 34, doc.lin([(0, danger, 0.0), (1, danger, 0.45)]), 3)
    # shroud: faceted gunmetal body
    s = Box(x0, y0, L, Hc - 14)
    doc.rect(s.x, s.y, s.w, s.h, doc.lin([(0, "#3A4246", 1), (0.5, "#262C2F", 1), (1, "#181C1E", 1)], 0, 0, 0.2,
                                         1), 16)
    doc.poly([(s.x + 16, s.y + 6), (s.x + s.w * 0.36, s.y + 6), (s.x + s.w * 0.30, s.y + 44),
              (s.x + 16, s.y + 44)], "#FFFFFF", opacity=0.05)
    doc.poly([(s.r - 16, s.b - 8), (s.r - s.w * 0.30, s.b - 8), (s.r - s.w * 0.25, s.b - 40),
              (s.r - 16, s.b - 40)], "#000", opacity=0.25)
    doc.rect(s.x, s.y, s.w, s.h, "none", 16, stroke="#5A6469", sw=1.5)
    # bevel lines
    doc.path(f"M{f(s.x + 20)} {f(s.b - 30)}H{f(s.x + 120)}L{f(s.x + 150)} {f(s.b - 56)}"
             f"M{f(s.r - 20)} {f(s.y + 30)}H{f(s.r - 120)}L{f(s.r - 150)} {f(s.y + 56)}", stroke="#59646A", sw=2)
    # fans
    r = min(s.h * 0.39, s.w * 0.17)
    for k, fxc in enumerate((s.x + s.w * 0.29, s.x + s.w * 0.69)):
        _fan(doc, fxc, s.cy + 4, r, phase=0.3 + k * 0.9)
    # PCIe bracket (left), I/O cut-outs
    bx = x0 - 46
    doc.rect(bx, y0 - 34, 46, Hc + 60, doc.lin([(0, "#C9CED1", 1), (0.5, "#9DA4A8", 1), (1, "#7F878C", 1)], 0, 0,
                                               1, 0), 3)
    doc.rect(bx + 4, y0 + Hc + 24, 24, 50, "#9DA4A8", 2)
    for k in range(3):
        doc.rect(bx + 13, y0 + 20 + k * 52, 20, 36, "#0B0D0E", 3)
    doc.rect(bx + 14, y0 + 182, 18, 46, "#0B0D0E", 3)
    vents = "".join(f"M{f(bx + 10)} {f(y0 + 250 + k * 12)}h26" for k in range(int((Hc - 270) / 12)))
    doc.path(vents, stroke="#4C5458", sw=5)
    return s


def _heat(doc: Doc, x0: float, x1: float, y: float, danger: str, rng: random.Random) -> None:
    doc.glow((x0 + x1) / 2, y - 30, (x1 - x0) * 0.5, 70, danger, 0.32)
    d = []
    for k in range(9):
        x = x0 + (k + 0.5) * (x1 - x0) / 9 + rng.uniform(-12, 12)
        yy = y - 40
        seg = f"M{f(x)} {f(yy)}"
        for j in range(3):
            seg += f"q{f(-14 if j % 2 else 14)} -22 0 -44"
        d.append(seg)
    doc.path("".join(d), stroke=danger, sw=2.5, opacity=0.5)


def _gauge(doc: Doc, cx: float, cy: float, r: float, safe: str, danger: str, label: str) -> None:
    """Analog load gauge: bezel, face, zone arcs, two needles."""
    a0, a1 = math.radians(215), math.radians(-35)        # sweep, clockwise from lower-left

    def at(t: float, rr: float) -> tuple[float, float]:
        a = a0 + (a1 - a0) * t
        return cx + rr * math.cos(a), cy - rr * math.sin(a)

    def arc(t0: float, t1: float, rr: float) -> str:
        (x0, y0), (x1, y1) = at(t0, rr), at(t1, rr)
        large = 1 if abs(t1 - t0) * 250 > 180 else 0
        return f"M{f(x0)} {f(y0)}A{f(rr)} {f(rr)} 0 {large} 1 {f(x1)} {f(y1)}"

    doc.circle(cx + 14, cy + 34, r + 10, "#000", opacity=0.55)
    doc.add(f'<circle cx="{f(cx + 14)}" cy="{f(cy + 40)}" r="{f(r + 16)}" fill="#000" opacity="0.5" '
            f'filter="{doc.blur(26)}"/>')
    doc.circle(cx, cy, r + 22, doc.lin([(0, "#D7DEDA", 1), (0.5, "#7C8782", 1), (1, "#2C3330", 1)], 0, 0, 0.6, 1))
    doc.circle(cx, cy, r + 8, doc.lin([(0, "#202824", 1), (1, "#4A544F", 1)], 0, 0, 0.4, 1))
    doc.circle(cx, cy, r, doc.rad([(0, "#18241E", 1), (1, "#0A100D", 1)], 0.45, 0.35, 0.75))
    # zones
    doc.path(arc(0.0, 0.32, r * 0.80), stroke=safe, sw=r * 0.07, cap="butt", opacity=0.85)
    doc.path(arc(0.70, 1.0, r * 0.80), stroke=danger, sw=r * 0.07, cap="butt", opacity=0.9)
    # ticks
    d = ""
    for k in range(41):
        t = k / 40
        big = k % 5 == 0
        (x0, y0), (x1, y1) = at(t, r * 0.90), at(t, r * (0.74 if big else 0.84))
        d += f"M{f(x0)} {f(y0)}L{f(x1)} {f(y1)}"
    doc.path(d, stroke="#DCE7E1", sw=3, opacity=0.75)
    doc.text(label, cx, cy + r * 0.52, r * 0.24, "#DCE7E1", "display", anchor="middle", opacity=0.92)
    # real load: pinned high, red, ghosted with a glow
    tx, ty = at(0.94, r * 0.78)
    doc.path(f"M{f(cx)} {f(cy)}L{f(tx)} {f(ty)}", stroke=danger, sw=16, opacity=0.35,
             extra=f' filter="{doc.blur(8)}"')
    doc.path(f"M{f(cx)} {f(cy)}L{f(tx)} {f(ty)}", stroke=danger, sw=10, opacity=0.95, dash="22 9", cap="butt")
    # reported load: low, pale, solid
    rx, ry = at(0.08, r * 0.80)
    bx, by = at(0.58, r * 0.10)
    doc.path(f"M{f(bx)} {f(by)}L{f(rx)} {f(ry)}", stroke="#000", sw=12, opacity=0.4,
             extra=f' filter="{doc.blur(4)}"')
    doc.path(f"M{f(bx)} {f(by)}L{f(rx)} {f(ry)}", stroke="#F2F6F3", sw=9)
    doc.circle(cx, cy, r * 0.09, doc.lin([(0, "#E8EEEA", 1), (1, "#7C8782", 1)]))
    doc.circle(cx, cy, r * 0.035, "#1A211D")
    # glass reflection
    doc.path(f"M{f(cx - r * 0.8)} {f(cy - r * 0.2)}A{f(r * 0.85)} {f(r * 0.85)} 0 0 1 {f(cx + r * 0.3)} "
             f"{f(cy - r * 0.8)}A{f(r * 1.1)} {f(r * 1.1)} 0 0 0 {f(cx - r * 0.8)} {f(cy - r * 0.2)}Z",
             fill="#FFFFFF", opacity=0.06)


@scene("gpu_cryptominer")
def gpu_cryptominer(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    doc.rect(0, 0, W, H, doc.lin([(0, p.bg1, 1), (1, p.bg0, 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FFFFFF", 0.07), (1, "#FFFFFF", 0)], 0.3, 0.35, 0.6))
    _board(doc, 740, rng)
    x0, y0, L, Hc = 120, 380, 900, 362
    sx0, sw = x0 + 18, 610
    doc.rect(sx0, 726, sw, 30, "#121416", 4)
    s = _card(doc, x0, y0, L, Hc, p.danger, rng)
    doc.rect(sx0, 740, sw, 34, doc.lin([(0, "#1A1D20", 1), (1, "#0D0F11", 1)]), 3)
    doc.rect(sx0, 740, sw, 3, "#30363B", 1)
    # the card is working hard: red heat inside the fans and off the fin stack
    r = min(s.h * 0.39, s.w * 0.17)
    for fxc in (s.x + s.w * 0.29, s.x + s.w * 0.69):
        doc.circle(fxc, s.cy + 4, r, doc.rad([(0, p.danger, 0.55), (0.6, p.danger, 0.18), (1, p.danger, 0)]))
    _heat(doc, x0 + 40, x0 + L - 80, y0 - 26, p.danger, rng)
    name = next((e for e in brief.entities if e.upper() == "SANSAR"), "")
    if name:
        doc.text(name, 130, 150, 64, p.ink, "display", tracking=4)
    _gauge(doc, 1160, 380, 280, p.safe, p.danger, "GPU")
    doc.rect(0, 0, W, H, doc.rad([(0.55, "#000", 0), (1, "#000", 0.5)], 0.45, 0.5, 0.78))
    doc.focus = Box(110, 40, 1400, 788)
