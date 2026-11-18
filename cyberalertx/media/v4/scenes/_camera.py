"""A small perspective camera for scenes that draw one solid object in 3/4
view (controller hardware, blocks, a gavel). Not a scene: no @scene here.

World axes: X right, Y up, Z toward the viewer. Faces are projected exactly at
their corners; detail on a face (vents, ports, type) is drawn in the face's own
2-D coordinates under an affine transform fitted at the face centre, which is
exact enough for the long lenses these scenes use."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from ..kit import Doc, Pt, f

V3 = tuple[float, float, float]


def _sub(a: V3, b: V3) -> V3:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _dot(a: V3, b: V3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: V3, b: V3) -> V3:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _norm(a: V3) -> V3:
    n = math.sqrt(_dot(a, a)) or 1.0
    return a[0] / n, a[1] / n, a[2] / n


def add(a: V3, b: V3, k: float = 1.0) -> V3:
    return a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k


@dataclass(frozen=True)
class Camera:
    eye: V3
    target: V3
    focal: float            # pixels
    cx: float               # screen position of the target
    cy: float

    def _basis(self) -> tuple[V3, V3, V3]:
        fw = _norm(_sub(self.target, self.eye))
        rt = _norm(_cross(fw, (0.0, 1.0, 0.0)))
        up = _cross(rt, fw)
        return fw, rt, up

    def p(self, q: V3) -> Pt:
        fw, rt, up = self._basis()
        d = _sub(q, self.eye)
        z = max(_dot(d, fw), 1e-3)
        return self.cx + self.focal * _dot(d, rt) / z, self.cy - self.focal * _dot(d, up) / z

    def depth(self, q: V3) -> float:
        fw, _, _ = self._basis()
        return _dot(_sub(q, self.eye), fw)

    def scale_at(self, q: V3) -> float:
        """Pixels per world unit at `q` (for line widths and blur)."""
        return self.focal / self.depth(q)

    def face(self, origin: V3, u: V3, v: V3, size: tuple[float, float]) -> str:
        """SVG matrix mapping face-local (u right, v down, in world units) to
        the screen. `origin` is the face's top-left corner; `u` and `v` are
        unit vectors along the face."""
        w, h = size
        c = add(add(origin, u, w / 2), v, h / 2)
        e = 0.5
        pc = self.p(c)
        pu, pv = self.p(add(c, u, e)), self.p(add(c, v, e))
        a, b = (pu[0] - pc[0]) / e, (pu[1] - pc[1]) / e
        cc, d = (pv[0] - pc[0]) / e, (pv[1] - pc[1]) / e
        ox = pc[0] - a * w / 2 - cc * h / 2
        oy = pc[1] - b * w / 2 - d * h / 2
        return f"matrix({a:.4f} {b:.4f} {cc:.4f} {d:.4f} {ox:.1f} {oy:.1f})"

    def poly(self, doc: Doc, pts: Sequence[V3], fill: str, stroke: str = "", sw: float = 1,
             opacity: float = 1.0) -> list[Pt]:
        s = [self.p(q) for q in pts]
        doc.poly(s, fill, stroke, sw, opacity)
        return s

    def visible(self, pts: Sequence[V3]) -> bool:
        """True when the face's corners run clockwise on screen (front-facing
        for faces listed counter-clockwise as seen from outside)."""
        s = [self.p(q) for q in pts]
        area = sum(s[i][0] * s[(i + 1) % len(s)][1] - s[(i + 1) % len(s)][0] * s[i][1] for i in range(len(s)))
        return area < 0


def path_of(pts: Sequence[Pt], closed: bool = True) -> str:
    d = "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts)
    return d + ("Z" if closed else "")
