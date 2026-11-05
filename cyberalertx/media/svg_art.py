"""Article-specific editorial illustrations rendered as SVG, on the server.

No model, no network, no GPU: a deterministic composition system draws one
1600x900 image per story from its visual brief (media/illustrations.py):

  * the technology SCENE comes from verified fields — affected platforms,
    audience, and technology words in the source title (cloud, industrial
    control, AI services) — drawn as isometric infrastructure, never as a
    brand or logo;
  * the EVENT overlay comes from the category and the evidence labels, and
    follows them: an attack path is drawn only when exploitation is
    confirmed, records leave an archive only when exposure is confirmed,
    otherwise the image shows exposure or inspection;
  * a stable seed (story key + brief) varies layout, counts and angles, so
    two stories of the same kind do not get the same picture, and the same
    story always gets the same one.

Output uses only plain SVG shapes, gradients and a blur filter: no text,
scripts, foreignObject, images or external references (see `sanitize_svg`).
These are programmatic illustrations, labelled `generation_method="svg"`; they
are never presented as model-generated imagery.
"""
from __future__ import annotations

import hashlib
import math
import random
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable

W, H = 1600, 900
RENDERER_VERSION = "cax-svg-1"

CYAN = "#06B6D4"
CYAN_DIM = "#0E7490"
CYAN_SOFT = "#67E8F9"
INK = "#E6EDF3"
FACE_TOP, FACE_LEFT, FACE_RIGHT = "#3A4350", "#29303A", "#1C222A"
EDGE = "#4A5566"
MUTED = "#4B5563"


# ---------------------------------------------------------------- drawing kit

def _f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _pts(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{_f(x)},{_f(y)}" for x, y in points)


@dataclass
class Canvas:
    rng: random.Random
    parts: list[str] = field(default_factory=list)
    scale: float = 46.0
    ox: float = 800.0
    oy: float = 520.0

    def add(self, s: str) -> None:
        self.parts.append(s)

    # isometric projection: x to the right-down, y to the left-down, z up
    def iso(self, x: float, y: float, z: float = 0.0) -> tuple[float, float]:
        c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
        return (self.ox + (x - y) * c * self.scale, self.oy + (x + y) * s * self.scale - z * self.scale)

    def box(self, x: float, y: float, z: float, w: float, d: float, h: float, *,
            top: str = FACE_TOP, left: str = FACE_LEFT, right: str = FACE_RIGHT,
            edge: str = EDGE, opacity: float = 1.0) -> dict[str, list[tuple[float, float]]]:
        p = self.iso
        t = [p(x, y, z + h), p(x + w, y, z + h), p(x + w, y + d, z + h), p(x, y + d, z + h)]
        lf = [p(x, y + d, z), p(x + w, y + d, z), p(x + w, y + d, z + h), p(x, y + d, z + h)]
        rt = [p(x + w, y, z), p(x + w, y + d, z), p(x + w, y + d, z + h), p(x + w, y, z + h)]
        op = f' opacity="{_f(opacity)}"' if opacity < 1 else ""
        self.add(f'<g{op}><polygon points="{_pts(lf)}" fill="{left}" stroke="{edge}" stroke-width="1"/>'
                 f'<polygon points="{_pts(rt)}" fill="{right}" stroke="{edge}" stroke-width="1"/>'
                 f'<polygon points="{_pts(t)}" fill="{top}" stroke="{edge}" stroke-width="1"/></g>')
        return {"top": t, "left": lf, "right": rt}

    def line(self, a: tuple[float, float], b: tuple[float, float], color: str = EDGE, width: float = 1.5,
             opacity: float = 1.0, dash: str = "") -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<line x1="{_f(a[0])}" y1="{_f(a[1])}" x2="{_f(b[0])}" y2="{_f(b[1])}" stroke="{color}" '
                 f'stroke-width="{_f(width)}" opacity="{_f(opacity)}" stroke-linecap="round"{d}/>')

    def dot(self, c: tuple[float, float], r: float, color: str = CYAN, opacity: float = 1.0) -> None:
        self.add(f'<circle cx="{_f(c[0])}" cy="{_f(c[1])}" r="{_f(r)}" fill="{color}" opacity="{_f(opacity)}"/>')

    def glow(self, c: tuple[float, float], r: float, opacity: float = 0.35, color: str = CYAN) -> None:
        self.add(f'<circle cx="{_f(c[0])}" cy="{_f(c[1])}" r="{_f(r)}" fill="{color}" opacity="{_f(opacity)}" '
                 f'filter="url(#blur)"/>')

    def ring(self, c: tuple[float, float], r: float, color: str = CYAN, width: float = 2.0, opacity: float = 1.0,
             dash: str = "") -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<circle cx="{_f(c[0])}" cy="{_f(c[1])}" r="{_f(r)}" fill="none" stroke="{color}" '
                 f'stroke-width="{_f(width)}" opacity="{_f(opacity)}"{d}/>')

    def arc(self, c: tuple[float, float], r: float, a0: float, a1: float, color: str = CYAN, width: float = 2.0,
            opacity: float = 1.0) -> None:
        x0, y0 = c[0] + r * math.cos(math.radians(a0)), c[1] + r * math.sin(math.radians(a0))
        x1, y1 = c[0] + r * math.cos(math.radians(a1)), c[1] + r * math.sin(math.radians(a1))
        large = 1 if (a1 - a0) % 360 > 180 else 0
        self.add(f'<path d="M{_f(x0)} {_f(y0)} A{_f(r)} {_f(r)} 0 {large} 1 {_f(x1)} {_f(y1)}" fill="none" '
                 f'stroke="{color}" stroke-width="{_f(width)}" opacity="{_f(opacity)}" stroke-linecap="round"/>')

    def curve(self, a: tuple[float, float], ctrl: tuple[float, float], b: tuple[float, float], color: str = CYAN,
              width: float = 3.0, opacity: float = 1.0, dash: str = "") -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<path d="M{_f(a[0])} {_f(a[1])} Q{_f(ctrl[0])} {_f(ctrl[1])} {_f(b[0])} {_f(b[1])}" '
                 f'fill="none" stroke="{color}" stroke-width="{_f(width)}" opacity="{_f(opacity)}" '
                 f'stroke-linecap="round"{d}/>')


