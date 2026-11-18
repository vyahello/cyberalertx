"""Deepfake video calls: a meeting window in which the active speaker's face
is a synthetic mesh being assembled in real time (half rendered skin, half
wireframe), while beside the call a transfer is being approved.

No hooded figure, no real conferencing interface: a generic meeting window,
placeholder names, a masked wallet address. The money figure appears only
when the sources state it."""
from __future__ import annotations

import math
import random
import re

from ..brief import EditorialBrief
from ..kit import Box, Doc, f, icon, pill
from . import scene

Pt = tuple[float, float]


# ---------------------------------------------------------------- geometry

def _delaunay(pts: list[Pt]) -> list[tuple[int, int, int]]:
    """Bowyer-Watson triangulation (about 70 points: cheap)."""
    big = 1e5
    allp = list(pts) + [(-big, -big), (big, -big), (0.0, big)]
    n = len(pts)
    tris = [(n, n + 1, n + 2)]

    def circ(t: tuple[int, int, int]) -> tuple[float, float, float]:
        (ax, ay), (bx, by), (cx, cy) = allp[t[0]], allp[t[1]], allp[t[2]]
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by)) or 1e-9
        ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
        uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
        return ux, uy, (ax - ux) ** 2 + (ay - uy) ** 2

    for i, (px, py) in enumerate(pts):
        bad = []
        for t in tris:
            ux, uy, r2 = circ(t)
            if (px - ux) ** 2 + (py - uy) ** 2 < r2:
                bad.append(t)
        edges: dict[tuple[int, int], int] = {}
        for t in bad:
            for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = (min(e), max(e))
                edges[k] = edges.get(k, 0) + 1
        tris = [t for t in tris if t not in bad]
        for (a, b), c in edges.items():
            if c == 1:
                tris.append((a, b, i))
    return [t for t in tris if max(t) < n]


def _face_points(rng: random.Random) -> list[Pt]:
    """Facial landmarks on a unit face (x right, y down, centre ~ nose bridge)."""
    pts: list[Pt] = []
    # outline: an egg, narrower toward the chin
    for k in range(24):
        a = -math.pi / 2 + k * 2 * math.pi / 24
        y = 0.64 * math.sin(a)
        x = 0.45 * math.cos(a) * (1 - 0.30 * max(y, 0) / 0.64)
        pts.append((x, y))
    for s in (-1, 1):
        for k in range(6):                                  # eye
            a = k * math.pi / 3
            pts.append((s * 0.18 + 0.085 * math.cos(a), -0.07 + 0.035 * math.sin(a)))
        for k in range(4):                                  # brow
            pts.append((s * (0.08 + k * 0.065), -0.19 - 0.03 * math.sin(math.pi * k / 3)))
        pts += [(s * 0.06, 0.17), (s * 0.30, 0.09), (s * 0.26, 0.27), (s * 0.16, -0.40), (s * 0.32, -0.33),
                (s * 0.12, 0.47), (s * 0.20, 0.38), (s * 0.34, -0.12)]
    pts += [(0, -0.07), (0, 0.04), (0, 0.13), (0, 0.20), (0, -0.46), (0, -0.30), (0, 0.55)]
    for k in range(8):                                      # mouth
        a = k * math.pi / 4
        pts.append((0.13 * math.cos(a), 0.32 + 0.035 * math.sin(a)))
    return [(x + rng.uniform(-0.006, 0.006), y + rng.uniform(-0.006, 0.006)) for x, y in pts]


def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a[i] + (b[i] - a[i]) * max(0.0, min(1.0, t))):02X}" for i in range(3))


# ---------------------------------------------------------------- people

def _room(doc: Doc, b: Box, base: str, rng: random.Random) -> None:
    """A soft, out-of-focus home-office background."""
    doc.rect(b.x, b.y, b.w, b.h, doc.lin([(0, _mix(base, "#FFFFFF", 0.12), 1), (1, _mix(base, "#000000", 0.35), 1)]))
    blobs = []
    for _ in range(5):
        x, y = b.x + rng.uniform(0, b.w), b.y + rng.uniform(0, b.h * 0.6)
        blobs.append(f'<rect x="{f(x)}" y="{f(y)}" width="{f(b.w * rng.uniform(0.08, 0.2))}" '
                     f'height="{f(b.h * rng.uniform(0.15, 0.4))}" '
                     f'fill="{_mix(base, "#FFFFFF", rng.uniform(0.15, 0.35))}" '
                     f'opacity="0.5"/>')
    doc.add(f'<g clip-path="{doc.clip_rect(b.x, b.y, b.w, b.h)}"><g filter="{doc.blur(max(6, b.w / 40))}">'
            f'{"".join(blobs)}</g></g>')


