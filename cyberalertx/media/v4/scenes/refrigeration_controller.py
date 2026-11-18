"""Commercial refrigeration controller, close up: a large panel-mounted
controller on a cold-room wall, its network cable leading out of frame with
an open padlock on it (remote access without a login).

No temperature is shown: the 7-segment readout is drawn unlit (ghost
segments only), because no source states a reading. With an advisory the
controller is frosted and calm; only when the evidence reports attacks do the
heating / defrost pictograms light red and the room warm (the sources state
that settings were changed to force heating)."""
from __future__ import annotations

import math
import random


from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f
from . import scene

# 7-segment map: segments a b c d e f g
_SEG = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc",
        "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g", " ": ""}


def _seg_poly(x: float, y: float, w: float, h: float, t: float, seg: str) -> list[tuple[float, float]]:
    """Hexagonal segment polygon inside a digit cell (x, y, w, h)."""
    hh = h / 2
    def hor(cy: float) -> list[tuple[float, float]]:
        return [(x + t * 0.6, cy), (x + t * 1.1, cy - t / 2), (x + w - t * 1.1, cy - t / 2), (x + w - t * 0.6, cy),
                (x + w - t * 1.1, cy + t / 2), (x + t * 1.1, cy + t / 2)]
    def ver(cx: float, y0: float, y1: float) -> list[tuple[float, float]]:
        return [(cx, y0 + t * 0.6), (cx + t / 2, y0 + t * 1.1), (cx + t / 2, y1 - t * 1.1), (cx, y1 - t * 0.6),
                (cx - t / 2, y1 - t * 1.1), (cx - t / 2, y0 + t * 1.1)]
    polys: dict[str, list[tuple[float, float]]] = {"a": hor(y + t / 2), "g": hor(y + hh), "d": hor(y + h - t / 2),
            "f": ver(x + t / 2, y, y + hh), "b": ver(x + w - t / 2, y, y + hh),
            "e": ver(x + t / 2, y + hh, y + h), "c": ver(x + w - t / 2, y + hh, y + h)}
    return polys[seg]


def _seven(doc: Doc, s: str, x: float, y: float, w: float, h: float, on: str, off: str, gap: float = 18) -> float:
    """Draw a 7-segment string (digits, '-', '.'), slanted like a real LED readout."""
    lit: list[str] = []
    dim: list[str] = []
    t = w * 0.2
    cx = x
    for ch in s:
        if ch == ".":
            lit.append(f"M{f(cx - gap * 0.55)} {f(y + h - t * 0.9)}h{f(t * 0.9)}v{f(t * 0.9)}h{f(-t * 0.9)}Z")
            continue
        segs = _SEG.get(ch, "")
        for sg in "abcdefg":
            pts = _seg_poly(cx, y, w, h, t, sg)
            d = "M" + "L".join(f"{f(px)} {f(py)}" for px, py in pts) + "Z"
            (lit if sg in segs else dim).append(d)
        cx += w + gap
    sk = f"skewX(-7) translate({f(y * 0.123)} 0)"
    with doc.g(transform=sk):
        doc.path("".join(dim), fill=off)
        doc.path("".join(lit), fill=on, extra=f' filter="{doc.blur(5)}"', opacity=0.55)
        doc.path("".join(lit), fill=on)
    return cx