def _qpoint(a: tuple[float, float], c: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return ((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * c[0] + t ** 2 * b[0],
            (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * c[1] + t ** 2 * b[1])


# ---------------------------------------------------------------- scenes
# Each scene draws one technology around the isometric origin and returns the
# screen point that is the story's focal component.

def _rack(cv: Canvas, x: float, y: float, h: float = 4.2, highlight: bool = False) -> tuple[float, float]:
    f = cv.box(x, y, 0, 1.3, 1.1, h)
    lf = f["left"]
    n = int(h * 3)
    for i in range(1, n):
        t = i / n
        a = (lf[0][0] + (lf[3][0] - lf[0][0]) * t, lf[0][1] + (lf[3][1] - lf[0][1]) * t)
        b = (lf[1][0] + (lf[2][0] - lf[1][0]) * t, lf[1][1] + (lf[2][1] - lf[1][1]) * t)
        cv.line(a, b, "#2E3744", 1.2)
        if cv.rng.random() < 0.35:
            led = (a[0] + (b[0] - a[0]) * 0.85, a[1] + (b[1] - a[1]) * 0.85 - 4)
            cv.dot(led, 2.2, CYAN if (highlight and cv.rng.random() < 0.5) else "#5B6675", 0.9)
    top = f["top"]
    return ((top[0][0] + top[2][0]) / 2, (top[0][1] + top[2][1]) / 2)


def scene_server_room(cv: Canvas) -> tuple[float, float]:
    n = cv.rng.randint(3, 4)
    focal_i = cv.rng.randrange(n)
    focal = (0.0, 0.0)
    for i in range(n):
        p = _rack(cv, -3.0 + i * 1.9, -1.0, h=cv.rng.uniform(3.6, 4.6), highlight=i == focal_i)
        if i == focal_i:
            focal = p
    return focal


def scene_rack(cv: Canvas) -> tuple[float, float]:
    focal = (0.0, 0.0)
    for i, x in enumerate((-2.2, -0.4)):
        p = _rack(cv, x, -0.6 + i * 0.3, h=4.4 - i * 0.6, highlight=i == 0)
        if i == 0:
            focal = p
    return focal


def scene_network_edge(cv: Canvas) -> tuple[float, float]:
    focal = (0.0, 0.0)
    layers = cv.rng.randint(2, 3)
    for i in range(layers):
        f = cv.box(-2.0, -1.0, i * 0.75, 3.6, 2.0, 0.5, top="#303845" if i == layers - 1 else FACE_TOP)
        right = f["right"]
        for k in range(7):
            t = (k + 1) / 8
            pt = (right[0][0] + (right[1][0] - right[0][0]) * t, right[0][1] + (right[1][1] - right[0][1]) * t - 9)
            cv.dot(pt, 2.6, CYAN if (i == layers - 1 and k in (2, 5)) else "#566173", 0.95)
        focal = ((f["top"][0][0] + f["top"][2][0]) / 2, (f["top"][0][1] + f["top"][2][1]) / 2)
    edge_a, edge_b = cv.iso(2.6, -1.0, 0.4), cv.iso(5.5, -1.0, 0.4)
    cv.line(edge_a, edge_b, CYAN_DIM, 2, 0.6, "6 10")
    return focal


def scene_workstation(cv: Canvas) -> tuple[float, float]:
    cv.box(-1.4, 0.2, 0, 2.8, 1.4, 0.15)
    cv.box(-0.15, 0.6, 0.15, 0.3, 0.3, 1.0)
    s = cv.box(-1.6, 0.55, 1.1, 3.2, 0.12, 2.0, top=FACE_TOP, left="#202833")
    lf = s["left"]
    cx = (lf[0][0] + lf[2][0]) / 2
    cy = (lf[0][1] + lf[2][1]) / 2
    cv.add(f'<polygon points="{_pts(lf)}" fill="url(#screen)" opacity=".85"/>')
    return (cx, cy)


def scene_phone(cv: Canvas) -> tuple[float, float]:
    f = cv.box(-0.6, 0.0, 0, 1.6, 0.18, 3.0, left="#1F2630")
    lf = f["left"]
    inset = [(lf[0][0] + 7, lf[0][1] - 9), (lf[1][0] - 7, lf[1][1] - 6), (lf[2][0] - 7, lf[2][1] + 12),
             (lf[3][0] + 7, lf[3][1] + 9)]
    cv.add(f'<polygon points="{_pts(inset)}" fill="url(#screen)" opacity=".9"/>')
    return ((lf[0][0] + lf[2][0]) / 2, (lf[0][1] + lf[2][1]) / 2)


def scene_web(cv: Canvas) -> tuple[float, float]:
    _rack(cv, -3.4, -0.4, h=3.2)
    return _browser_frame(cv, (cv.ox + 70, cv.oy - 150), 420, 260)


def _browser_frame(cv: Canvas, center: tuple[float, float], w: float, h: float) -> tuple[float, float]:
    x, y = center[0] - w / 2, center[1] - h / 2
    cv.add(f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" rx="14" fill="#161B22" '
           f'stroke="{EDGE}" stroke-width="1.5"/>')
    cv.add(f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="34" rx="14" fill="#1F2630"/>')
    for i in range(3):
        cv.dot((x + 22 + i * 18, y + 17), 4.5, "#3B4553")
    cv.add(f'<rect x="{_f(x + 18)}" y="{_f(y + 52)}" width="{_f(w - 36)}" height="{_f(h - 70)}" rx="8" '
           f'fill="url(#screen)" opacity=".55"/>')
    return (center[0], center[1] + 15)


def scene_browser(cv: Canvas) -> tuple[float, float]:
    return _browser_frame(cv, (cv.ox, cv.oy - 120), 520, 320)


def scene_mail(cv: Canvas) -> tuple[float, float]:
    focal = (0.0, 0.0)
    for i in range(cv.rng.randint(3, 4)):
        f = cv.box(-1.8 + i * 0.25, -0.6 - i * 0.2, i * 0.55, 3.0, 2.0, 0.22,
                   top="#323A47" if i else FACE_TOP)
        focal = ((f["top"][0][0] + f["top"][2][0]) / 2, (f["top"][0][1] + f["top"][2][1]) / 2)
        t = f["top"]
        cv.line(t[0], ((t[0][0] + t[2][0]) / 2, (t[0][1] + t[2][1]) / 2), "#4A5566", 1.2)
        cv.line(t[1], ((t[0][0] + t[2][0]) / 2, (t[0][1] + t[2][1]) / 2), "#4A5566", 1.2)
    return focal


def scene_vm(cv: Canvas) -> tuple[float, float]:
    f = cv.box(-2.4, -1.6, 0, 4.8, 3.2, 1.2)
    focal = (0.0, 0.0)
    cells = [(i, j) for i in range(3) for j in range(2)]
    hot = cv.rng.choice(cells)
    for i, j in cells:
        b = cv.box(-2.1 + i * 1.5, -1.3 + j * 1.5, 1.2, 1.1, 1.1, cv.rng.uniform(0.6, 1.1),
                   top="#33404E" if (i, j) == hot else FACE_TOP)
        if (i, j) == hot:
            focal = ((b["top"][0][0] + b["top"][2][0]) / 2, (b["top"][0][1] + b["top"][2][1]) / 2)
    del f
    return focal


def scene_containers(cv: Canvas) -> tuple[float, float]:
    focal = (0.0, 0.0)
    n = cv.rng.randint(7, 10)
    spots = [(i % 4, i // 4) for i in range(n)]
    hot = cv.rng.randrange(n)
    for k, (i, j) in enumerate(spots):
        b = cv.box(-3.0 + i * 1.6, -2.0 + j * 1.6, 0, 1.0, 1.0, cv.rng.uniform(0.6, 1.3),
                   top="#33404E" if k == hot else FACE_TOP)
        if k == hot:
            focal = ((b["top"][0][0] + b["top"][2][0]) / 2, (b["top"][0][1] + b["top"][2][1]) / 2)
    for k in range(n - 1):
        a = cv.iso(-2.5 + spots[k][0] * 1.6, -1.5 + spots[k][1] * 1.6, 0)
        b2 = cv.iso(-2.5 + spots[k + 1][0] * 1.6, -1.5 + spots[k + 1][1] * 1.6, 0)
        cv.line(a, b2, "#2C3542", 1.2, 0.8)
    return focal


def scene_payments(cv: Canvas) -> tuple[float, float]:
    f = cv.box(-2.0, -0.8, 0.0, 3.4, 2.2, 0.12, top="#303A47")
    t = f["top"]
    cv.line(((t[0][0] * 3 + t[3][0]) / 4, (t[0][1] * 3 + t[3][1]) / 4),
            ((t[1][0] * 3 + t[2][0]) / 4, (t[1][1] * 3 + t[2][1]) / 4), "#455061", 6)
    for i in range(cv.rng.randint(3, 5)):
        c = cv.iso(2.2, 0.4, 0.15 + i * 0.22)
        cv.add(f'<ellipse cx="{_f(c[0])}" cy="{_f(c[1])}" rx="46" ry="23" fill="{FACE_TOP}" stroke="{EDGE}"/>')
    return ((t[0][0] + t[2][0]) / 2, (t[0][1] + t[2][1]) / 2)


def scene_wallet(cv: Canvas) -> tuple[float, float]:
    cv.box(-1.6, -0.9, 0, 2.6, 1.8, 0.9, top="#2F3743")
    c = cv.iso(1.8, 0.2, 1.2)
    hexa = [(c[0] + 60 * math.cos(math.radians(a)), c[1] + 60 * math.sin(math.radians(a))) for a in range(30, 390, 60)]
    cv.add(f'<polygon points="{_pts(hexa)}" fill="{FACE_TOP}" stroke="{EDGE}" stroke-width="1.5"/>')
    cv.ring(c, 28, "#5B6675", 2)
    k0 = cv.iso(-0.3, 0.0, 1.0)
    cv.ring((k0[0], k0[1] - 30), 26, INK, 3, 0.8)
    cv.line((k0[0] + 22, k0[1] - 18), (k0[0] + 110, k0[1] + 30), INK, 3, 0.8)
    return (k0[0], k0[1] - 30)


def scene_pipeline(cv: Canvas) -> tuple[float, float]:
    cv.box(-4.0, 0.0, 0, 8.0, 1.0, 0.25, top="#2A313B")
    focal = (0.0, 0.0)
    n = cv.rng.randint(4, 6)
    hot = cv.rng.randrange(1, n)
    for i in range(n):
        b = cv.box(-3.7 + i * 1.45, 0.15, 0.25, 0.75, 0.7, 0.7, top="#35414F" if i == hot else FACE_TOP)
        if i == hot:
            focal = ((b["top"][0][0] + b["top"][2][0]) / 2, (b["top"][0][1] + b["top"][2][1]) / 2)
    return focal


def scene_corporate(cv: Canvas) -> tuple[float, float]:
    core = cv.box(-0.8, -0.8, 0, 1.6, 1.6, 2.4, top="#303A46")
    focal = ((core["top"][0][0] + core["top"][2][0]) / 2, (core["top"][0][1] + core["top"][2][1]) / 2)
    for ang in sorted(cv.rng.sample(range(0, 360, 30), 5)):
        r = cv.rng.uniform(4.0, 5.2)
        x, y = r * math.cos(math.radians(ang)), r * math.sin(math.radians(ang))
        b = cv.box(x - 0.5, y - 0.5, 0, 1.0, 1.0, cv.rng.uniform(0.8, 1.8))
        cv.line(cv.iso(x, y, 0), cv.iso(0, 0, 0), "#2F3946", 1.4, 0.9)
        del b
    return focal


def scene_home(cv: Canvas) -> tuple[float, float]:
    cv.box(-2.4, -0.4, 0, 2.6, 1.8, 0.12)
    s = cv.box(-2.4, -0.45, 0.12, 2.6, 0.08, 1.6, left="#202833")
    cv.add(f'<polygon points="{_pts(s["left"])}" fill="url(#screen)" opacity=".7"/>')
    p = cv.box(1.4, 0.4, 0, 0.9, 0.12, 1.7, left="#1F2630")
    return ((p["left"][0][0] + p["left"][2][0]) / 2, (p["left"][0][1] + p["left"][2][1]) / 2)


def scene_cloud(cv: Canvas) -> tuple[float, float]:
    focal = (0.0, 0.0)
    for i in range(3):
        f = cv.box(-2.6 + i * 0.3, -1.8 + i * 0.3, i * 0.9, 5.2 - i * 0.6, 3.6 - i * 0.6, 0.18,
                   top="#2E3743", opacity=0.92 - i * 0.12)
        focal = ((f["top"][0][0] + f["top"][2][0]) / 2, (f["top"][0][1] + f["top"][2][1]) / 2)
    for k in range(cv.rng.randint(4, 6)):
        p = cv.iso(cv.rng.uniform(-2.0, 2.2), cv.rng.uniform(-1.4, 1.4), 2.0)
        cv.line(p, focal, "#334050", 1.2, 0.8)
        cv.ring(p, 9, INK if k == 0 else "#5B6675", 2, 0.85)
    return focal


def scene_industrial(cv: Canvas) -> tuple[float, float]:
    focal = (0.0, 0.0)
    for i in range(cv.rng.randint(2, 3)):
        f = cv.box(-3.0 + i * 1.7, -1.2, 0, 1.3, 0.9, 2.6, top="#2F3743")
        for k in range(3):
            pt = (f["left"][0][0] + 18 + k * 16, f["left"][3][1] + 40)
            cv.dot(pt, 4, CYAN if (i == 0 and k == 1) else "#556070")
        if i == 0:
            focal = ((f["left"][0][0] + f["left"][2][0]) / 2, (f["left"][0][1] + f["left"][2][1]) / 2)
    a, b = cv.iso(-3.5, 1.4, 0.6), cv.iso(4.0, 1.4, 0.6)
    cv.line(a, b, "#3A4452", 14)
    cv.line(a, b, "#262E38", 9)
    v = cv.iso(1.6, 1.4, 0.6)
    cv.add(f'<polygon points="{_pts([(v[0] - 18, v[1] - 16), (v[0] + 18, v[1] + 16), (v[0] + 18, v[1] - 16), (v[0] - 18, v[1] + 16)])}" '
           f'fill="#3A4452" stroke="{EDGE}"/>')
    return focal


def scene_ai(cv: Canvas) -> tuple[float, float]:
    layers = [cv.rng.randint(3, 4), cv.rng.randint(5, 6), cv.rng.randint(4, 5), 2]
    pos: list[list[tuple[float, float]]] = []
    for li, n in enumerate(layers):
        col = []
        for k in range(n):
            col.append((cv.ox - 360 + li * 240, cv.oy - 210 + (k + 0.5) * (420 / n)))
        pos.append(col)
    for li in range(len(pos) - 1):
        for a in pos[li]:
            for b in pos[li + 1]:
                cv.line(a, b, "#2C3542", 1.0, 0.8)
    for col in pos:
        for p in col:
            cv.dot(p, 9, FACE_TOP)
            cv.ring(p, 9, EDGE, 1.5)
    return pos[2][len(pos[2]) // 2]


def scene_core(cv: Canvas) -> tuple[float, float]:
    f = cv.box(-1.2, -1.2, 0, 2.4, 2.4, 2.4, top="#303A46")
    for ang in range(0, 360, 60):
        p = cv.iso(4.2 * math.cos(math.radians(ang + 15)), 4.2 * math.sin(math.radians(ang + 15)), 0)
        cv.line(p, cv.iso(0, 0, 0), "#2C3542", 1.2)
        cv.dot(p, 6, "#4B5563")
    return ((f["top"][0][0] + f["top"][2][0]) / 2, (f["top"][0][1] + f["top"][2][1]) / 2)


SCENES: dict[str, Callable[[Canvas], tuple[float, float]]] = {
    "server_room": scene_server_room, "rack": scene_rack, "network_edge": scene_network_edge,
    "workstation": scene_workstation, "phone": scene_phone, "web": scene_web, "browser": scene_browser,
    "mail": scene_mail, "vm": scene_vm, "containers": scene_containers, "payments": scene_payments,
    "wallet": scene_wallet, "pipeline": scene_pipeline, "corporate": scene_corporate, "home": scene_home,
    "cloud": scene_cloud, "industrial": scene_industrial, "ai": scene_ai, "core": scene_core,
}


# ---------------------------------------------------------------- event overlays

def ov_exploited(cv: Canvas, f: tuple[float, float]) -> None:
    start = (cv.rng.uniform(60, 220), cv.rng.uniform(140, 760))
    ctrl = ((start[0] + f[0]) / 2 + cv.rng.uniform(-80, 80), min(start[1], f[1]) - cv.rng.uniform(80, 200))
    cv.curve(start, ctrl, f, CYAN, 9, 0.18)
    cv.curve(start, ctrl, f, CYAN, 3, 0.95)
    for t in (0.35, 0.55, 0.75):
        p, q = _qpoint(start, ctrl, f, t), _qpoint(start, ctrl, f, t + 0.02)
        ang = math.atan2(q[1] - p[1], q[0] - p[0])
        tip = (p[0] + 14 * math.cos(ang), p[1] + 14 * math.sin(ang))
        l = (p[0] + 9 * math.cos(ang + 2.5), p[1] + 9 * math.sin(ang + 2.5))
        r = (p[0] + 9 * math.cos(ang - 2.5), p[1] + 9 * math.sin(ang - 2.5))
        cv.add(f'<polygon points="{_pts([tip, l, r])}" fill="{CYAN_SOFT}"/>')
    cv.glow(f, 70, 0.45)
    for k in range(4):
        a = cv.rng.uniform(0, 2 * math.pi)
        cv.line(f, (f[0] + 46 * math.cos(a), f[1] + 46 * math.sin(a)), CYAN_SOFT, 2, 0.8)
    cv.dot(f, 7, INK)


def ov_exposed(cv: Canvas, f: tuple[float, float]) -> None:
    cv.glow(f, 60, 0.3)
    cv.ring(f, 30, CYAN, 2.5)
    cv.ring(f, 62, CYAN, 1.5, 0.6, "4 8")
    a0 = cv.rng.uniform(0, 360)
    cv.arc(f, 96, a0, a0 + 70, CYAN, 3, 0.8)
    cv.add(f'<path d="M{_f(f[0])} {_f(f[1])} L{_f(f[0] + 96 * math.cos(math.radians(a0)))} '
           f'{_f(f[1] + 96 * math.sin(math.radians(a0)))} A96 96 0 0 1 '
           f'{_f(f[0] + 96 * math.cos(math.radians(a0 + 70)))} {_f(f[1] + 96 * math.sin(math.radians(a0 + 70)))} Z" '
           f'fill="{CYAN}" opacity=".10"/>')
    cv.dot(f, 6, CYAN_SOFT)


def ov_ransomware(cv: Canvas, f: tuple[float, float]) -> None:
    for i in range(cv.rng.randint(4, 6)):
        x, y = cv.rng.uniform(-6.5, 5.5), cv.rng.uniform(2.2, 3.6)
        b = cv.box(x, y, 0, 1.2, 1.0, cv.rng.uniform(0.6, 1.2), top="#262D37", opacity=0.9)
        t = b["top"]
        cv.line(t[0], t[2], "#0B0E13", 6, 0.9)
        cv.line(t[1], t[3], "#0B0E13", 6, 0.9)
    cv.glow(f, 80, 0.35)
    cv.ring(f, 40, CYAN, 6)
    cv.ring(f, 40, "#0B0E13", 2)
    for ang in range(0, 360, 45):
        cv.line((f[0] + 46 * math.cos(math.radians(ang)), f[1] + 46 * math.sin(math.radians(ang))),
                (f[0] + 58 * math.cos(math.radians(ang)), f[1] + 58 * math.sin(math.radians(ang))), CYAN, 3)


def _archive(cv: Canvas) -> tuple[float, float]:
    stack = []
    for i in range(4):
        b = cv.box(3.8, -2.0, i * 0.7, 2.0, 1.4, 0.6, top="#2E3642" if i == 3 else FACE_TOP)
        stack.append(b)
    lf = stack[1]["left"]
    return ((lf[0][0] + lf[2][0]) / 2, (lf[0][1] + lf[2][1]) / 2)


def ov_breach_confirmed(cv: Canvas, f: tuple[float, float]) -> None:
    opening = _archive(cv)
    cv.glow(opening, 60, 0.4)
    end = (opening[0] + cv.rng.uniform(220, 320), opening[1] + cv.rng.uniform(-260, -140))
    ctrl = (opening[0] + 60, end[1] + 40)
    for k in range(cv.rng.randint(9, 13)):
        t = (k + 1) / 14
        p = _qpoint(opening, ctrl, end, t)
        cv.add(f'<rect x="{_f(p[0] - 14)}" y="{_f(p[1] - 9)}" width="28" height="18" rx="3" fill="{INK}" '
               f'opacity="{_f(0.85 - t * 0.6)}" transform="rotate({_f(cv.rng.uniform(-25, 25))} {_f(p[0])} {_f(p[1])})"/>')
    cv.curve(opening, ctrl, end, CYAN, 2, 0.6, "3 9")
    cv.ring(opening, 26, CYAN, 3)


def ov_breach_unconfirmed(cv: Canvas, f: tuple[float, float]) -> None:
    c = _archive(cv)
    cv.glow(c, 60, 0.25)
    cv.ring(c, 38, CYAN, 2.5)
    cv.ring(c, 72, CYAN, 1.2, 0.55, "4 8")
    a0 = cv.rng.uniform(0, 360)
    cv.arc(c, 104, a0, a0 + 60, CYAN, 3, 0.7)


def ov_phishing(cv: Canvas, f: tuple[float, float]) -> None:
    e = (cv.rng.uniform(170, 260), cv.rng.uniform(220, 360))
    w, h = 130, 86
    cv.add(f'<rect x="{_f(e[0] - w / 2)}" y="{_f(e[1] - h / 2)}" width="{w}" height="{h}" rx="8" fill="#20262F" '
           f'stroke="{EDGE}" stroke-width="1.5"/>')
    cv.add(f'<polyline points="{_pts([(e[0] - w / 2 + 6, e[1] - h / 2 + 8), (e[0], e[1] + 6), (e[0] + w / 2 - 6, e[1] - h / 2 + 8)])}" '
           f'fill="none" stroke="#5B6675" stroke-width="2"/>')
    gates = [(1240 + cv.rng.uniform(-30, 30), 300 + cv.rng.uniform(-30, 30)), (1250 + cv.rng.uniform(-30, 30), 560)]
    fake = cv.rng.randrange(2)
    for i, g in enumerate(gates):
        col = CYAN if i == fake else "#5B6675"
        off = 7 if i == fake else 0
        cv.add(f'<path d="M{_f(g[0] - 60 + off)} {_f(g[1] + 70)} L{_f(g[0] - 60 + off)} {_f(g[1] - 30)} '
               f'A60 60 0 0 1 {_f(g[0] + 60 + off)} {_f(g[1] - 30)} L{_f(g[0] + 60 + off)} {_f(g[1] + 70)}" '
               f'fill="#161B22" stroke="{col}" stroke-width="3"/>')
    tgt = gates[fake]
    ctrl = ((e[0] + tgt[0]) / 2, min(e[1], tgt[1]) - 120)
    cv.curve((e[0] + w / 2, e[1]), ctrl, (tgt[0] - 60, tgt[1] + 20), CYAN, 2.5, 0.85, "8 10")
    cv.glow(tgt, 70, 0.3)


def ov_scam(cv: Canvas, f: tuple[float, float]) -> None:
    ov_phishing(cv, f)


def ov_malware(cv: Canvas, f: tuple[float, float]) -> None:
    n = cv.rng.randint(5, 7)
    nodes = [(140 + i * (1320 / (n - 1)), 760 - cv.rng.uniform(0, 90) - 30 * math.sin(i)) for i in range(n)]
    for a, b in zip(nodes, nodes[1:]):
        cv.line(a, b, "#3A4452", 2)
    k = cv.rng.randint(1, n - 2)
    for i, p in enumerate(nodes):
        cv.dot(p, 10, "#3E4A59" if i > k else FACE_TOP)
        cv.ring(p, 10, CYAN if i > k else EDGE, 2, 0.9 if i > k else 1)
    hx = ((nodes[k][0] + nodes[k + 1][0]) / 2, (nodes[k][1] + nodes[k + 1][1]) / 2)
    hexa = [(hx[0] + 18 * math.cos(math.radians(a)), hx[1] + 18 * math.sin(math.radians(a))) for a in range(0, 360, 60)]
    cv.add(f'<polygon points="{_pts(hexa)}" fill="{INK}"/>')
    cv.curve(nodes[k + 1], ((nodes[k + 1][0] + f[0]) / 2, f[1] + 120), f, CYAN, 2.5, 0.8, "6 8")
    cv.glow(f, 55, 0.3)
    cv.dot(f, 6, INK)


def ov_botnet(cv: Canvas, f: tuple[float, float]) -> None:
    hub = (cv.rng.uniform(1180, 1360), cv.rng.uniform(190, 280))
    for _ in range(cv.rng.randint(26, 36)):
        p = (cv.rng.uniform(80, 1500), cv.rng.uniform(520, 860))
        cv.line(p, hub, CYAN, 0.8, 0.22)
        cv.dot(p, 4, "#6B7686")
    for r, o in ((18, 1.0), (40, 0.5), (66, 0.25)):
        cv.ring(hub, r, CYAN, 2, o)
    cv.glow(hub, 60, 0.35)


def ov_disrupted(cv: Canvas, f: tuple[float, float]) -> None:
    n = cv.rng.randint(5, 7)
    nodes = [(cv.rng.uniform(150, 1450), cv.rng.uniform(150, 420)) for _ in range(n)]
    for a, b in zip(nodes, nodes[1:]):
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        cv.line(a, (mid[0] - 12, mid[1] - 6), "#4B5563", 2)
        cv.line((mid[0] + 12, mid[1] + 6), b, "#4B5563", 2)
        cv.line((mid[0] - 10, mid[1] + 14), (mid[0] + 10, mid[1] - 14), CYAN, 3)
    for p in nodes:
        cv.dot(p, 9, "#2A313B")
        cv.ring(p, 9, "#4B5563", 1.5)


def ov_analysis(cv: Canvas, f: tuple[float, float]) -> None:
    for i, r in enumerate((54, 92, 134)):
        cv.ring(f, r, CYAN, 1.4, 0.55 - i * 0.15, "2 7" if i else "")
    a0 = cv.rng.uniform(0, 360)
    cv.arc(f, 134, a0, a0 + 40, CYAN, 3, 0.85)
    cv.glow(f, 46, 0.28)
    cv.dot(f, 6, CYAN_SOFT)


def ov_campaign_waves(cv: Canvas, origin: tuple[float, float]) -> None:
    for i, r in enumerate((80, 150, 230, 320)):
        cv.ring(origin, r, CYAN, 1.2, 0.28 - i * 0.06)


OVERLAYS: dict[str, Callable[[Canvas, tuple[float, float]], None]] = {
    "exploited": ov_exploited, "exposed": ov_exposed, "ransomware": ov_ransomware,
    "breach_confirmed": ov_breach_confirmed, "breach_unconfirmed": ov_breach_unconfirmed,
    "phishing": ov_phishing, "scam": ov_scam, "malware": ov_malware, "botnet": ov_botnet,
    "disrupted": ov_disrupted, "analysis": ov_analysis,
}


# ---------------------------------------------------------------- composition

def _defs() -> str:
    return (
        '<defs>'
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#141921"/><stop offset=".55" stop-color="#0F1318"/>'
        '<stop offset="1" stop-color="#0A0D11"/></linearGradient>'
        '<radialGradient id="vig" cx="50%" cy="50%" r="75%">'
        '<stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/>'
        '</radialGradient>'
        '<linearGradient id="screen" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{CYAN_DIM}" stop-opacity=".55"/><stop offset="1" stop-color="#0B1520" stop-opacity=".9"/>'
        '</linearGradient>'
        '<filter id="blur" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="22"/></filter>'
        '<filter id="soft" x="-50%" y="-80%" width="200%" height="260%"><feGaussianBlur stdDeviation="90"/></filter>'
        '</defs>'
    )


def _atmosphere(cv: Canvas) -> None:
    # Perspective floor lines converging on a horizon, very faint.
    hz = cv.rng.uniform(380, 460)
    vx = cv.rng.uniform(650, 950)
    for i in range(-10, 11):
        cv.line((vx, hz), (vx + i * 170, H + 40), "#1B212A", 1, 0.9)
    for k in range(1, 7):
        y = hz + (H - hz) * (k / 7) ** 1.8
        cv.line((0, y), (W, y), "#191E26", 1, 0.8)
    for _ in range(cv.rng.randint(30, 50)):
        cv.dot((cv.rng.uniform(0, W), cv.rng.uniform(0, H)), cv.rng.uniform(0.8, 1.8), "#9FB3C8",
               cv.rng.uniform(0.05, 0.18))


def _brand_mark(cv: Canvas) -> None:
    c = (W - 62, H - 58)
    cv.ring(c, 17, INK, 2, 0.35)
    cv.ring(c, 9, INK, 2, 0.35)
    cv.dot((c[0] + 12, c[1] - 12), 4, CYAN, 0.8)


@dataclass(frozen=True)
class VisualBrief:
    event: str
    scenes: tuple[str, ...]
    seed: str
    campaign_active: bool = False

    @property
    def scene(self) -> str:
        return self.scenes[0] if self.scenes else "core"


def render_svg(brief: VisualBrief) -> str:
    rng = random.Random(int(hashlib.sha256(brief.seed.encode()).hexdigest()[:16], 16))
    cv = Canvas(rng=rng, scale=rng.uniform(64, 74), ox=rng.uniform(740, 860), oy=rng.uniform(520, 570))
    cv.add(f'<rect width="{W}" height="{H}" fill="url(#bg)"/>')
    _atmosphere(cv)
    # Ambient rim light behind the scene and a soft ground shadow under it.
    cv.add(f'<ellipse cx="{_f(cv.ox)}" cy="{_f(cv.oy - 120)}" rx="520" ry="300" fill="{CYAN}" opacity=".10" '
           f'filter="url(#soft)"/>')
    cv.add(f'<ellipse cx="{_f(cv.ox)}" cy="{_f(cv.oy + 40)}" rx="430" ry="120" fill="#000" opacity=".55" '
           f'filter="url(#soft)"/>')
    focal = SCENES.get(brief.scene, scene_core)(cv)
    if brief.campaign_active:
        ov_campaign_waves(cv, focal)
    OVERLAYS.get(brief.event, ov_analysis)(cv, focal)
    cv.add(f'<rect width="{W}" height="{H}" fill="url(#vig)"/>')
    _brand_mark(cv)
    body = "".join(cv.parts)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'{_defs()}{body}</svg>')


# ---------------------------------------------------------------- sanitizer

_ALLOWED_TAGS = {"svg", "defs", "g", "rect", "circle", "ellipse", "line", "polyline", "polygon", "path",
                 "linearGradient", "radialGradient", "stop", "filter", "feGaussianBlur"}
_ALLOWED_ATTRS = {"xmlns", "width", "height", "viewBox", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r",
                  "rx", "ry", "points", "d", "fill", "stroke", "stroke-width", "stroke-dasharray",
                  "stroke-linecap", "opacity", "stop-color", "stop-opacity", "offset", "id", "filter",
                  "stdDeviation", "transform"}
_URL_REF = re.compile(r"url\((?!#[A-Za-z][\w-]*\))", re.I)
MAX_SVG_BYTES = 2 * 1024 * 1024


class UnsafeSvg(ValueError):
    pass


def sanitize_svg(data: bytes) -> tuple[int, int]:
    """Accept only the element/attribute subset this renderer emits.

    Rejects DOCTYPE/entities, scripts, foreignObject, images, links, event
    handlers, external `url()` references and anything not on the allowlist.
    Returns (width, height). Raises UnsafeSvg."""
    if len(data) > MAX_SVG_BYTES:
        raise UnsafeSvg("SVG too large")
    text = data.decode("utf-8", errors="strict")
    if re.search(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", text, re.I):
        raise UnsafeSvg("DOCTYPE, entities and stylesheets are not allowed")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise UnsafeSvg(f"not well-formed: {exc}") from exc
    ns = "{http://www.w3.org/2000/svg}"
    if root.tag != f"{ns}svg":
        raise UnsafeSvg("root element is not <svg>")
    for el in root.iter():
        tag = el.tag.replace(ns, "")
        if tag not in _ALLOWED_TAGS:
            raise UnsafeSvg(f"element <{tag}> not allowed")
        for name, value in el.attrib.items():
            if name not in _ALLOWED_ATTRS:
                raise UnsafeSvg(f"attribute {name!r} not allowed on <{tag}>")
            if _URL_REF.search(value) or "javascript:" in value.lower():
                raise UnsafeSvg(f"external reference in {name!r}")
        if (el.text or "").strip():
            raise UnsafeSvg(f"text content in <{tag}>")
    try:
        w, h = int(float(root.attrib["width"])), int(float(root.attrib["height"]))
    except (KeyError, ValueError) as exc:
        raise UnsafeSvg("width/height missing") from exc
    if not (512 <= w <= 4096 and 288 <= h <= 4096):
        raise UnsafeSvg(f"dimensions {w}x{h} out of range")
    return w, h


__all__ = ["H", "OVERLAYS", "RENDERER_VERSION", "SCENES", "UnsafeSvg", "VisualBrief", "W", "render_svg",
           "sanitize_svg"]
