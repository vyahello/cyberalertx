"""Industrial control advisory: the hardware itself, close and lit.

The sources of an ICS advisory state the vendor, the products and (sometimes)
the CVE. They do not state device states, so nothing here claims one: LED
lenses are dark, no display shows a value, there is no product interface.
The story's identifier (the first CVE of `brief.facts`, else the vendor's
advisory) is set once, large. The vendor name appears as plain text only when
the headline names it. Modules are generic: anthracite housings, no vendor
design. The amber (or, when exploited, red) patch cable is the one signal:
these are networked products.

Alternatives:
  a  a DIN-rail controller and its I/O modules in 3/4 view, the controller as
     hero, the row receding; the identifier is set above it on the dark wall.
  b  one fanless edge device as a lit product shot on a dark ground, its
     network cable running toward the viewer; the identifier sits beside it.
"""
from __future__ import annotations

import random
import re
from typing import Callable

from .. import type as T
from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f
from . import scene
from ._camera import V3, Camera, add, path_of

_VENDORS = ("Siemens", "Schneider Electric", "Rockwell Automation", "Mitsubishi Electric", "ABB", "Honeywell",
            "Emerson", "Yokogawa", "Phoenix Contact", "Moxa", "Delta Electronics", "Hitachi Energy", "GE Vernova")

_X: V3 = (1.0, 0.0, 0.0)
_Y_DOWN: V3 = (0.0, -1.0, 0.0)
_Z: V3 = (0.0, 0.0, 1.0)


def _vendor(brief: EditorialBrief) -> str:
    """The vendor, only when the headline (the start of the text) names it."""
    head = (brief.text or "")[:120]
    for v in _VENDORS:
        if re.search(r"\b" + re.escape(v.lower()) + r"\b", head):
            return v
    return ""


def _identifier(brief: EditorialBrief) -> tuple[str, str]:
    """(large identifier, small qualifier). A CVE only when facts carry it."""
    cves = [c for c in (brief.facts.get("cves") or []) if re.fullmatch(r"CVE-\d{4}-\d{4,7}", str(c))]
    if cves:
        return str(cves[0]), (f"+{len(cves) - 1} more" if len(cves) > 1 else "")
    return "ADVISORY", ""


# ---------------------------------------------------------------- materials

_HOUSING = {"front": ("#383D44", "#262A30"), "top": ("#5B626B", "#454B53"), "side": ("#1B1E22", "#141619")}


def _box(doc: Doc, cam: Camera, x0: float, y0: float, z0: float, w: float, h: float, d: float,
         mat: dict[str, tuple[str, str]], rim: str = "#9AA3AD") -> None:
    """A lit housing: x0..x0+w, y0..y0+h (y up), z0..z0+d (toward viewer).
    Draws the left, top and front faces (camera above-left)."""
    x1, y1, z1 = x0 + w, y0 + h, z0 + d
    left = [(x0, y1, z0), (x0, y1, z1), (x0, y0, z1), (x0, y0, z0)]
    top = [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)]
    front = [(x0, y1, z1), (x1, y1, z1), (x1, y0, z1), (x0, y0, z1)]
    a, b = mat["side"]
    cam.poly(doc, left, doc.lin([(0, a, 1), (1, b, 1)], 0, 0, 1, 0))
    a, b = mat["top"]
    cam.poly(doc, top, doc.lin([(0, b, 1), (1, a, 1)], 0, 0, 0, 1))
    a, b = mat["front"]
    fr = cam.poly(doc, front, doc.lin([(0, a, 1), (0.55, b, 1), (1, b, 1)], 0, 0, 0.25, 1))
    # rim light along the front-top and front-left edges
    doc.path(path_of([fr[3], fr[0], fr[1]], closed=False), stroke=rim, sw=max(1.0, cam.scale_at(front[0]) * 0.7),
             opacity=0.55)


def _vents(doc: Doc, cam: Camera, x0: float, y1: float, z0: float, w: float, d: float, n: int) -> None:
    """Ventilation slots across a top face."""
    m = cam.face((x0, y1, z0), _X, _Z, (w, d))
    step = w / (n + 1)
    dd = "".join(f"M{f(step * (i + 1))} {f(d * 0.12)}V{f(d * 0.88)}" for i in range(n))
    with doc.g(m):
        doc.path(dd, stroke="#16181B", sw=w / n * 0.42, cap="round")


