"""GitHub Actions SHA pinning and how it was got around.

Evidence used (s:2357990c49651d): pinning GitHub Actions to an exact version
of their code (SHA pinning) is the go-to defence against supply-chain
attacks; in March 2026 the hijackers of Trivy got around it by planting
malicious code made to look like GitHub's official checkout action.

What is drawn: a version tag (`@v4`) is a label that can be moved; a commit
SHA is a fingerprint of one exact version of the code and cannot be moved;
but a pinned fingerprint still names whatever code it was taken from, here a
look-alike of the official checkout action. Not drawn: YAML, repository
names other than `actions/checkout`, hex hashes (a SHA is an abstract
fingerprint glyph), how the look-alike was reached, or anything the source
truncates ("they even labeled it a...").

Two compositions (ALTERNATIVES):

* "a" the pin: a large push-pin whose head carries the pinned fingerprint is
  driven through the look-alike card, which lies over the official one; the
  tag hangs on the left and visibly moves.
* "b" the history line: the official action's history as a rail of commits
  with the `@v4` tag that moves along it; below and apart from the rail the
  look-alike, which the pinned fingerprint names.

"a" is the default: one large object (the pin) carries the story's point,
and at feed size it reads as "pinned, but into the wrong one".
"""
from __future__ import annotations

import random
from typing import Callable

from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, icon
from . import scene

_INK = "#17181C"


def _glyph_bits(rng: random.Random) -> list[list[bool]]:
    """A 5x5 mirrored fingerprint pattern (abstract: not a hash)."""
    while True:
        half = [[rng.random() < 0.55 for _ in range(3)] for _ in range(5)]
        bits = [row + [row[1], row[0]] for row in half]
        n = sum(sum(r) for r in bits)
        if 9 <= n <= 17:
            return bits


def _glyph(doc: Doc, x: float, y: float, size: float, bits: list[list[bool]], color: str, bg: str = "",
           r: float = 0) -> None:
    """Draw a fingerprint glyph in a `size` square at (x, y)."""
    if bg:
        doc.rect(x, y, size, size, bg, r or size * 0.12)
    pad = size * 0.14
    cell = (size - 2 * pad) / 5
    d = []
    for i, row in enumerate(bits):
        for j, on in enumerate(row):
            if on:
                d.append(f"M{f(x + pad + j * cell)} {f(y + pad + i * cell)}h{f(cell)}v{f(cell)}h-{f(cell)}Z")
    doc.path("".join(d), fill=color)


def _tag(doc: Doc, x: float, y: float, w: float, label: str, *, fill: str, ink: str, ghost: bool = False,
         angle: float = 0) -> None:
    """A paper luggage tag hanging from (x, y) (the eyelet)."""
    h = w * 0.5
    with doc.g(transform=f"rotate({f(angle)} {f(x)} {f(y)})", opacity=0.45 if ghost else 1.0):
        d = (f"M{f(x - 30)} {f(y - h / 2)}H{f(x + w)}V{f(y + h / 2)}H{f(x - 30)}L{f(x - 70)} {f(y + h / 4)}"
             f"V{f(y - h / 4)}Z")
        if ghost:
            doc.path(d, stroke=ink, sw=3, dash="10 9")
        else:
            doc.path(d, fill="#000", opacity=0.18, extra=f' transform="translate(8 16)" filter="{doc.blur(10)}"')
            doc.path(d, fill=fill, stroke=ink, sw=2.5)
            doc.circle(x - 34, y, 11, "#F5EFE4", ink, 2.5)
            doc.text(label, x + 10, y + h * 0.2, h * 0.56, ink, "mono_bold")


