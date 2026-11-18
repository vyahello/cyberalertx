"""Product drawings for advisory scenes: the affected product as a careful
elevation (rack server, network appliance, CPU package, phone, browser,
database cluster, laptop, code editor, 3D printer). Generic on purpose: no
logos, no vendor interface. Each takes a centre and a width and returns the
point a status tag should hang from."""
from __future__ import annotations

import random

from ..kit import Doc, f, icon
from ._editorial import phone, rack_unit

Pt = tuple[float, float]


def _box3(doc: Doc, x: float, y: float, w: float, h: float, depth: float, front: str, top: str, side: str,
          r: float = 4) -> None:
    """Front face at (x, y, w, h) with a top and right face receding up-right."""
    dx, dy = depth * 0.55, depth * 0.32
    doc.poly([(x, y), (x + dx, y - dy), (x + w + dx, y - dy), (x + w, y)], top)
    doc.poly([(x + w, y), (x + w + dx, y - dy), (x + w + dx, y + h - dy), (x + w, y + h)], side)
    doc.rect(x, y, w, h, front, r)


def contact(doc: Doc, cx: float, y: float, w: float, opacity: float = 0.5) -> None:
    doc.add(f'<ellipse cx="{f(cx)}" cy="{f(y)}" rx="{f(w / 2)}" ry="{f(w * 0.05)}" fill="#000" '
            f'opacity="{opacity:.2f}" filter="{doc.blur(10)}"/>')


