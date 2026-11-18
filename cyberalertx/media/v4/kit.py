"""Drawing kit of the editorial renderer: document, art directions, materials,
interface surfaces, annotation and a small icon set.

Every scene composes these pieces; none of them is a stand-in for a subject
(no cubes, no orbs). A scene shows the thing the story is about — a workflow
file, a sign-in page, a controller display — and uses the kit for the craft:
consistent type, light, shadow, texture and annotation.
"""
from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Iterator, Sequence

from . import type as T

W, H = 1600, 900
Pt = tuple[float, float]


def f(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


# ---------------------------------------------------------------- art directions

@dataclass(frozen=True)
class Palette:
    """One art direction. Light directions exist on purpose: a phishing story,
    a court case and a ransomware incident should not all be dark and cyan."""
    name: str
    bg0: str
    bg1: str
    surface: str        # panels, windows
    surface2: str       # panel chrome, table stripes
    ink: str            # primary type and line work on the background
    on_surface: str     # type on panels
    muted: str
    line: str
    accent: str         # the story's signal colour
    danger: str
    safe: str
    warn: str
    dark: bool = True


PALETTES: dict[str, Palette] = {p.name: p for p in (
    Palette("midnight", "#0A0F1A", "#121B2C", "#151E2F", "#1C2740", "#E8EDF5", "#E8EDF5", "#7D8AA3", "#2A3650",
            "#5EEAD4", "#FF5A4F", "#4ADE80", "#FBBF24"),
    Palette("paper", "#ECE6DA", "#DDD4C3", "#FBF8F2", "#EFE9DE", "#17181C", "#17181C", "#6B6558", "#C9BFAE",
            "#1E4FD8", "#D7372B", "#1F8A4C", "#C27C0E", dark=False),
    Palette("ember", "#0F0909", "#1E1110", "#1F1514", "#2A1C1A", "#F5E9E6", "#F5E9E6", "#A08680", "#3A2826",
            "#FF7A45", "#FF3B30", "#4ADE80", "#FFB020"),
    Palette("steel", "#12161B", "#1E242B", "#20272F", "#2A323C", "#EDEFF2", "#EDEFF2", "#8C96A3", "#36404C",
            "#F5A524", "#FF4D3D", "#4ADE80", "#F5A524"),
    Palette("court", "#F1EBDD", "#E3D8C1", "#FBF7EE", "#EFE6D4", "#1B2333", "#1B2333", "#6E6656", "#CDBFA3",
            "#A07C3B", "#B3261E", "#2F7D4F", "#A07C3B", dark=False),
    Palette("violet", "#0D0A18", "#18122C", "#1B1530", "#251C40", "#EEEAFB", "#EEEAFB", "#8E86A8", "#332A52",
            "#B69CFF", "#FF5C7A", "#5EE6A8", "#FFC857"),
    Palette("glacier", "#DCE5EC", "#C5D3DF", "#F8FAFC", "#EDF2F6", "#0F1B2A", "#0F1B2A", "#5B6B7D", "#B3C2D0",
            "#0B6BCB", "#D93A2B", "#13804B", "#B7791F", dark=False),
    Palette("forest", "#0B1310", "#13201A", "#15221C", "#1C2E25", "#E6F0EA", "#E6F0EA", "#7F988A", "#29402F",
            "#7CE0A8", "#FF6B5B", "#7CE0A8", "#F2C14E"),
)}


# ---------------------------------------------------------------- document

@dataclass
class Doc:
    pal: Palette
    parts: list[str] = field(default_factory=list)
    defs: dict[str, str] = field(default_factory=dict)
    _ids: dict[str, str] = field(default_factory=dict)
    #: Region (16:9) the small feed thumbnail crops to, so the subject stays
    #: legible at ~170 px wide. None = the whole frame.
    focus: "Box | None" = None
    #: Every string set as type in the image, as drawn (after `T.supported`).
    #: `consistency.check` compares the alt text against it.
    labels: list[str] = field(default_factory=list)

    def add(self, s: str) -> None:
        if s:
            self.parts.append(s)

    def _def(self, key: str, body: str) -> str:
        """Register a definition once; returns its id."""
        if key not in self._ids:
            ident = f"d{len(self._ids)}"
            self._ids[key] = ident
            self.defs[ident] = body.replace("{id}", ident)
        return self._ids[key]

    # ---- paint servers and filters
    def lin(self, stops: Sequence[tuple[float, str, float]], x1: float = 0, y1: float = 0, x2: float = 0,
            y2: float = 1) -> str:
        st = "".join(f'<stop offset="{o:.3f}" stop-color="{c}" stop-opacity="{a:.3f}"/>' for o, c, a in stops)
        key = f"lin{stops}{x1}{y1}{x2}{y2}"
        return "url(#" + self._def(key, f'<linearGradient id="{{id}}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">'
                                        f'{st}</linearGradient>') + ")"

    def rad(self, stops: Sequence[tuple[float, str, float]], cx: float = 0.5, cy: float = 0.5,
            r: float = 0.5) -> str:
        st = "".join(f'<stop offset="{o:.3f}" stop-color="{c}" stop-opacity="{a:.3f}"/>' for o, c, a in stops)
        key = f"rad{stops}{cx}{cy}{r}"
        return "url(#" + self._def(key, f'<radialGradient id="{{id}}" cx="{cx}" cy="{cy}" r="{r}">'
                                        f'{st}</radialGradient>') + ")"

    def blur(self, sd: float) -> str:
        return "url(#" + self._def(f"blur{sd}", f'<filter id="{{id}}" x="-50%" y="-50%" width="200%" '
                                              f'height="200%"><feGaussianBlur stdDeviation="{sd}"/></filter>') + ")"

    def clip_rect(self, x: float, y: float, w: float, h: float, r: float = 0) -> str:
        key = f"clip{x}{y}{w}{h}{r}"
        return "url(#" + self._def(key, f'<clipPath id="{{id}}"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" '
                                        f'height="{f(h)}" rx="{f(r)}"/></clipPath>') + ")"

    def clip_path(self, d: str) -> str:
        return "url(#" + self._def(f"clipd{d}", f'<clipPath id="{{id}}"><path d="{d}"/></clipPath>') + ")"

    def grain(self, opacity: float = 0.07, seed: int = 3) -> None:
        """Fine film grain over the whole frame: the shared material of every
        CyberAlertX image (it also stops large gradients from banding)."""
        fid = self._def(f"grain{seed}", f'<filter id="{{id}}" x="0" y="0" width="100%" height="100%">'
                        f'<feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="1" seed="{seed}"/>'
                        f'<feColorMatrix type="matrix" values="0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0 0.5  '
                        f'0 0 0 1.4 -0.45"/></filter>')
        self.add(f'<rect width="{W}" height="{H}" filter="url(#{fid})" opacity="{opacity:.3f}"/>')

    # ---- structure
    @contextmanager
    def g(self, transform: str = "", opacity: float = 1.0, clip: str = "", filt: str = "") -> Iterator[None]:
        attrs = ""
        if transform:
            attrs += f' transform="{transform}"'
        if opacity < 1:
            attrs += f' opacity="{opacity:.3f}"'
        if clip:
            attrs += f' clip-path="{clip}"'
        if filt:
            attrs += f' filter="{filt}"'
        self.add(f"<g{attrs}>")
        yield
        self.add("</g>")

    def svg(self) -> str:
        defs = "".join(self.defs.values())
        focus = ""
        if self.focus is not None:
            b = self.focus
            w = max(480.0, min(float(W), b.w))
            h = w * 9 / 16
            x = min(max(0.0, b.cx - w / 2), W - w)
            y = min(max(0.0, b.cy - h / 2), H - h)
            # Read by the site's /media route (preview variant); invisible.
            focus = (f'<rect id="cax-focus" x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" '
                     f'fill="none"/>')
        return (f'<svg xmlns="http://www.w3.org/2000/svg" id="cax-editorial-4" width="{W}" height="{H}" '
                f'viewBox="0 0 {W} {H}"><defs>{defs}</defs>{"".join(self.parts)}{focus}</svg>')

    # ---- primitives
    def rect(self, x: float, y: float, w: float, h: float, fill: str, r: float = 0, stroke: str = "",
             sw: float = 1, opacity: float = 1.0, extra: str = "") -> None:
        st = f' stroke="{stroke}" stroke-width="{f(sw)}"' if stroke else ""
        op = f' opacity="{opacity:.3f}"' if opacity < 1 else ""
        rr = f' rx="{f(r)}"' if r else ""
        self.add(f'<rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}"{rr} fill="{fill}"{st}{op}{extra}/>')

    def circle(self, cx: float, cy: float, r: float, fill: str, stroke: str = "", sw: float = 1,
               opacity: float = 1.0) -> None:
        st = f' stroke="{stroke}" stroke-width="{f(sw)}"' if stroke else ""
        op = f' opacity="{opacity:.3f}"' if opacity < 1 else ""
        self.add(f'<circle cx="{f(cx)}" cy="{f(cy)}" r="{f(r)}" fill="{fill}"{st}{op}/>')

    def path(self, d: str, fill: str = "none", stroke: str = "", sw: float = 1, opacity: float = 1.0,
             cap: str = "round", join: str = "round", dash: str = "", extra: str = "") -> None:
        st = (f' stroke="{stroke}" stroke-width="{f(sw)}" stroke-linecap="{cap}" stroke-linejoin="{join}"'
              if stroke else "")
        ds = f' stroke-dasharray="{dash}"' if dash else ""
        op = f' opacity="{opacity:.3f}"' if opacity < 1 else ""
        self.add(f'<path d="{d}" fill="{fill}"{st}{ds}{op}{extra}/>')

    def line(self, a: Pt, b: Pt, stroke: str, sw: float = 1, opacity: float = 1.0, dash: str = "") -> None:
        self.path(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}", stroke=stroke, sw=sw, opacity=opacity, dash=dash)

    def poly(self, pts: Sequence[Pt], fill: str, stroke: str = "", sw: float = 1, opacity: float = 1.0) -> None:
        self.path("M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z", fill=fill, stroke=stroke, sw=sw,
                  opacity=opacity)

    def text(self, s: str, x: float, y: float, size: float, fill: str, font: str = "ui", anchor: str = "start",
             tracking: float = 0.0, opacity: float = 1.0) -> float:
        svg, w = T.text_path(s, x, y, size, font=font, fill=fill, anchor=anchor, tracking=tracking,
                             opacity=opacity)
        drawn = T.supported(s, font).strip()
        if svg and drawn:
            self.labels.append(drawn)
        self.add(svg)
        return w

    # ---- light and depth
    def shadow(self, x: float, y: float, w: float, h: float, r: float = 12, depth: float = 1.0) -> None:
        """Soft contact shadow + longer cast shadow under a raised surface."""
        self.rect(x + 6 * depth, y + 26 * depth, w, h, "#000", r, opacity=0.38 if self.pal.dark else 0.20,
                  extra=f' filter="{self.blur(round(18 * depth))}"')
        self.rect(x + 2, y + 6, w, h, "#000", r, opacity=0.35 if self.pal.dark else 0.14,
                  extra=f' filter="{self.blur(4)}"')

    def glow(self, cx: float, cy: float, rx: float, ry: float, color: str, opacity: float = 0.35) -> None:
        self.add(f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{f(rx)}" ry="{f(ry)}" fill="{color}" '
                 f'opacity="{opacity:.3f}" filter="{self.blur(round(min(rx, ry) * 0.45))}"/>')


def background(doc: Doc, *, light: Pt = (0.7, 0.25), floor: float | None = None) -> None:
    """The stage: a lit backdrop with a key light and an optional floor plane."""
    p = doc.pal
    doc.rect(0, 0, W, H, doc.lin([(0, p.bg1, 1), (1, p.bg0, 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FFFFFF", 0.10 if p.dark else 0.55), (1, "#FFFFFF", 0)],
                                 light[0], light[1], 0.65))
    if floor is not None:
        doc.rect(0, floor, W, H - floor, doc.lin([(0, "#000", 0.0), (1, "#000", 0.35 if p.dark else 0.10)]))


def vignette(doc: Doc, strength: float = 0.55) -> None:
    doc.rect(0, 0, W, H, doc.rad([(0.55, "#000", 0), (1, "#000", strength if doc.pal.dark else strength * 0.4)],
                                 0.5, 0.5, 0.75))


def signature(doc: Doc) -> None:
    """The CyberAlertX mark: small, bottom right, the same on every image."""
    p = doc.pal
    c = (W - 56, H - 52)
    ink = p.ink
    doc.circle(c[0], c[1], 15, "none", ink, 2, 0.45)
    doc.circle(c[0], c[1], 7.5, "none", ink, 2, 0.45)
    doc.circle(c[0] + 11, c[1] - 11, 3.6, p.accent, opacity=0.9)


# ---------------------------------------------------------------- interface surfaces

@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def r(self) -> float:
        return self.x + self.w

    @property
    def b(self) -> float:
        return self.y + self.h

    def inset(self, dx: float, dy: float | None = None) -> "Box":
        dy = dx if dy is None else dy
        return Box(self.x + dx, self.y + dy, self.w - 2 * dx, self.h - 2 * dy)


def window(doc: Doc, b: Box, *, title: str = "", url: str = "", lock: bool | None = None, r: float = 14,
           surface: str = "", chrome: str = "", depth: float = 1.0, url_color: str = "") -> Box:
    """A desktop window (browser when `url` is given). Returns the content box."""
    p = doc.pal
    surface = surface or p.surface
    chrome = chrome or p.surface2
    if depth:
        doc.shadow(b.x, b.y, b.w, b.h, r, depth)
    doc.rect(b.x, b.y, b.w, b.h, surface, r, stroke=p.line, sw=1.2)
    bar = 46 if url else 38
    doc.add(f'<path d="M{f(b.x)} {f(b.y + r)}Q{f(b.x)} {f(b.y)} {f(b.x + r)} {f(b.y)}H{f(b.r - r)}'
            f'Q{f(b.r)} {f(b.y)} {f(b.r)} {f(b.y + r)}V{f(b.y + bar)}H{f(b.x)}Z" fill="{chrome}"/>')
    doc.line((b.x, b.y + bar), (b.r, b.y + bar), p.line, 1)
    for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        doc.circle(b.x + 22 + i * 18, b.y + bar / 2, 5.5, c, opacity=0.85)
    if url:
        ux, uw = b.x + 86, b.w - 110
        doc.rect(ux, b.y + 9, uw, bar - 18, p.surface if not p.dark else "#0000", 8, stroke=p.line, sw=1)
        tx = ux + 14
        if lock is not None:
            icon(doc, "lock" if lock else "unlock", tx + 7, b.y + bar / 2, 15,
                 p.safe if lock else p.danger)
            tx += 22
        doc.text(T.fit(url, 15, uw - (tx - ux) - 10, "mono"), tx, b.y + bar / 2 + 5, 15,
                 url_color or p.on_surface, "mono", opacity=0.92)
    elif title:
        doc.text(title, b.cx, b.y + bar / 2 + 5, 14, p.muted, "ui", anchor="middle")
    return Box(b.x, b.y + bar, b.w, b.h - bar)


Run = tuple[str, str]           # (text, colour)


def code(doc: Doc, x: float, y: float, lines: Sequence[Sequence[Run] | str], *, size: float = 18,
         lh: float = 1.55, gutter: bool = True, start: int = 1, marks: dict[int, str] | None = None,
         width: float = 0, font: str = "mono") -> float:
    """Monospaced listing. `marks` highlights whole lines (index -> colour).
    Returns the y below the last line."""
    p = doc.pal
    step = size * lh
    for i, ln in enumerate(lines):
        base = y + i * step
        if marks and i in marks:
            doc.rect(x - (54 if gutter else 12), base - size * 1.05, (width or 640) + (54 if gutter else 12),
                     step, marks[i], opacity=0.16)
            doc.rect(x - (54 if gutter else 12), base - size * 1.05, 4, step, marks[i])
        if gutter:
            doc.text(str(start + i), x - 18, base, size * 0.85, p.muted, "mono", anchor="end", opacity=0.6)
        runs: Sequence[Run] = [(ln, p.on_surface)] if isinstance(ln, str) else ln
        cx = x
        for txt, col in runs:
            cx += doc.text(txt, cx, base, size, col, font)
    return y + len(lines) * step


def pill(doc: Doc, x: float, y: float, s: str, *, fg: str, bg: str, size: float = 15, font: str = "mono",
         anchor: str = "start", pad: float = 10, stroke: str = "") -> Box:
    w = T.measure(T.supported(s, font), size, font) + 2 * pad
    h = size * 1.9
    if anchor == "middle":
        x -= w / 2
    elif anchor == "end":
        x -= w
    doc.rect(x, y, w, h, bg, h / 2 if font != "mono" else 6, stroke=stroke, sw=1.2)
    doc.text(s, x + pad, y + h / 2 + T.cap_height(size, font) / 2, size, fg, font)
    return Box(x, y, w, h)


def arrow(doc: Doc, pts: Sequence[Pt], color: str, sw: float = 3, head: float = 14, dash: str = "",
          opacity: float = 1.0, smooth: bool = True) -> None:
    """A path through `pts` (rounded corners when `smooth`) ending in an arrowhead."""
    if len(pts) < 2:
        return
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    ang = math.atan2(y1 - y0, x1 - x0)
    back = (x1 - head * 0.6 * math.cos(ang), y1 - head * 0.6 * math.sin(ang))
    pts = [*pts[:-1], back]
    d = f"M{f(pts[0][0])} {f(pts[0][1])}"
    if smooth and len(pts) > 2:
        for i in range(1, len(pts) - 1):
            mx, my = (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2
            if i == len(pts) - 2:
                mx, my = pts[i + 1]
            d += f"Q{f(pts[i][0])} {f(pts[i][1])} {f(mx)} {f(my)}"
    else:
        d += "".join(f"L{f(x)} {f(y)}" for x, y in pts[1:])
    doc.path(d, stroke=color, sw=sw, dash=dash, opacity=opacity)
    a1, a2 = ang + math.radians(152), ang - math.radians(152)
    doc.poly([(x1, y1), (x1 + head * math.cos(a1), y1 + head * math.sin(a1)),
              (x1 + head * math.cos(a2), y1 + head * math.sin(a2))], color, opacity=opacity)


def callout(doc: Doc, target: Pt, at: Pt, label: str, *, color: str = "", size: float = 16,
            font: str = "mono", sub: str = "", anchor: str = "start") -> None:
    """Technical annotation: a dot on the subject, a leader line, a label."""
    p = doc.pal
    color = color or p.ink
    doc.circle(target[0], target[1], 5, color)
    doc.circle(target[0], target[1], 11, "none", color, 1.5, 0.5)
    elbow = (at[0], at[1]) if abs(at[1] - target[1]) < 4 else (target[0] + (at[1] - target[1]) * 0.0, at[1])
    doc.path(f"M{f(target[0])} {f(target[1])}L{f(elbow[0])} {f(elbow[1])}L{f(at[0])} {f(at[1])}", stroke=color,
             sw=1.5, opacity=0.8)
    tx = at[0] + (10 if anchor == "start" else -10)
    doc.text(label, tx, at[1] + 6, size, color, font, anchor=anchor)
    if sub:
        doc.text(sub, tx, at[1] + 6 + size * 1.35, size * 0.8, p.muted, "ui", anchor=anchor)


# ---------------------------------------------------------------- icons (24-unit grid, stroked)

_ICONS: dict[str, str] = {
    "lock": "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
    "unlock": "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 6.6-1.6",
    "key": "M8 15.5a3.5 3.5 0 1 1 0-7a3.5 3.5 0 0 1 0 7zM11.5 12H20M17 12v3M20 12v2.5",
    "warn": "M12 4L21 19.5H3zM12 10v4.5M12 17v.4",
    "check": "M5 12.5l4.5 4.5L19 7.5",
    "cross": "M6.5 6.5l11 11M17.5 6.5l-11 11",
    "user": "M12 12a4 4 0 1 0 0-8a4 4 0 0 0 0 8zM4.5 20.5c1.2-3.7 4-5.5 7.5-5.5s6.3 1.8 7.5 5.5",
    "file": "M7 3.5h7l4 4v13H7zM14 3.5v4h4",
    "cookie": "M12 4a8 8 0 1 0 8 8a3 3 0 0 1-3.5-3A3 3 0 0 1 13 5.5A2 2 0 0 1 12 4zM9 10v.3M9.5 15v.3M14 14.5v.3",
    "clock": "M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18zM12 7.5V12l3 2",
    "terminal": "M4 5h16v14H4zM7.5 9.5l3 2.5l-3 2.5M12.5 15h4",
    "chip": "M7 7h10v10H7zM9.5 4v3M14.5 4v3M9.5 17v3M14.5 17v3M4 9.5h3M4 14.5h3M17 9.5h3M17 14.5h3",
    "globe": "M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18zM3.5 12h17M12 3c2.6 2.6 3.6 5.6 3.6 9S14.6 18.4 12 21"
             "M12 3C9.4 5.6 8.4 8.6 8.4 12s1 6.4 3.6 9",
    "mail": "M3.5 6h17v12h-17zM3.5 6.5L12 13l8.5-6.5",
    "phone": "M8 3h8v18H8zM11 18h2",
    "shieldx": "M12 3l7.5 3v5.5c0 4.6-3.2 8-7.5 9.5c-4.3-1.5-7.5-4.9-7.5-9.5V6zM9.5 9.5l5 5M14.5 9.5l-5 5",
    "download": "M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14",
    "upload": "M12 15V4M7.5 8.5L12 4l4.5 4.5M5 19.5h14",
    "link": "M10 14a4 4 0 0 0 6 .4l3-3a4 4 0 0 0-5.7-5.7l-1.6 1.6M14 10a4 4 0 0 0-6-.4l-3 3a4 4 0 0 0 5.7 5.7"
            "l1.6-1.6",
    "gear": "M12 15a3 3 0 1 0 0-6a3 3 0 0 0 0 6zM12 2.8v2.6M12 18.6v2.6M2.8 12h2.6M18.6 12h2.6M5.5 5.5l1.9 1.9"
            "M16.6 16.6l1.9 1.9M5.5 18.5l1.9-1.9M16.6 7.4l1.9-1.9",
    "play": "M8 5.5v13l10.5-6.5z",
    "monitor": "M3.5 4.5h17v11h-17zM9 20h6M12 15.5V20",
    "server": "M4 4h16v6H4zM4 14h16v6H4zM7.5 7h.3M7.5 17h.3",
    "usb": "M9 3h6v6H9zM7.5 9h9v12h-9zM11 5v1.5M13 5v1.5",
    "eye": "M2.5 12s3.5-6.5 9.5-6.5s9.5 6.5 9.5 6.5s-3.5 6.5-9.5 6.5s-9.5-6.5-9.5-6.5zM12 15a3 3 0 1 0 0-6a3 3 0 0"
           " 0 0 0 6z",
}


def icon(doc: Doc, name: str, cx: float, cy: float, size: float, color: str, sw: float = 2.0,
         opacity: float = 1.0) -> None:
    k = size / 24
    doc.add(f'<path transform="translate({f(cx - 12 * k)} {f(cy - 12 * k)}) scale({k:.3f})" d="{_ICONS[name]}" '
            f'fill="none" stroke="{color}" stroke-width="{f(sw / k)}" stroke-linecap="round" '
            f'stroke-linejoin="round"' + (f' opacity="{opacity:.3f}"' if opacity < 1 else "") + "/>")


def with_accent(p: Palette, accent: str) -> Palette:
    return replace(p, accent=accent)