def _card(doc: Doc, b: Box, *, title: str, owner: str, bits: list[list[bool]], accent: str, official: bool,
          glyph: float) -> tuple[float, float]:
    """An action, as a card: its name, (for the official one) the owner line,
    and the fingerprint of its code at the right. Returns the glyph centre."""
    p = doc.pal
    doc.shadow(b.x, b.y, b.w, b.h, 18, 1.0)
    doc.rect(b.x, b.y, b.w, b.h, "#FFFDF8", 18, stroke=accent if not official else p.line,
             sw=5 if not official else 1.5)
    icon(doc, "file", b.x + 50, b.y + 60, 46, accent, 2.6)
    doc.text(title, b.x + 88, b.y + 78, 52, _INK, "mono_bold")
    gx, gy = b.r - 36 - glyph, b.b - 36 - glyph
    _glyph(doc, gx, gy, glyph, bits, accent if not official else _INK, bg="#F1EADD")
    if official:
        doc.text(owner, b.x + 42, b.y + 140, 28, p.muted, "mono")
        icon(doc, "check", b.x + 66, b.b - 76, 54, p.safe, 5)
        doc.text("official", b.x + 106, b.b - 58, 46, p.safe, "ui_bold")
    else:
        icon(doc, "warn", b.x + 66, b.b - 76, 54, accent, 3.4)
        doc.text("look-alike", b.x + 106, b.b - 58, 46, accent, "ui_bold")
    return gx + glyph / 2, gy + glyph / 2


def _pin(doc: Doc, tip: tuple[float, float], scale: float, angle: float, color: str) -> None:
    """A push-pin (side view) driven in at `tip`, leaning by `angle` degrees."""
    tx, ty = tip
    k = scale
    # cast shadow on the card, falling right
    doc.path(f"M{f(tx)} {f(ty)}L{f(tx + 210 * k)} {f(ty - 70 * k)}", stroke="#000", sw=34 * k, opacity=0.16,
             extra=f' filter="{doc.blur(10)}"')
    doc.circle(tx, ty, 7 * k, "#000", opacity=0.5)
    with doc.g(transform=f"translate({f(tx)} {f(ty)}) rotate({f(angle)}) scale({k:.3f})"):
        doc.path("M-4 -100L0 0L4 -100Z", fill="#8D939C")                       # needle
        doc.path("M-62 -100H62Q66 -118 50 -122H-50Q-66 -118 -62 -100Z", fill=color)  # flange
        doc.path("M-34 -122L-26 -210H26L34 -122Z", fill=color)                  # waist
        doc.rect(-70, -262, 140, 56, color, 20)                                  # head
        doc.rect(-70, -262, 140, 56, doc.lin([(0, "#FFFFFF", 0.35), (1, "#FFFFFF", 0.0)], 0, 0, 1, 0), 20)
        doc.rect(-30, -206, 14, 80, "#FFFFFF", 6, opacity=0.25)


def _pin_comp(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.6, 0.15))
    official_bits, fake_bits = _glyph_bits(rng), _glyph_bits(rng)

    # left: the tag hangs from a rail and can be moved (ghost = where it was)
    doc.line((330, 112), (790, 112), _INK, 6)
    doc.path("M400 112V178", stroke=_INK, sw=3, opacity=0.4, dash="6 6")
    _tag(doc, 400, 214, 190, "@v4", fill="#F7E7B4", ink=_INK, ghost=True, angle=3)
    doc.path("M600 112V178", stroke=_INK, sw=3)
    _tag(doc, 600, 214, 190, "", fill="#F7E7B4", ink=_INK, angle=-4)
    with doc.g(transform="rotate(-4 600 214)"):
        doc.text("@v4", 600, 214 + 95 * 0.22, 58, _INK, "mono_bold")
    doc.path("M420 300Q520 350 620 306", stroke=_INK, sw=4)
    doc.poly([(634, 300), (616, 322), (608, 298)], _INK)
    doc.text("a tag can be moved", 340, 404, 40, _INK, "ui_bold")
    doc.text("a SHA pins one", 340, 452, 34, p.muted, "ui")
    doc.text("exact version", 340, 494, 34, p.muted, "ui")

    # right: the official action behind, the look-alike in front; the pin
    # (the pinned SHA) goes into the look-alike's fingerprint
    _card(doc, Box(840, 56, 580, 300), title="checkout", owner="actions/checkout", bits=official_bits,
          accent=_INK, official=True, glyph=180)
    tip = _card(doc, Box(700, 392, 780, 372), title="checkout", owner="", bits=fake_bits, accent=p.danger,
                official=False, glyph=270)
    doc.text("pinned SHA", 640, 640, 52, p.danger, "ui_bold", anchor="end")
    doc.path(f"M654 622C760 622 {f(tip[0] - 260)} {f(tip[1] + 20)} {f(tip[0] - 16)} {f(tip[1] + 4)}",
             stroke=p.danger, sw=4)
    _pin(doc, tip, 1.15, 30, p.danger)
    doc.focus = Box(300, 40, 1300, 731)