def server(doc: Doc, cx: float, cy: float, w: float, mark: str, rng: random.Random) -> Pt:
    """A 2U rack server in three-quarter view; one drive bay marked."""
    h = w * 0.22
    cx -= w * 0.13
    x, y = cx - w / 2, cy - h / 2
    contact(doc, cx + w * 0.08, y + h + 10, w * 1.1)
    _box3(doc, x, y, w, h, w * 0.5, "#2B3038", "#3B414B", "#1C2026")
    doc.rect(x, y, w, h, doc.lin([(0, "#3A404A", 1), (1, "#22262D", 1)]), 4, stroke="#12151A", sw=1.5)
    doc.rect(x, y, w, 2.5, "#FFFFFF", opacity=0.12)
    for ex in (x + 6, x + w - 28):
        doc.rect(ex, y + 6, 22, h - 12, "#454C57", 3)
        doc.circle(ex + 11, y + h * 0.3, 3.4, "#14171C")
        doc.circle(ex + 11, y + h * 0.7, 3.4, "#14171C")
    n, bx0, bw = 8, x + 44, (w * 0.62) / 8
    hit = rng.randrange(1, n - 1)
    for i in range(n):
        bx = bx0 + i * bw
        doc.rect(bx, y + 9, bw - 6, h - 18, "#1A1D22", 3, stroke="#0D0F13", sw=1)
        doc.rect(bx + 5, y + 15, bw - 16, 4, "#3A404A", 1.5)
        doc.circle(bx + bw - 13, y + h - 18, 3, mark if i == hit else "#4ADE80", opacity=0.95)
    vx = bx0 + n * bw + 14
    for i in range(int((x + w - 40 - vx) // 9)):
        doc.rect(vx + i * 9, y + 12, 4, h - 24, "#15181D", 2)
    hx = bx0 + hit * bw + (bw - 6) / 2
    doc.rect(bx0 + hit * bw - 3, y + 6, bw, h - 12, "none", 4, stroke=mark, sw=3)
    return hx, y + 6


def appliance(doc: Doc, cx: float, cy: float, w: float, mark: str, rng: random.Random) -> Pt:
    """A 1U network appliance (gateway / voice platform): ports and status display."""
    h = w * 0.13
    cx -= w * 0.15
    x, y = cx - w / 2, cy - h / 2
    contact(doc, cx + w * 0.08, y + h + 8, w * 1.1)
    _box3(doc, x, y, w, h, w * 0.55, "#C9CED6", "#E1E5EA", "#9EA5AF")
    doc.rect(x, y, w, h, doc.lin([(0, "#D8DCE2", 1), (1, "#AEB4BD", 1)]), 4, stroke="#7D848F", sw=1.2)
    doc.rect(x + 18, y + h * 0.25, w * 0.16, h * 0.5, "#0E1A14", 3)
    doc.rect(x + 24, y + h * 0.38, w * 0.1, h * 0.12, "#4ADE80", 1, opacity=0.8)
    px0 = x + w * 0.26
    for i in range(10):
        px = px0 + i * w * 0.05
        doc.rect(px, y + h * 0.28, w * 0.04, h * 0.44, "#23272E", 2)
        doc.rect(px + w * 0.012, y + h * 0.22, w * 0.016, h * 0.08, "#4ADE80" if i % 3 else "#F5A524", 1)
    for i in range(2):
        doc.rect(x + w * 0.8 + i * w * 0.07, y + h * 0.28, w * 0.055, h * 0.44, "#3A4049", 2)
    doc.circle(x + w - 22, cy, 5, mark)
    return x + w - 22, y


def cpu(doc: Doc, cx: float, cy: float, w: float, mark: str, rng: random.Random) -> Pt:
    """A server CPU package, top view in slight perspective: substrate,
    capacitor fields, nickel heat spreader."""
    h = w * 0.78
    x, y = cx - w / 2, cy - h / 2
    contact(doc, cx, y + h + 14, w * 1.05, 0.55)
    doc.shadow(x, y, w, h, 10, 0.8)
    doc.rect(x, y, w, h, doc.lin([(0, "#1E5B3A", 1), (1, "#123A26", 1)], 0, 0, 1, 1), 10, stroke="#0B2618", sw=2)
    for i in range(int(w // 14)):
        doc.rect(x + 10 + i * 14, y + 6, 6, 4, "#C9A24A", 1)
        doc.rect(x + 10 + i * 14, y + h - 10, 6, 4, "#C9A24A", 1)
    for j in range(6):
        for i in range(3):
            doc.rect(x + 16 + i * 10, y + h * 0.2 + j * 16, 6, 10, "#A9A39A", 1)
            doc.rect(x + w - 46 + i * 10, y + h * 0.2 + j * 16, 6, 10, "#A9A39A", 1)
    ix, iy, iw, ih = x + w * 0.14, y + h * 0.12, w * 0.72, h * 0.76
    doc.rect(ix + 4, iy + 6, iw, ih, "#000", 8, opacity=0.35)
    doc.rect(ix, iy, iw, ih, doc.lin([(0, "#E9ECEF", 1), (0.45, "#B9BEC5", 1), (1, "#D7DBE0", 1)], 0, 0, 1, 1), 8,
             stroke="#8C929B", sw=1.5)
    doc.path(f"M{f(ix + iw * 0.1)} {f(iy)}L{f(ix + iw * 0.45)} {f(iy)}L{f(ix)} {f(iy + ih * 0.55)}L{f(ix)} "
             f"{f(iy + ih * 0.2)}Z", fill="#FFFFFF", opacity=0.35)
    # die outlines under the lid (core complexes): one marked
    cols, rows = 4, 2
    hit = rng.randrange(cols * rows)
    dw, dh = iw * 0.17, ih * 0.3
    for k in range(cols * rows):
        i, j = k % cols, k // cols
        dx = ix + iw * 0.08 + i * iw * 0.22
        dy = iy + ih * 0.12 + j * ih * 0.46
        doc.rect(dx, dy, dw, dh, "none", 3, stroke=mark if k == hit else "#8C929B", sw=3 if k == hit else 1.2,
                 opacity=1 if k == hit else 0.6)
    return ix + iw * 0.08 + (hit % cols) * iw * 0.22 + dw / 2, iy + ih * 0.12 + (hit // cols) * ih * 0.46


def handset(doc: Doc, cx: float, cy: float, w: float, mark: str, rng: random.Random, mode: str = "chat") -> Pt:
    """A phone with a chat thread (or a wallet) on screen; one item marked."""
    h = w * 2.05
    x, y = cx - w / 2, cy - h / 2
    sx, sy, sw, sh = phone(doc, x, y, w, h, body="#16181D", screen="#F4F6F9")
    doc.rect(sx, sy, sw, sh * 0.12, "#E6EAF0", w * 0.12)
    doc.rect(sx, sy + sh * 0.08, sw, sh * 0.04, "#E6EAF0")
    doc.circle(sx + sw * 0.16, sy + sh * 0.085, sw * 0.055, "#C3CCD8")
    doc.rect(sx + sw * 0.26, sy + sh * 0.075, sw * 0.4, 8, "#AEB9C7", 4)
    if mode == "wallet":
        doc.rect(sx + sw * 0.08, sy + sh * 0.18, sw * 0.84, sh * 0.22, "#1B2333", 12)
        doc.rect(sx + sw * 0.14, sy + sh * 0.24, sw * 0.3, 8, "#5B6B7D", 4)
        doc.rect(sx + sw * 0.14, sy + sh * 0.31, sw * 0.5, 16, "#E8EDF5", 5)
        for i in range(4):
            yy = sy + sh * 0.47 + i * sh * 0.1
            doc.rect(sx + sw * 0.08, yy, sw * 0.84, sh * 0.075, "#FFFFFF", 8, stroke="#DCE2EA")
            for j in range(3):
                doc.rect(sx + sw * 0.14 + j * sw * 0.26, yy + sh * 0.03, sw * 0.18, 7, "#B7C2CF", 3)
        tx, ty = sx + sw * 0.5, sy + sh * 0.47
        doc.rect(sx + sw * 0.08, ty, sw * 0.84, sh * 0.075 + sh * 0.3, "none", 8, stroke=mark, sw=3)
        return tx, ty
    bubbles = [(0, 0.55), (1, 0.45), (0, 0.62), (1, 0.38), (0, 0.5)]
    yy = sy + sh * 0.18
    hit = 2
    tx, ty = cx, cy
    for i, (side, ww) in enumerate(bubbles):
        bh = sh * (0.1 if i == hit else 0.065)
        bw = sw * ww
        bx = sx + sw * 0.07 if side == 0 else sx + sw * 0.93 - bw
        col = "#FFFFFF" if side == 0 else "#2F6FDB"
        doc.rect(bx, yy, bw, bh, col, 14, stroke="#DCE2EA" if side == 0 else "")
        doc.rect(bx + 14, yy + bh * 0.35, bw * 0.6, 6, "#C3CCD8" if side == 0 else "#A9C4F2", 3)
        if i == hit:
            doc.rect(bx, yy, bw, bh, "none", 14, stroke=mark, sw=3)
            icon(doc, "play", bx + bw - 26, yy + bh / 2, 22, mark, 2.4)
            tx, ty = bx + bw, yy + bh / 2
        yy += bh + sh * 0.035
    return tx, ty


def browser(doc: Doc, cx: float, cy: float, w: float, mark: str, rng: random.Random) -> Pt:
    """A browser window with tabs; the page area marked by a crash-free but
    flagged tab (no vendor chrome)."""
    h = w * 0.68
    x, y = cx - w / 2, cy - h / 2
    doc.shadow(x, y, w, h, 12, 0.9)
    doc.rect(x, y, w, h, "#F7F8FA", 12, stroke="#2A3650", sw=1.2)
    doc.rect(x, y, w, 76, "#DCE1E8", 12)
    doc.rect(x, y + 40, w, 36, "#EEF1F5")
    for i in range(3):
        doc.circle(x + 20 + i * 16, y + 20, 5, ("#FF5F57", "#FEBC2E", "#28C840")[i], opacity=0.85)
    tabs = 3
    tw = (w - 120) / tabs
    for i in range(tabs):
        tx = x + 76 + i * tw
        active = i == 1
        doc.rect(tx, y + 8, tw - 6, 34, "#EEF1F5" if active else "#CBD2DB", 8)
        doc.rect(tx + 32, y + 21, tw * 0.45, 7, "#8C97A6", 3)
        doc.circle(tx + 17, y + 25, 6, mark if active else "#9AA5B4")
    doc.rect(x + 70, y + 46, w - 90, 24, "#FFFFFF", 12, stroke="#CBD2DB")
    doc.rect(x + 92, y + 55, w * 0.32, 6, "#AEB8C5", 3)
    bx, by = x + 34, y + 96
    ph = h - 96 - 24
    doc.rect(bx, by + ph * 0.06, w * 0.42, ph * 0.1, "#2A3346", 4)
    for i in range(3):
        doc.rect(bx, by + ph * (0.3 + i * 0.12), (w - 70) * (0.95 - 0.12 * (i % 3)), ph * 0.05, "#D4DAE2", 4)
    doc.rect(bx, by + ph * 0.68, w * 0.27, ph * 0.3, "#E3E8EE", 8)
    doc.rect(bx + w * 0.3, by + ph * 0.68, w * 0.27, ph * 0.3, "#E3E8EE", 8)
    return x + 76 + tw + 17, y + 25


def database(doc: Doc, cx: float, cy: float, w: float, mark: str, rng: random.Random) -> Pt:
    """Three stacked database volumes (cylinders) with metal shading; the
    middle one marked."""
    rx, ry, seg = w / 2, w * 0.16, w * 0.32
    top = cy - seg * 1.5
    contact(doc, cx, top + seg * 3 + ry + 10, w * 1.15, 0.55)
    body = doc.lin([(0, "#6F7885", 1), (0.35, "#C7CDD5", 1), (0.6, "#9AA2AD", 1), (1, "#4D5560", 1)], 0, 0, 1, 0)
    for i in (2, 1, 0):
        yt = top + i * seg
        doc.path(f"M{f(cx - rx)} {f(yt)}V{f(yt + seg - 10)}A{f(rx)} {f(ry)} 0 0 0 {f(cx + rx)} {f(yt + seg - 10)}"
                 f"V{f(yt)}Z", fill=body)
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(yt)}" rx="{f(rx)}" ry="{f(ry)}" fill="#DDE2E8" stroke="#8C949F" '
                f'stroke-width="1.5"/>')
        col = mark if i == 1 else "#4ADE80"
        doc.circle(cx + rx * 0.62, yt + seg * 0.55, 5, col)
        doc.rect(cx - rx * 0.7, yt + seg * 0.5, rx * 0.9, 6, "#3B424C", 3, opacity=0.6)
    yt = top + seg
    doc.path(f"M{f(cx - rx - 8)} {f(yt - 4)}V{f(yt + seg - 10)}A{f(rx + 8)} {f(ry + 6)} 0 0 0 {f(cx + rx + 8)} "
             f"{f(yt + seg - 10)}V{f(yt - 4)}", stroke=mark, sw=3)
    return cx + rx + 8, yt + seg * 0.4


def laptop(doc: Doc, cx: float, cy: float, w: float, mark: str, rng: random.Random) -> Pt:
    """An open laptop, front elevation, with a desktop and an elevated-rights
    prompt on screen."""
    sh = w * 0.6
    x, y = cx - w / 2, cy - sh / 2 - w * 0.04
    contact(doc, cx, y + sh + w * 0.06, w * 1.2, 0.55)
    doc.rect(x, y, w, sh, "#1C1F25", 14, stroke="#4A4F58", sw=2)
    sx, sy, sw_, sh_ = x + 16, y + 16, w - 32, sh - 32
    doc.rect(sx, sy, sw_, sh_, doc.lin([(0, "#20406E", 1), (1, "#16233D", 1)], 0, 0, 1, 1), 4)
    doc.rect(sx, sy + sh_ - 30, sw_, 30, "#0E1524", opacity=0.9)
    for i in range(5):
        doc.rect(sx + sw_ / 2 - 80 + i * 34, sy + sh_ - 22, 22, 14, "#3A4A66", 3)
    wx, wy, ww, wh = sx + sw_ * 0.2, sy + sh_ * 0.14, sw_ * 0.6, sh_ * 0.56
    doc.rect(wx, wy, ww, wh, "#F4F6F9", 6)
    doc.rect(wx, wy, ww, 26, "#E1E6ED", 6)
    for i, c in enumerate(("#C3CCD8", "#C3CCD8", mark)):
        doc.rect(wx + ww - 76 + i * 24, wy + 9, 14, 8, c, 2)
    icon(doc, "shieldx", wx + 40, wy + 70, 40, mark, 2.4)
    doc.rect(wx + 74, wy + 56, ww * 0.5, 9, "#8C97A6", 4)
    doc.rect(wx + 74, wy + 76, ww * 0.38, 7, "#C3CCD8", 3)
    doc.rect(wx + ww - 120, wy + wh - 44, 96, 28, mark, 5)
    # base
    by = y + sh
    doc.path(f"M{f(x - w * 0.08)} {f(by)}H{f(x + w * 1.08)}L{f(x + w * 1.04)} {f(by + w * 0.04)}H{f(x - w * 0.04)}Z",
             fill=doc.lin([(0, "#B7BDC6", 1), (1, "#7E8590", 1)]))
    doc.rect(cx - w * 0.1, by, w * 0.2, 6, "#8C929B", 3)
    return wx + 40, wy + 50


def editor(doc: Doc, cx: float, cy: float, w: float, mark: str, rng: random.Random) -> Pt:
    """A repository file tree with a submodule entry marked."""
    h = w * 0.82
    x, y = cx - w / 2, cy - h / 2
    doc.shadow(x, y, w, h, 12, 0.9)
    doc.rect(x, y, w, h, "#0F1522", 12, stroke="#2A3650", sw=1.2)
    doc.rect(x, y, w, 40, "#172033", 12)
    doc.rect(x, y + 28, w, 12, "#172033")
    for i in range(3):
        doc.circle(x + 20 + i * 16, y + 20, 5, ("#FF5F57", "#FEBC2E", "#28C840")[i], opacity=0.85)
    rows = [(0, "repo/", "#E8EDF5"), (1, ".gitmodules", "#E8EDF5"), (1, "src/", "#7D8AA3"),
            (1, "vendor/", "#7D8AA3"), (2, "lib/  (submodule)", mark), (3, ".git/", mark),
            (1, "README.md", "#7D8AA3")]
    hit_y = 0.0
    for i, (lvl, name, col) in enumerate(rows):
        yy = y + 84 + i * 46
        tx = x + 36 + lvl * 30
        icon(doc, "file", tx + 10, yy - 7, 22, col, 1.8)
        doc.text(name, tx + 32, yy, 22, col, "mono")
        if i == 4:
            doc.rect(x + 12, yy - 30, w - 24, 42, mark, 6, opacity=0.14)
            hit_y = yy - 9
    return x + w - 12, hit_y


def printer3d(doc: Doc, cx: float, cy: float, w: float, mark: str, rng: random.Random) -> Pt:
    """A desktop 3D printer in front elevation: frame, gantry, print head, bed
    and the control display (marked: the firmware)."""
    h = w * 1.05
    x, y = cx - w / 2, cy - h / 2
    contact(doc, cx, y + h + 6, w * 1.15, 0.55)
    frame = doc.lin([(0, "#3A3F47", 1), (1, "#22262C", 1)], 0, 0, 1, 0)
    doc.rect(x + w * 0.08, y, w * 0.08, h * 0.88, frame, 4)
    doc.rect(x + w * 0.84, y, w * 0.08, h * 0.88, frame, 4)
    doc.rect(x + w * 0.06, y, w * 0.88, w * 0.06, frame, 4)
    doc.rect(x, y + h * 0.82, w, h * 0.18, doc.lin([(0, "#30343B", 1), (1, "#1A1D22", 1)]), 8)
    gy = y + h * 0.3
    doc.rect(x + w * 0.12, gy, w * 0.76, w * 0.05, "#5A606A", 3)
    doc.rect(cx - w * 0.07, gy - w * 0.06, w * 0.14, w * 0.17, "#E86A2C", 6)
    doc.rect(cx - w * 0.015, gy + w * 0.11, w * 0.03, w * 0.05, "#B9BEC5", 1)
    by = y + h * 0.68
    doc.rect(x + w * 0.16, by, w * 0.68, w * 0.04, "#151719", 2)
    doc.rect(x + w * 0.18, by - w * 0.025, w * 0.64, w * 0.025, "#C9A24A", 2)
    doc.rect(cx - w * 0.08, by - w * 0.14, w * 0.16, w * 0.115, "#E86A2C", 4, opacity=0.85)
    dx, dy = x + w * 0.06, y + h * 0.86
    doc.rect(dx, dy, w * 0.3, h * 0.1, "#0C0E11", 4)
    doc.rect(dx + 6, dy + 6, w * 0.3 - 12, h * 0.1 - 12, "#1F3B57", 2)
    doc.rect(dx - 4, dy - 4, w * 0.3 + 8, h * 0.1 + 8, "none", 6, stroke=mark, sw=3)
    doc.circle(x + w * 0.5, dy + h * 0.05, w * 0.03, "#3A3F47")
    return dx + w * 0.3 + 4, dy + h * 0.05


DRAW = {"server": server, "appliance": appliance, "cpu": cpu, "phone": handset, "browser": browser,
        "database": database, "os": laptop, "code": editor, "printer": printer3d}
# Width each drawing is designed for, relative to the slot it is given.
SCALE = {"server": 0.82, "appliance": 0.82, "cpu": 0.72, "phone": 0.36, "browser": 0.86, "database": 0.5,
         "os": 0.78, "code": 0.74, "printer": 0.55}
# Height / width of each drawing (to fit a slot by height as well).
ASPECT = {"server": 0.5, "appliance": 0.35, "cpu": 0.85, "phone": 2.1, "browser": 0.7, "database": 1.45,
          "os": 0.75, "code": 0.85, "printer": 1.1}
