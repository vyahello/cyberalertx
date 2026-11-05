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
RENDERER_VERSION = "cax-svg-2"

CYAN = "#06B6D4"
CYAN_DIM = "#0E7490"
CYAN_SOFT = "#67E8F9"
INK = "#E6EDF3"
FACE_TOP, FACE_LEFT, FACE_RIGHT = "#3A4350", "#29303A", "#1C222A"
EDGE = "#4A5566"
RIM = "#8A97A8"
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
    bbox: list[float] = field(default_factory=lambda: [1e9, 1e9, -1e9, -1e9])

    def add(self, s: str) -> None:
        self.parts.append(s)

    def track(self, *pts: tuple[float, float], pad: float = 0.0) -> None:
        b = self.bbox
        for x, y in pts:
            b[0], b[1] = min(b[0], x - pad), min(b[1], y - pad)
            b[2], b[3] = max(b[2], x + pad), max(b[3], y + pad)

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
        # Materials: the default faces are lit gradients (key light from the
        # upper right), and the two visible top edges catch a rim highlight.
        top = "url(#mt)" if top == FACE_TOP else top
        left = "url(#ml)" if left == FACE_LEFT else left
        right = "url(#mr)" if right == FACE_RIGHT else right
        self.add(f'<g{op}><polygon points="{_pts(lf)}" fill="{left}" stroke="{edge}" stroke-width="1"/>'
                 f'<polygon points="{_pts(rt)}" fill="{right}" stroke="{edge}" stroke-width="1"/>'
                 f'<polygon points="{_pts(t)}" fill="{top}" stroke="{edge}" stroke-width="1"/>'
                 f'<polyline points="{_pts([t[3], t[2], t[1]])}" fill="none" stroke="{RIM}" stroke-width="1.4" '
                 f'opacity=".7"/></g>')
        self.track(*t, *lf, *rt)
        return {"top": t, "left": lf, "right": rt}

    def line(self, a: tuple[float, float], b: tuple[float, float], color: str = EDGE, width: float = 1.5,
             opacity: float = 1.0, dash: str = "") -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.track(a, b)
        self.add(f'<line x1="{_f(a[0])}" y1="{_f(a[1])}" x2="{_f(b[0])}" y2="{_f(b[1])}" stroke="{color}" '
                 f'stroke-width="{_f(width)}" opacity="{_f(opacity)}" stroke-linecap="round"{d}/>')

    def dot(self, c: tuple[float, float], r: float, color: str = CYAN, opacity: float = 1.0) -> None:
        self.track(c, pad=r)
        self.add(f'<circle cx="{_f(c[0])}" cy="{_f(c[1])}" r="{_f(r)}" fill="{color}" opacity="{_f(opacity)}"/>')

    def glow(self, c: tuple[float, float], r: float, opacity: float = 0.35, color: str = CYAN) -> None:
        opacity *= 0.6                      # restrained: light marks the subject, it is not the subject
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
    rt = f["right"]
    for i in range(1, 7):                                                     # side vents
        t = i / 7
        a = (rt[0][0] + (rt[3][0] - rt[0][0]) * t, rt[0][1] + (rt[3][1] - rt[0][1]) * t)
        b = (a[0] + (rt[1][0] - rt[0][0]) * 0.6, a[1] + (rt[1][1] - rt[0][1]) * 0.6)
        cv.line(a, b, "#161B22", 2, 0.8)
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
        f = cv.box(-2.4, -1.0, i * 0.8, 4.4, 2.0, 0.6, top="#303845" if i == layers - 1 else FACE_TOP)
        right = f["right"]
        for k in range(10):                                                   # port bank
            t = (k + 0.7) / 11
            a = (right[0][0] + (right[1][0] - right[0][0]) * t, right[0][1] + (right[1][1] - right[0][1]) * t)
            cv.add(f'<polygon points="{_pts([(a[0] - 6, a[1] - 14), (a[0] + 6, a[1] - 10), (a[0] + 6, a[1] - 2), (a[0] - 6, a[1] - 6)])}" '
                   f'fill="#12171E" stroke="#3E4856" stroke-width=".8"/>')
            cv.dot((a[0], a[1] - 19), 2.2, CYAN if (i == layers - 1 and k in (3, 7)) else "#5B6675", 0.95)
        focal = ((f["top"][0][0] + f["top"][2][0]) / 2, (f["top"][0][1] + f["top"][2][1]) / 2)
    for k in range(2):                                                        # antennas
        b = cv.iso(-1.8 + k * 1.4, -0.8, layers * 0.8 - 0.2)
        cv.line(b, (b[0], b[1] - 70), "#5B6675", 3)
        cv.dot((b[0], b[1] - 70), 4, "#7D8A9C")
    for k in range(3):                                                        # uplinks leaving the frame
        a = cv.iso(2.0, -0.6 + k * 0.6, 0.3)
        cv.line(a, (a[0] + 260, a[1] - 40 + k * 30), "#33404E", 2.5, 0.9)
    return focal