def _rail_comp(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.3, 0.1))
    commits = [_glyph_bits(rng) for _ in range(6)]
    fake = _glyph_bits(rng)
    ry = 330.0
    doc.text("actions/checkout", 60, 132, 46, _INK, "mono_bold")
    doc.text("official history", 64, 178, 30, p.muted, "ui")
    doc.line((40, ry), (1560, ry), _INK, 8)
    xs = [140 + i * 250 for i in range(6)]
    for x, bits in zip(xs, commits):
        doc.rect(x - 54, ry - 54, 108, 108, "#FFFDF8", 16, stroke=_INK, sw=4)
        _glyph(doc, x - 46, ry - 46, 92, bits, _INK)
    # the tag: where it points now, and the commit it pointed at before
    _tag(doc, xs[4] + 80, ry - 140, 200, "@v4", fill="#F7E7B4", ink=_INK, angle=0)
    _tag(doc, xs[2] + 80, ry - 140, 200, "@v4", fill="#F7E7B4", ink=_INK, ghost=True)
    doc.path(f"M{xs[2] + 200} {ry - 196}Q{(xs[2] + xs[4]) / 2 + 100} {ry - 260} {xs[4] + 20} {ry - 200}", stroke=_INK,
             sw=3.5)
    doc.poly([(xs[4] + 30, ry - 192), (xs[4] + 6, ry - 196), (xs[4] + 22, ry - 214)], _INK)
    for x in (xs[2], xs[4]):
        doc.line((x, ry - 112), (x, ry - 56), _INK, 3, dash="5 6")
    doc.text("a tag can be moved", xs[2] + 20, ry - 270, 32, _INK, "ui_bold")

    # below, apart from the rail: the look-alike, named exactly by the pinned SHA
    lx, ly, ls = 1010, 560, 270
    doc.line((lx + ls / 2, ry + 70), (lx + ls / 2, ly - 20), p.danger, 4, dash="4 14")
    icon(doc, "cross", lx + ls / 2, (ry + ly) / 2 + 20, 46, p.danger, 4)
    doc.shadow(lx, ly, ls, ls, 26, 1.0)
    _glyph(doc, lx, ly, ls, fake, "#FFFFFF", bg=p.danger, r=26)
    doc.text("look-alike", lx + ls + 36, ly + 92, 50, p.danger, "ui_bold")
    doc.text("checkout", lx + ls + 36, ly + 152, 40, _INK, "mono_bold")
    # the pinned reference: the same fingerprint, fixed with a pin
    px, py, ps = 300, 610, 170
    doc.rect(px - 30, py - 30, ps + 60, ps + 60, "#FFFDF8", 24, stroke=_INK, sw=3)
    _glyph(doc, px, py, ps, fake, p.danger)
    doc.text("pinned SHA", px - 28, py + ps + 96, 44, _INK, "ui_bold")
    doc.path(f"M{px + ps + 50} {py + ps / 2}C{px + ps + 260} {py + ps / 2} {lx - 260} {ly + ls / 2} {lx - 30} "
             f"{ly + ls / 2}", stroke=p.danger, sw=7)
    doc.poly([(lx - 12, ly + ls / 2), (lx - 44, ly + ls / 2 - 18), (lx - 44, ly + ls / 2 + 18)], p.danger)
    doc.text("same fingerprint", (px + ps + lx) / 2 + 30, ly + ls / 2 - 30, 32, p.danger, "ui_bold",
             anchor="middle")
    doc.focus = Box(0, 0, 1600, 900)


ALTERNATIVES: dict[str, Callable[[Doc, EditorialBrief, random.Random], None]] = {"a": _pin_comp, "b": _rail_comp}


@scene("ci_pinning")
def ci_pinning(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    _pin_comp(doc, brief, rng)