def _person(doc: Doc, cx: float, top: float, s: float, skin: str, hair: str, shirt: str, clip: str,
            style: int) -> None:
    """Head-and-shoulders, flat editorial shading. `s` = head width."""
    hw, hh = s / 2, s * 0.64
    hy = top + hh
    with doc.g(clip=clip):
        # shoulders
        sy = hy + hh * 0.95
        doc.path(f"M{f(cx - s * 1.25)} {f(sy + s * 1.4)}C{f(cx - s * 1.2)} {f(sy + s * 0.2)} {f(cx - s * 0.7)} "
                 f"{f(sy)} {f(cx)} {f(sy - s * 0.04)}C{f(cx + s * 0.7)} {f(sy)} {f(cx + s * 1.2)} {f(sy + s * 0.2)} "
                 f"{f(cx + s * 1.25)} {f(sy + s * 1.4)}Z", fill=shirt)
        # collar opening + neck
        doc.rect(cx - hw * 0.42, hy + hh * 0.55, hw * 0.84, hh * 0.55, _mix(skin, "#000000", 0.18), hw * 0.3)
        doc.path(f"M{f(cx - s * 0.26)} {f(sy - 2)}L{f(cx)} {f(sy + s * 0.32)}L{f(cx + s * 0.26)} {f(sy - 2)}Z",
                 fill=_mix(skin, "#000000", 0.12))
        # head
        face = doc.lin([(0, _mix(skin, "#FFFFFF", 0.12), 1), (1, _mix(skin, "#000000", 0.15), 1)], 0, 0, 1, 0)
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(hy)}" rx="{f(hw * 0.9)}" ry="{f(hh)}" '
                f'fill="{face}"/>')
        doc.add(f'<ellipse cx="{f(cx - hw * 0.88)}" cy="{f(hy + hh * 0.08)}" rx="{f(hw * 0.12)}" ry="{f(hh * 0.18)}" '
                f'fill="{_mix(skin, "#000000", 0.1)}"/>')
        doc.add(f'<ellipse cx="{f(cx + hw * 0.88)}" cy="{f(hy + hh * 0.08)}" rx="{f(hw * 0.12)}" ry="{f(hh * 0.18)}" '
                f'fill="{_mix(skin, "#000000", 0.18)}"/>')
        # hair
        if style == 0:
            doc.path(f"M{f(cx - hw * 0.95)} {f(hy - hh * 0.05)}C{f(cx - hw)} {f(top - hh * 0.25)} {f(cx + hw)} "
                     f"{f(top - hh * 0.25)} {f(cx + hw * 0.95)} {f(hy - hh * 0.05)}C{f(cx + hw * 0.7)} "
                     f"{f(top + hh * 0.2)} {f(cx - hw * 0.5)} {f(top + hh * 0.35)} {f(cx - hw * 0.95)} "
                     f"{f(hy - hh * 0.05)}Z", fill=hair)
        elif style == 1:
            doc.path(f"M{f(cx - hw * 1.05)} {f(hy + hh * 0.9)}C{f(cx - hw * 1.3)} {f(top - hh * 0.3)} "
                     f"{f(cx + hw * 1.3)} {f(top - hh * 0.3)} {f(cx + hw * 1.05)} {f(hy + hh * 0.9)}"
                     f"C{f(cx + hw * 0.8)} {f(hy)} {f(cx + hw * 0.6)} {f(top + hh * 0.3)} {f(cx)} {f(top + hh * 0.25)}"
                     f"C{f(cx - hw * 0.6)} {f(top + hh * 0.3)} {f(cx - hw * 0.8)} {f(hy)} {f(cx - hw * 1.05)} "
                     f"{f(hy + hh * 0.9)}Z", fill=hair)
        else:
            doc.path(f"M{f(cx - hw * 0.92)} {f(hy - hh * 0.2)}C{f(cx - hw * 0.9)} {f(top - hh * 0.1)} "
                     f"{f(cx + hw * 0.9)} {f(top - hh * 0.1)} {f(cx + hw * 0.92)} {f(hy - hh * 0.2)}"
                     f"C{f(cx + hw * 0.5)} {f(top + hh * 0.12)} {f(cx - hw * 0.5)} {f(top + hh * 0.12)} "
                     f"{f(cx - hw * 0.92)} {f(hy - hh * 0.2)}Z", fill=hair)
        # features, kept minimal
        ink = _mix(skin, "#000000", 0.55)
        for sx in (-1, 1):
            doc.add(f'<ellipse cx="{f(cx + sx * hw * 0.36)}" cy="{f(hy - hh * 0.02)}" rx="{f(hw * 0.07)}" '
                    f'ry="{f(hh * 0.045)}" fill="{ink}"/>')
            doc.path(f"M{f(cx + sx * hw * 0.22)} {f(hy - hh * 0.2)}Q{f(cx + sx * hw * 0.36)} {f(hy - hh * 0.27)} "
                     f"{f(cx + sx * hw * 0.52)} {f(hy - hh * 0.19)}", stroke=_mix(hair, skin, 0.2),
                     sw=max(2, s * 0.025))
        doc.path(f"M{f(cx - hw * 0.02)} {f(hy + hh * 0.04)}L{f(cx - hw * 0.1)} {f(hy + hh * 0.3)}L{f(cx + hw * 0.06)} "
                 f"{f(hy + hh * 0.32)}", stroke=_mix(skin, "#000000", 0.25), sw=max(1.5, s * 0.018))
        doc.path(f"M{f(cx - hw * 0.25)} {f(hy + hh * 0.5)}Q{f(cx)} {f(hy + hh * 0.6)} {f(cx + hw * 0.25)} "
                 f"{f(hy + hh * 0.5)}", stroke=_mix(skin, "#000000", 0.4), sw=max(2, s * 0.022))