def _case(doc: Doc, b: Box, rng: random.Random, warm: bool) -> None:
    """Open multideck display case in elevation (cropped by the frame)."""
    p = doc.pal
    doc.rect(b.x, b.y, b.w, b.h, doc.lin([(0, "#E9EEF2", 1), (1, "#C9D3DC", 1)], 0, 0, 1, 0), 10)
    inner = b.inset(28, 40)
    doc.rect(inner.x, inner.y, inner.w, inner.h, doc.lin([(0, "#1B2A3A", 1), (1, "#22374C", 1)]), 4)
    # cold light from the canopy and the shelf strips
    doc.rect(inner.x, inner.y, inner.w, 70, doc.lin([(0, "#BFE3FF", 0.55), (1, "#BFE3FF", 0)]))
    shelves = 5
    sh = (inner.h - 40) / shelves
    palette = ["#E8EEF3", "#F4D35E", "#7FB7E6", "#F1F5F9", "#E07A5F", "#9BD3AE", "#D8E2EA", "#5B8DB8"]
    for k in range(shelves):
        sy = inner.y + 30 + (k + 1) * sh
        # products: cartons and bottles standing on the shelf
        x = inner.x + 12
        while x < inner.r - 30:
            kind = rng.random()
            col = rng.choice(palette)
            if kind < 0.5:
                w, h = rng.uniform(34, 46), sh * rng.uniform(0.55, 0.72)
                doc.rect(x, sy - h, w, h, col, 3)
                doc.path(f"M{f(x)} {f(sy - h)}L{f(x + w / 2)} {f(sy - h - 12)}L{f(x + w)} {f(sy - h)}Z", fill=col)
                doc.rect(x + w * 0.62, sy - h, w * 0.38, h, "#000", 0, opacity=0.12)
            else:
                w, h = rng.uniform(22, 28), sh * rng.uniform(0.6, 0.78)
                doc.rect(x, sy - h * 0.72, w, h * 0.72, col, 6)
                doc.rect(x + w * 0.3, sy - h, w * 0.4, h * 0.3, col, 3)
                doc.rect(x + 3, sy - h * 0.6, 4, h * 0.45, "#FFFFFF", 2, opacity=0.35)
            x += w + rng.uniform(5, 10)
        # shelf edge with price rail and LED strip
        doc.rect(inner.x - 6, sy, inner.w + 12, 12, "#D9E2EA", 2)
        doc.rect(inner.x - 6, sy + 12, inner.w + 12, 5, "#9FB1C1")
        doc.rect(inner.x, sy + 17, inner.w, 10, doc.lin([(0, "#DFF3FF", 0.6), (1, "#DFF3FF", 0)]))
    # air curtain grille at the bottom, kick plate
    doc.rect(inner.x, inner.b - 30, inner.w, 30, "#9FB1C1")
    doc.path("".join(f"M{f(xx)} {f(inner.b - 26)}v22" for xx in range(int(inner.x + 8), int(inner.r), 9)),
             stroke="#6E8295", sw=2)
    # haze: the case sits behind the controller
    doc.rect(b.x, b.y, b.w, b.h, "#C5D3DF", opacity=0.22)
    if warm:
        doc.rect(inner.x, inner.y, inner.w, inner.h, doc.lin([(0, p.danger, 0.0), (1, p.danger, 0.22)]))
    # glass reflection
    doc.poly([(inner.x + inner.w * 0.15, inner.y), (inner.x + inner.w * 0.32, inner.y),
              (inner.x + inner.w * 0.08, inner.b), (inner.x - 4, inner.b)], "#FFFFFF", opacity=0.06)


def _panel_texture(doc: Doc, b: Box, rng: random.Random) -> None:
    """Brushed stainless cold-room wall panel."""
    doc.rect(b.x, b.y, b.w, b.h, doc.lin([(0, "#D3DCE3", 1), (0.5, "#E7EDF2", 1), (1, "#C7D1D9", 1)], 0, 0, 1, 0))
    d = "".join(f"M{f(b.x)} {f(b.y + rng.uniform(0, b.h))}h{f(b.w)}" for _ in range(70))
    doc.path(d, stroke="#FFFFFF", sw=1, opacity=0.35)
    d = "".join(f"M{f(b.x)} {f(b.y + rng.uniform(0, b.h))}h{f(b.w)}" for _ in range(50))
    doc.path(d, stroke="#8C9BA8", sw=1, opacity=0.18)
    # panel seams and rivets
    doc.line((b.x, b.y), (b.x, b.b), "#8E9CA8", 2)
    doc.line((b.r, b.y), (b.r, b.b), "#8E9CA8", 2)
    for yy in range(int(b.y + 40), int(b.b), 160):
        doc.circle(b.x + 16, yy, 4, "#9AA8B4")
        doc.circle(b.r - 16, yy, 4, "#9AA8B4")


