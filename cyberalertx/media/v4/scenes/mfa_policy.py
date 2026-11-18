"""Password and MFA requirements: two factors as two objects on one key ring.
A brass key with a masked password engraved on its bow (something you know)
hangs beside a hardware security key (something you have), on a paper desk
under a soft key light.

Variants from the sources only: a named policy framework (CJIS, NIST...) or
the story's product name is set as the headline label; when the story says
tokens or 2FA were rotated / reset, a pair of reset arrows circles the ring;
when it is about a default password (the stated `admin:admin` or a blank
password), the second key is missing (an empty hook) and the password key
carries a tag with the stated credential in the danger colour. No clause
numbers, no sign-in screens, no invented fields."""
from __future__ import annotations

import math
import random
import re

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene
from ._editorial import fit_size, primary_product


def _brass_key(doc: Doc, x: float, y: float, rot: float, s: float, label_col: str) -> None:
    """A key hanging from (x, y) (the bow's hole), rotated by `rot` degrees."""
    metal = doc.lin([(0, "#F3D98B", 1), (0.45, "#C99A3A", 1), (1, "#8A6420", 1)], 0, 0, 1, 0.3)
    with doc.g(f"translate({f(x + 18)} {f(y + 30)}) rotate({f(rot)})", opacity=0.22):
        _key_shape(doc, s, "#000", blur=True)
    with doc.g(f"translate({f(x)} {f(y)}) rotate({f(rot)})"):
        _key_shape(doc, s, metal)
        # engraved masked password on the bow
        for k in range(4):
            doc.circle(-45 * s + k * 30 * s, 120 * s, 10 * s, "#6E4E14", opacity=0.85)
            doc.circle(-45 * s + k * 30 * s + 1.5, 120 * s + 2, 10 * s, "#FFF2C4", opacity=0.35)
        doc.path(f"M{f(-80 * s)} {f(60 * s)}A{f(95 * s)} {f(95 * s)} 0 0 1 {f(60 * s)} {f(40 * s)}",
                 stroke="#FFF6D6", sw=5 * s, opacity=0.6)


def _key_shape(doc: Doc, s: float, fill: str, blur: bool = False) -> None:
    ex = f' filter="{doc.blur(10)}"' if blur else ""
    bow_r = 105 * s
    cy = 115 * s
    d = (f"M0 {f(cy - bow_r)}A{f(bow_r)} {f(bow_r)} 0 1 1 {f(-0.1)} {f(cy - bow_r)}Z"
         f"M0 {f(10 * s)}a{f(16 * s)} {f(16 * s)} 0 1 0 0.1 0Z")
    doc.path(d, fill=fill, extra=f' fill-rule="evenodd"{ex}')
    sx, sy, sw, sl = -22 * s, cy + bow_r - 8 * s, 44 * s, 330 * s
    doc.rect(sx, sy, sw, sl, fill, 6 * s, extra=ex)
    # bit with teeth on the right
    tb = sy + sl - 120 * s
    teeth = (f"M{f(sx + sw)} {f(tb)}h{f(70 * s)}v{f(28 * s)}h{f(-24 * s)}v{f(16 * s)}h{f(24 * s)}v{f(30 * s)}"
             f"h{f(-36 * s)}v{f(16 * s)}h{f(36 * s)}v{f(30 * s)}H{f(sx + sw)}Z")
    doc.path(teeth, fill=fill, extra=ex)


def _token(doc: Doc, x: float, y: float, rot: float, s: float, accent: str) -> None:
    """A hardware security key hanging from (x, y) (its lanyard hole)."""
    w, h = 170 * s, 360 * s
    with doc.g(f"translate({f(x + 20)} {f(y + 34)}) rotate({f(rot)})", opacity=0.25):
        doc.rect(-w / 2, -26 * s, w, h, "#000", 34 * s, extra=f' filter="{doc.blur(12)}"')
    with doc.g(f"translate({f(x)} {f(y)}) rotate({f(rot)})"):
        # USB-C connector at the bottom
        doc.rect(-38 * s, h - 40 * s, 76 * s, 86 * s, doc.lin([(0, "#E9EDF1", 1), (0.5, "#9BA4AE", 1),
                                                                 (1, "#D0D6DC", 1)], 0, 0, 1, 0), 14 * s)
        doc.rect(-24 * s, h + 10 * s, 48 * s, 18 * s, "#3B4148", 9 * s)
        body = doc.lin([(0, "#3A3D44", 1), (0.5, "#1C1E23", 1), (1, "#101114", 1)], 0, 0, 1, 0.2)
        d = (f"M{f(-w / 2)} {f(-26 * s + 34 * s)}a{f(34 * s)} {f(34 * s)} 0 0 1 {f(34 * s)} {f(-34 * s)}"
             f"h{f(w - 68 * s)}a{f(34 * s)} {f(34 * s)} 0 0 1 {f(34 * s)} {f(34 * s)}V{f(h - 30 * s)}"
             f"a{f(30 * s)} {f(30 * s)} 0 0 1 {f(-30 * s)} {f(30 * s)}H{f(-w / 2 + 30 * s)}"
             f"a{f(30 * s)} {f(30 * s)} 0 0 1 {f(-30 * s)} {f(-30 * s)}Z"
             f"M0 {f(0)}a{f(18 * s)} {f(18 * s)} 0 1 0 0.1 0Z")
        doc.path(d, fill=body, extra=' fill-rule="evenodd"')
        doc.rect(-w / 2 + 10 * s, -18 * s, 8 * s, h - 30 * s, "#FFFFFF", 4 * s, opacity=0.10)
        # gold touch contact
        cy = h * 0.52
        doc.circle(0, cy, 52 * s, doc.lin([(0, "#F7DE8E", 1), (1, "#B8892B", 1)], 0, 0, 1, 1))
        doc.circle(0, cy, 40 * s, "none", "#8A6420", 2.5 * s, 0.6)