def _synthetic(doc: Doc, cx: float, cy: float, s: float, rng: random.Random, reveal: float, skin: str,
               line: str, clip: str) -> list[Pt]:
    """The synthetic face: a landmark mesh, rendered skin left of `reveal`
    (fraction across the face), bare wireframe right of it."""
    pts = [(cx + x * s, cy + y * s) for x, y in _face_points(rng)]
    tris = _delaunay(pts)
    rx = cx + (reveal - 0.5) * s * 0.9
    fills, wires = [], []
    for t in tris:
        (ax, ay), (bx, by), (qx, qy) = pts[t[0]], pts[t[1]], pts[t[2]]
        gx, gy = (ax + bx + qx) / 3, (ay + by + qy) / 3
        d = f"M{f(ax)} {f(ay)}L{f(bx)} {f(by)}L{f(qx)} {f(qy)}Z"
        if gx < rx:
            # light from the upper left; features darker
            shade = 0.5 + 0.35 * (gx - cx) / s + 0.25 * (gy - cy) / s + rng.uniform(-0.06, 0.06)
            fills.append(f'<path d="{d}" fill="{_mix(_mix(skin, "#FFFFFF", 0.18), _mix(skin, "#000000", 0.4), shade)}" '
                         f'stroke="{_mix(skin, "#000000", 0.1)}" stroke-width="0.6"/>')
        wires.append(d)
    def U(x: float, y: float) -> Pt:
        return (cx + x * s, cy + y * s)

    def poly(ps: list[Pt], z: str = "Z") -> str:
        return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in ps) + z

    left = doc.clip_rect(cx - s, cy - s, rx - (cx - s), 2 * s)
    right = doc.clip_rect(rx, cy - s, cx + s - rx, 2 * s)
    eyes = [[U(sx * 0.18 + 0.085 * math.cos(k * math.pi / 3), -0.07 + 0.035 * math.sin(k * math.pi / 3))
             for k in range(6)] for sx in (-1, 1)]
    brows = [[U(sx * (0.08 + k * 0.065), -0.19 - 0.03 * math.sin(math.pi * k / 3)) for k in range(4)]
             for sx in (-1, 1)]
    lips = [U(0.13 * math.cos(k * math.pi / 4), 0.32 + 0.035 * math.sin(k * math.pi / 4)) for k in range(8)]
    with doc.g(clip=clip):
        # hair on the rendered half: the synthesis paints a person over the mesh
        with doc.g(clip=left):
            doc.add("".join(fills))
            hx0, hy0 = U(-0.47, -0.05)
            doc.path(f"M{f(hx0)} {f(hy0)}C{f(cx - s * 0.52)} {f(cy - s * 0.62)} {f(cx - s * 0.1)} {f(cy - s * 0.8)} "
                     f"{f(cx + s * 0.3)} {f(cy - s * 0.66)}L{f(cx + s * 0.2)} {f(cy - s * 0.44)}C{f(cx - s * 0.05)} "
                     f"{f(cy - s * 0.5)} {f(cx - s * 0.36)} {f(cy - s * 0.4)} {f(cx - s * 0.42)} {f(cy - s * 0.02)}Z",
                     fill="#2B1F1A")
            for e in eyes:
                ex = sum(x for x, _ in e) / 6
                ey = sum(y for _, y in e) / 6
                doc.path(poly(e), fill="#F2ECE6", stroke="#3A2620", sw=2)
                doc.circle(ex, ey, s * 0.026, "#4A3426")
                doc.circle(ex - s * 0.008, ey - s * 0.008, s * 0.007, "#FFFFFF")
            for b in brows:
                doc.path(poly(b, ""), stroke="#2B1F1A", sw=s * 0.022)
            doc.path(poly(lips), fill="#A85E5A", stroke="#7A3E3A", sw=1.5)
            doc.path(f"M{f(U(-0.06, 0.17)[0])} {f(U(-0.06, 0.17)[1])}Q{f(cx)} {f(cy + s * 0.215)} "
                     f"{f(U(0.06, 0.17)[0])} {f(U(0.06, 0.17)[1])}", stroke="#7A4A3A", sw=2.5)
        with doc.g(clip=right):
            doc.path("".join(wires), stroke=line, sw=1.4, opacity=0.95)
            for e in eyes:
                doc.path(poly(e), stroke="#FFFFFF", sw=2.2)
            for b in brows:
                doc.path(poly(b, ""), stroke="#FFFFFF", sw=2.2)
            doc.path(poly(lips), stroke="#FFFFFF", sw=2.2)
            doc.path(poly([U(0, -0.07), U(0, 0.04), U(0, 0.13), U(0.06, 0.17), U(0, 0.20)], ""), stroke="#FFFFFF",
                     sw=2.2)
        # the edge where synthesis is happening
        doc.rect(rx - 2, cy - s * 0.78, 4, s * 1.56, line, opacity=0.9)
        doc.rect(rx - 30, cy - s * 0.78, 60, s * 1.56, line, opacity=0.18, extra=f' filter="{doc.blur(10)}"')
        for x, y in pts:
            if x >= rx - 2:
                doc.circle(x, y, 3.2, line)
            else:
                doc.circle(x, y, 1.8, "#FFFFFF", opacity=0.5)
    return pts


