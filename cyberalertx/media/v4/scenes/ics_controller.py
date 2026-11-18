"""Industrial control advisory: an open control cabinet (mounting plate,
wiring ducts, a PLC with I/O modules on a DIN rail, terminal blocks and
breakers) cabled to an engineering workstation that carries the advisory.

An advisory shows exposure, not an attack: the signal colour sits on the
advisory banner and the network path, and turns to danger only when the
evidence says the flaw is exploited. Modules are generic (no vendor design);
the vendor name appears only as plain text from the headline."""
from __future__ import annotations

import random

from .. import type as T
from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f, icon
from . import scene

_ANTH = "#2B2F35"        # module housings (anthracite)
_ANTH2 = "#363B42"
_GREY = "#C7CBC9"        # enclosure (RAL 7035-like light grey)


def _duct(doc: Doc, x: float, y: float, w: float, h: float, vertical: bool = False) -> None:
    """Slotted wiring duct with its cover."""
    doc.rect(x + 2, y + 4, w, h, "#000", 2, opacity=0.18, extra=f' filter="{doc.blur(3)}"')
    doc.rect(x, y, w, h, doc.lin([(0, "#AEB2B3", 1), (1, "#8E9395", 1)], 0, 0, *((1, 0) if vertical else (0, 1))),
             2)
    d = []
    if vertical:
        yy = y + 8
        while yy < y + h - 8:
            d.append(f"M{f(x)} {f(yy)}h{f(w * 0.22)}M{f(x + w)} {f(yy)}h{f(-w * 0.22)}")
            yy += 13
        doc.rect(x + w * 0.22, y, w * 0.56, h, "#B9BDBE", 1)
    else:
        xx = x + 8
        while xx < x + w - 8:
            d.append(f"M{f(xx)} {f(y)}v{f(h * 0.22)}M{f(xx)} {f(y + h)}v{f(-h * 0.22)}")
            xx += 13
        doc.rect(x, y + h * 0.22, w, h * 0.56, "#B9BDBE", 1)
    doc.path("".join(d), stroke="#6E7375", sw=2.2)


def _rail(doc: Doc, x: float, y: float, w: float) -> None:
    doc.rect(x, y - 17, w, 34, doc.lin([(0, "#E9ECEE", 1), (0.5, "#B9BEC2", 1), (1, "#8F959A", 1)]), 1)
    d = "".join(f"M{f(xx)} {f(y - 4)}h16v8h-16Z" for xx in range(int(x + 14), int(x + w - 20), 34))
    doc.path(d, fill="#6E757B")


