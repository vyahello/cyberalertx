"""Commercial refrigeration controller: a panel-mounted controller with a
7-segment temperature readout beside a supermarket display case, its network
port reachable without a login and its set point open to change.

The readout value is device texture (a typical chiller reading), not a story
figure. With an advisory the set point is shown as writable; only when the
evidence reports attacks is it shown changed and the case warming."""
from __future__ import annotations

import math
import random

from .. import type as T
from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, arrow, f, icon, pill
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


def _controller(doc: Doc, c: Box, reading: str, *, alarm: bool) -> tuple[float, float]:
    """Controller housing (front + right side), display, keys. Returns the
    network port position."""
    p = doc.pal
    dep = 34
    doc.shadow(c.x, c.y, c.w + dep, c.h, 18, 1.1)
    # right side (depth) with the ports
    side = [(c.r - 2, c.y + 10), (c.r + dep, c.y + 26), (c.r + dep, c.b - 4), (c.r - 2, c.b - 18)]
    doc.poly(side, doc.lin([(0, "#AEB9C3", 1), (1, "#8B98A4", 1)], 0, 0, 1, 0))
    # housing front
    doc.rect(c.x, c.y, c.w, c.h, doc.lin([(0, "#FBFCFD", 1), (1, "#E3E8ED", 1)], 0, 0, 0.2, 1), 18,
             stroke="#B9C4CE", sw=1.5)
    doc.rect(c.x + 3, c.y + 3, c.w - 6, 40, doc.lin([(0, "#FFFFFF", 0.8), (1, "#FFFFFF", 0)]), 16)
    # display window
    d = Box(c.x + 40, c.y + 54, c.w - 80, 190)
    doc.rect(d.x - 6, d.y - 6, d.w + 12, d.h + 12, "#AEB8C2", 12)
    doc.rect(d.x, d.y, d.w, d.h, doc.lin([(0, "#0B1218", 1), (1, "#141E27", 1)]), 8)
    on = "#FF5A4F" if alarm else "#7FD6FF"
    off = "#1A2731"
    end = _seven(doc, reading, d.x + 40, d.y + 52, 64, 112, on, off, gap=20)
    # degree mark and unit
    doc.circle(end + 2, d.y + 62, 8, "none", on, 3.5)
    doc.text("C", end + 16, d.y + 100, 40, on, "ui_bold")
    # status pictograms in a row along the top of the display
    icons = (("comp", True), ("fan", True), ("defrost", False), ("alarm", alarm))
    for k, (name, lit) in enumerate(icons):
        ix, iy = d.x + 40 + k * 44, d.y + 26
        col = (p.danger if name == "alarm" else "#7FD6FF") if lit else "#2A3944"
        if name == "comp":     # snowflake
            for a in range(3):
                ang = math.pi * a / 3
                dx, dy = 11 * math.cos(ang), 11 * math.sin(ang)
                doc.line((ix - dx, iy - dy), (ix + dx, iy + dy), col, 2.4)
        elif name == "fan":
            for a in range(3):
                doc.add(f'<ellipse cx="{f(ix)}" cy="{f(iy - 6.5)}" rx="3.2" ry="6" fill="{col}" '
                        f'transform="rotate({a * 120} {f(ix)} {f(iy)})"/>')
        elif name == "defrost":
            doc.path(f"M{f(ix)} {f(iy - 11)}C{f(ix - 9)} {f(iy)} {f(ix - 8)} {f(iy + 10)} {f(ix)} {f(iy + 10)}"
                     f"C{f(ix + 8)} {f(iy + 10)} {f(ix + 9)} {f(iy)} {f(ix)} {f(iy - 11)}Z", fill=col)
        else:
            icon(doc, "warn", ix, iy, 24, col, 2.2)
    # keys
    keys = ("SET", "up", "down", "on")
    kw = (c.w - 80 - 3 * 18) / 4
    for k, name in enumerate(keys):
        kx, ky = c.x + 40 + k * (kw + 18), c.b - 92
        doc.rect(kx, ky + 4, kw, 58, "#000", 10, opacity=0.12, extra=f' filter="{doc.blur(3)}"')
        doc.rect(kx, ky, kw, 58, doc.lin([(0, "#F4F6F8", 1), (1, "#D5DCE3", 1)]), 10, stroke="#B4BFC9")
        cx, cy = kx + kw / 2, ky + 29
        ink = "#4A5866"
        if name == "SET":
            doc.text("SET", cx, cy + 7, 20, ink, "ui_bold", anchor="middle")
        elif name == "up":
            doc.poly([(cx - 11, cy + 6), (cx + 11, cy + 6), (cx, cy - 8)], ink)
        elif name == "down":
            doc.poly([(cx - 11, cy - 6), (cx + 11, cy - 6), (cx, cy + 8)], ink)
        else:
            doc.path(f"M{f(cx - 7)} {f(cy - 7)}A10 10 0 1 0 {f(cx + 7)} {f(cy - 7)}M{f(cx)} {f(cy - 13)}"
                     f"V{f(cy - 1)}", stroke=ink, sw=2.6)
    # ports on the side: terminal block + RJ45
    tb = [(c.r + 4, c.y + 60), (c.r + dep - 4, c.y + 68), (c.r + dep - 4, c.y + 150), (c.r + 4, c.y + 142)]
    doc.poly(tb, "#2F7D4F")
    for k in range(4):
        y0 = c.y + 74 + k * 18
        doc.circle(c.r + dep / 2, y0 + 2, 3.5, "#C9D6CF")
    j = [(c.r + 4, c.y + 200), (c.r + dep - 4, c.y + 210), (c.r + dep - 4, c.y + 262), (c.r + 4, c.y + 252)]
    doc.poly(j, "#1D252D")
    doc.poly([(c.r + 9, c.y + 212), (c.r + dep - 9, c.y + 219), (c.r + dep - 9, c.y + 250),
              (c.r + 9, c.y + 244)], "#05080B")
    return c.r + dep - 6, c.y + 234


