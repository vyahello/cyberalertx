"""Deepfake video calls: a real person and the synthetic copy that speaks for
them on a call.

What the sources state (s:31008e64145065 and alike): the FBI says North
Korean actors stole over $400 million in crypto through a social-engineering
scheme that used faked (deepfake) video calls. They do not describe the
victims, the meeting, the wallet or the transfer, so none of that is drawn:
no meeting title, no participant names, no wallet address, no approval
dialog. The money figure appears only from `brief.facts`, with "+" only when
the text says "over / more than".

Three compositions (ALTERNATIVES), none of them a drawn cartoon face:

* "a" duplicate: two strong profiles face each other across the edge of a
  call screen; the real one is lit flesh-and-shadow, the one inside the call
  is the same silhouette rebuilt as a sliced, displaced synthetic mesh.
* "b" mask: one call tile fills the frame; the participant is a person in
  shadow wearing a smooth porcelain mask whose edge lifts off to show the
  mesh underneath.
* "c" device: over the shoulder of a viewer (dark silhouette, lit by the
  screen) to a laptop on a call whose caller is visibly being synthesised.

"b" is the registered scene: at 176 px it is one white form on a dark call
tile (the strongest value contrast of the three), a mask reads as "someone
else's face" without any caption, the call controls say "video call", and
the money figure sits inside the feed crop. "a" is the close runner-up; its
sliced copy gets busy at feed size.
"""
from __future__ import annotations

import math
import random
import re
from typing import Callable

from ..brief import EditorialBrief
from ..kit import Box, Doc, f
from . import scene

Pt = tuple[float, float]


# ---------------------------------------------------------------- geometry

def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a[i] + (b[i] - a[i]) * max(0.0, min(1.0, t))):02X}" for i in range(3))


def _smooth(pts: list[Pt], closed: bool = True, k: float = 1 / 6) -> str:
    """Catmull-Rom spline through `pts` as cubic Beziers."""
    n = len(pts)
    d = f"M{f(pts[0][0])} {f(pts[0][1])}"
    last = n if closed else n - 1
    for i in range(last):
        p0 = pts[(i - 1) % n] if closed or i > 0 else pts[0]
        p1, p2 = pts[i], pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if closed or i + 2 < n else p2
        c1 = (p1[0] + (p2[0] - p0[0]) * k, p1[1] + (p2[1] - p0[1]) * k)
        c2 = (p2[0] - (p3[0] - p1[0]) * k, p2[1] - (p3[1] - p1[1]) * k)
        d += f"C{f(c1[0])} {f(c1[1])} {f(c2[0])} {f(c2[1])} {f(p2[0])} {f(p2[1])}"
    return d + ("Z" if closed else "")


# A head-and-shoulders profile facing right; unit = crown-to-chin height.
_PROFILE: list[Pt] = [
    (-0.10, 1.95), (-0.02, 1.42), (0.14, 1.16), (0.12, 0.98), (0.03, 0.80), (0.00, 0.55), (0.07, 0.27),
    (0.27, 0.06), (0.52, 0.00), (0.72, 0.08), (0.81, 0.22), (0.835, 0.36), (0.83, 0.43), (0.815, 0.465),
    (0.86, 0.545), (0.92, 0.615), (0.935, 0.645), (0.915, 0.672), (0.865, 0.685), (0.868, 0.72), (0.895, 0.75),
    (0.872, 0.775), (0.888, 0.805), (0.858, 0.845), (0.872, 0.905), (0.85, 0.965), (0.78, 0.995), (0.67, 1.01),
    (0.60, 1.06), (0.61, 1.20), (0.70, 1.34), (1.02, 1.47), (1.22, 1.62), (1.30, 1.95),
]
# The ear, the jaw line and the eye socket (shading only).
_EAR: list[Pt] = [(0.36, 0.44), (0.42, 0.40), (0.47, 0.45), (0.47, 0.56), (0.43, 0.64), (0.37, 0.65), (0.35, 0.56)]
_JAW: list[Pt] = [(0.36, 0.70), (0.42, 0.86), (0.55, 0.96), (0.70, 1.0)]


