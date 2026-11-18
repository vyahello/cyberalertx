"""Ransomware impact: the systems the story names, wrapped in a heavy chain
and shut with one large padlock, lit red from behind. The locked object
follows the sources: a hypervisor host carrying a row of virtual machines
when the story is about ESXi / vCenter, a stack of databases when the claim
is about databases, a stack of file folders otherwise. Records drift off the
top only when the sources report (or a gang claims) data theft.

No ransom note, file extension, victim ID, contact or file name is drawn:
none is stated by the sources."""
from __future__ import annotations

import math
import random
import re

from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene
from ._editorial import fit_size, primary_product


def _kind(text: str) -> str:
    if re.search(r"esxi|vcenter|hypervisor|гіпервізор", text):
        return "vm"
    if re.search(r"database|бази даних|\bsql\b", text):
        return "db"
    return "fs"


def _host(doc: Doc, b: Box, rng: random.Random) -> None:
    """A hypervisor host: one physical server carrying a row of VMs."""
    doc.shadow(b.x, b.y, b.w, b.h, 14, 1.4)
    doc.rect(b.x, b.y, b.w, b.h, doc.lin([(0, "#3A2C2A", 1), (1, "#1C1413", 1)]), 14, stroke="#4A3835", sw=2)
    doc.rect(b.x + 20, b.y + 20, b.w - 40, 34, "#120C0B", 6)
    for i in range(int((b.w - 60) // 18)):
        doc.rect(b.x + 30 + i * 18, b.y + 28, 10, 18, "#2E2120", 2)
    n = 5
    gw = (b.w - 60 - (n - 1) * 18) / n
    for k in range(n):
        x = b.x + 30 + k * (gw + 18)
        doc.rect(x, b.y + 80, gw, b.h - 110, doc.lin([(0, "#F3E6E1", 1), (1, "#CDB9B2", 1)]), 10)
        doc.rect(x, b.y + 80, gw, 26, "#B9A49C", 10)
        doc.rect(x, b.y + 96, gw, 10, "#B9A49C")
        for j in range(3):
            doc.rect(x + 16, b.y + 130 + j * 30, gw * (0.7 - 0.15 * j), 10, "#8F7A73", 5)
        doc.text("VM", x + gw / 2, b.b - 50, 34, "#5A4440", "display", anchor="middle")


def _dbs(doc: Doc, cx: float, top: float, rx: float, ry: float, n: int) -> None:
    body = doc.lin([(0, "#9A7D75", 1), (0.45, "#6A524C", 1), (1, "#2E2220", 1)], 0, 0, 1, 0)
    hgt = 120.0
    for k in reversed(range(n)):
        y = top + k * (hgt + 10)
        doc.path(f"M{f(cx - rx)} {f(y)}V{f(y + hgt)}A{f(rx)} {f(ry)} 0 0 0 {f(cx + rx)} {f(y + hgt)}V{f(y)}Z",
                 fill=body)
        doc.path(f"M{f(cx - rx)} {f(y + hgt)}A{f(rx)} {f(ry)} 0 0 0 {f(cx + rx)} {f(y + hgt)}", stroke="#1C1413",
                 sw=8)
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(y)}" rx="{f(rx)}" ry="{f(ry)}" fill="#B89A91"/>')
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(y)}" rx="{f(rx - 20)}" ry="{f(ry - 8)}" fill="none" '
                f'stroke="#8C716A" stroke-width="3"/>')


def _folders(doc: Doc, cx: float, top: float, w: float, n: int) -> None:
    for k in range(n):
        y = top + k * 70
        x = cx - w / 2 + (k % 2) * 18 - 9
        doc.shadow(x, y, w, 220, 10, 0.5)
        doc.path(f"M{f(x)} {f(y)}h{f(w * 0.32)}l26 30H{f(x + w)}V{f(y + 220)}H{f(x)}Z",
                 fill=doc.lin([(0, "#C9A27A", 1), (1, "#8E6A48", 1)]))
        doc.rect(x, y + 30, w, 190, doc.lin([(0, "#E2BE93", 1), (1, "#A37C55", 1)]), 6)