# ---------------------------------------------------------------- scene

@scene("deepfake_call")
def deepfake_call(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    doc.rect(0, 0, 1600, 900, doc.lin([(0, "#191232", 1), (1, "#0B0816", 1)], 0, 0, 0.5, 1))
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#7A5CFF", 0.20), (1, "#7A5CFF", 0)], 0.33, 0.45, 0.6))

    # ---- the meeting window
    win = Box(60, 86, 1010, 730)
    doc.shadow(win.x, win.y, win.w, win.h, 16, 1.2)
    doc.rect(win.x, win.y, win.w, win.h, "#0F0C1C", 16, stroke="#2E2650", sw=1.2)
    doc.rect(win.x, win.y, win.w, 46, "#17122A", 16)
    doc.rect(win.x, win.y + 30, win.w, 16, "#17122A")
    for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        doc.circle(win.x + 24 + i * 18, win.y + 23, 5.5, c, opacity=0.85)
    doc.text("Weekly sync - partners", win.x + win.w / 2, win.y + 29, 16, p.muted, "ui", anchor="middle")
    doc.circle(win.r - 120, win.y + 23, 5, p.danger)
    doc.text("REC  00:41:12", win.r - 108, win.y + 29, 14, p.muted, "mono")

    # active speaker: the synthetic participant (hero)
    main = Box(win.x + 18, win.y + 64, 700, 560)
    clip_main = doc.clip_rect(main.x, main.y, main.w, main.h, 10)
    with doc.g(clip=clip_main):
        _room(doc, main, "#3B3358", rng)
        # suit shoulders under the mesh head
        s = 300
        cx, cy = main.cx + 10, main.y + 250
        sy = cy + s * 0.55
        doc.path(f"M{f(cx - s * 1.15)} {f(main.b + 10)}C{f(cx - s * 1.1)} {f(sy + s * 0.3)} {f(cx - s * 0.6)} "
                 f"{f(sy + s * 0.08)} {f(cx)} {f(sy + s * 0.05)}C{f(cx + s * 0.6)} {f(sy + s * 0.08)} "
                 f"{f(cx + s * 1.1)} {f(sy + s * 0.3)} {f(cx + s * 1.15)} {f(main.b + 10)}Z", fill="#1E2233")
        doc.rect(cx - s * 0.14, cy + s * 0.4, s * 0.28, s * 0.3, "#B98E76", s * 0.08)
        doc.path(f"M{f(cx - s * 0.17)} {f(sy + s * 0.06)}L{f(cx)} {f(sy + s * 0.26)}L{f(cx + s * 0.17)} "
                 f"{f(sy + s * 0.06)}Z", fill="#D9DCE6")
        doc.path(f"M{f(cx - s * 0.035)} {f(sy + s * 0.15)}L{f(cx)} {f(sy + s * 0.3)}L{f(cx + s * 0.035)} "
                 f"{f(sy + s * 0.15)}Z", fill="#5B2A3A")
        pts = _synthetic(doc, cx, cy, s, rng, 0.52, "#D6A98C", p.danger, clip_main)
    doc.rect(main.x, main.y, main.w, main.h, "none", 10, stroke=p.danger, sw=3)
    # tracking brackets around the face
    fx0, fx1 = min(x for x, _ in pts) - 26, max(x for x, _ in pts) + 26
    fy0, fy1 = min(y for _, y in pts) - 26, max(y for _, y in pts) + 26
    for (bx, by, dx, dy) in ((fx0, fy0, 1, 1), (fx1, fy0, -1, 1), (fx0, fy1, 1, -1), (fx1, fy1, -1, -1)):
        doc.path(f"M{f(bx)} {f(by + dy * 26)}V{f(by)}H{f(bx + dx * 26)}", stroke="#FFFFFF", sw=2.5, opacity=0.8,
                 cap="square", join="miter")
    # name plate (placeholder) + speaking indicator
    doc.rect(main.x + 16, main.b - 50, 230, 34, "#000000", 6, opacity=0.55)
    for k, hgt in enumerate((8, 14, 10)):
        doc.rect(main.x + 30 + k * 7, main.b - 33 - hgt / 2, 4, hgt, "#5EE6A8", 2)
    doc.text("Investor (partner fund)", main.x + 60, main.b - 27, 16, "#FFFFFF", "ui")

    # the rest of the meeting: ordinary participants
    side = [Box(main.r + 14, main.y + i * 190, win.r - main.r - 32, 178) for i in range(3)]
    looks = [("#E0B394", "#3B2A20", "#3F5B7A", 0), ("#8D5E45", "#1C1410", "#7A4E5E", 2),
             ("#F0C8AE", "#A8763E", "#4F6B55", 1)]
    names = ("you", "Ops lead", "Finance")
    for i, (tile, (skin, hair, shirt, st)) in enumerate(zip(side, looks)):
        cl = doc.clip_rect(tile.x, tile.y, tile.w, tile.h, 8)
        with doc.g(clip=cl):
            _room(doc, tile, ("#2C3A4A", "#3A3328", "#2E3B33")[i], rng)
        _person(doc, tile.cx, tile.y + 30, 74, skin, hair, shirt, cl, st)
        doc.rect(tile.x, tile.y, tile.w, tile.h, "none", 8, stroke="#2E2650", sw=1.2)
        doc.rect(tile.x + 10, tile.b - 34, 14 + 9 * len(names[i]), 24, "#000000", 5, opacity=0.5)
        doc.text(names[i], tile.x + 18, tile.b - 17, 14, "#FFFFFF", "ui")

    # control bar
    by = win.b - 66
    for k, (ic, col) in enumerate((("phone", "#2A2442"), ("monitor", "#2A2442"), ("user", "#2A2442"))):
        doc.circle(win.x + 400 + k * 70, by + 28, 24, col)
        icon(doc, ic, win.x + 400 + k * 70, by + 28, 24, "#CFC8EA", 2)
    doc.rect(win.x + 600, by + 6, 104, 44, p.danger, 22)
    doc.text("Leave", win.x + 652, by + 34, 17, "#FFFFFF", "ui_bold", anchor="middle")

    # callout on the mesh
    lx, ly = main.x + 470, main.y + 150
    doc.line((lx, ly), (main.x + 560, main.y + 92), "#FFFFFF", 1.5, opacity=0.8)
    pill(doc, main.x + 470, main.y + 74, "synthetic face", fg="#FFFFFF", bg=p.danger, size=16, font="ui_bold")
    doc.circle(lx, ly, 5, "#FFFFFF")

    doc.focus = Box(main.x + 60, main.y + 40, 600, 338)

    # ---- the transfer being approved, beside the call
    tb = Box(1110, 230, 440, 380)
    doc.shadow(tb.x, tb.y, tb.w, tb.h, 14, 1.0)
    doc.rect(tb.x, tb.y, tb.w, tb.h, "#F6F3FF", 14)
    doc.text("Confirm transaction", tb.x + 32, tb.y + 56, 26, "#17122A", "display")
    doc.text("wallet signature request", tb.x + 32, tb.y + 86, 16, "#6E6690", "ui")
    rows = (("from", "treasury hot wallet"), ("to", "0x7d3a...c41e"), ("network", "mainnet"))
    for k, (a, b) in enumerate(rows):
        yy = tb.y + 132 + k * 44
        doc.line((tb.x + 32, yy + 16), (tb.r - 32, yy + 16), "#DDD6F2", 1)
        doc.text(a, tb.x + 32, yy, 16, "#6E6690", "ui")
        doc.text(b, tb.r - 32, yy, 17, "#17122A", "mono", anchor="end")
    # buttons, with the pointer about to approve
    doc.rect(tb.x + 32, tb.b - 92, 170, 54, "#FFFFFF", 10, stroke="#CFC6EA", sw=1.5)
    doc.text("Reject", tb.x + 117, tb.b - 58, 19, "#17122A", "ui_bold", anchor="middle")
    doc.rect(tb.r - 202, tb.b - 92, 170, 54, "#6D4CFF", 10)
    doc.text("Approve", tb.r - 117, tb.b - 58, 19, "#FFFFFF", "ui_bold", anchor="middle")
    px, py = tb.r - 92, tb.b - 54
    doc.path(f"M{f(px)} {f(py)}l0 34l9-8l7 15l7-3l-7-15l12-1z", fill="#FFFFFF", stroke="#17122A", sw=2)
    # the call drives the approval
    chip = pill(doc, tb.x, tb.y - 52, "asked for on the call", fg="#FFFFFF", bg="#2A2442", size=15, font="ui",
                pad=14, stroke="#4A3F78")
    _ = chip

    money = brief.facts.get("money")
    if money:
        plus = re.search(r"(more than|over|понад|більше)\s+\$?\s?" + re.escape(str(money).strip("$MB")[:3]), text)
        label = f"{money}+" if plus else str(money)
        doc.text(label, tb.x + 2, tb.b + 100, 76, "#FFFFFF", "display")
        stolen = re.search(r"\bstole|stolen|theft|викра", text)
        doc.text("in crypto stolen via faked calls" if stolen else "in crypto", tb.x + 6, tb.b + 136, 19, p.muted,
                 "ui")
