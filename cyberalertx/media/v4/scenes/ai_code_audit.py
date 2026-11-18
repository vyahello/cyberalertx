"""Model-assisted code review: a long page of source code, drawn as abstract
syntax-coloured token bars (texture: no readable code), swept by a scanning
band of light as it is read top to bottom; where the band stops, a large
lens magnifies the lines and one of them is flagged in the danger colour.

The subject is the review itself (reading, sweeping, flagging), not a
picture of "AI". No code, file names, function names, bug classes or
severities are drawn: the sources of these stories do not state them."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene

_SYNTAX = ("#C7B8FF", "#DCD6EE", "#9EE6C4", "#FFD58A", "#8F86B3")


def _lines(rng: random.Random, n: int) -> list[list[tuple[float, float, str]]]:
    """n lines of (x offset, width, colour) tokens; deterministic from rng."""
    out: list[list[tuple[float, float, str]]] = []
    indent = 0
    for _ in range(n):
        r = rng.random()
        if r < 0.12:
            out.append([])
            indent = 0 if rng.random() < 0.5 else indent
            continue
        indent = max(0, min(3, indent + rng.choice((-1, 0, 0, 1))))
        x = indent * 44.0
        toks = []
        for _ in range(rng.randint(2, 5)):
            w = rng.uniform(30, 150)
            toks.append((x, w, rng.choice(_SYNTAX)))
            x += w + rng.uniform(10, 18)
        out.append(toks)
    return out


def _draw_lines(doc: Doc, lines: list[list[tuple[float, float, str]]], x0: float, y0: float, lh: float,
                th: float, flag: int, danger: str, opacity: float = 1.0) -> None:
    with doc.g(opacity=opacity):
        for i, toks in enumerate(lines):
            y = y0 + i * lh
            for x, w, c in toks:
                doc.rect(x0 + x, y, w, th, danger if i == flag else c, th / 2, opacity=1 if i == flag else 0.85)


@scene("ai_code_audit")
def ai_code_audit(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.3, 0.1))
    lines = _lines(rng, 26)
    flag = 15
    while not lines[flag]:
        flag += 1
    x0, y0, lh, th = 380.0, 60.0, 34.0, 14.0
    # the page
    page = Box(280, -20, 1000, 960)
    doc.rect(page.x + 20, page.y, page.w, page.h, "#000", 0, opacity=0.4, extra=f' filter="{doc.blur(24)}"')
    doc.rect(page.x, page.y, page.w, page.h, "#120E20")
    for i in range(len(lines)):          # gutter ticks (no numbers)
        doc.rect(page.x + 40, y0 + i * lh + 4, 26, 6, "#3A3256", 3)
    # the read part above the band is dimmed; the unread part below is plain
    _draw_lines(doc, lines[:flag], x0, y0, lh, th, -1, p.danger, opacity=0.45)
    _draw_lines(doc, lines[flag:], x0, y0 + flag * lh, lh, th, 0, p.danger, opacity=0.9)
    by = y0 + flag * lh + th / 2
    # the scanning band, stopped on the flagged line
    doc.rect(page.x, by - 120, page.w, 120, doc.lin([(0, p.accent, 0), (1, p.accent, 0.22)]))
    doc.rect(page.x, by - 3, page.w, 6, p.accent, opacity=0.85)
    doc.glow(page.x + page.w / 2, by, page.w * 0.5, 30, p.accent, 0.3)
    # gutter marker on the flagged line
    doc.rect(page.x, by - lh / 2, 10, lh, p.danger)
    # the lens: magnified lines around the flag
    cx, cy, r = 1040.0, by, 270.0
    lens_clip = doc.clip_path(f"M{f(cx - r)} {f(cy)}a{f(r)} {f(r)} 0 1 0 {f(2 * r)} 0a{f(r)} {f(r)} 0 1 0 "
                              f"{f(-2 * r)} 0Z")
    doc.circle(cx + 16, cy + 30, r + 26, "#000", opacity=0.45)
    with doc.g(clip=lens_clip):
        doc.rect(cx - r, cy - r, 2 * r, 2 * r, "#1A1430")
        k = 2.0
        with doc.g(f"translate({f(cx)} {f(cy)}) scale({k}) translate({f(-690)} {f(-by)})"):
            _draw_lines(doc, lines[flag - 6:flag], x0, y0 + (flag - 6) * lh, lh, th, -1, p.danger, 0.55)
            _draw_lines(doc, lines[flag:flag + 7], x0, y0 + flag * lh, lh, th, 0, p.danger, 0.95)
        doc.rect(cx - r, cy - 36, 2 * r, 72, p.danger, opacity=0.12)
    doc.circle(cx, cy, r, "none", "#2A2340", 34)
    doc.circle(cx, cy, r, "none", doc.lin([(0, "#E9E4FF", 1), (1, "#7A6FA8", 1)], 0, 0, 1, 1), 22)
    doc.path(f"M{f(cx - r * 0.72)} {f(cy - r * 0.42)}A{f(r * 0.86)} {f(r * 0.86)} 0 0 1 {f(cx - r * 0.1)} "
             f"{f(cy - r * 0.84)}", stroke="#FFFFFF", sw=10, opacity=0.35)
    # handle
    hx, hy = cx + r * 0.72, cy + r * 0.72
    doc.path(f"M{f(hx)} {f(hy)}L{f(hx + 190)} {f(hy + 190)}", stroke="#000", sw=58, opacity=0.35,
             extra=f' filter="{doc.blur(10)}"')
    doc.path(f"M{f(hx)} {f(hy)}L{f(hx + 190)} {f(hy + 190)}", stroke="#2A2340", sw=52)
    doc.path(f"M{f(hx + 14)} {f(hy + 6)}L{f(hx + 186)} {f(hy + 178)}", stroke="#5A4E86", sw=12, opacity=0.8)
    vignette(doc, 0.45)
    doc.focus = Box(360, 250, 1160, 653)
    _ = brief
