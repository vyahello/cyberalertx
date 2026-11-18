"""Telecom infrastructure resilience: a mobile network site drawn as an
engineering elevation. A lattice mast with sector antennas, radio units and a
microwave dish; the equipment and battery cabinets at its foot; fibre
backhaul in a buried duct to the exchange, with a diverse second route.

Analysis, not an incident: the signal colour marks the resilience measures
(backup power, the second fibre route, the microwave link). Only when the
sources report attacks on the network (e.g. interception) is a tap drawn on
the backhaul, in the danger colour."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f, icon
from . import scene

_GROUND = 700.0


def _grid(doc: Doc) -> None:
    d = "".join(f"M{x} 0V{H}" for x in range(0, W + 1, 32)) + "".join(f"M0 {y}H{W}" for y in range(0, H + 1, 32))
    doc.path(d, stroke="#7FA6D9", sw=1, opacity=0.06)
    d = "".join(f"M{x} 0V{H}" for x in range(0, W + 1, 160)) + "".join(f"M0 {y}H{W}"
                                                                        for y in range(0, H + 1, 160))
    doc.path(d, stroke="#7FA6D9", sw=1, opacity=0.10)


def _label(doc: Doc, target: tuple[float, float], at: tuple[float, float], s: str, color: str,
           anchor: str = "start") -> None:
    doc.circle(target[0], target[1], 4, color)
    doc.path(f"M{f(target[0])} {f(target[1])}L{f(at[0])} {f(at[1])}", stroke=color, sw=1.3, opacity=0.75)
    end = at[0] + (90 if anchor == "start" else -90)
    doc.line(at, (end, at[1]), color, 1.3, 0.75)
    doc.text(s, at[0] + (4 if anchor == "start" else -4), at[1] - 8, 16, color, "mono",
             anchor=anchor)


def _mast(doc: Doc, cx: float, top: float, ink: str) -> dict[str, tuple[float, float]]:
    """Tapered lattice mast in elevation. Returns anchor points for labels."""
    base_w, top_w = 170.0, 46.0
    def leg(y: float) -> tuple[float, float]:
        t = (y - top) / (_GROUND - top)
        hw = (top_w + (base_w - top_w) * t) / 2
        return cx - hw, cx + hw
    # legs
    lt, rt = leg(top)
    lb, rb = leg(_GROUND)
    doc.path(f"M{f(lt)} {f(top)}L{f(lb)} {f(_GROUND)}M{f(rt)} {f(top)}L{f(rb)} {f(_GROUND)}", stroke=ink, sw=4)
    # panels with K / X bracing
    d = []
    ys = []
    y = top
    step = 54.0
    while y < _GROUND - 1:
        ys.append(y)
        y += step
        step *= 1.07
    ys.append(_GROUND)
    for a, b in zip(ys, ys[1:]):
        la, ra = leg(a)
        lb_, rb_ = leg(b)
        d.append(f"M{f(la)} {f(a)}H{f(ra)}")
        d.append(f"M{f(la)} {f(a)}L{f(rb_)} {f(b)}M{f(ra)} {f(a)}L{f(lb_)} {f(b)}")
    doc.path("".join(d), stroke=ink, sw=1.6, opacity=0.8)
    # foundation
    doc.rect(lb - 26, _GROUND, rb - lb + 52, 26, "none", stroke=ink, sw=2)
    doc.path("".join(f"M{f(x)} {f(_GROUND + 26)}l-10 12" for x in range(int(lb - 20), int(rb + 40), 14)),
             stroke=ink, sw=1, opacity=0.5)
    # lightning rod + aviation light
    doc.line((cx, top), (cx, top - 70), ink, 2)
    doc.circle(cx, top - 72, 5, "#FF8A65")
    # antenna headframe and three sector panels (centre face-on, sides edge-on)
    hy = top + 26
    doc.line((cx - 110, hy), (cx + 110, hy), ink, 3)
    doc.line((cx - 110, hy + 120), (cx + 110, hy + 120), ink, 3)
    for px, pw in ((cx - 104, 18), (cx - 26, 52), (cx + 86, 18)):
        doc.rect(px, hy - 14, pw, 148, "#0F1828", 6, stroke=ink, sw=2.2)
        if pw > 20:
            doc.path("".join(f"M{f(px + 10)} {f(hy + 6 + k * 18)}h{f(pw - 20)}" for k in range(7)), stroke=ink,
                     sw=1, opacity=0.4)
    # radio units behind the antennas
    rru_y = hy + 150
    for rx in (cx - 74, cx + 44):
        doc.rect(rx, rru_y, 30, 52, "#0F1828", 3, stroke=ink, sw=1.8)
        doc.path(f"M{f(rx + 6)} {f(rru_y + 10)}v32M{f(rx + 15)} {f(rru_y + 10)}v32M{f(rx + 24)} {f(rru_y + 10)}v32",
                 stroke=ink, sw=1, opacity=0.5)
    # microwave dish (side elevation), right leg, mid height
    my = top + 300
    _, r_leg = leg(my)
    dx = r_leg + 26
    doc.line((r_leg, my), (dx, my), ink, 2.5)
    doc.add(f'<ellipse cx="{f(dx + 10)}" cy="{f(my)}" rx="14" ry="44" fill="#0F1828" stroke="{ink}" '
            f'stroke-width="2.2"/>')
    doc.rect(dx + 10, my - 44, 18, 88, "#0F1828", 4, stroke=ink, sw=2.2)
    # cable ladder down the left leg
    pts = []
    for yy in range(int(rru_y + 52), int(_GROUND), 22):
        lx, _ = leg(yy)
        pts.append((lx + 14, yy))
    doc.path("M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts), stroke=ink, sw=2.6, opacity=0.9)
    return {"antenna": (cx - 26 + 52, hy + 40), "rru": (cx + 74, rru_y + 26), "dish": (dx + 28, my),
            "top": (cx, top - 72), "base_r": (rb, _GROUND), "ladder": pts[len(pts) // 2]}


def _cabinet(doc: Doc, b: Box, ink: str, title: str, accent: str = "") -> None:
    col = accent or ink
    doc.rect(b.x, b.y, b.w, b.h, "#0F1828", 4, stroke=col, sw=2.2)
    doc.rect(b.x - 8, b.y - 10, b.w + 16, 10, "#0F1828", 2, stroke=col, sw=2)
    doc.line((b.cx, b.y + 8), (b.cx, b.b - 8), col, 1.2, 0.6)
    doc.path("".join(f"M{f(b.x + 10)} {f(b.y + 16 + k * 9)}h{f(b.w / 2 - 20)}" for k in range(5)), stroke=col,
             sw=1.2, opacity=0.6)
    doc.rect(b.cx + 10, b.cy - 6, 6, 18, col, 2)


@scene("telecom")
def telecom(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    ink = "#CBD8EA"
    acc = p.accent
    doc.rect(0, 0, W, H, doc.lin([(0, "#0D1626", 1), (1, "#0A111E", 1)], 0, 0, 0.3, 1))
    _grid(doc)
    # drawing frame
    doc.rect(24, 24, W - 48, H - 48, "none", stroke=ink, sw=1.2, opacity=0.35)

    # ground line and soil hatch
    doc.line((24, _GROUND), (W - 24, _GROUND), ink, 2)
    doc.rect(24, _GROUND, W - 48, H - 24 - _GROUND, "#000", opacity=0.18)

    cx, top = 470.0, 150.0
    a = _mast(doc, cx, top, ink)

    # site compound: equipment cabinet, battery cabinet, fence
    eq = Box(640, 590, 110, 110)
    bat = Box(770, 620, 90, 80)
    _cabinet(doc, eq, ink, "equipment")
    _cabinet(doc, bat, ink, "battery", accent=acc)
    doc.path("".join(f"M{f(x)} {f(_GROUND)}v-60" for x in range(250, 900, 26)), stroke=ink, sw=1, opacity=0.3)
    doc.line((250, _GROUND - 60), (900, _GROUND - 60), ink, 1, 0.3)
    # feeder from the ladder to the equipment cabinet
    lx, ly = a["ladder"]
    doc.path(f"M{f(lx)} {f(_GROUND - 40)}C{f(lx + 80)} {f(_GROUND - 40)} {f(eq.x - 40)} {f(eq.y + 30)} "
             f"{f(eq.x)} {f(eq.y + 30)}", stroke=ink, sw=2.4)

    # fibre backhaul: buried duct to the exchange (primary) + diverse route
    ex = Box(1240, 470, 290, 230)
    doc.rect(ex.x, ex.y, ex.w, ex.h, "#0F1828", 2, stroke=ink, sw=2.4)
    doc.path(f"M{f(ex.x - 14)} {f(ex.y)}L{f(ex.cx)} {f(ex.y - 70)}L{f(ex.r + 14)} {f(ex.y)}", stroke=ink, sw=2.4)
    for k in range(3):
        doc.rect(ex.x + 30 + k * 84, ex.y + 40, 56, 70, "none", 2, stroke=ink, sw=1.4, opacity=0.6)
    # racks visible through the open bay
    for k in range(4):
        doc.rect(ex.x + 36 + k * 58, ex.y + 136, 44, 94, "#0B1220", 2, stroke=ink, sw=1.2, opacity=0.9)
        doc.path("".join(f"M{f(ex.x + 42 + k * 58)} {f(ex.y + 148 + j * 12)}h32" for j in range(6)), stroke=ink,
                 sw=1, opacity=0.4)
    y1, y2 = _GROUND + 70, _GROUND + 128
    prim = (f"M{f(eq.cx)} {f(eq.b)}V{f(y1 - 20)}Q{f(eq.cx)} {f(y1)} {f(eq.cx + 20)} {f(y1)}"
            f"H{f(ex.x + 60)}Q{f(ex.x + 80)} {f(y1)} {f(ex.x + 80)} {f(y1 - 20)}V{f(ex.b)}")
    doc.path(prim, stroke=ink, sw=3.5)
    div = (f"M{f(eq.cx - 30)} {f(eq.b)}V{f(y2 - 20)}Q{f(eq.cx - 30)} {f(y2)} {f(eq.cx - 10)} {f(y2)}"
           f"H{f(ex.x + 160)}Q{f(ex.x + 180)} {f(y2)} {f(ex.x + 180)} {f(y2 - 20)}V{f(ex.b)}")
    doc.path(div, stroke=acc, sw=3.5, dash="14 8")
    # handholes on the primary route
    for hx in (930.0, 1110.0):
        doc.rect(hx - 16, y1 - 12, 32, 24, "#0F1828", 2, stroke=ink, sw=1.6)

    # microwave path (backup link) leaving the frame to the right, above the exchange
    dx, dy = a["dish"]
    doc.path(f"M{f(dx + 6)} {f(dy)}L{f(W - 40)} {f(dy - 150)}", stroke=acc, sw=2, dash="3 9")
    doc.path(f"M{f(dx + 6)} {f(dy - 30)}L{f(W - 40)} {f(dy - 200)}M{f(dx + 6)} {f(dy + 30)}L{f(W - 40)} {f(dy - 100)}",
             stroke=acc, sw=1, opacity=0.25)
    beam_y = dy - 150 * (900 - dx - 6) / (W - 40 - dx - 6)

    # annotation
    _label(doc, a["antenna"], (760, 196), "sector antennas", ink)
    _label(doc, a["rru"], (760, 300), "radio units", ink)
    _label(doc, (900, beam_y), (1000, 300), "microwave link (backup)", acc)
    _label(doc, (bat.cx, bat.y), (960, 560), "battery backup", acc)
    _label(doc, (1020, y1), (1040, y1 + 36), "fibre backhaul", ink)
    _label(doc, (700, y2), (590, y2 - 26), "diverse route", acc, anchor="end")
    doc.text("EXCHANGE", ex.cx, ex.y - 86, 18, ink, "mono_bold", anchor="middle", tracking=3)

    # height dimension (no figure: the sources state none)
    dxl = 250.0
    doc.line((dxl, top - 72), (dxl, _GROUND), ink, 1.2, 0.6)
    for yy in (top - 72, _GROUND):
        doc.line((dxl - 10, yy), (dxl + 10, yy), ink, 1.2, 0.6)
    doc.poly([(dxl, top - 72), (dxl - 6, top - 56), (dxl + 6, top - 56)], ink, opacity=0.6)
    doc.poly([(dxl, _GROUND), (dxl - 6, _GROUND - 16), (dxl + 6, _GROUND - 16)], ink, opacity=0.6)
    with doc.g(transform=f"rotate(-90 {f(dxl - 14)} {f((top + _GROUND) / 2)})"):
        doc.text("MAST ELEVATION", dxl - 14, (top + _GROUND) / 2, 14, ink, "mono", anchor="middle", tracking=3,
                 opacity=0.6)

    # reported interception on the backhaul (only when the sources say so)
    if brief.status in ("exploited", "attacks_observed", "confirmed") and "sms" in brief.text:
        tx, ty = ex.x + 36 + 2 * 58 + 22, ex.y + 180
        doc.circle(tx, ty, 10, p.danger)
        doc.circle(tx, ty, 20, "none", p.danger, 2, 0.6)
        doc.path(f"M{f(tx)} {f(ty)}L{f(tx - 40)} {f(ty - 40)}H{f(1010)}", stroke=p.danger, sw=2)
        doc.text("SMS intercepted", 1200, ty - 50, 18, p.danger, "mono_bold", anchor="end")
        icon(doc, "mail", 1010, ty - 56, 26, p.danger, 2.4)

    doc.focus = Box(150, 40, 1200, 675)