def scene_workstation(cv: Canvas) -> tuple[float, float]:
    cv.box(-2.2, -0.2, 0, 4.4, 2.2, 0.14, top="#2C343F")                     # desk
    cv.box(-1.2, 1.0, 0.14, 2.2, 0.7, 0.06, top="#39424F")                    # keyboard
    for i in range(10):
        a = cv.iso(-1.1 + i * 0.21, 1.15, 0.2)
        cv.add(f'<rect x="{_f(a[0] - 5)}" y="{_f(a[1] - 3)}" width="10" height="5" fill="#4A5566" opacity=".8"/>')
    cv.box(2.5, -0.4, 0, 0.9, 1.6, 2.0)                                       # tower
    cv.box(-0.15, 0.25, 0.14, 0.3, 0.3, 0.9)                                  # stand
    s = cv.box(-1.9, 0.2, 1.0, 3.8, 0.12, 2.3, top=FACE_TOP, left="#1C232D")
    lf = s["left"]
    scr = [(lf[3][0] + 10, lf[3][1] + 10), (lf[2][0] - 10, lf[2][1] + 10), (lf[1][0] - 10, lf[1][1] - 10),
           (lf[0][0] + 10, lf[0][1] - 10)]
    cv.add(f'<polygon points="{_pts(scr)}" fill="url(#screen)" opacity=".9"/>')
    _screen_tiles(cv, scr, 4, 3, cv.rng.randrange(12))
    return ((lf[0][0] + lf[2][0]) / 2, (lf[0][1] + lf[2][1]) / 2)


def _screen_tiles(cv: Canvas, quad: list[tuple[float, float]], cols: int, rows: int, hot: int) -> None:
    """App tiles on a (parallelogram) screen: no text, no logos."""
    (x0, y0), (x1, y1), _, (x3, y3) = quad
    for r in range(rows):
        for c in range(cols):
            u0, v0 = (c + 0.18) / cols, (r + 0.2) / rows
            u1, v1 = (c + 0.82) / cols, (r + 0.8) / rows
            def at(u: float, v: float) -> tuple[float, float]:
                return (x0 + (x1 - x0) * u + (x3 - x0) * v, y0 + (y1 - y0) * u + (y3 - y0) * v)
            k = r * cols + c
            cv.add(f'<polygon points="{_pts([at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1)])}" '
                   f'fill="{CYAN if k == hot else "#2E3A48"}" opacity="{".85" if k == hot else ".9"}"/>')


def scene_phone(cv: Canvas) -> tuple[float, float]:
    # Two handsets: the subject upright, a second one lying behind it.
    cv.box(2.0, -2.6, 0, 1.5, 2.8, 0.14, top="#2B333E")                       # second handset, set aside
    f = cv.box(-0.8, 0.0, 0, 1.9, 0.2, 3.7, left="#1A2029")
    lf = f["left"]
    inset = [(lf[3][0] + 9, lf[3][1] + 16), (lf[2][0] - 9, lf[2][1] + 16), (lf[1][0] - 9, lf[1][1] - 12),
             (lf[0][0] + 9, lf[0][1] - 12)]
    cv.add(f'<polygon points="{_pts(inset)}" fill="url(#screen)" opacity=".95"/>')
    hot = cv.rng.randrange(12)
    _screen_tiles(cv, [inset[0], inset[1], inset[2], inset[3]], 3, 4, hot)
    notch = ((lf[3][0] + lf[2][0]) / 2, (lf[3][1] + lf[2][1]) / 2 + 9)
    cv.add(f'<ellipse cx="{_f(notch[0])}" cy="{_f(notch[1])}" rx="16" ry="5" fill="#0C1016"/>')
    return ((lf[0][0] + lf[2][0]) / 2, (lf[0][1] + lf[2][1]) / 2)