def _rj45(doc: Doc, u: float, v: float, w: float = 15.0, h: float = 13.0) -> None:
    """A shielded RJ45 jack in face-local coordinates."""
    doc.rect(u - 0.6, v - 0.6, w + 1.2, h + 1.2, "#0B0C0E", 1.2)
    doc.rect(u, v, w, h, doc.lin([(0, "#D7DCE0", 1), (0.5, "#9097A0", 1), (1, "#C4C9CE", 1)], 0, 0, 1, 1), 1)
    doc.rect(u + 1.6, v + 1.6, w - 3.2, h - 3.2, "#050607", 0.6)
    doc.rect(u + w * 0.35, v + h - 3.4, w * 0.3, 2.2, "#050607", 0.4)
    for k in range(6):
        doc.rect(u + 3 + k * (w - 6) / 6 + 0.3, v + 2.4, 0.7, 2.6, "#B8913F")


def _lens(doc: Doc, u: float, v: float) -> None:
    """An unlit LED lens: smoked plastic with a speck of reflection."""
    doc.rect(u, v, 6, 3.2, "#121417", 0.8, stroke="#4B5159", sw=0.35)
    doc.rect(u + 0.8, v + 0.5, 2.2, 0.8, "#FFFFFF", 0.4, opacity=0.22)


def _cpu_front(doc: Doc, w: float, h: float) -> tuple[float, float]:
    """Controller front panel in local mm (w x h). Returns the port the patch
    cable plugs into (local)."""
    # moulded top strip
    doc.rect(0, 0, w, 9, "#FFFFFF", 0, opacity=0.05)
    doc.path("".join(f"M{f(10 + i * 7)} 3.5h4" for i in range(int((w - 20) / 7))), stroke="#111316", sw=2.2)
    # upper cover: dark glass, blank (no value is shown)
    doc.rect(7, 14, w - 14, 50, "#2E3238", 2.5, stroke="#4A5058", sw=0.5)
    doc.rect(12, 19, w - 24, 30, "#07090B", 1.5)
    doc.path(f"M12 19H{f(12 + (w - 24) * 0.55)}L{f(12 + (w - 24) * 0.30)} 49H12Z", fill="#FFFFFF", opacity=0.06)
    for i in range(3):
        _lens(doc, 14 + i * 9, 54.5)
    # lower cover with grip groove and a blank paper label strip
    doc.rect(7, 68, w - 14, 34, "#30343A", 2.5, stroke="#4A5058", sw=0.5)
    doc.rect(14, 72, w * 0.42, 9, "#E7E4DA", 0.8)
    doc.path("".join(f"M{f(16)} {f(75 + k * 2.5)}h{f(w * 0.42 - 4 - k * 6)}" for k in range(2)),
             stroke="#B9B4A6", sw=0.5)
    doc.rect(w - 52, 92, 40, 2.6, "#121417", 1.3)
    doc.rect(w - 52, 94.4, 40, 0.8, "#FFFFFF", 0.4, opacity=0.18)
    # ports and card slot
    _rj45(doc, 12, 112)
    _rj45(doc, 32, 112)
    doc.rect(w - 34, 118, 22, 2.2, "#0B0C0E", 1)
    doc.rect(w - 34, 116.6, 22, 0.6, "#FFFFFF", 0.3, opacity=0.25)
    # foot: the latch that holds the module on the rail
    doc.rect(w * 0.42, h - 7, w * 0.16, 4, "#1A1D21", 1)
    return 12 + 7.5, 112 + 6.5


def _io_front(doc: Doc, w: float, h: float, rng: random.Random, wire: str) -> None:
    """I/O module with its front connector open: two columns of screw
    terminals and the field wires dressed downward."""
    doc.rect(0, 0, w, 9, "#FFFFFF", 0, opacity=0.05)
    for i in range(2):
        _lens(doc, 4 + i * 8, 12)
    doc.rect(3, 19, w - 6, h - 30, "#1D2025", 1.5, stroke="#4A5058", sw=0.4)
    wires: list[str] = []
    screws: list[str] = []
    for col in range(2):
        cx = 9 + col * (w - 18)
        for k in range(10):
            cy = 26 + k * 10.4
            screws.append(f'<circle cx="{f(cx)}" cy="{f(cy)}" r="2.6" fill="#AEB5BC" stroke="#2A2E33" '
                          f'stroke-width="0.4"/><path d="M{f(cx - 1.7)} {f(cy + 1.1)}L{f(cx + 1.7)} {f(cy - 1.1)}" '
                          f'stroke="#3A3F45" stroke-width="0.8"/>')
            tx = w / 2 + (col - 0.5) * 6 + rng.uniform(-1, 1)
            wires.append(f"M{f(cx + (3 if col == 0 else -3))} {f(cy + 1.5)}C{f(tx)} {f(cy + 3)} {f(tx)} {f(cy + 6)} "
                         f"{f(tx)} {f(h - 4)}")
    doc.add("".join(screws))
    doc.path("".join(wires[::2]), stroke=wire, sw=1.7)
    doc.path("".join(wires[1::2]), stroke="#8E959C", sw=1.7)
    doc.path("".join(wires), stroke="#FFFFFF", sw=0.4, opacity=0.25)


