"""GPU cryptomining hidden by a tampered monitoring library: a graphics card
seated in a server board, fans spinning and heat rising off the fin stack,
while the monitoring terminal (which reads the card through a modified
NVML-style library) reports it idle.

Generic card design: no vendor logo, no product name on the shroud. The
library name appears only as a filename in the terminal."""
from __future__ import annotations

import math
import random

from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f, window
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


@scene("gpu_cryptominer")
def gpu_cryptominer(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    doc.rect(0, 0, W, H, doc.lin([(0, p.bg1, 1), (1, p.bg0, 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FFFFFF", 0.07), (1, "#FFFFFF", 0)], 0.3, 0.35, 0.6))
    _board(doc, 690, rng)
    # PCIe slot on the board
    doc.rect(150, 676, 600, 30, "#121416", 4)
    doc.rect(150, 676, 600, 6, "#2A2F33", 3)
    doc.rect(752, 670, 26, 40, "#22262A", 3)

    x0, y0, L, Hc = 132, 330, 860, 362
    s = _card(doc, x0, y0, L, Hc, p.danger, rng)
    # slot body in front of the gold fingers (the card is seated)
    doc.rect(150, 690, 600, 34, doc.lin([(0, "#1A1D20", 1), (1, "#0D0F11", 1)]), 3)
    doc.rect(150, 690, 600, 3, "#30363B", 1)
    _heat(doc, x0 + 40, x0 + L - 80, y0 - 26, p.danger, rng)
    # actual load: a full bar, no figure (the sources state none)
    lx, ly = x0 + 40, 92
    doc.text("GPU load", lx, ly, 18, p.muted, "ui_bold")
    doc.rect(lx, ly + 14, 380, 22, "#1E2A24", 5)
    doc.rect(lx, ly + 14, 380, 22, p.danger, 5)
    doc.text("mining", lx + 396, ly + 32, 18, p.danger, "mono_bold")

    # monitoring terminal: the tampered library reports idle
    win = Box(1030, 170, 520, 380)
    body = window(doc, win, title="root@gpu-node-03: ~", surface="#0C1310", chrome="#16211B")
    tx, ty = body.x + 26, body.y + 44
    doc.text("$ gpu-monitor --query", tx, ty, 18, "#C9D8CF", "mono")
    doc.text("GPU 0", tx, ty + 46, 18, "#8FA59A", "mono")
    doc.text("utilisation", tx, ty + 84, 18, "#8FA59A", "mono")
    hb = Box(tx + 190, ty + 52, 150, 58)
    doc.rect(hb.x, hb.y, hb.w, hb.h, p.danger, 6, opacity=0.14)
    doc.rect(hb.x, hb.y, hb.w, hb.h, "none", 6, stroke=p.danger, sw=2.5)
    doc.text("0%", hb.x + 20, hb.y + 44, 40, "#FFFFFF", "mono_bold")
    doc.text("state", tx, ty + 132, 18, "#8FA59A", "mono")
    doc.text("idle", tx + 190, ty + 132, 18, "#C9D8CF", "mono")
    doc.text("processes", tx, ty + 168, 18, "#8FA59A", "mono")
    doc.text("none found", tx + 190, ty + 168, 18, "#C9D8CF", "mono")
    doc.line((tx, ty + 196), (body.r - 26, ty + 196), "#24352C", 1.5)
    doc.text("via libnvidia-ml.so.1", tx, ty + 232, 17, "#8FA59A", "mono")
    doc.text("modified", tx + 270, ty + 232, 17, p.danger, "mono_bold")
    doc.text("$", tx, ty + 274, 18, "#C9D8CF", "mono")
    doc.rect(tx + 18, ty + 258, 11, 20, "#C9D8CF")

    # the contradiction: the card it describes
    doc.path(f"M{f(s.r - 30)} {f(s.y + 40)}C{f(s.r + 10)} {f(s.y - 10)} {f(win.x - 40)} {f(hb.cy)} "
             f"{f(win.x + 4)} {f(hb.cy)}", stroke=p.danger, sw=2.5, dash="8 7")
    doc.circle(s.r - 30, s.y + 40, 6, p.danger)

    doc.rect(0, 0, W, H, doc.rad([(0.55, "#000", 0), (1, "#000", 0.5)], 0.45, 0.5, 0.78))
    doc.focus = Box(120, 120, 1440, 810)