def _padlock(doc: Doc, cx: float, cy: float, s: float, color: str) -> None:
    """A large open padlock (body + shackle swung open), drawn as an object."""
    bw, bh = s, s * 0.78
    x, y = cx - bw / 2, cy - bh / 2 + s * 0.18
    sh = s * 0.30
    doc.add(f'<ellipse cx="{f(cx + 8)}" cy="{f(y + bh + 18)}" rx="{f(bw * 0.55)}" ry="{f(s * 0.07)}" '
            f'fill="#000" opacity="0.18" filter="{doc.blur(8)}"/>')
    # shackle: left leg in the body, right leg lifted out and swung open
    r = bw * 0.30
    lx = x + bw * 0.22
    doc.path(f"M{f(lx)} {f(y + 4)}V{f(y - sh)}A{f(r)} {f(r)} 0 0 1 {f(lx + 2 * r)} {f(y - sh)}V{f(y - sh * 0.35)}",
             stroke="#7C8792", sw=s * 0.11, cap="round")
    doc.path(f"M{f(lx)} {f(y + 4)}V{f(y - sh)}A{f(r)} {f(r)} 0 0 1 {f(lx + 2 * r)} {f(y - sh)}V{f(y - sh * 0.35)}",
             stroke="#C9D2DA", sw=s * 0.05, cap="round", opacity=0.9)
    doc.rect(x, y, bw, bh, doc.lin([(0, color, 1), (1, "#9E2318", 1)], 0, 0, 0.4, 1), s * 0.12)
    doc.rect(x + 6, y + 6, bw - 12, bh * 0.28, "#FFFFFF", s * 0.09, opacity=0.18)
    kx, ky = cx, y + bh * 0.48
    doc.circle(kx, ky, s * 0.085, "#3B0D08")
    doc.poly([(kx - s * 0.04, ky), (kx + s * 0.04, ky), (kx + s * 0.06, ky + s * 0.2), (kx - s * 0.06, ky + s * 0.2)],
             "#3B0D08")


def _controller(doc: Doc, c: Box, *, hot: bool) -> tuple[float, float]:
    """Controller housing (front + right side), unlit display, pictograms,
    keys. Returns the network port position."""
    p = doc.pal
    dep = 56
    doc.shadow(c.x, c.y, c.w + dep, c.h, 26, 1.6)
    side = [(c.r - 4, c.y + 14), (c.r + dep, c.y + 40), (c.r + dep, c.b - 6), (c.r - 4, c.b - 30)]
    doc.poly(side, doc.lin([(0, "#A9B5C0", 1), (1, "#7F8D9A", 1)], 0, 0, 1, 0))
    doc.rect(c.x, c.y, c.w, c.h, doc.lin([(0, "#FDFEFE", 1), (1, "#DCE3E9", 1)], 0, 0, 0.25, 1), 26,
             stroke="#AFBBC6", sw=2)
    doc.rect(c.x + 4, c.y + 4, c.w - 8, 60, doc.lin([(0, "#FFFFFF", 0.9), (1, "#FFFFFF", 0)]), 22)
    d = Box(c.x + 54, c.y + 64, c.w - 108, c.h * 0.50)
    doc.rect(d.x - 9, d.y - 9, d.w + 18, d.h + 18, "#A3AEB8", 16)
    doc.rect(d.x, d.y, d.w, d.h, doc.lin([(0, "#0A1016", 1), (1, "#131D26", 1)]), 10)
    # ghost segments only: no reading is stated by the sources
    _seven(doc, "   ", d.x + d.w * 0.30, d.y + d.h * 0.22, d.w * 0.11, d.h * 0.62, "#000", "#17232D",
           gap=d.w * 0.035)
    # pictogram column at the left of the display: cooling (snowflake) and heating/defrost
    ix = d.x + d.w * 0.14
    cool = "#2B3B47" if hot else "#7FD6FF"
    heat = p.danger if hot else "#2B3B47"
    iy = d.y + d.h * 0.32
    for a in range(3):
        ang = math.pi * a / 3
        dx, dy = 30 * math.cos(ang), 30 * math.sin(ang)
        doc.line((ix - dx, iy - dy), (ix + dx, iy + dy), cool, 7)
    iy2 = d.y + d.h * 0.72
    if hot:
        doc.glow(ix, iy2, 46, 46, p.danger, 0.55)
    for k in (-1, 0, 1):        # heat waves (defrost heater pictogram)
        x0 = ix + k * 24
        doc.path(f"M{f(x0)} {f(iy2 + 34)}c-12 -12 12 -22 0 -34s12 -22 0 -34", stroke=heat, sw=8)
    if not hot:
        doc.glow(ix, iy, 40, 40, "#7FD6FF", 0.35)
    doc.rect(d.x, d.y, d.w, d.h * 0.45, doc.lin([(0, "#FFFFFF", 0.07), (1, "#FFFFFF", 0)]), 10)
    # keys
    kw = (c.w - 108 - 3 * 22) / 4
    for k in range(4):
        kx, ky = c.x + 54 + k * (kw + 22), c.b - 118
        doc.rect(kx, ky + 6, kw, 78, "#000", 14, opacity=0.14, extra=f' filter="{doc.blur(4)}"')
        doc.rect(kx, ky, kw, 78, doc.lin([(0, "#F6F8FA", 1), (1, "#D3DAE1", 1)]), 14, stroke="#AFBBC6")
        cx, cy = kx + kw / 2, ky + 39
        ink = "#4A5866"
        if k == 0:
            doc.text("SET", cx, cy + 10, 28, ink, "ui_bold", anchor="middle")
        elif k == 1:
            doc.poly([(cx - 15, cy + 9), (cx + 15, cy + 9), (cx, cy - 11)], ink)
        elif k == 2:
            doc.poly([(cx - 15, cy - 9), (cx + 15, cy - 9), (cx, cy + 11)], ink)
        else:
            doc.path(f"M{f(cx - 10)} {f(cy - 10)}A14 14 0 1 0 {f(cx + 10)} {f(cy - 10)}M{f(cx)} {f(cy - 18)}"
                     f"V{f(cy - 2)}", stroke=ink, sw=3.5)
    # RJ45 on the side
    j = [(c.r + 6, c.y + 250), (c.r + dep - 6, c.y + 262), (c.r + dep - 6, c.y + 330), (c.r + 6, c.y + 318)]
    doc.poly(j, "#1D252D")
    doc.poly([(c.r + 12, c.y + 264), (c.r + dep - 12, c.y + 273), (c.r + dep - 12, c.y + 318),
              (c.r + 12, c.y + 310)], "#05080B")
    return c.r + dep - 10, c.y + 292


