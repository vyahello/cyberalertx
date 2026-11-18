"""Cloud-provider breaches: a company's records sit in storage at a cloud or
third-party provider, and a set of them is copied out. When the sources say
the attacker used a provider's trusted access (an access key or role shared
with customers), the key is drawn opening several customer accounts.

Generic storage browser, no vendor console; destination is a documentation
address (RFC 5737) or a `.example` host."""
from __future__ import annotations

import random
import re

from ..brief import EditorialBrief
from ..kit import Box, Doc, arrow, background, f, icon, pill, window
from . import scene


def _file_icon(doc: Doc, x: float, y: float, folder: bool, color: str) -> None:
    if folder:
        doc.path(f"M{f(x)} {f(y + 4)}h9l3 3h12v15h-24z", fill=color, opacity=0.85)
    else:
        doc.path(f"M{f(x + 2)} {f(y)}h13l6 6v17h-19z", fill="#FFFFFF", stroke=color, sw=1.6)
        doc.path(f"M{f(x + 15)} {f(y)}v6h6", stroke=color, sw=1.6)


def _sheet(doc: Doc, cx: float, cy: float, rot: float, color: str, opacity: float = 1.0) -> None:
    """A small record sheet in flight."""
    with doc.g(f"translate({f(cx)} {f(cy)}) rotate({f(rot)})", opacity=opacity):
        doc.rect(-25, -31, 50, 62, "#000", 4, opacity=0.12, extra=f' filter="{doc.blur(4)}"')
        doc.rect(-26, -34, 52, 64, "#FFFFFF", 4, stroke=color, sw=1.8)
        for k in range(4):
            doc.rect(-17, -22 + k * 11, 34 - (k % 2) * 10, 5, color, 2, opacity=0.5)