def _chain(doc: Doc, a: tuple[float, float], b: tuple[float, float]) -> None:
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    step = 50.0
    n = int(L / step)
    deg = math.degrees(ang)
    for k in range(n + 1):
        x, y = a[0] + math.cos(ang) * k * step, a[1] + math.sin(ang) * k * step
        flat = k % 2 == 1
        ry = 9.0 if flat else 22.0
        doc.add(f'<ellipse cx="{f(x + 4)}" cy="{f(y + 10)}" rx="36" ry="{f(ry)}" fill="none" stroke="#000" '
                f'stroke-width="13" opacity="0.35" transform="rotate({f(deg)} {f(x + 4)} {f(y + 10)})"/>')
        doc.add(f'<ellipse cx="{f(x)}" cy="{f(y)}" rx="36" ry="{f(ry)}" fill="none" stroke="#8D949B" '
                f'stroke-width="13" transform="rotate({f(deg)} {f(x)} {f(y)})"/>')
        doc.add(f'<ellipse cx="{f(x)}" cy="{f(y - 3)}" rx="34" ry="{f(max(ry - 4, 3))}" fill="none" '
                f'stroke="#E3E7EA" stroke-width="3" opacity="0.7" transform="rotate({f(deg)} {f(x)} {f(y)})"/>')


def _padlock(doc: Doc, cx: float, cy: float, s: float, danger: str) -> None:
    bw, bh = s, s * 0.82
    x, y = cx - bw / 2, cy - bh / 2 + s * 0.2
    r = bw * 0.30
    doc.glow(cx, cy, s * 0.9, s * 0.8, danger, 0.35)
    leg = f"M{f(cx - r)} {f(y + 6)}V{f(y - s * 0.22)}A{f(r)} {f(r)} 0 0 1 {f(cx + r)} {f(y - s * 0.22)}V{f(y + 6)}"
    doc.path(leg, stroke="#5F666D", sw=s * 0.13)
    doc.path(leg, stroke="#C9D0D6", sw=s * 0.05, opacity=0.8)
    doc.rect(x + 14, y + 30, bw, bh, "#000", s * 0.12, opacity=0.5, extra=f' filter="{doc.blur(14)}"')
    doc.rect(x, y, bw, bh, doc.lin([(0, "#4A4F56", 1), (0.5, "#2A2E33", 1), (1, "#16181B", 1)], 0, 0, 1, 1),
             s * 0.12)
    doc.rect(x, y, bw, bh, "none", s * 0.12, stroke=danger, sw=5, opacity=0.9)
    doc.rect(x + 10, y + 10, bw - 20, bh * 0.22, "#FFFFFF", s * 0.08, opacity=0.08)
    kx, ky = cx, y + bh * 0.46
    doc.circle(kx, ky, s * 0.09, danger)
    doc.poly([(kx - s * 0.045, ky), (kx + s * 0.045, ky), (kx + s * 0.065, ky + s * 0.22),
              (kx - s * 0.065, ky + s * 0.22)], danger)


def _sheets(doc: Doc, pts: list[tuple[float, float, float]], color: str) -> None:
    for x, y, rot in pts:
        with doc.g(f"rotate({f(rot)} {f(x)} {f(y)})"):
            doc.rect(x - 34, y - 44, 68, 88, "#F3E6E1", 5)
            for j in range(4):
                doc.rect(x - 22, y - 28 + j * 16, 44 - (j % 2) * 14, 6, "#8F7A73", 3)
            doc.rect(x - 34, y - 44, 68, 88, "none", 5, stroke=color, sw=3)


@scene("ransomware_impact")
def ransomware_impact(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.5, 0.35))
    doc.glow(820, 470, 620, 330, p.danger, 0.22)
    t = brief.text
    kind = _kind(t)
    theft = bool(re.search(r"data theft|stole|stolen|exfiltrat|викра", t))
    if theft:
        _sheets(doc, [(1180, 230, 12), (1310, 150, -8), (1440, 90, 16)], p.danger)
        doc.path("M1040 300C1120 260 1200 200 1460 60", stroke=p.danger, sw=4, dash="4 14", opacity=0.8)
    if kind == "vm":
        _host(doc, Box(330, 250, 940, 420), rng)
        x0, x1, y0, y1 = 330.0, 1270.0, 290.0, 640.0
    elif kind == "db":
        _dbs(doc, 800, 250, 300, 70, 3)
        x0, x1, y0, y1 = 480.0, 1120.0, 280.0, 660.0
    else:
        _folders(doc, 800, 240, 560, 3)
        x0, x1, y0, y1 = 500.0, 1100.0, 260.0, 640.0
    # two chains crossed over the object, locked where they cross
    _chain(doc, (x0, y0), (x1, y1))
    _chain(doc, (x0, y1), (x1, y0))
    _padlock(doc, 800, 470, 300, p.danger)
    name = primary_product(brief)[0]
    if name and name not in ("BYOD", "LLMs"):
        size = fit_size(name, 60, 640, "display")
        doc.text(name, 90, 840, size, p.ink, "display")
    doc.focus = Box(250, 90, 1150, 647)
    vignette(doc, 0.55)