def _ring(doc: Doc, cx: float, cy: float, r: float) -> None:
    doc.add(f'<circle cx="{f(cx + 10)}" cy="{f(cy + 22)}" r="{f(r)}" fill="none" stroke="#000" stroke-width="16" '
            f'opacity="0.18" filter="{doc.blur(7)}"/>')
    doc.circle(cx, cy, r, "none", "#7E8790", 16)
    doc.circle(cx, cy, r, "none", "#D9DEE3", 7)
    doc.path(f"M{f(cx - r * 0.7)} {f(cy - r * 0.7)}A{f(r)} {f(r)} 0 0 1 {f(cx + r * 0.5)} {f(cy - r * 0.86)}",
             stroke="#FFFFFF", sw=3, opacity=0.8)


@scene("mfa_policy")
def mfa_policy(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.62, 0.2))
    t = brief.text
    default_pw = bool(re.search(r"default .{0,12}password|admin:admin|blank password", t))
    reset = bool(re.search(r"rotat\w* .{0,30}(token|secret|key)|2fa resets?|mfa resets?|reset .{0,10}2fa", t))
    framework = next((e for e in brief.entities if e in ("CJIS", "NIST", "PCI", "HIPAA", "NIS2")), "")
    name = framework or primary_product(brief)[0]
    if name in ("MFA", "API", "2FA", "SMS"):
        name = ""
    factor = "MFA" if re.search(r"\bmfa\b|multi-factor", t) else "2FA" if re.search(r"\b2fa\b|two-factor", t) else ""

    rx, ry, rr = 1060.0, 150.0, 80.0
    # keys hang from the bottom of the ring
    _brass_key(doc, rx - 30, ry + rr - 8, 24, 1.3, p.danger)
    if default_pw:
        # the second factor is missing: an empty hook on the ring, a danger tag on the key
        doc.path(f"M{f(rx + 40)} {f(ry + rr - 12)}c18 30 46 40 54 80", stroke="#7E8790", sw=8, dash="4 14")
        cred = "admin:admin" if "admin:admin" in t else "blank password" if "blank password" in t else "default"
        tx, ty = 1150.0, 470.0
        doc.path(f"M{f(rx + 4)} {f(ry + rr)}L{f(tx)} {f(ty)}", stroke="#5B5348", sw=3)
        tw = T.measure(cred, 40, "mono_bold") + 70
        with doc.g(f"rotate(-6 {f(tx)} {f(ty)})"):
            doc.rect(tx + 6, ty - 34 + 10, tw, 76, "#000", 10, opacity=0.18, extra=f' filter="{doc.blur(6)}"')
            doc.rect(tx, ty - 34, tw, 76, p.danger, 10)
            doc.circle(tx + 24, ty + 4, 9, p.bg0)
            doc.text(cred, tx + 46, ty + 18, 40, "#FFFFFF", "mono_bold")
    else:
        _token(doc, rx + 36, ry + rr - 6, -24, 1.3, p.accent)
    _ring(doc, rx, ry, rr)
    if reset:     # tokens / second factors rotated or reset
        r2 = rr + 62
        for a0, a1 in ((150, 300), (-30, 120)):
            x0, y0 = rx + r2 * math.cos(math.radians(a0)), ry + r2 * math.sin(math.radians(a0))
            x1, y1 = rx + r2 * math.cos(math.radians(a1)), ry + r2 * math.sin(math.radians(a1))
            doc.path(f"M{f(x0)} {f(y0)}A{f(r2)} {f(r2)} 0 0 1 {f(x1)} {f(y1)}", stroke=p.bg0, sw=20)
            doc.path(f"M{f(x0)} {f(y0)}A{f(r2)} {f(r2)} 0 0 1 {f(x1)} {f(y1)}", stroke=p.accent, sw=10)
            ang = math.radians(a1 + 90)
            doc.poly([(x1 + 30 * math.cos(ang), y1 + 30 * math.sin(ang)),
                      (x1 + 22 * math.cos(ang + 2.3), y1 + 22 * math.sin(ang + 2.3)),
                      (x1 + 22 * math.cos(ang - 2.3), y1 + 22 * math.sin(ang - 2.3))], p.accent)

    # headline label: what the policy / story is
    lx = 140
    if name:
        size = fit_size(name, 150, 560, "display")
        doc.text(name, lx, 480, size, p.ink, "display")
    if factor:
        doc.text(f"password + {factor}" if not default_pw else "no second factor", lx + 4,
                 480 + (84 if name else 0), 44, p.danger if default_pw else p.accent, "ui_bold")
    vignette(doc, 0.3)
    doc.focus = Box(80, 50, 1420, 799)