def _place(pts: list[Pt], x: float, y: float, s: float, flip: bool = False) -> list[Pt]:
    return [(x + (-px if flip else px) * s, y + py * s) for px, py in pts]


def _inside(pt: Pt, poly: list[Pt]) -> bool:
    x, y = pt
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            c = not c
        j = i
    return c


def _delaunay(pts: list[Pt]) -> list[tuple[int, int, int]]:
    """Bowyer-Watson triangulation (a few dozen points: cheap)."""
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


def _mesh(outline: list[Pt], rng: random.Random, n: int = 46) -> tuple[list[Pt], list[tuple[int, int, int]]]:
    """Landmark-like points: the outline plus jittered interior points."""
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    pts = list(outline)
    tries = 0
    while len(pts) < len(outline) + n and tries < 2000:
        tries += 1
        q = (rng.uniform(min(xs), max(xs)), rng.uniform(min(ys), max(ys)))
        if _inside(q, outline) and all((q[0] - a) ** 2 + (q[1] - b) ** 2 > 1600 for a, b in pts):
            pts.append(q)
    return pts, _delaunay(pts)


def _money(brief: EditorialBrief) -> str:
    money = brief.facts.get("money")
    if not money:
        return ""
    digits = re.sub(r"[^\d.]", "", str(money))
    over = re.search(r"(more than|over|понад|більше)\s+\$?\s?" + re.escape(digits[:3]), brief.text or "")
    return f"{money}+" if over else str(money)


def _figure_block(doc: Doc, brief: EditorialBrief, x: float, y: float, size: float, color: str,
                  sub_color: str, anchor: str = "start") -> None:
    """The stated amount and what it was (crypto), nothing else."""
    label = _money(brief)
    if not label:
        return
    doc.text(label, x, y, size, color, "display", anchor=anchor, tracking=-size * 0.02)
    crypto = re.search(r"crypto|bitcoin|ether|крипт", brief.text or "")
    doc.text("in crypto stolen" if crypto else "stolen", x + (4 if anchor == "start" else 0), y + size * 0.42,
             size * 0.26, sub_color, "ui_bold", anchor=anchor, tracking=size * 0.012)


def _call_controls(doc: Doc, cx: float, y: float, r: float, end: str) -> None:
    """Generic call controls: microphone, camera, hang up."""
    for k, (name, col) in enumerate((("mic", "#FFFFFF"), ("cam", "#FFFFFF"), ("end", end))):
        x = cx + (k - 1) * r * 2.7
        if name == "end":
            doc.circle(x, y, r, end)
            doc.path(f"M{f(x - r * 0.48)} {f(y + r * 0.1)}Q{f(x)} {f(y - r * 0.42)} {f(x + r * 0.48)} {f(y + r * 0.1)}",
                     stroke="#FFFFFF", sw=r * 0.2)
            continue
        doc.circle(x, y, r, "#FFFFFF", opacity=0.14)
        if name == "mic":
            doc.rect(x - r * 0.17, y - r * 0.5, r * 0.34, r * 0.62, col, r * 0.17)
            doc.path(f"M{f(x - r * 0.34)} {f(y - r * 0.02)}Q{f(x - r * 0.34)} {f(y + r * 0.36)} {f(x)} {f(y + r * 0.36)}"
                     f"Q{f(x + r * 0.34)} {f(y + r * 0.36)} {f(x + r * 0.34)} {f(y - r * 0.02)}M{f(x)} {f(y + r * 0.36)}"
                     f"V{f(y + r * 0.55)}", stroke=col, sw=r * 0.09)
        else:
            doc.rect(x - r * 0.5, y - r * 0.3, r * 0.68, r * 0.6, col, r * 0.1)
            doc.poly([(x + r * 0.22, y - r * 0.08), (x + r * 0.5, y - r * 0.28), (x + r * 0.5, y + r * 0.28),
                      (x + r * 0.22, y + r * 0.08)], col)