def _module(doc: Doc, x: float, y: float, w: float, h: float, *, leds: int, rng: random.Random,
            lit: str = "#5BE38B", flap: bool = True, label: str = "") -> None:
    """A DIN-rail module: housing, front flap with terminal screws, LED strip."""
    doc.rect(x + 3, y + 8, w, h, "#000", 3, opacity=0.35, extra=f' filter="{doc.blur(5)}"')
    doc.rect(x, y, w, h, doc.lin([(0, _ANTH2, 1), (1, _ANTH, 1)], 0, 0, 1, 0), 3)
    doc.rect(x, y, w, 6, "#4A5058", 3)
    doc.line((x + w - 1, y + 4), (x + w - 1, y + h - 4), "#000", 1.5, 0.5)
    # LED strip with labels
    for i in range(leds):
        ly = y + 26 + i * 15
        on = rng.random() < 0.6
        doc.rect(x + 9, ly - 4, 9, 7, lit if on else "#1A1D21", 1.5)
        doc.rect(x + 22, ly - 2, w * 0.35, 3, "#5B626B", 1)
    if flap:
        fy = y + 30 + leds * 15
        fh = h - (fy - y) - 30
        doc.rect(x + 5, fy, w - 10, fh, doc.lin([(0, "#3E444C", 1), (1, "#30353B", 1)], 0, 0, 0, 1), 2)
        for k in range(int(fh // 24)):
            sy = fy + 14 + k * 24
            doc.circle(x + w / 2, sy, 5, "#A3A9B0")
            doc.line((x + w / 2 - 3, sy - 3), (x + w / 2 + 3, sy + 3), "#4A5058", 1.6)
    if label:
        doc.text(label, x + w / 2, y + h - 12, 11, "#9AA2AC", "mono", anchor="middle")


def _cpu(doc: Doc, x: float, y: float, w: float, h: float, signal: str) -> tuple[float, float]:
    """The controller: status LEDs, a small display, card slot and two
    Ethernet ports. Returns the port the network cable leaves from."""
    doc.rect(x + 3, y + 8, w, h, "#000", 3, opacity=0.4, extra=f' filter="{doc.blur(6)}"')
    doc.rect(x, y, w, h, doc.lin([(0, "#3A3F46", 1), (1, "#2A2E34", 1)], 0, 0, 1, 0), 3)
    doc.rect(x, y, w, 6, "#4A5058", 3)
    for i, (lab, col) in enumerate((("RUN", "#5BE38B"), ("ERR", "#1A1D21"), ("MAINT", "#1A1D21"))):
        doc.rect(x + 12, y + 22 + i * 18, 14, 8, col, 2)
        doc.text(lab, x + 32, y + 30 + i * 18, 11, "#9AA2AC", "mono")
    # display
    d = Box(x + 12, y + 82, w - 24, 52)
    doc.rect(d.x, d.y, d.w, d.h, "#0E1A14", 3, stroke="#59616A", sw=1)
    doc.text("RUN", d.x + 10, d.y + 22, 15, "#7BE3A0", "mono_bold")
    doc.rect(d.x + 10, d.y + 32, d.w * 0.55, 4, "#3C6B50", 1)
    doc.rect(d.x + 10, d.y + 40, d.w * 0.35, 4, "#3C6B50", 1)
    # memory-card slot
    doc.rect(x + 14, y + 148, w - 28, 8, "#16191D", 2)
    # Ethernet ports X1 P1 / P2
    pts = []
    for i in range(2):
        px, py = x + 18 + i * ((w - 36) / 2 + 4), y + h - 66
        pw = (w - 44) / 2
        doc.rect(px, py, pw, 36, "#121418", 3, stroke="#5B626B", sw=1.2)
        doc.rect(px + pw * 0.2, py + 6, pw * 0.6, 18, "#050607", 1)
        doc.rect(px + 3, py + 3, 6, 4, "#5BE38B" if i == 0 else "#1A1D21", 1)
        doc.rect(px + pw - 9, py + 3, 6, 4, signal if i == 0 else "#1A1D21", 1)
        doc.text(f"P{i + 1}", px + pw / 2, py - 6, 11, "#9AA2AC", "mono", anchor="middle")
        pts.append((px + pw / 2, py + 36))
    return pts[0]


def _terminals(doc: Doc, x: float, y: float, n: int) -> float:
    cols = ["#9EA5AB"] * 6 + ["#3B82C4"] * 4 + ["#9EA5AB"] * 4 + ["#D9B44A", "#4E9F58"]
    for i in range(n):
        c = cols[i % len(cols)]
        tx = x + i * 15
        doc.rect(tx, y - 52, 14, 104, doc.lin([(0, c, 1), (1, c, 0.82)], 0, 0, 1, 0), 1.5)
        doc.line((tx + 14, y - 52), (tx + 14, y + 52), "#000", 1, 0.35)
        for yy in (y - 38, y + 38):
            doc.circle(tx + 7, yy, 4, "#2F3337")
        doc.rect(tx + 2, y - 8, 10, 16, "#EEF0F1", 1)
    return x + n * 15


def _breaker(doc: Doc, x: float, y: float, on: bool = True) -> None:
    w, h = 34, 120
    doc.rect(x + 2, y + 6, w, h, "#000", 2, opacity=0.25, extra=f' filter="{doc.blur(3)}"')
    doc.rect(x, y, w, h, doc.lin([(0, "#F1F2F2", 1), (1, "#CFD2D3", 1)], 0, 0, 1, 0), 2, stroke="#A9AEB1")
    doc.rect(x + 6, y + 30, w - 12, 60, "#E2E4E5", 2, stroke="#B5B9BC")
    doc.rect(x + 9, y + (36 if on else 62), w - 18, 22, "#2B2F35", 2)
    doc.rect(x + 9, y + 96, w - 18, 6, "#4E9F58" if on else "#C0392B", 1)


def _cabinet(doc: Doc, c: Box, rng: random.Random, signal: str) -> tuple[float, float]:
    """Open enclosure, front elevation. Returns the cable exit point."""
    # enclosure and the open door's edge (left, foreshortened)
    doc.shadow(c.x, c.y, c.w, c.h, 6, 1.2)
    doc.rect(c.x, c.y, c.w, c.h, doc.lin([(0, "#D6D9D7", 1), (1, "#B3B7B5", 1)], 0, 0, 1, 1), 6)
    door = [(c.x - 6, c.y + 6), (c.x - 120, c.y - 26), (c.x - 120, c.b + 26), (c.x - 6, c.b - 6)]
    doc.poly(door, doc.lin([(0, "#9DA2A0", 1), (1, "#C2C6C4", 1)], 0, 0, 1, 0))
    doc.path("M" + "L".join(f"{f(a)} {f(b)}" for a, b in door) + "Z", stroke="#7F8482", sw=1.5)
    doc.poly([(c.x - 104, c.y - 4), (c.x - 22, c.y + 22), (c.x - 22, c.b - 22), (c.x - 104, c.b + 4)],
             "#8E9391", opacity=0.45)
    for hy in (c.y + 120, c.b - 120):
        doc.rect(c.x - 12, hy - 18, 12, 36, "#6D7270", 2)
    # mounting plate (galvanised), recessed: shadow along top and left
    m = c.inset(24)
    doc.rect(m.x, m.y, m.w, m.h, doc.lin([(0, "#E4E6E3", 1), (0.6, "#CDD1CE", 1), (1, "#BEC2C0", 1)], 0, 0,
                                         0.4, 1), 2)
    doc.rect(m.x, m.y, m.w, 26, doc.lin([(0, "#000", 0.28), (1, "#000", 0)]))
    doc.rect(m.x, m.y, 22, m.h, doc.lin([(0, "#000", 0.22), (1, "#000", 0)], 0, 0, 1, 0))

    # ducts: top, middle, bottom + both sides
    _duct(doc, m.x + 16, m.y + 20, 40, m.h - 40, vertical=True)
    _duct(doc, m.r - 56, m.y + 20, 40, m.h - 40, vertical=True)
    _duct(doc, m.x + 64, m.y + 20, m.w - 128, 42)
    _duct(doc, m.x + 64, m.y + 368, m.w - 128, 42)
    _duct(doc, m.x + 64, m.y + 618, m.w - 128, 42)

    # rail 1: power supply, controller, I/O modules
    ry = m.y + 216
    _rail(doc, m.x + 64, ry, m.w - 128)
    top = m.y + 84
    x = m.x + 80
    # power supply
    doc.rect(x + 3, top + 8, 96, 262, "#000", 3, opacity=0.35, extra=f' filter="{doc.blur(5)}"')
    doc.rect(x, top, 96, 262, doc.lin([(0, "#E3E5E6", 1), (1, "#BFC3C5", 1)], 0, 0, 1, 0), 3, stroke="#9EA3A6")
    vents = "".join(f"M{f(x + 14)} {f(top + 20 + k * 9)}h68" for k in range(9))
    doc.path(vents, stroke="#8C9194", sw=3)
    doc.text("24V DC", x + 48, top + 130, 14, "#3A3F45", "mono_bold", anchor="middle")
    doc.rect(x + 14, top + 144, 10, 8, "#5BE38B", 2)
    for k in range(4):
        doc.circle(x + 22 + k * 18, top + 232, 6, "#7F8487")
    x += 104
    port = _cpu(doc, x, top, 150, 262, signal)
    x += 158
    for i in range(5):
        _module(doc, x, top, 62, 262, leds=8 if i < 4 else 4, rng=rng, label=("DI", "DI", "DQ", "DQ", "AI")[i])
        x += 66
    # field wiring from the module fronts into the middle duct
    wires = []
    for i in range(5):
        mx = m.x + 80 + 104 + 158 + i * 66 + 31
        for k in range(3):
            wx = mx - 12 + k * 12
            wires.append(f"M{f(wx)} {f(top + 262)}C{f(wx)} {f(top + 284)} {f(wx + 4)} {f(top + 290)} "
                         f"{f(wx + 4)} {f(m.y + 372)}")
    doc.path("".join(wires), stroke="#2F6FB0", sw=3)

    # rail 2: terminal blocks, breakers, a small switch
    r2 = m.y + 510
    _rail(doc, m.x + 64, r2, m.w - 128)
    tx = _terminals(doc, m.x + 80, r2, 16)
    for k in range(4):
        _breaker(doc, tx + 18 + k * 38, r2 - 60, on=True)
    sx = tx + 18 + 4 * 38 + 14
    sw_w = min(150, m.r - 72 - sx)
    doc.rect(sx + 3, r2 - 52, sw_w, 104, "#000", 3, opacity=0.3, extra=f' filter="{doc.blur(4)}"')
    doc.rect(sx, r2 - 56, sw_w, 104, doc.lin([(0, "#3A3F46", 1), (1, "#2A2E34", 1)], 0, 0, 1, 0), 3)
    sports = []
    for k in range(4):
        px = sx + 10 + k * (sw_w - 20) / 4
        doc.rect(px, r2 - 6, (sw_w - 20) / 4 - 6, 26, "#121418", 2, stroke="#5B626B")
        doc.rect(px + 2, r2 - 12, 5, 3, "#5BE38B" if k < 3 else "#1A1D21", 1)
        sports.append((px + ((sw_w - 20) / 4 - 6) / 2, r2 + 20))
    doc.text("SWITCH", sx + sw_w / 2, r2 - 30, 11, "#9AA2AC", "mono", anchor="middle")

    # patch cable: controller P1 -> switch -> down and out of the cabinet
    cab = (f"M{f(port[0])} {f(port[1])}C{f(port[0])} {f(port[1] + 40)} {f(port[0] + 30)} {f(m.y + 330)} "
           f"{f(port[0] + 60)} {f(m.y + 380)}L{f(sports[0][0] - 20)} {f(m.y + 390)}"
           f"C{f(sports[0][0])} {f(m.y + 400)} {f(sports[0][0])} {f(r2 - 40)} {f(sports[0][0])} {f(r2 - 6)}")
    doc.path(cab, stroke="#1A9E8F", sw=5)
    vx = m.r - 36
    out = (f"M{f(sports[3][0])} {f(sports[3][1])}V{f(r2 + 70)}Q{f(sports[3][0])} {f(r2 + 84)} "
           f"{f(sports[3][0] + 14)} {f(r2 + 84)}H{f(vx - 14)}Q{f(vx)} {f(r2 + 84)} {f(vx)} {f(r2 + 98)}"
           f"V{f(c.b + 6)}")
    doc.path(out, stroke=signal, sw=5)
    # earth bar and glands at the bottom
    doc.rect(m.x + 70, m.b - 34, m.w - 200, 14, doc.lin([(0, "#D9A35B", 1), (1, "#9E6B2C", 1)]), 2)
    for k in range(8):
        doc.circle(m.x + 92 + k * 52, m.b - 27, 4, "#6B4A20")
    return vx, c.b + 6


def _workstation(doc: Doc, s: Box, brief: EditorialBrief, signal: str, exploited: bool) -> tuple[float, float]:
    p = doc.pal
    # monitor body, stand
    doc.rect(s.cx - 70, s.b + 18, 140, 70, doc.lin([(0, "#3A4049", 1), (1, "#22262C", 1)]), 4)
    doc.rect(s.cx - 140, s.b + 82, 280, 14, "#2E333A", 7)
    doc.shadow(s.x - 14, s.y - 14, s.w + 28, s.h + 34, 12, 1.0)
    doc.rect(s.x - 14, s.y - 14, s.w + 28, s.h + 34, "#16191E", 12, stroke="#3B414A", sw=1.2)
    doc.rect(s.x, s.y, s.w, s.h, "#E9ECEF", 3)
    # app chrome
    doc.rect(s.x, s.y, s.w, 34, "#2D3640", 3)
    title = "Industrial Edge Management" if "industrial edge" in brief.text else (
        "Building automation - engineering" if "building automation" in brief.text else "Engineering station")
    doc.text(title, s.x + 16, s.y + 23, 15, "#E6EAEE", "ui_bold")
    # project tree
    tree = Box(s.x, s.y + 34, 170, s.h - 34)
    doc.rect(tree.x, tree.y, tree.w, tree.h, "#DCE1E5")
    items = ("Project", "  PLC_1 [CPU]", "    Program", "    I/O config", "  Edge device", "    Apps",
             "  HMI_1", "  Network")
    for i, it in enumerate(items):
        doc.text(it, tree.x + 12, tree.y + 30 + i * 26, 13, "#3A4450", "mono")
    lx0, lx1 = tree.r + 34, s.r - 30
    if "industrial edge" in brief.text:
        # The advisory concerns the edge management software: show what it
        # manages (edge devices and their apps), not controller logic.
        doc.text("Edge devices", lx0, s.y + 74, 15, "#3A4450", "ui_bold")
        for r in range(4):
            yy = s.y + 92 + r * 46
            doc.rect(lx0, yy, lx1 - lx0, 38, "#F4F6F8" if r % 2 == 0 else "#E9ECEF", 3)
            doc.circle(lx0 + 16, yy + 19, 5, "#3BA55C")
            doc.text(f"edge-device-0{r + 1}", lx0 + 32, yy + 25, 13, "#1F2A36", "mono")
            doc.rect(lx1 - 70, yy + 9, 56, 20, "#C9D2DA", 10)
        return _banner(doc, s, tree, brief, signal, exploited)
    # ladder rung editor
    for r in range(3):
        yy = s.y + 120 + r * 70
        doc.line((lx0, yy), (lx1, yy), "#4C5866", 2)
        cx = lx0 + 50
        n = 2 + r % 2
        step = (lx1 - 60 - lx0 - 50) / (n + 0.4)
        for j in range(n):
            doc.line((cx, yy - 14), (cx, yy + 14), "#1F2A36", 2.5)
            doc.line((cx + 18, yy - 14), (cx + 18, yy + 14), "#1F2A36", 2.5)
            doc.rect(cx + 1, yy - 4, 16, 8, "#E9ECEF")
            if (r + j) % 3 == 1:
                doc.line((cx + 3, yy + 11), (cx + 15, yy - 11), "#1F2A36", 2)
            doc.text(f"I{r}.{j}", cx + 9, yy - 22, 11, "#5B6673", "mono", anchor="middle")
            cx += step
        ox = lx1 - 60
        doc.rect(ox - 2, yy - 16, 30, 32, "#E9ECEF")
        doc.path(f"M{f(ox + 6)} {f(yy - 14)}Q{f(ox - 4)} {f(yy)} {f(ox + 6)} {f(yy + 14)}"
                 f"M{f(ox + 20)} {f(yy - 14)}Q{f(ox + 30)} {f(yy)} {f(ox + 20)} {f(yy + 14)}",
                 stroke="#1F2A36", sw=2.5)
        doc.text(f"Q{r}.0", ox + 13, yy - 22, 11, "#5B6673", "mono", anchor="middle")
    doc.line((lx0, s.y + 92), (lx0, s.y + 284), "#4C5866", 3)
    doc.line((lx1, s.y + 92), (lx1, s.y + 284), "#4C5866", 3)
    return _banner(doc, s, tree, brief, signal, exploited)


def _banner(doc: Doc, s: Box, tree: Box, brief: EditorialBrief, signal: str,
            exploited: bool) -> tuple[float, float]:
    # the advisory banner (focal)
    b = Box(tree.r + 16, s.b - 98, s.r - tree.r - 32, 80)
    doc.rect(b.x, b.y, b.w, b.h, "#FFF6E3" if not exploited else "#FDE8E6", 6, stroke=signal, sw=2.5)
    doc.rect(b.x, b.y, 8, b.h, signal, 3)
    icon(doc, "warn", b.x + 38, b.y + 40, 34, signal, 2.6)
    head = "Actively exploited" if exploited else "Security advisory"
    doc.text(head, b.x + 66, b.y + 32, 19, "#2A2316", "ui_bold")
    cves = brief.facts.get("cves") or []
    vendor = T.supported(brief.entities[0], "mono_bold") if brief.entities else ""
    sub = cves[0] if cves else (f"{vendor} products" if vendor else "vendor advisory")
    if len(cves) > 1:
        sub += f"  +{len(cves) - 1}"
    doc.text(T.fit(sub, 18, b.w - 80, "mono"), b.x + 66, b.y + 60, 18, "#2A2316", "mono_bold")
    return s.x - 14, s.b - 10


@scene("ics_controller")
def ics_controller(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    exploited = brief.status in ("exploited", "attacks_observed")
    signal = p.danger if exploited else p.accent

    # steel plant-room backdrop: a wall and a concrete floor
    doc.rect(0, 0, W, H, doc.lin([(0, "#1E242B", 1), (1, "#12161B", 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FFFFFF", 0.09), (1, "#FFFFFF", 0)], 0.35, 0.2, 0.7))
    doc.rect(0, 812, W, 88, doc.lin([(0, "#0D1014", 1), (1, "#090B0E", 1)]))
    doc.line((0, 812), (W, 812), "#3A434E", 1.5)

    cab = Box(178, 36, 700, 760)
    ex = _cabinet(doc, cab, rng, signal)

    scr = Box(1012, 150, 520, 400)
    wx, wy = _workstation(doc, scr, brief, signal, exploited)
    # desk
    doc.rect(930, 646, 640, 18, doc.lin([(0, "#3B434D", 1), (1, "#262C33", 1)]), 3)
    doc.rect(930, 664, 640, 10, "#000", opacity=0.35, extra=f' filter="{doc.blur(5)}"')

    # network path: cabinet -> workstation (the exposed link)
    doc.path(f"M{f(ex[0])} {f(ex[1])}C{f(ex[0])} {f(ex[1] + 10)} {f(ex[0] + 10)} 800 {f(ex[0] + 60)} 800"
             f"L900 800C960 800 960 770 960 740L960 660", stroke=signal, sw=5)
    doc.circle(960, 656, 7, signal)

    doc.rect(0, 0, W, H, doc.rad([(0.55, "#000", 0), (1, "#000", 0.5)], 0.5, 0.5, 0.75))
    doc.focus = Box(60, 20, 1500, 844)