@scene("refrigeration_controller")
def refrigeration_controller(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    attacked = brief.status in ("exploited", "attacks_observed")
    doc.rect(0, 0, W, H, doc.lin([(0, p.bg1, 1), (1, p.bg0, 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FFFFFF", 0.55), (1, "#FFFFFF", 0)], 0.45, 0.3, 0.7))

    _case(doc, Box(-60, 40, 560, 900), rng, warm=attacked)
    wall = Box(470, -10, 640, 920)
    doc.rect(wall.x - 16, wall.y, 26, wall.h, "#000", opacity=0.18, extra=f' filter="{doc.blur(10)}"')
    _panel_texture(doc, wall, rng)

    reading = " 8.4" if attacked else "-2.5"
    ctl = Box(540, 250, 470, 400)
    port = _controller(doc, ctl, reading, alarm=attacked)
    doc.text("COLD ROOM 2", ctl.cx, ctl.y - 30, 18, "#5B6B7D", "mono_bold", anchor="middle", tracking=2)

    # the remote session: reaches the controller over the network, no login
    card = Box(1188, 290, 360, 300)
    doc.shadow(card.x, card.y, card.w, card.h, 14, 0.8)
    doc.rect(card.x, card.y, card.w, card.h, "#FFFFFF", 14, stroke=p.line, sw=1.2)
    doc.rect(card.x, card.y, card.w, 50, "#EDF2F6", 14)
    doc.rect(card.x, card.y + 36, card.w, 14, "#EDF2F6")
    icon(doc, "globe", card.x + 30, card.y + 25, 22, p.muted, 2)
    doc.text("remote session", card.x + 52, card.y + 32, 18, p.on_surface, "ui_bold")
    rows = card.y + 92
    doc.text("login", card.x + 26, rows, 18, p.muted, "mono")
    pill(doc, card.x + 150, rows - 24, "not required", fg="#FFFFFF", bg=p.danger, size=16)
    doc.line((card.x + 20, rows + 26), (card.r - 20, rows + 26), p.line, 1)
    doc.text("set point", card.x + 26, rows + 70, 18, p.muted, "mono")
    if attacked:
        doc.text("changed", card.x + 150, rows + 70, 22, p.danger, "mono_bold")
    else:
        bx = Box(card.x + 150, rows + 40, 170, 48)
        doc.rect(bx.x, bx.y, bx.w, bx.h, "#F8FAFC", 8, stroke=p.danger, sw=2)
        doc.text(reading.strip(), bx.x + 16, bx.y + 33, 24, p.on_surface, "mono_bold")
        cx = bx.x + 16 + T.measure(reading.strip(), 24, "mono_bold") + 6
        doc.rect(cx, bx.y + 11, 3, 27, p.danger)
        icon(doc, "unlock", bx.r - 26, bx.cy, 22, p.danger, 2.2)
    doc.line((card.x + 20, rows + 110), (card.r - 20, rows + 110), p.line, 1)
    doc.text("defrost, alarms", card.x + 26, rows + 152, 18, p.muted, "mono")
    doc.text("open", card.x + 230, rows + 152, 18, p.danger, "mono_bold")

    # patch cable from the RJ45 down to a wall data outlet; the remote
    # session reaches the controller through it (danger: no login)
    px, py = port
    ox, oy = 1150, 700
    doc.path(f"M{f(px)} {f(py)}C{f(px + 70)} {f(py + 10)} {f(ox)} {f(oy - 170)} {f(ox)} {f(oy - 22)}",
             stroke="#2E3A46", sw=7)
    doc.shadow(ox - 30, oy - 26, 60, 64, 6, 0.4)
    doc.rect(ox - 30, oy - 26, 60, 64, doc.lin([(0, "#FFFFFF", 1), (1, "#DCE3EA", 1)]), 6, stroke="#AEB9C3")
    doc.rect(ox - 13, oy - 14, 26, 22, "#1D252D", 3)
    doc.rect(ox - 8, oy - 8, 16, 14, "#05080B", 1)
    doc.text("LAN", ox, oy + 28, 12, "#5B6B7D", "mono_bold", anchor="middle")
    arrow(doc, [(card.x + 70, card.b + 8), (card.x + 70, oy + 6), (ox + 44, oy + 6)], p.danger, sw=4, head=18,
          dash="10 8")
    doc.rect(0, 0, W, H, doc.rad([(0.6, "#000", 0), (1, "#000", 0.2)], 0.5, 0.5, 0.75))
    doc.focus = Box(500, 170, 800, 450)