def _cable(doc: Doc, cam: Camera, pts: list[V3], color: str, width: float) -> None:
    """A patch cable through 3-D control points (Catmull-Rom), with a
    highlight; its width follows the perspective."""
    samples: list[V3] = []
    for i in range(len(pts) - 1):
        p0, p1 = pts[max(i - 1, 0)], pts[i]
        p2, p3 = pts[i + 1], pts[min(i + 2, len(pts) - 1)]
        for k in range(12):
            t = k / 12
            t2, t3 = t * t, t * t * t
            c = [0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                        + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in range(3)]
            samples.append((c[0], c[1], c[2]))
    samples.append(pts[-1])
    # draw in short runs so the width can grow toward the viewer
    run = 6
    segs = []
    for s in range(0, len(samples) - 1, run):
        seg = samples[s:s + run + 1]
        segs.append((path_of([cam.p(q) for q in seg], closed=False), cam.scale_at(seg[len(seg) // 2])))
    doc.add('<g opacity="0.3">' + "".join(f'<path d="{d}" fill="none" stroke="#000" stroke-width="{f(width * sc * 1.3)}" '
                                          f'stroke-linecap="round"/>' for d, sc in segs) + "</g>")
    for d, sc in segs:
        doc.path(d, stroke=color, sw=width * sc)
    d_all = path_of([cam.p((q[0] - 0.9, q[1] + 1.3, q[2])) for q in samples], closed=False)
    doc.path(d_all, stroke="#FFFFFF", sw=max(1.5, width * 0.18 * cam.scale_at(samples[-1]) * 0.6), opacity=0.35)


def _plug(doc: Doc, cam: Camera, u: float, v: float, x0: float, y1: float, z1: float, color: str) -> V3:
    """An RJ45 plug seated in the port at face-local (u, v); returns where the
    cable leaves the boot."""
    px, py = x0 + u, y1 - v
    _box(doc, cam, px - 7, py - 6, z1, 14, 12, 9, {"front": ("#D9DEE2", "#A9B0B6"), "top": ("#F2F4F5", "#C9CED2"),
                                                     "side": ("#8B9298", "#6E757B")}, rim="#FFFFFF")
    _box(doc, cam, px - 5.5, py - 5, z1 + 9, 11, 10, 12,
         {"front": (color, color), "top": ("#FFE2A6", color), "side": ("#9C6410", "#7A4E0C")}, rim="#FFE9B8")
    return px, py, z1 + 21


# ---------------------------------------------------------------- shared type

def _title_block(doc: Doc, brief: EditorialBrief, x: float, y: float, size: float, signal: str,
                 exploited: bool, max_w: float) -> None:
    ident, more = _identifier(brief)
    vendor = _vendor(brief)
    kicker = ((vendor.upper() + "  ") if vendor else "") + ("EXPLOITED" if exploited else "SECURITY ADVISORY")
    doc.rect(x, y - 92, 64, 8, signal)
    doc.text(kicker, x, y - 46, 30, "#C9CFD6", "ui_bold", tracking=3)
    while T.measure(ident, size, "ui_bold") > max_w and size > 40:
        size -= 2
    doc.text(ident, x - size * 0.03, y + T.cap_height(size, "ui_bold") + 6, size, "#F3F5F7", "ui_bold")
    if more:
        doc.text(more, x, y + T.cap_height(size, "ui_bold") + 52, 26, "#8C96A3", "ui")


def _backdrop(doc: Doc, light: tuple[float, float]) -> None:
    doc.rect(0, 0, W, H, doc.lin([(0, "#1B2026", 1), (1, "#0C0F12", 1)], 0, 0, 0.2, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FFFFFF", 0.13), (0.5, "#FFFFFF", 0.03), (1, "#FFFFFF", 0)], light[0],
                                 light[1], 0.6))


# ---------------------------------------------------------------- alternative a: the controller row

def _comp_rail(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    exploited = brief.status in ("exploited", "attacks_observed")
    signal = p.danger if exploited else p.accent
    _backdrop(doc, (0.42, 0.66))
    cam = Camera(eye=(-90.0, 140.0, 430.0), target=(150.0, -10.0, 70.0), focal=1300, cx=820, cy=500)
    pw = 1400.0
    c = cam.p((90.0, 0.0, 0.0))
    doc.glow(c[0] + 40, c[1] - 10, 560, 300, "#C9D3DE", 0.13)

    # DIN rail (35 mm hat profile) along the wall
    rl = [(-700.0, 17.5, 7.5), (pw, 17.5, 7.5), (pw, -17.5, 7.5), (-700.0, -17.5, 7.5)]
    rs = cam.poly(doc, rl, doc.lin([(0, "#B9C0C6", 1), (0.45, "#7E868D", 1), (1, "#555C63", 1)], 0, 0, 0, 1))
    doc.path(path_of([rs[0], rs[1]], closed=False), stroke="#E6EAED", sw=2, opacity=0.7)
    doc.poly(rs, doc.lin([(0, "#0C0F12", 0.75), (0.35, "#0C0F12", 0.0), (0.8, "#0C0F12", 0.0), (1, "#0C0F12", 0.6)], 0, 0, 1, 0))
    slots = "".join(path_of([cam.p((sx, 5.0, 7.6)), cam.p((sx + 15, 5.0, 7.6)), cam.p((sx + 15, -5.0, 7.6)),
                             cam.p((sx, -5.0, 7.6))]) for sx in range(-690, -10, 25))
    doc.path(slots, fill="#2B3036")

    mod_h, mod_d = 150.0, 128.0
    y0 = -mod_h / 2 - 6
    cpu_w, io_w = 130.0, 35.0
    n_io = 9
    # cast shadow of the row on the plate (key light from the upper right)
    sh = [cam.p(q) for q in ((-10.0, y0 + mod_h - 20, 0.0), (cpu_w + n_io * io_w, y0 + mod_h - 20, 0.0),
                             (cpu_w + n_io * io_w - 40, y0 - 40, 0.0), (-50.0, y0 - 40, 0.0))]
    doc.path(path_of(sh), fill="#000000", opacity=0.6, extra=f' filter="{doc.blur(22)}"')

    # I/O modules, far to near
    for k in reversed(range(n_io)):
        x0 = cpu_w + k * io_w
        _box(doc, cam, x0, y0, 0.0, io_w - 0.6, mod_h, mod_d, _HOUSING)
        _vents(doc, cam, x0, y0 + mod_h, 0.0, io_w - 0.6, mod_d, 4)
        with doc.g(cam.face((x0, y0 + mod_h, mod_d), _X, _Y_DOWN, (io_w - 0.6, mod_h))):
            _io_front(doc, io_w - 0.6, mod_h, rng, "#2F6FB0")
        # depth haze on the far modules
        if k > 3:
            q = [(x0, y0 + mod_h, mod_d), (x0 + io_w, y0 + mod_h, mod_d), (x0 + io_w, y0, mod_d),
                 (x0, y0, mod_d)]
            cam.poly(doc, q, "#0C0F12", opacity=min(0.55, 0.09 * (k - 3)))

    # the controller (hero)
    _box(doc, cam, 0.0, y0, 0.0, cpu_w, mod_h, mod_d, _HOUSING)
    _vents(doc, cam, 0.0, y0 + mod_h, 0.0, cpu_w, mod_d, 14)
    with doc.g(cam.face((0.0, y0 + mod_h, mod_d), _X, _Y_DOWN, (cpu_w, mod_h))):
        pu, pv = _cpu_front(doc, cpu_w, mod_h)
    # specular sheen across the controller front
    fr = [cam.p(q) for q in ((0.0, y0 + mod_h, mod_d), (cpu_w, y0 + mod_h, mod_d), (cpu_w, y0, mod_d),
                             (0.0, y0, mod_d))]
    doc.path(path_of(fr), fill=doc.lin([(0, "#FFFFFF", 0.0), (0.45, "#FFFFFF", 0.07), (0.6, "#FFFFFF", 0.0)],
                                       0, 0, 1, 0.6))

    # patch cable: seated in the first port, hanging toward the viewer and out of frame
    end = _plug(doc, cam, pu, pv, 0.0, y0 + mod_h, mod_d, signal)
    _cable(doc, cam, [end, add(end, (0.0, -4.0, 26.0)), (end[0] - 20, end[1] - 50, end[2] + 70),
                      (end[0] - 90, end[1] - 110, end[2] + 110), (end[0] - 220, end[1] - 160, end[2] + 140)],
           signal, 5.8)

    # the advisory identifier on the dark wall above the row
    _title_block(doc, brief, 96, 120, 104, signal, exploited, 1000)
    doc.rect(0, 0, W, H, doc.rad([(0.6, "#000", 0), (1, "#000", 0.45)], 0.5, 0.55, 0.78))
    doc.focus = Box(60, 40, 1240, 698)


# ---------------------------------------------------------------- alternative b: the edge device

def _comp_edge(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    exploited = brief.status in ("exploited", "attacks_observed")
    signal = p.danger if exploited else p.accent
    doc.rect(0, 0, W, H, doc.lin([(0, "#161B21", 1), (1, "#07090B", 1)], 0, 0, 0, 1))
    cam = Camera(eye=(-330.0, 260.0, 560.0), target=(40.0, 30.0, 40.0), focal=1700, cx=1080, cy=440)
    # floor glow and the device's contact shadow
    c = cam.p((80.0, 0.0, 60.0))
    doc.glow(c[0], c[1] - 40, 560, 230, "#AFC1D3", 0.20)
    w, h, d = 230.0, 160.0, 120.0
    x0, z0 = -40.0, -20.0
    sh = [cam.p(q) for q in ((x0 - 8, 0.0, z0 - 30), (x0 + w + 40, 0.0, z0 - 30), (x0 + w + 40, 0.0, z0 + d + 10),
                             (x0 - 8, 0.0, z0 + d + 10))]
    doc.path(path_of(sh), fill="#000000", opacity=0.75, extra=f' filter="{doc.blur(18)}"')
    alu = {"front": ("#3F454D", "#2A2F35"), "top": ("#6B737D", "#4E555E"), "side": ("#20242A", "#181B1F")}
    # body (front panel) and the heat-sink fins on top
    _box(doc, cam, x0, 0.0, z0, w, h - 28, d, alu, rim="#C3CBD4")
    fins = 15
    for i in reversed(range(fins)):
        fx = x0 + 6 + i * (w - 12) / fins
        _box(doc, cam, fx, h - 28, z0 + 4, 5.0, 28.0, d - 8,
             {"front": ("#5E6670", "#434951"), "top": ("#B5BEC8", "#8C959F"), "side": ("#2A2F35", "#202429")},
             rim="#D8DEE5")
    # front panel detail
    with doc.g(cam.face((x0, h - 28, z0 + d), _X, _Y_DOWN, (w, h - 28))):
        fw, fh = w, h - 28
        doc.rect(8, 8, fw - 16, fh - 16, "#2B3036", 3, stroke="#555C64", sw=0.6)
        for k in range(4):
            _rj45(doc, 18 + k * 21, fh - 40)
        doc.rect(110, fh - 38, 12, 9, "#0B0C0E", 1.5, stroke="#7C848C", sw=0.6)     # USB
        doc.rect(126, fh - 38, 12, 9, "#0B0C0E", 1.5, stroke="#7C848C", sw=0.6)
        doc.rect(fw - 66, fh - 42, 44, 16, "#0B0C0E", 2, stroke="#7C848C", sw=0.6)  # display port
        for i in range(3):
            _lens(doc, 18 + i * 10, 20)
        doc.circle(fw - 26, 24, 6.5, "#1A1D21", stroke="#7C848C", sw=0.8)          # power button
        doc.path("".join(f"M{f(18)} {f(40 + k * 4.2)}h{f(fw - 36)}" for k in range(9)), stroke="#1A1D21", sw=1.6)
        doc.path("".join(f"M{f(18)} {f(41.2 + k * 4.2)}h{f(fw - 36)}" for k in range(9)), stroke="#FFFFFF", sw=0.4,
                 opacity=0.1)
        doc.path(f"M8 8H{f(fw * 0.5)}L{f(fw * 0.3)} {f(fh - 8)}H8Z", fill="#FFFFFF", opacity=0.04)
    end = _plug(doc, cam, 18 + 7.5, h - 28 - 40 + 6.5, x0, h - 28, z0 + d, signal)
    _cable(doc, cam, [end, add(end, (0.0, -6.0, 26.0)), (end[0] + 30, 0.0, end[2] + 120),
                      (end[0] + 130, -6.0, end[2] + 220), (end[0] + 330, -10.0, end[2] + 260)], signal, 5.8)
    _title_block(doc, brief, 80, 300, 112, signal, exploited, 790)
    doc.rect(0, 0, W, H, doc.rad([(0.6, "#000", 0), (1, "#000", 0.5)], 0.5, 0.5, 0.8))
    doc.focus = Box(60, 110, 1420, 799)


ALTERNATIVES: dict[str, Callable[[Doc, EditorialBrief, random.Random], None]] = {
    "a": _comp_rail, "b": _comp_edge}


@scene("ics_controller")
def ics_controller(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    _comp_rail(doc, brief, rng)