# ---------------------------------------------------------------- the two heads

def _real_head(doc: Doc, pts: list[Pt], body: str, rim: str, shift: tuple[float, float], s: float) -> None:
    """A dark silhouette with a rim of light along its leading edge."""
    d = _smooth(pts)
    clip = doc.clip_path(d)
    facing_right = pts[15][0] > pts[0][0]
    lit = doc.lin([(0, rim, 0.0), (0.55, rim, 0.7), (0.8, rim, 1.0)], 0 if facing_right else 1, 0,
                  1 if facing_right else 0, 0)
    with doc.g(clip=clip):
        doc.path(d, fill=lit)
        with doc.g(transform=f"translate({f(shift[0])} {f(shift[1])})"):
            doc.path(d, fill=body)
        # a broad soft fill light on the face plane
        fx = max(p[0] for p in pts[10:28]) if shift[0] < 0 else min(p[0] for p in pts[10:28])
        doc.add(f'<ellipse cx="{f(fx - shift[0] * 9)}" cy="{f(pts[14][1])}" rx="{f(s * 0.32)}" ry="{f(s * 0.5)}" '
                f'fill="{rim}" opacity="0.16" filter="{doc.blur(round(s * 0.08))}"/>')


def _synthetic_head(doc: Doc, pts: list[Pt], rng: random.Random, fill_a: str, fill_b: str, line: str,
                    bands: int, amp: float, top: float, bottom: float, bright: float = 1.0) -> None:
    """The same silhouette rebuilt as a synthetic mesh, cut into horizontal
    bands and displaced: the copy that is not quite holding together."""
    d = _smooth(pts)
    mesh_pts, tris = _mesh(pts, rng)
    wires = "".join(f"M{f(mesh_pts[a][0])} {f(mesh_pts[a][1])}L{f(mesh_pts[b][0])} {f(mesh_pts[b][1])}"
                    f"L{f(mesh_pts[c][0])} {f(mesh_pts[c][1])}Z" for a, b, c in tris)
    xs = [p[0] for p in pts]
    face_left = pts[15][0] < pts[0][0]
    grad = doc.lin([(0, fill_a, 1), (1, fill_b, 1)], 0 if face_left else 1, 0, 1 if face_left else 0, 1)
    h = (bottom - top) / bands
    for i in range(bands):
        y0 = top + i * h
        off = 0.0 if rng.random() < 0.45 else rng.uniform(-amp, amp)
        if i in (bands // 3, bands // 3 + 1):
            off = amp * 1.25 * (1 if i % 2 else -1)
        with doc.g(clip=doc.clip_rect(min(xs) - amp * 2, y0, max(xs) - min(xs) + amp * 4, h + 0.5)):
            with doc.g(transform=f"translate({f(off)} 0)"):
                doc.path(d, fill=grad, opacity=0.92 * bright)
                with doc.g(clip=doc.clip_path(d)):
                    doc.path(wires, stroke=line, sw=1.3, opacity=0.75)
                    for k, (x, y) in enumerate(mesh_pts):
                        if y0 - 4 < y < y0 + h + 4 and k % 2 == 0:
                            doc.circle(x, y, 2.6, "#FFFFFF", opacity=0.8)
                doc.path(d, stroke=line, sw=2.5, opacity=0.9)
    # scan lines across the copy
    sl = "".join(f"M{f(min(xs) - 40)} {f(top + k * 7)}H{f(max(xs) + 40)}" for k in range(int((bottom - top) / 7)))
    with doc.g(clip=doc.clip_path(d)):
        doc.path(sl, stroke="#000000", sw=2, opacity=0.18)


# ---------------------------------------------------------------- A: duplicate

def _comp_duplicate(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    doc.rect(0, 0, 1600, 900, doc.lin([(0, "#1A1230", 1), (1, "#07050E", 1)], 0, 0, 0.4, 1))
    # the call screen: right two thirds, a cool synthetic light
    scr = Box(742, 70, 820, 760)
    doc.shadow(scr.x, scr.y, scr.w, scr.h, 26, 1.4)
    doc.rect(scr.x - 14, scr.y - 14, scr.w + 28, scr.h + 28, "#04030A", 36, stroke="#2B2246", sw=2)
    doc.rect(scr.x, scr.y, scr.w, scr.h, doc.lin([(0, "#2A1D52", 1), (1, "#120C26", 1)], 0, 0, 0.6, 1), 24)
    with doc.g(clip=doc.clip_rect(scr.x, scr.y, scr.w, scr.h, 24)):
        doc.add(f'<ellipse cx="{f(scr.x + scr.w * 0.62)}" cy="{f(scr.y + scr.h * 0.42)}" rx="420" ry="380" '
                f'fill="{p.accent}" opacity="0.20" filter="{doc.blur(90)}"/>')
        # a soft out-of-focus room behind the caller
        for i in range(5):
            bx = scr.x + 420 + i * 92 + rng.uniform(-20, 20)
            doc.rect(bx, scr.y + 90 + rng.uniform(0, 60), 58, rng.uniform(180, 330), "#FFFFFF", 6, opacity=0.04)
        s = 520
        copy = _place(_PROFILE, scr.x + 590, 190, s, flip=True)
        _synthetic_head(doc, copy, rng, "#D9C2FF", "#4A2386", p.danger, 22, 24, 190, 900)
        # call chrome: only what any call has
        doc.rect(scr.x, scr.b - 120, scr.w, 120, doc.lin([(0, "#000", 0), (1, "#000", 0.65)]))
        _call_controls(doc, scr.x + scr.w * 0.62, scr.b - 62, 30, p.danger)
        doc.circle(scr.x + 46, scr.y + 46, 9, p.danger)
        doc.rect(scr.x + 66, scr.y + 38, 92, 16, "#FFFFFF", 8, opacity=0.35)
    doc.rect(scr.x, scr.y, scr.w, scr.h, "none", 24, stroke=p.danger, sw=3, opacity=0.9)
    # the real person: in front of the screen, warm key light from the right
    s = 600
    real = _place(_PROFILE, 150, 110, s)
    doc.add(f'<ellipse cx="560" cy="460" rx="320" ry="420" fill="#FFB38A" opacity="0.07" filter="{doc.blur(80)}"/>')
    _real_head(doc, real, "#0C0913", "#F2B48E", (-8, 1), s)
    # the gap between them: where the identity is copied
    doc.path("M716 120V800", stroke=p.danger, sw=2, dash="4 10", opacity=0.5)
    _figure_block(doc, brief, 64, 720, 132, "#FFFFFF", "#D8CCF5")
    doc.focus = Box(30, 40, 1540, 866)


# ---------------------------------------------------------------- B: mask

def _mask_outline(cx: float, cy: float, s: float) -> list[Pt]:
    """A smooth porcelain face mask (front view), s = height."""
    w = s * 0.74
    pts: list[Pt] = []
    for k in range(40):
        a = -math.pi / 2 + k * 2 * math.pi / 40
        y = math.sin(a)
        taper = 1 - 0.28 * max(y, 0) ** 1.6
        x = math.cos(a) * taper * (1 + 0.04 * (1 - abs(y)))
        pts.append((cx + x * w / 2, cy + y * s / 2))
    return pts


def _mask(doc: Doc, cx: float, cy: float, s: float, rng: random.Random, accent: str, danger: str,
          lift: float = 0.0) -> None:
    out = _mask_outline(cx, cy, s)
    d = _smooth(out)
    w = s * 0.74
    # porcelain: lit from the upper left
    doc.add(f'<path d="{d}" fill="#000" opacity="0.45" transform="translate(14 22)" filter="{doc.blur(14)}"/>')
    porcelain = doc.rad([(0, "#FFFFFF", 1), (0.55, "#E6E0F2", 1), (1, "#A99FC4", 1)], 0.38, 0.32, 0.8)
    doc.path(d, fill=porcelain)
    with doc.g(clip=doc.clip_path(d)):
        # the sculpted planes: brow, cheek hollows, nose ridge, chin
        doc.add(f'<ellipse cx="{f(cx + w * 0.3)}" cy="{f(cy + s * 0.12)}" rx="{f(w * 0.28)}" ry="{f(s * 0.32)}" '
                f'fill="#4A3C78" opacity="0.30" filter="{doc.blur(round(s * 0.05))}"/>')
        doc.add(f'<ellipse cx="{f(cx - w * 0.3)}" cy="{f(cy + s * 0.16)}" rx="{f(w * 0.16)}" ry="{f(s * 0.2)}" '
                f'fill="#4A3C78" opacity="0.14" filter="{doc.blur(round(s * 0.05))}"/>')
        doc.path(f"M{f(cx - w * 0.04)} {f(cy - s * 0.12)}C{f(cx - w * 0.05)} {f(cy + s * 0.02)} {f(cx - w * 0.1)} "
                 f"{f(cy + s * 0.12)} {f(cx - w * 0.08)} {f(cy + s * 0.16)}L{f(cx + w * 0.06)} {f(cy + s * 0.17)}"
                 f"C{f(cx + w * 0.07)} {f(cy + s * 0.08)} {f(cx + w * 0.05)} {f(cy)} {f(cx + w * 0.05)} "
                 f"{f(cy - s * 0.12)}Z", fill="#3A2E62", opacity=0.22, extra=f' filter="{doc.blur(6)}"')
        doc.add(f'<ellipse cx="{f(cx - w * 0.05)}" cy="{f(cy + s * 0.02)}" rx="{f(w * 0.035)}" '
                f'ry="{f(s * 0.12)}" fill="#FFFFFF" opacity="0.7" filter="{doc.blur(round(s * 0.012))}"/>')
        # brow ridge highlight
        for sx in (-1, 1):
            doc.path(f"M{f(cx + sx * w * 0.08)} {f(cy - s * 0.16)}Q{f(cx + sx * w * 0.24)} {f(cy - s * 0.22)} "
                     f"{f(cx + sx * w * 0.38)} {f(cy - s * 0.15)}", stroke="#FFFFFF", sw=s * 0.018, opacity=0.6,
                     extra=f' filter="{doc.blur(4)}"')
    # eye openings: almond cut-outs into darkness
    for sx in (-1, 1):
        ex, ey = cx + sx * w * 0.22, cy - s * 0.075
        ew, eh = w * 0.15, s * 0.036
        doc.path(f"M{f(ex - ew)} {f(ey)}Q{f(ex)} {f(ey - eh * 1.9)} {f(ex + ew)} {f(ey + eh * 0.15 * sx)}"
                 f"Q{f(ex)} {f(ey + eh * 1.5)} {f(ex - ew)} {f(ey)}Z", fill="#07050D")
        doc.path(f"M{f(ex - ew)} {f(ey)}Q{f(ex)} {f(ey - eh * 1.9)} {f(ex + ew)} {f(ey + eh * 0.15 * sx)}",
                 stroke="#6B5C93", sw=2, opacity=0.6)
    # closed lips, sculpted rather than drawn
    my = cy + s * 0.27
    doc.path(f"M{f(cx - w * 0.15)} {f(my)}Q{f(cx - w * 0.05)} {f(my - s * 0.03)} {f(cx)} {f(my - s * 0.012)}"
             f"Q{f(cx + w * 0.05)} {f(my - s * 0.03)} {f(cx + w * 0.15)} {f(my)}Q{f(cx)} {f(my + s * 0.05)} "
             f"{f(cx - w * 0.15)} {f(my)}Z", fill="#7A6AA6", opacity=0.35, extra=f' filter="{doc.blur(3)}"')
    doc.path(f"M{f(cx - w * 0.13)} {f(my)}Q{f(cx)} {f(my + s * 0.01)} {f(cx + w * 0.13)} {f(my)}",
             stroke="#4A3C78", sw=2, opacity=0.6)
    doc.path(d, stroke="#FFFFFF", sw=2, opacity=0.5)
    if lift:
        # the right edge lifts: the mesh under it shows
        rim = [q for q in out if q[0] > cx + w * 0.18]
        doc.path(_smooth(rim, closed=False), stroke=danger, sw=3)


def _comp_mask(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    doc.rect(0, 0, 1600, 900, "#07050E")
    tile = Box(40, 40, 1520, 820)
    doc.rect(tile.x, tile.y, tile.w, tile.h, doc.lin([(0, "#2B1E50", 1), (1, "#0E0A1C", 1)], 0, 0, 0.8, 1), 28)
    with doc.g(clip=doc.clip_rect(tile.x, tile.y, tile.w, tile.h, 28)):
        doc.add(f'<ellipse cx="900" cy="380" rx="520" ry="420" fill="{p.accent}" opacity="0.16" '
                f'filter="{doc.blur(100)}"/>')
        for i in range(4):
            doc.rect(1090 + i * 110, 120 + rng.uniform(0, 50), 70, rng.uniform(220, 360), "#FFFFFF", 6, opacity=0.035)
        # the person behind the mask: shoulders and head in shadow
        cx, cy, s = 900, 400, 470
        doc.path(f"M{f(cx - 430)} 900C{f(cx - 420)} 700 {f(cx - 260)} 640 {f(cx - 90)} 620L{f(cx - 70)} 560"
                 f"H{f(cx + 70)}L{f(cx + 90)} 620C{f(cx + 260)} 640 {f(cx + 420)} 700 {f(cx + 430)} 900Z",
                 fill="#06040C")
        head = _mask_outline(cx + 6, cy - 10, s * 1.1)
        doc.path(_smooth(head), fill="#06040C")
        # mesh peeking out where the mask lifts away (right side)
        mesh_pts, tris = _mesh(_mask_outline(cx + 6, cy - 10, s * 1.04), rng, 30)
        wires = "".join(f"M{f(mesh_pts[a][0])} {f(mesh_pts[a][1])}L{f(mesh_pts[b][0])} {f(mesh_pts[b][1])}"
                        f"L{f(mesh_pts[c][0])} {f(mesh_pts[c][1])}Z" for a, b, c in tris)
        with doc.g(clip=doc.clip_rect(cx + 60, 0, 600, 900)):
            doc.path(wires, stroke=p.danger, sw=1.6, opacity=0.9)
        with doc.g(transform=f"rotate(-7 {f(cx - 120)} {f(cy)}) translate(-34 4)"):
            _mask(doc, cx, cy, s, rng, p.accent, p.danger, lift=1.0)
        # call chrome
        doc.rect(tile.x, tile.b - 150, tile.w, 150, doc.lin([(0, "#000", 0), (1, "#000", 0.7)]))
        _call_controls(doc, cx, tile.b - 74, 34, p.danger)
        doc.rect(tile.x + 34, tile.b - 92, 250, 44, "#000000", 10, opacity=0.5)
        doc.rect(tile.x + 56, tile.b - 76, 150, 12, "#FFFFFF", 6, opacity=0.5)
        # self view: an ordinary person, small, in the corner
        sv = Box(tile.r - 300, tile.y + 30, 260, 160)
        doc.rect(sv.x, sv.y, sv.w, sv.h, "#2C3A4A", 14, stroke="#FFFFFF", sw=1.5, opacity=0.95)
        with doc.g(clip=doc.clip_rect(sv.x, sv.y, sv.w, sv.h, 14)):
            me = _place(_PROFILE, sv.x + 70, sv.y + 34, 104)
            _real_head(doc, me, "#121822", "#E9B48F", (-4, 1), 104)
    _figure_block(doc, brief, 110, 200, 124, "#FFFFFF", "#D8CCF5")
    doc.focus = Box(90, 100, 1300, 731)


# ---------------------------------------------------------------- C: device

def _comp_device(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    doc.rect(0, 0, 1600, 900, doc.lin([(0, "#140E24", 1), (1, "#050309", 1)], 0, 0, 0.3, 1))
    # the laptop, three-quarter front, screen glowing
    lx, ly, lw, lh = 600, 90, 860, 540
    doc.add(f'<ellipse cx="{f(lx + lw / 2)}" cy="{f(ly + lh / 2)}" rx="640" ry="420" fill="{p.accent}" '
            f'opacity="0.14" filter="{doc.blur(90)}"/>')
    doc.rect(lx - 18, ly - 18, lw + 36, lh + 36, "#16141C", 26, stroke="#3A3550", sw=2)
    scr = Box(lx, ly, lw, lh)
    doc.rect(scr.x, scr.y, scr.w, scr.h, doc.lin([(0, "#2C2050", 1), (1, "#120C26", 1)], 0, 0, 0.6, 1), 8)
    with doc.g(clip=doc.clip_rect(scr.x, scr.y, scr.w, scr.h, 8)):
        for i in range(4):
            doc.rect(scr.x + 520 + i * 90, scr.y + 60 + rng.uniform(0, 40), 56, rng.uniform(180, 300), "#FFFFFF", 6,
                     opacity=0.04)
        s = 400
        caller = _place(_PROFILE, scr.x + 560, scr.y + 70, s, flip=True)
        _synthetic_head(doc, caller, rng, "#C9A6FF", "#5B2D9E", p.danger, 24, 20, scr.y + 70, scr.b)
        doc.rect(scr.x, scr.b - 90, scr.w, 90, doc.lin([(0, "#000", 0), (1, "#000", 0.6)]))
        _call_controls(doc, scr.cx, scr.b - 46, 22, p.danger)
    by = ly + lh + 18
    doc.path(f"M{f(lx - 18)} {f(by)}H{f(lx + lw + 18)}L{f(lx + lw + 150)} {f(by + 120)}H{f(lx - 150)}Z",
             fill=doc.lin([(0, "#2A2638", 1), (1, "#14121C", 1)]))
    doc.path(f"M{f(lx - 150)} {f(by + 120)}H{f(lx + lw + 150)}V{f(by + 134)}H{f(lx - 150)}Z", fill="#0A0910")
    for r in range(4):
        t0, t1 = 0.12 + r * 0.17, 0.12 + r * 0.17 + 0.13
        y0, y1 = by + 120 * t0, by + 120 * t1
        doc.path(f"M{f(lx + 40 - 130 * t0)} {f(y0)}H{f(lx + lw - 40 + 130 * t0)}L{f(lx + lw - 40 + 130 * t1)} "
                 f"{f(y1)}H{f(lx + 40 - 130 * t1)}Z", fill="#0E0C15", opacity=0.8)
    doc.add(f'<ellipse cx="{f(lx + lw / 2)}" cy="{f(by + 8)}" rx="{f(lw * 0.5)}" ry="30" fill="{p.accent}" '
            f'opacity="0.18" filter="{doc.blur(20)}"/>')
    # the viewer: close to camera, in profile, lit only by the call
    s = 700
    viewer = _place(_PROFILE, -250, 150, s)
    _real_head(doc, viewer, "#050309", "#B69CFF", (-9, 1), s)
    _figure_block(doc, brief, 1460, 840, 92, "#FFFFFF", "#D8CCF5", anchor="end")
    doc.focus = Box(100, 60, 1440, 810)


ALTERNATIVES: dict[str, Callable[[Doc, EditorialBrief, random.Random], None]] = {
    "a": _comp_duplicate, "b": _comp_mask, "c": _comp_device}


@scene("deepfake_call")
def deepfake_call(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    _comp_mask(doc, brief, rng)