@scene("refrigeration_controller")
def refrigeration_controller(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    attacked = brief.status in ("exploited", "attacks_observed", "confirmed")
    _panel_texture(doc, Box(0, 0, W, H), rng)
    doc.rect(0, 0, W, H, doc.rad([(0, "#FFFFFF", 0.55), (1, "#FFFFFF", 0)], 0.4, 0.3, 0.7))
    if attacked:   # the room warms: red heat rising from below
        doc.rect(0, 0, W, H, doc.lin([(0, p.danger, 0.0), (0.55, p.danger, 0.10), (1, p.danger, 0.42)]))
    else:
        doc.rect(0, 0, W, H, doc.lin([(0, "#BFE3FF", 0.35), (1, "#BFE3FF", 0.05)]))
    # blurred display case at the far left edge: context, not subject
    with doc.g(filt=doc.blur(5), opacity=0.9):
        _case(doc, Box(-330, 60, 560, 900), rng, warm=attacked)

    ctl = Box(330, 150, 720, 590)
    port = _controller(doc, ctl, hot=attacked)

    # network cable from the controller's port out of frame (to the network)
    px, py = port
    cable = f"M{f(px)} {f(py)}C{f(px + 160)} {f(py + 10)} {f(1300)} {f(560)} {f(W + 40)} {f(520)}"
    doc.path(cable, stroke="#000", sw=26, opacity=0.12, extra=f' filter="{doc.blur(8)}"')
    doc.path(cable, stroke="#2E3A46", sw=18)
    doc.path(cable, stroke="#56687A", sw=4, opacity=0.6)
    doc.rect(px - 8, py - 26, 46, 52, "#3A4856", 8)
    # the open padlock hung on the cable: reachable without a login
    _padlock(doc, 1340, 400, 190, p.danger)
    name = next((e for e in brief.entities if e.lower() == "danfoss"), "")
    if name:
        doc.text(name, 330, 856, 40, p.ink, "display", opacity=0.85)
    doc.rect(0, 0, W, H, doc.rad([(0.6, "#000", 0), (1, "#000", 0.2)], 0.5, 0.5, 0.75))
    doc.focus = Box(300, 110, 1250, 703)