def scene_web(cv: Canvas) -> tuple[float, float]:
    _rack(cv, -3.4, -0.4, h=3.2)
    return _browser_frame(cv, (cv.ox + 70, cv.oy - 150), 420, 260)


def _browser_frame(cv: Canvas, center: tuple[float, float], w: float, h: float) -> tuple[float, float]:
    x, y = center[0] - w / 2, center[1] - h / 2
    cv.track((x, y), (x + w, y + h))
    cv.add(f'<rect x="{_f(x + 14)}" y="{_f(y + 18)}" width="{_f(w)}" height="{_f(h)}" rx="14" fill="#000" opacity=".45"/>')
    cv.add(f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" rx="14" fill="#161B22" '
           f'stroke="#5D6878" stroke-width="1.5"/>')
    cv.add(f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="34" rx="14" fill="#1F2630"/>')
    for i in range(3):
        cv.dot((x + 22 + i * 18, y + 17), 4.5, "#3B4553")
    cv.add(f'<rect x="{_f(x + 90)}" y="{_f(y + 9)}" width="{_f(w * 0.5)}" height="16" rx="8" fill="#2A323D"/>')
    px, py, pw = x + 18, y + 52, w - 36
    cv.add(f'<rect x="{_f(px)}" y="{_f(py)}" width="{_f(pw)}" height="{_f(h * 0.3)}" rx="6" fill="url(#screen)" opacity=".6"/>')
    for r in range(4):                                                        # page body: blocks, no text
        yy = py + h * 0.3 + 16 + r * 22
        if yy > y + h - 20:
            break
        cv.add(f'<rect x="{_f(px)}" y="{_f(yy)}" width="{_f(pw * cv.rng.uniform(0.45, 0.62))}" height="9" rx="4" fill="#2C3541"/>')
        cv.add(f'<rect x="{_f(px + pw * 0.7)}" y="{_f(yy)}" width="{_f(pw * 0.3)}" height="9" rx="4" fill="#252D37"/>')
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
    term = cv.box(-1.4, -0.4, 0, 1.6, 1.2, 1.4, top="#303A47")              # card terminal
    lf = term["left"]
    for r in range(3):
        for col in range(3):
            a = (lf[3][0] + (lf[2][0] - lf[3][0]) * (0.25 + col * 0.25), lf[3][1] + (lf[2][1] - lf[3][1]) * (0.25 + col * 0.25)
                 + 26 + r * 14)
            cv.add(f'<rect x="{_f(a[0] - 6)}" y="{_f(a[1])}" width="12" height="8" rx="2" fill="#4A5566"/>')
    card = cv.box(0.8, -1.2, 1.6, 1.7, 1.1, 0.06, top="#3B4757")              # card, floating
    ct = card["top"]
    cv.line(((ct[0][0] * 3 + ct[3][0]) / 4, (ct[0][1] * 3 + ct[3][1]) / 4),
            ((ct[1][0] * 3 + ct[2][0]) / 4, (ct[1][1] * 3 + ct[2][1]) / 4), "#1E252E", 7)
    for i in range(cv.rng.randint(3, 5)):                                     # settlement stack
        c = cv.iso(2.6, 0.9, 0.15 + i * 0.22)
        cv.add(f'<ellipse cx="{_f(c[0])}" cy="{_f(c[1])}" rx="46" ry="23" fill="url(#mt)" stroke="{EDGE}"/>')
        cv.track((c[0] - 46, c[1] - 23), (c[0] + 46, c[1] + 23))
    return ((ct[0][0] + ct[2][0]) / 2, (ct[0][1] + ct[2][1]) / 2)


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
    cv.box(-2.6, -0.4, 0, 3.0, 1.9, 0.12, top="#2C343F")                     # laptop base
    s = cv.box(-2.6, -0.45, 0.12, 3.0, 0.08, 1.9, left="#1C232D")
    lf = s["left"]
    scr = [(lf[3][0] + 8, lf[3][1] + 8), (lf[2][0] - 8, lf[2][1] + 8), (lf[1][0] - 8, lf[1][1] - 8),
           (lf[0][0] + 8, lf[0][1] - 8)]
    cv.add(f'<polygon points="{_pts(scr)}" fill="url(#screen)" opacity=".85"/>')
    _screen_tiles(cv, scr, 3, 2, cv.rng.randrange(6))
    p = cv.box(1.4, 0.4, 0, 1.0, 0.14, 2.0, left="#1A2029")                  # phone
    pl = p["left"]
    ins = [(pl[3][0] + 6, pl[3][1] + 10), (pl[2][0] - 6, pl[2][1] + 10), (pl[1][0] - 6, pl[1][1] - 8),
           (pl[0][0] + 6, pl[0][1] - 8)]
    cv.add(f'<polygon points="{_pts(ins)}" fill="url(#screen)" opacity=".95"/>')
    _screen_tiles(cv, ins, 2, 3, cv.rng.randrange(6))
    return ((pl[0][0] + pl[2][0]) / 2, (pl[0][1] + pl[2][1]) / 2)


def _person(cv: Canvas, c: tuple[float, float], r: float, color: str) -> None:
    """An identity: head and shoulders, no face."""
    cv.add(f'<circle cx="{_f(c[0])}" cy="{_f(c[1] - r * 1.1)}" r="{_f(r * 0.55)}" fill="{color}"/>')
    cv.add(f'<path d="M{_f(c[0] - r)} {_f(c[1] + r * 0.4)} Q{_f(c[0])} {_f(c[1] - r * 0.9)} {_f(c[0] + r)} {_f(c[1] + r * 0.4)} Z" '
           f'fill="{color}"/>')
    cv.track((c[0] - r, c[1] - r * 1.7), (c[0] + r, c[1] + r * 0.4))


def scene_cloud(cv: Canvas) -> tuple[float, float]:
    focal = (0.0, 0.0)
    tops = []
    for i in range(3):
        f = cv.box(-2.8 + i * 0.3, -1.9 + i * 0.3, i * 1.0, 5.6 - i * 0.6, 3.8 - i * 0.6, 0.22,
                   top="#2E3743", opacity=0.95 - i * 0.1)
        tops.append(f["top"])
        focal = ((f["top"][0][0] + f["top"][2][0]) / 2, (f["top"][0][1] + f["top"][2][1]) / 2)
    for i in range(cv.rng.randint(4, 6)):                                     # workloads on the lower layers
        x, y = cv.rng.uniform(-2.3, 1.8), cv.rng.uniform(-1.4, 1.2)
        cv.box(x, y, 0.22, 0.5, 0.5, cv.rng.uniform(0.3, 0.7))
    n = cv.rng.randint(3, 5)
    hot = cv.rng.randrange(n)
    for k in range(n):                                                        # identities above the top layer
        p = cv.iso(cv.rng.uniform(-1.6, 1.6), cv.rng.uniform(-1.0, 1.0), 3.0)
        cv.line(p, focal, "#3A4858", 1.4, 0.9, "4 6")
        _person(cv, p, 16, INK if k == hot else "#5B6675")
    key = (focal[0] + 70, focal[1] - 10)                                      # access key
    cv.ring(key, 13, CYAN_SOFT, 3, 0.9)
    cv.line((key[0] + 13, key[1]), (key[0] + 54, key[1]), CYAN_SOFT, 3, 0.9)
    cv.line((key[0] + 44, key[1]), (key[0] + 44, key[1] + 10), CYAN_SOFT, 3, 0.9)
    return focal


def scene_industrial(cv: Canvas) -> tuple[float, float]:
    focal = (0.0, 0.0)
    n = cv.rng.randint(2, 3)
    for i in range(n):
        f = cv.box(-3.0 + i * 1.8, -1.2, 0, 1.4, 1.0, 3.0, top="#2F3743")     # control cabinets
        lf = f["left"]
        for row in range(3):                                                  # DIN-rail modules
            for k in range(5):
                t = (k + 0.5) / 5.6
                y0 = 0.18 + row * 0.26
                a = (lf[3][0] + (lf[2][0] - lf[3][0]) * t, lf[3][1] + (lf[2][1] - lf[3][1]) * t + (lf[0][1] - lf[3][1]) * y0)
                hot = i == 0 and row == 1 and k == 2
                cv.add(f'<rect x="{_f(a[0] - 6)}" y="{_f(a[1])}" width="12" height="26" fill="{"#1D3A44" if hot else "#232B35"}" '
                       f'stroke="{CYAN if hot else "#3E4856"}" stroke-width="1"/>')
                cv.dot((a[0], a[1] + 6), 1.8, CYAN if hot else "#6B7686")
        if i == 0:
            focal = ((lf[0][0] + lf[2][0]) / 2, (lf[0][1] + lf[2][1]) / 2)
    for z, w in ((0.6, 16), (1.3, 11)):                                       # process pipes
        a, b = cv.iso(-3.5, 1.5, z), cv.iso(4.2, 1.5, z)
        cv.line(a, b, "#3A4452", w)
        cv.line(a, b, "#262E38", w - 5)
    v = cv.iso(1.6, 1.5, 0.6)
    cv.add(f'<polygon points="{_pts([(v[0] - 20, v[1] - 18), (v[0] + 20, v[1] + 18), (v[0] + 20, v[1] - 18), (v[0] - 20, v[1] + 18)])}" '
           f'fill="#3A4452" stroke="{EDGE}"/>')
    g = cv.iso(3.2, 1.5, 1.3)                                                 # gauge
    cv.add(f'<circle cx="{_f(g[0])}" cy="{_f(g[1] - 34)}" r="22" fill="#1B2129" stroke="{RIM}" stroke-width="2"/>')
    ang = math.radians(cv.rng.uniform(-40, 60))
    cv.line((g[0], g[1] - 34), (g[0] + 16 * math.cos(ang), g[1] - 34 - 16 * math.sin(ang)), CYAN_SOFT, 2.5)
    cv.track((g[0] - 22, g[1] - 56))
    for k in range(3):                                                        # field sensors
        p = cv.iso(-2.4 + k * 2.2, 2.6, 0)
        cv.box(-2.6 + k * 2.2, 2.4, 0, 0.35, 0.35, 0.6)
        cv.line(p, cv.iso(-2.4 + k * 2.2, 1.5, 0.6), "#33404E", 1.5)
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
                cv.line(a, b, "#3A4656", 1.4, 0.85)
    for col in pos:
        for p in col:
            cv.dot(p, 15, "#3A4350")
            cv.ring(p, 15, RIM, 2, 0.8)
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


def _visitor_phone(cv: Canvas, c: tuple[float, float]) -> tuple[float, float]:
    x, y = c[0] - 23, c[1] - 42
    cv.add(f'<rect x="{_f(x)}" y="{_f(y)}" width="46" height="84" rx="9" fill="{FACE_TOP}" '
           f'stroke="{EDGE}" stroke-width="1.5"/>')
    cv.add(f'<rect x="{_f(x + 5)}" y="{_f(y + 9)}" width="36" height="62" rx="4" fill="url(#screen)" opacity=".9"/>')
    return (c[0], c[1] - 4)


def _visitor_laptop(cv: Canvas, c: tuple[float, float]) -> tuple[float, float]:
    x, y = c[0] - 58, c[1] - 46
    cv.add(f'<rect x="{_f(x)}" y="{_f(y)}" width="116" height="74" rx="6" fill="{FACE_TOP}" '
           f'stroke="{EDGE}" stroke-width="1.5"/>')
    cv.add(f'<rect x="{_f(x + 6)}" y="{_f(y + 6)}" width="104" height="60" rx="3" fill="url(#screen)" opacity=".9"/>')
    base = [(x - 12, y + 80), (x + 128, y + 80), (x + 116, y + 74), (x, y + 74)]
    cv.add(f'<polygon points="{_pts(base)}" fill="{FACE_LEFT}" stroke="{EDGE}" stroke-width="1"/>')
    return (c[0], c[1] - 12)


def ov_script_injection(cv: Canvas, f: tuple[float, float]) -> None:
    """A tampered third-party script inside the page, carried out to the
    devices of the people who visit it."""
    mod = (f[0] + cv.rng.uniform(80, 130), f[1] - cv.rng.uniform(25, 55))
    hexa = [(mod[0] + 20 * math.cos(math.radians(a)), mod[1] + 20 * math.sin(math.radians(a)))
            for a in range(30, 390, 60)]
    cv.glow(mod, 58, 0.4)
    cv.add(f'<polygon points="{_pts(hexa)}" fill="{INK}" stroke="{CYAN}" stroke-width="2.5"/>')
    cv.dot(mod, 5, CYAN_SOFT)
    n = cv.rng.randint(3, 4)
    ys = [cv.rng.uniform(250, 290) + i * (430 / n) for i in range(n)]
    for i, y in enumerate(ys):
        x = cv.rng.uniform(1100, 1190)          # inside the centre crop used for thumbnails
        screen = _visitor_laptop(cv, (x, y)) if i % 2 else _visitor_phone(cv, (x, y))
        ctrl = ((mod[0] + screen[0]) / 2, min(mod[1], screen[1]) - cv.rng.uniform(20, 90))
        cv.curve(mod, ctrl, screen, CYAN, 2.4, 0.85, "7 9")
        cv.glow(screen, 26, 0.35)
        cv.dot(screen, 5, CYAN)


def ov_campaign_waves(cv: Canvas, origin: tuple[float, float]) -> None:
    for i, r in enumerate((80, 150, 230, 320)):
        cv.ring(origin, r, CYAN, 1.2, 0.28 - i * 0.06)


OVERLAYS: dict[str, Callable[[Canvas, tuple[float, float]], None]] = {
    "exploited": ov_exploited, "exposed": ov_exposed, "ransomware": ov_ransomware,
    "breach_confirmed": ov_breach_confirmed, "breach_unconfirmed": ov_breach_unconfirmed,
    "phishing": ov_phishing, "scam": ov_scam, "malware": ov_malware, "botnet": ov_botnet,
    "disrupted": ov_disrupted, "analysis": ov_analysis, "script_injection": ov_script_injection,
}


# ---------------------------------------------------------------- composition

def _defs() -> str:
    return (
        '<defs>'
        '<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#121820"/><stop offset=".5" stop-color="#0E1218"/>'
        '<stop offset="1" stop-color="#090C10"/></linearGradient>'
        '<linearGradient id="floor" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#151B23"/><stop offset="1" stop-color="#0A0D11"/></linearGradient>'
        '<linearGradient id="haze" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{CYAN}" stop-opacity="0"/><stop offset=".5" stop-color="{CYAN}" stop-opacity=".07"/>'
        f'<stop offset="1" stop-color="{CYAN}" stop-opacity="0"/></linearGradient>'
        '<radialGradient id="vig" cx="50%" cy="50%" r="75%">'
        '<stop offset=".6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".5"/>'
        '</radialGradient>'
        '<linearGradient id="screen" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{CYAN_DIM}" stop-opacity=".5"/><stop offset="1" stop-color="#0B1520" stop-opacity=".95"/>'
        '</linearGradient>'
        # Materials: key light from the upper right, cool fill from the left.
        '<linearGradient id="mt" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#3A4350"/><stop offset="1" stop-color="#4C5767"/></linearGradient>'
        '<linearGradient id="ml" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#2D3540"/><stop offset="1" stop-color="#1D232B"/></linearGradient>'
        '<linearGradient id="mr" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#1F2B34"/><stop offset="1" stop-color="#14191F"/></linearGradient>'
        '<filter id="blur" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="22"/></filter>'
        '<filter id="soft" x="-50%" y="-80%" width="200%" height="260%"><feGaussianBlur stdDeviation="60"/></filter>'
        '<filter id="dof" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="2.4"/></filter>'
        '</defs>'
    )


# ---------------------------------------------------------------- backdrops (far layer, out of focus)

_FAMILY = {
    "server_room": "datacenter", "rack": "datacenter", "vm": "datacenter", "containers": "datacenter",
    "core": "datacenter", "corporate": "city", "mail": "city", "network_edge": "city", "web": "city",
    "browser": "city", "home": "city", "workstation": "city", "phone": "city", "industrial": "plant",
    "cloud": "strata", "ai": "strata", "payments": "finance", "wallet": "finance", "pipeline": "plant",
}


def _backdrop(rng: random.Random, family: str, horizon: float) -> str:
    out: list[str] = []
    dim = ("#151B23", "#18202A", "#1B232D")
    if family == "datacenter":
        for row in range(3):
            k = 1 - row * 0.22
            x = rng.uniform(-40, 0)
            while x < W:
                h = rng.uniform(150, 230) * k
                w = rng.uniform(54, 70) * k
                y = horizon - h + row * 26
                out.append(f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" fill="{dim[row]}"/>')
                for _ in range(rng.randint(2, 5)):
                    out.append(f'<circle cx="{_f(x + w * 0.8)}" cy="{_f(y + rng.uniform(10, h - 10))}" r="1.6" '
                               f'fill="{CYAN}" opacity="{_f(rng.uniform(0.12, 0.35))}"/>')
                x += w + rng.uniform(6, 16) * k
    elif family == "city":
        tops = []
        x = rng.uniform(-30, 0)
        while x < W:
            w, h = rng.uniform(40, 110), rng.uniform(60, 280)
            out.append(f'<rect x="{_f(x)}" y="{_f(horizon - h)}" width="{_f(w)}" height="{_f(h)}" fill="{rng.choice(dim)}"/>')
            for _ in range(rng.randint(0, 6)):
                out.append(f'<rect x="{_f(x + rng.uniform(6, w - 10))}" y="{_f(horizon - rng.uniform(12, h - 8))}" '
                           f'width="3" height="3" fill="#7D8A9C" opacity="{_f(rng.uniform(0.08, 0.25))}"/>')
            tops.append((x + w / 2, horizon - h))
            x += w + rng.uniform(4, 30)
        for a, b in zip(tops[::3], tops[2::3]):
            out.append(f'<line x1="{_f(a[0])}" y1="{_f(a[1])}" x2="{_f(b[0])}" y2="{_f(b[1])}" stroke="{CYAN_DIM}" '
                       f'stroke-width="1" opacity=".25"/>')
    elif family == "plant":
        x = rng.uniform(-20, 40)
        while x < W:
            kind = rng.random()
            if kind < 0.4:
                w, h = rng.uniform(90, 150), rng.uniform(90, 170)
                out.append(f'<rect x="{_f(x)}" y="{_f(horizon - h)}" width="{_f(w)}" height="{_f(h)}" fill="{dim[1]}"/>')
                out.append(f'<ellipse cx="{_f(x + w / 2)}" cy="{_f(horizon - h)}" rx="{_f(w / 2)}" ry="{_f(w / 7)}" fill="{dim[2]}"/>')
            elif kind < 0.6:
                w, h = rng.uniform(14, 24), rng.uniform(200, 300)
                out.append(f'<rect x="{_f(x)}" y="{_f(horizon - h)}" width="{_f(w)}" height="{_f(h)}" fill="{dim[0]}"/>')
            else:
                w, h = rng.uniform(120, 220), rng.uniform(50, 110)
                out.append(f'<rect x="{_f(x)}" y="{_f(horizon - h)}" width="{_f(w)}" height="{_f(h)}" fill="{dim[0]}"/>')
            x += w + rng.uniform(10, 50)
        for k in range(3):
            y = horizon - 30 - k * 34
            out.append(f'<line x1="0" y1="{_f(y)}" x2="{W}" y2="{_f(y)}" stroke="#1E2630" stroke-width="{6 - k}"/>')
    elif family == "strata":
        for k in range(4):
            y = horizon - 60 - k * 70
            out.append(f'<ellipse cx="{_f(W / 2 + rng.uniform(-200, 200))}" cy="{_f(y)}" rx="{_f(rng.uniform(600, 900))}" '
                       f'ry="{_f(rng.uniform(26, 44))}" fill="{dim[k % 3]}" opacity=".9"/>')
        pts = [(rng.uniform(0, W), rng.uniform(horizon - 330, horizon - 40)) for _ in range(26)]
        for a, b in zip(pts, pts[1:]):
            if abs(a[0] - b[0]) < 320:
                out.append(f'<line x1="{_f(a[0])}" y1="{_f(a[1])}" x2="{_f(b[0])}" y2="{_f(b[1])}" stroke="#2A3542" stroke-width="1"/>')
        for p in pts:
            out.append(f'<circle cx="{_f(p[0])}" cy="{_f(p[1])}" r="3" fill="#3A4858"/>')
    else:                                                                     # finance: ledger towers
        x = rng.uniform(0, 40)
        while x < W:
            w = rng.uniform(40, 60)
            n = rng.randint(3, 9)
            for k in range(n):
                out.append(f'<rect x="{_f(x)}" y="{_f(horizon - (k + 1) * 26)}" width="{_f(w)}" height="22" fill="{dim[k % 3]}"/>')
            x += w + rng.uniform(16, 40)
    return f'<g filter="url(#dof)" opacity=".9">{"".join(out)}</g>'


# ---------------------------------------------------------------- framing

def _fit(bbox: list[float], tw: float, th: float, cx: float, cy: float, mirror: bool) \
        -> tuple[str, Callable[[tuple[float, float]], tuple[float, float]], float]:
    """Scale and place a scene so it fills (tw, th) around (cx, cy)."""
    x0, y0, x1, y1 = bbox
    bw, bh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    s = min(tw / bw, th / bh)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    sx = -s if mirror else s
    transform = f"translate({_f(cx - sx * mx)} {_f(cy - s * my)}) scale({_f(sx)} {_f(s)})"

    def to_screen(p: tuple[float, float]) -> tuple[float, float]:
        return (cx + sx * (p[0] - mx), cy + s * (p[1] - my))
    return transform, to_screen, s


#: Camera presets: subject anchor (fraction of width) and mirroring.
_CAMERAS = ((0.5, False), (0.44, True), (0.56, False), (0.4, False), (0.6, True), (0.5, True))
#: Overlays that bring their own props: no secondary scene next to them.
_BUSY = frozenset({"script_injection", "botnet", "malware", "disrupted", "breach_confirmed", "breach_unconfirmed",
                   "phishing", "scam"})


@dataclass(frozen=True)
class VisualBrief:
    event: str
    scenes: tuple[str, ...]
    seed: str
    campaign_active: bool = False

    @property
    def scene(self) -> str:
        return self.scenes[0] if self.scenes else "core"


def _brand_mark(cv: Canvas) -> None:
    c = (W - 62, H - 58)
    cv.ring(c, 17, INK, 2, 0.35)
    cv.ring(c, 9, INK, 2, 0.35)
    cv.dot((c[0] + 12, c[1] - 12), 4, CYAN, 0.8)


def _scene_layer(rng: random.Random, name: str) -> tuple[Canvas, tuple[float, float]]:
    """Draw a scene around the origin; framing happens afterwards (`_fit`)."""
    sc = Canvas(rng=rng, scale=60.0, ox=0.0, oy=0.0)
    focal = SCENES.get(name, scene_core)(sc)
    sc.track(focal)
    return sc, focal


def render_svg(brief: VisualBrief) -> str:
    rng = random.Random(int(hashlib.sha256(brief.seed.encode()).hexdigest()[:16], 16))
    anchor, mirror = _CAMERAS[rng.randrange(len(_CAMERAS))]
    horizon = rng.uniform(470, 540)
    parts = [f'<rect width="{W}" height="{H}" fill="url(#bg)"/>',
             _backdrop(rng, _FAMILY.get(brief.scene, "datacenter"), horizon),
             f'<rect x="0" y="{_f(horizon)}" width="{W}" height="{_f(H - horizon)}" fill="url(#floor)"/>',
             f'<rect x="0" y="{_f(horizon - 90)}" width="{W}" height="180" fill="url(#haze)"/>']

    # Mid layer: the story's second technology, smaller, dimmed and out of focus.
    second = next((s for s in brief.scenes[1:] if s != brief.scene), "")
    if second and brief.event not in _BUSY:
        lay, _ = _scene_layer(rng, second)
        side = 0.83 if anchor <= 0.5 else 0.17
        tr, _, _ = _fit(lay.bbox, W * 0.24, H * 0.3, W * side, horizon - 40, not mirror)
        parts.append(f'<g opacity=".5" filter="url(#dof)"><g transform="{tr}">{"".join(lay.parts)}</g></g>')

    # The subject: fitted to fill about half of the frame.
    main, main_focal = _scene_layer(rng, brief.scene)
    tw, th = W * rng.uniform(0.5, 0.6), H * rng.uniform(0.56, 0.64)
    cx, cy = W * anchor, H * 0.54
    tr, to_screen, scale = _fit(main.bbox, tw, th, cx, cy, mirror)
    bottom = cy + th / 2
    parts.append(f'<ellipse cx="{_f(cx)}" cy="{_f(bottom - 10)}" rx="{_f(tw * 0.5)}" ry="{_f(th * 0.12)}" fill="#000" '
                 f'opacity=".6" filter="url(#soft)"/>')
    parts.append(f'<ellipse cx="{_f(cx + tw * 0.15)}" cy="{_f(cy - th * 0.3)}" rx="{_f(tw * 0.45)}" ry="{_f(th * 0.35)}" '
                 f'fill="{CYAN}" opacity=".06" filter="url(#soft)"/>')
    parts.append(f'<g transform="{tr}">{"".join(main.parts)}</g>')

    # Event overlay in screen space, around the subject's focal point.
    focal = to_screen(main_focal)
    ov = Canvas(rng=rng, scale=60.0 * min(scale, 1.2), ox=cx, oy=cy + th * 0.12)
    if brief.campaign_active:
        ov_campaign_waves(ov, focal)
    OVERLAYS.get(brief.event, ov_analysis)(ov, focal)
    parts.extend(ov.parts)
    parts.append(f'<rect width="{W}" height="{H}" fill="url(#vig)"/>')
    bm = Canvas(rng=rng)
    _brand_mark(bm)
    parts.extend(bm.parts)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'{_defs()}{"".join(parts)}</svg>')


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
