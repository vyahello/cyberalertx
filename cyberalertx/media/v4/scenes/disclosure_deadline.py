"""Disclosure policy: the time a vendor gets to fix a reported bug, drawn as
a tape measure running from the bug across the frame, and a large pair of
scissors cutting it short; the cut-off length drops away, ghosted.

The tape carries unlabelled ticks only: a day count is printed at the cut
only when `brief.facts` states one. No tracker card, no issue number, no
invented status text."""
from __future__ import annotations

import math
import random

from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene
from ._editorial import fit_size

_TAPE_Y, _TAPE_H = 360.0, 120.0


def _tape(doc: Doc, x0: float, x1: float, y: float, h: float, ink: str, opacity: float = 1.0) -> None:
    with doc.g(opacity=opacity):
        doc.rect(x0 + 6, y + 16, x1 - x0, h, "#000", 4, opacity=0.18, extra=f' filter="{doc.blur(8)}"')
        doc.rect(x0, y, x1 - x0, h, doc.lin([(0, "#FFD866", 1), (1, "#E7B53A", 1)]), 4)
        doc.rect(x0, y, x1 - x0, 6, "#FFFFFF", opacity=0.35)
        d = ""
        x = x0 + 12
        k = 0
        while x < x1 - 4:
            ln = 46 if k % 10 == 0 else 30 if k % 5 == 0 else 18
            d += f"M{f(x)} {f(y)}v{ln}M{f(x)} {f(y + h)}v{-ln}"
            x += 14
            k += 1
        doc.path(d, stroke=ink, sw=2.6, opacity=0.8, cap="butt")


def _bug(doc: Doc, cx: float, cy: float, s: float, color: str) -> None:
    d = ""
    for k in (-1, 0, 1):
        y = cy + k * 26 * s
        d += f"M{f(cx - 40 * s)} {f(y)}l{f(-34 * s)} {f(k * 14 * s - 8 * s)}"
        d += f"M{f(cx + 40 * s)} {f(y)}l{f(34 * s)} {f(k * 14 * s - 8 * s)}"
    d += f"M{f(cx - 14 * s)} {f(cy - 60 * s)}l{f(-14 * s)} {f(-26 * s)}M{f(cx + 14 * s)} {f(cy - 60 * s)}" \
         f"l{f(14 * s)} {f(-26 * s)}"
    doc.path(d, stroke=color, sw=8 * s)
    doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy + 6 * s)}" rx="{f(44 * s)}" ry="{f(58 * s)}" fill="{color}"/>')
    doc.circle(cx, cy - 52 * s, 26 * s, color)
    doc.line((cx, cy - 40 * s), (cx, cy + 60 * s), "#FFFFFF", 3 * s, 0.5)


def _blade(doc: Doc, pivot: tuple[float, float], ang: float, length: float, back: bool) -> None:
    px, py = pivot
    ca, sa = math.cos(ang), math.sin(ang)
    nx, ny = -sa, ca
    tip = (px + ca * length, py + sa * length)
    w = 34.0
    pts = [(px - ca * 30 + nx * w * 0.6, py - sa * 30 + ny * w * 0.6),
           (px + ca * length * 0.55 + nx * w * 0.55, py + sa * length * 0.55 + ny * w * 0.55), tip,
           (px + ca * length * 0.5 - nx * w * 0.45, py + sa * length * 0.5 - ny * w * 0.45),
           (px - ca * 30 - nx * w * 0.6, py - sa * 30 - ny * w * 0.6)]
    steel = doc.lin([(0, "#F4F6F8", 1), (0.5, "#B9C1C9", 1), (1, "#7C8790", 1)], 0, 0, 1, 1)
    doc.poly(pts, "#56606A" if back else steel)
    if not back:
        doc.path(f"M{f(pts[1][0])} {f(pts[1][1])}L{f(tip[0])} {f(tip[1])}", stroke="#FFFFFF", sw=2.5, opacity=0.8)


def _handle(doc: Doc, pivot: tuple[float, float], ang: float, length: float, color: str) -> None:
    px, py = pivot
    ca, sa = math.cos(ang), math.sin(ang)
    hx, hy = px + ca * length, py + sa * length
    doc.path(f"M{f(px)} {f(py)}L{f(hx)} {f(hy)}", stroke="#4A525B", sw=26)
    doc.add(f'<ellipse cx="{f(hx + ca * 40)}" cy="{f(hy + sa * 40)}" rx="70" ry="48" fill="none" '
            f'stroke="{color}" stroke-width="30" transform="rotate({f(math.degrees(ang))} {f(hx + ca * 40)} '
            f'{f(hy + sa * 40)})"/>')
    doc.add(f'<ellipse cx="{f(hx + ca * 40)}" cy="{f(hy + sa * 40 - 4)}" rx="62" ry="40" fill="none" '
            f'stroke="#FFFFFF" stroke-width="4" opacity="0.25" transform="rotate({f(math.degrees(ang))} '
            f'{f(hx + ca * 40)} {f(hy + sa * 40)})"/>')


@scene("disclosure_deadline")
def disclosure_deadline(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.35, 0.2))
    days = brief.facts.get("days")
    y, h = _TAPE_Y, _TAPE_H
    cut = 1010.0
    # the cut-off length, dropping away
    with doc.g(f"rotate(9 {f(cut + 30)} {f(y + h)})"):
        _tape(doc, cut + 30, 1700, y + 40, h, p.ink, opacity=0.35)
    # the tape that remains: from the reported bug to the cut
    _tape(doc, 250, cut, y, h, p.ink)
    doc.path(f"M{f(cut)} {f(y)}l-8 20l10 22l-10 26l8 24l-6 28", stroke=p.danger, sw=4)
    _bug(doc, 150, y + h / 2, 1.3, p.ink)
    # the scissors: blades across the tape, handles below
    pivot = (cut + 6, y + h + 130)
    _blade(doc, pivot, math.radians(-104), 420, back=True)
    _handle(doc, pivot, math.radians(66), 120, p.danger)
    _handle(doc, pivot, math.radians(114), 120, p.danger)
    _blade(doc, pivot, math.radians(-80), 420, back=False)
    doc.circle(pivot[0], pivot[1], 18, "#D9DEE3", "#56606A", 4)
    if days:
        doc.text(f"{days} days", cut - 20, y - 40, 56, p.danger, "display", anchor="end")
    if "project zero" in brief.text:
        size = fit_size("Project Zero", 84, 700, "display")
        doc.text("Project Zero", 110, 190, size, p.ink, "display")
    doc.focus = Box(20, 60, 1340, 754)
    vignette(doc, 0.3)
    _ = rng