@scene("cloud_breach")
def cloud_breach(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    background(doc, light=(0.35, 0.15))
    trusted = re.search(r"trusted (aws )?access|iam credential|access key|credentials for|role", text) is not None
    secrets = re.search(r"secret|credential", text) is not None
    provider = re.search(r"cloud provider|third-party", text) is not None

    # ---- the provider environment: a dashed boundary
    env = Box(270 if trusted else 70, 110, 830 if trusted else 1020, 690)
    doc.rect(env.x, env.y, env.w, env.h, p.surface, 26, opacity=0.35)
    doc.rect(env.x, env.y, env.w, env.h, "none", 26, stroke=p.accent, sw=2.5, extra=' stroke-dasharray="10 8"')
    # cloud glyph + label on the boundary
    lx, ly = env.x + 40, env.y
    doc.rect(lx - 12, ly - 22, 330, 44, p.bg0, 22)
    doc.path(f"M{f(lx)} {f(ly + 11)}H{f(lx + 36)}A10 10 0 0 0 {f(lx + 34)} {f(ly - 9)}A14 14 0 0 0 "
             f"{f(lx + 8)} {f(ly - 12)}A10 10 0 0 0 {f(lx)} {f(ly + 11)}Z", stroke=p.accent, sw=2.4)
    doc.text("third-party cloud provider" if provider else "customer cloud accounts" if trusted else "cloud account",
             lx + 50, ly + 7, 20, p.ink, "ui_bold")

    # tenants behind the main one (trusted-access variant)
    win = Box(env.x + 60, env.y + 90, env.w - 120, env.h - 150)
    if trusted:
        for k in (2, 1):
            tb = Box(win.x + 26 * k, win.y - 24 * k, win.w, win.h)
            window(doc, tb, title=f"customer-{'abc'[k]} / storage", surface="#F3F6F9", depth=0.4)
    body = window(doc, win, title="customer-a / storage / records" if trusted else "storage / company-records",
                  surface="#FFFFFF", depth=0.8)

    # ---- the object list
    fourth = ("prod-secrets.json", False, "sec", "6 KB") if secrets else ("contracts/", True, "", "--")
    files = [("exports/", True, "", "--"), ("customers_2024.parquet", False, "rec", "1.8 GB"),
             ("employees.csv", False, "rec", "42 MB"), fourth,
             ("billing_history.parquet", False, "rec", "960 MB"), ("logs/", True, "", "--"),
             ("backups/", True, "", "--")]
    hx = body.x + 30
    hy = body.y + 46
    doc.text("NAME", hx + 56, hy, 13, p.muted, "ui_bold", tracking=1.5)
    doc.text("SIZE", body.r - 200, hy, 13, p.muted, "ui_bold", tracking=1.5)
    doc.text("STATUS", body.r - 110, hy, 13, p.muted, "ui_bold", tracking=1.5)
    doc.line((body.x + 20, hy + 14), (body.r - 20, hy + 14), p.line, 1)
    rh = 58
    taken: list[tuple[float, float]] = []
    for i, (name, folder, tag, size) in enumerate(files):
        ry = hy + 30 + i * rh
        if ry + rh > body.b - 6:
            break
        hit = tag != ""
        if hit:
            doc.rect(body.x + 12, ry - 6, body.w - 24, rh - 8, p.danger, 6, opacity=0.08)
            doc.rect(body.x + 12, ry - 6, 4, rh - 8, p.danger)
        doc.rect(hx, ry + 8, 20, 20, "#FFFFFF", 4, stroke=p.danger if hit else p.line, sw=1.6)
        if hit:
            doc.path(f"M{f(hx + 4)} {f(ry + 18)}l5 5l8-10", stroke=p.danger, sw=2.4)
        _file_icon(doc, hx + 42, ry + 6, folder, p.accent if not hit else p.danger)
        doc.text(name, hx + 80, ry + 26, 20, p.on_surface, "mono_bold" if hit else "mono")
        doc.text(size, body.r - 200, ry + 26, 17, p.muted, "mono")
        if hit:
            doc.text("copied", body.r - 110, ry + 26, 17, p.danger, "ui_bold")
            taken.append((body.r - 20, ry + 18))

    # ---- records leaving the provider
    dest = Box(1300, 330, 260, 250)
    if taken:
        sx, sy = env.r + 6, sum(y for _, y in taken) / len(taken)
        x0 = body.r + 6
        doc.circle(x0, sy, 6, p.danger)
        doc.path(f"M{f(x0)} {f(sy)}C{f(x0 + 120)} {f(sy)} {f(dest.x - 90)} {f(dest.cy)} "
                 f"{f(dest.x - 14)} {f(dest.cy)}", stroke=p.danger, sw=3, dash="2 10")
        arrow(doc, [(dest.x - 40, dest.cy), (dest.x - 10, dest.cy)], p.danger, sw=3, head=16)
        n = 3 if dest.x - x0 < 260 else 4
        for k in range(n):
            t = (k + 0.7) / (n + 0.6)
            x = (1 - t) ** 3 * x0 + 3 * (1 - t) ** 2 * t * (x0 + 120) + 3 * (1 - t) * t * t * \
                (dest.x - 90) + t ** 3 * (dest.x - 14)
            y = (1 - t) ** 3 * sy + 3 * (1 - t) ** 2 * t * sy + 3 * (1 - t) * t * t * dest.cy + t ** 3 * dest.cy
            _sheet(doc, x, y, rng.uniform(-14, 14), p.danger)
        _ = sx
    # destination: an outside host
    doc.shadow(dest.x, dest.y, dest.w, dest.h, 14, 0.8)
    doc.rect(dest.x, dest.y, dest.w, dest.h, "#1A2433", 14)
    icon(doc, "download", dest.cx, dest.y + 70, 54, p.danger, 3)
    doc.text("outside host", dest.cx, dest.y + 140, 20, "#FFFFFF", "ui_bold", anchor="middle")
    doc.text("203.0.113.47", dest.cx, dest.y + 170, 17, "#A9B6C6", "mono", anchor="middle")
    doc.rect(dest.x + 30, dest.y + 200, dest.w - 60, 10, "#2E3B4F", 5)
    doc.rect(dest.x + 30, dest.y + 200, (dest.w - 60) * 0.68, 10, p.danger, 5)

    # ---- trusted access: the provider's own key opens customer accounts
    if trusted:
        kx, ky = 26, 300
        doc.shadow(kx, ky, 220, 210, 14, 0.8)
        doc.rect(kx, ky, 220, 210, "#FFFFFF", 14, stroke=p.line)
        icon(doc, "key", kx + 110, ky + 66, 64, p.danger, 2.8)
        doc.text("platform access", kx + 110, ky + 132, 18, p.on_surface, "ui_bold", anchor="middle")
        doc.text("key ****7F2Q", kx + 110, ky + 160, 16, p.muted, "mono", anchor="middle")
        pill(doc, kx + 110, ky + 222, "trusted by customers", fg=p.on_surface, bg=p.surface2, size=13, font="ui",
             anchor="middle")
        targets = [(win.x + 26 * 2 + 6, win.y - 48 + 14), (win.x + 26 + 6, win.y - 24 + 14), (win.x - 10, win.y + 120)]
        for k, (tx, ty) in enumerate(targets):
            arrow(doc, [(kx + 228, ky + 60 + k * 36), (tx, ty)], p.danger, sw=2.5, head=12,
                  dash="" if k == 2 else "6 6")

    doc.focus = Box(env.x, 100, min(1500, dest.r) - env.x, (min(1500, dest.r) - env.x) * 9 / 16)
