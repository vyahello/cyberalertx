"""Edge-device intrusion that ends in a hypervisor wiper: a 19-inch rack with
the security gateway (2U front panel: grille, display, LEDs, ports) above the
virtualisation host; the intrusion path leaves the gateway and reaches the
host, whose virtual machines are shown being wiped in an exploded inventory.

When the sources describe only the gateway compromise (no wiper, no ESXi),
the exploded view shows a root shell on the gateway instead. No vendor
logos; names from the headline appear as plain text."""
from __future__ import annotations

import random

from .. import type as T
from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, arrow, f, pill
from . import scene

_U = 66.0                # one rack unit at this scale (19 in = 720 px)


def _rails(doc: Doc, x0: float, x1: float) -> None:
    for x in (x0, x1 - 40):
        doc.rect(x, 0, 40, H, doc.lin([(0, "#2B2120", 1), (0.5, "#3A2D2B", 1), (1, "#211918", 1)], 0, 0, 1, 0))
        holes = []
        y = 6.0
        while y < H:
            for k in range(3):
                holes.append(f"M{f(x + 14)} {f(y + k * 22)}h11v11h-11Z")
            y += _U
        doc.path("".join(holes), fill="#0B0707")


def _ears(doc: Doc, x: float, y: float, w: float, h: float) -> None:
    for ex in (x - 34, x + w + 2):
        doc.rect(ex, y, 32, h, "#4A3E3C", 2)
        for k in range(int(h // _U)):
            doc.circle(ex + 16, y + _U / 2 + k * _U, 6, "#211918", "#6B5D5A", 1.5)


def _panel(doc: Doc, x: float, y: float, w: float, h: float, *, base: str = "#2C2423") -> None:
    doc.rect(x, y + 3, w, h, "#000", 3, opacity=0.5, extra=f' filter="{doc.blur(4)}"')
    doc.rect(x, y, w, h - 2, doc.lin([(0, base, 1), (1, "#1A1414", 1)]), 3)
    doc.line((x + 2, y + 1), (x + w - 2, y + 1), "#FFFFFF", 1, 0.12)


def _honeycomb(doc: Doc, b: Box) -> None:
    d = []
    r = 5.0
    row = 0
    y = b.y + r
    while y < b.b - r:
        x = b.x + r + (r if row % 2 else 0)
        while x < b.r - r:
            d.append(f"M{f(x - r * 0.86)} {f(y - r / 2)}l{f(r * 0.86)} {f(-r / 2)}l{f(r * 0.86)} {f(r / 2)}"
                     f"v{f(r)}l{f(-r * 0.86)} {f(r / 2)}l{f(-r * 0.86)} {f(-r / 2)}Z")
            x += r * 2
        y += r * 1.6
        row += 1
    doc.rect(b.x, b.y, b.w, b.h, "#0D0909", 3)
    doc.path("".join(d), fill="#241C1B")


def _rj45(doc: Doc, x: float, y: float, lit: bool, color: str = "#4ADE80") -> None:
    doc.rect(x, y, 34, 28, "#0B0808", 2, stroke="#5A4C49", sw=1)
    doc.rect(x + 7, y + 6, 20, 15, "#000")
    doc.rect(x + 11, y + 21, 12, 5, "#000")
    doc.rect(x + 2, y + 2, 6, 3, color if lit else "#2A2120", 1)
    doc.rect(x + 26, y + 2, 6, 3, "#FFB020" if lit else "#2A2120", 1)


def _gateway(doc: Doc, b: Box, danger: str, rng: random.Random) -> tuple[float, float]:
    """2U security gateway front. Returns the external (WAN) port position."""
    _ears(doc, b.x, b.y, b.w, b.h)
    _panel(doc, b.x, b.y, b.w, b.h, base="#3A302E")
    _honeycomb(doc, Box(b.x + 24, b.y + 14, 110, b.h - 30))
    # LCD + buttons
    lcd = Box(b.x + 150, b.y + 20, 140, 50)
    doc.rect(lcd.x, lcd.y, lcd.w, lcd.h, "#0E1A12", 3, stroke="#5A4C49")
    doc.text("gw-edge-01", lcd.x + 10, lcd.y + 22, 13, "#8FE3A4", "mono")
    doc.text("policy on", lcd.x + 10, lcd.y + 40, 13, "#5FA374", "mono")
    for k in range(4):
        doc.circle(lcd.x + 20 + k * 34, b.y + 96, 9, "#2A2120", "#6B5D5A", 1.5)
    # status LEDs
    for k, (lab, col) in enumerate((("PWR", "#4ADE80"), ("STS", "#4ADE80"), ("ALR", danger))):
        doc.circle(b.x + 304, b.y + 30 + k * 30, 5, col)
        if col == danger:
            doc.glow(b.x + 304, b.y + 30 + k * 30, 16, 16, danger, 0.6)
        doc.text(lab, b.x + 316, b.y + 35 + k * 30, 11, "#A08680", "mono")
    # port block: 2 x 4 copper, then SFP cages over the WAN / MGMT ports
    px0 = b.x + 350
    for r in range(2):
        for c in range(4):
            _rj45(doc, px0 + c * 40, b.y + 22 + r * 50, rng.random() < 0.7)
    sx = px0 + 4 * 40 + 16
    for k in range(2):
        doc.rect(sx + k * 46, b.y + 76, 38, 24, "#0B0808", 2, stroke="#7F6F6B", sw=1.2)
        doc.rect(sx + k * 46 + 4, b.y + 81, 30, 14, "#1A1212", 1)
    wan = (sx + 19, b.y + 22)
    doc.rect(sx, b.y + 22, 38, 28, "#0B0808", 2, stroke=danger, sw=2.2)
    doc.rect(sx + 8, b.y + 28, 22, 15, "#000")
    doc.text("WAN", sx + 19, b.y + 66, 11, danger, "mono_bold", anchor="middle")
    doc.rect(sx + 46, b.y + 22, 38, 28, "#0B0808", 2, stroke="#5A4C49")
    doc.rect(sx + 54, b.y + 28, 22, 15, "#000")
    doc.text("MGMT", sx + 65, b.y + 66, 11, "#A08680", "mono", anchor="middle")
    # handles
    for hx in (b.x + 4, b.r - 16):
        doc.rect(hx, b.y + 18, 12, b.h - 36, "#5A4C49", 3)
    return wan


def _server(doc: Doc, b: Box, *, bays: int, hot: bool, danger: str, rng: random.Random) -> None:
    _ears(doc, b.x, b.y, b.w, b.h)
    _panel(doc, b.x, b.y, b.w, b.h, base="#2E2625")
    bw = (b.w - 200) / bays
    for k in range(bays):
        bx = b.x + 20 + k * bw
        doc.rect(bx, b.y + 12, bw - 6, b.h - 26, "#1A1414", 2, stroke="#4A3E3C", sw=1)
        doc.path("".join(f"M{f(bx + 8)} {f(b.y + 24 + j * 7)}h{f(bw - 30)}" for j in range(int((b.h - 52) / 7))),
                 stroke="#2E2524", sw=3)
        col = danger if hot and rng.random() < 0.8 else "#4ADE80"
        doc.rect(bx + bw - 18, b.y + 18, 5, 5, col, 1)
    doc.rect(b.r - 160, b.y + 16, 140, b.h - 32, "#211918", 3)
    doc.circle(b.r - 40, b.cy, 9, "none", "#4ADE80", 2)


def _vm_panel(doc: Doc, b: Box, brief: EditorialBrief, danger: str, rng: random.Random) -> None:
    p = doc.pal
    doc.shadow(b.x, b.y, b.w, b.h, 14, 1.0)
    doc.rect(b.x, b.y, b.w, b.h, "#1A1211", 14, stroke="#3A2826", sw=1.2)
    doc.rect(b.x, b.y, b.w, 56, "#241918", 14)
    doc.rect(b.x, b.y + 42, b.w, 14, "#241918")
    title = "VMware ESXi host" if "esxi" in brief.text else "hypervisor host"
    doc.text(title, b.x + 24, b.y + 36, 20, p.ink, "ui_bold")
    doc.text("esx-01.corp.example", b.r - 24, b.y + 36, 15, p.muted, "mono", anchor="end")
    cols, rows = 3, 3
    gw, gh = (b.w - 48 - (cols - 1) * 14) / cols, (b.h - 90 - (rows - 1) * 14) / rows
    states = ["wiped", "wiped", "wiping", "wiped", "wiped", "ok", "wiped", "wiping", "ok"]
    for i in range(cols * rows):
        r, c = divmod(i, cols)
        t = Box(b.x + 24 + c * (gw + 14), b.y + 72 + r * (gh + 14), gw, gh)
        st = states[i]
        if st == "wiped":
            doc.rect(t.x, t.y, t.w, t.h, "#2A0F0D", 8, stroke=danger, sw=1.5)
            hatch = "".join(f"M{f(t.x + k)} {f(t.b)}L{f(t.x + k + t.h)} {f(t.y)}"
                            for k in range(int(-t.h), int(t.w), 14))
            with doc.g(clip=doc.clip_rect(t.x, t.y, t.w, t.h, 8)):
                doc.path(hatch, stroke=danger, sw=1.5, opacity=0.35)
        else:
            doc.rect(t.x, t.y, t.w, t.h, "#251C1B", 8, stroke="#3A2826", sw=1.2)
        # VM glyph: a small screen
        doc.rect(t.x + 16, t.y + 16, 34, 24, "none", 3, stroke=p.muted if st == "ok" else danger, sw=2)
        doc.text(f"vm-{i + 1:02d}", t.x + 62, t.y + 34, 16, p.ink, "mono")
        if st == "wiped":
            doc.text("wiped", t.x + 16, t.b - 18, 18, danger, "mono_bold")
        elif st == "wiping":
            doc.rect(t.x + 16, t.b - 34, t.w - 32, 12, "#3A2826", 4)
            doc.rect(t.x + 16, t.b - 34, (t.w - 32) * rng.uniform(0.35, 0.7), 12, danger, 4)
        else:
            doc.text("running", t.x + 16, t.b - 18, 16, p.safe, "mono")


def _shell_panel(doc: Doc, b: Box, brief: EditorialBrief, danger: str) -> None:
    p = doc.pal
    doc.shadow(b.x, b.y, b.w, b.h, 14, 1.0)
    doc.rect(b.x, b.y, b.w, b.h, "#120C0B", 14, stroke="#3A2826", sw=1.2)
    doc.text("gateway shell", b.x + 24, b.y + 40, 20, p.ink, "ui_bold")
    rows = [("$ id", p.ink), ("uid=0(root) gid=0(root)", danger), ("", p.ink), ("$ uname -n", p.ink),
            ("gw-edge-01", p.muted)]
    for k, (s, c) in enumerate(rows):
        doc.text(s, b.x + 24, b.y + 100 + k * 34, 20, c, "mono_bold" if c == danger else "mono")


@scene("edge_wiper")
def edge_wiper(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    doc.rect(0, 0, W, H, doc.lin([(0, p.bg1, 1), (1, p.bg0, 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FF7A45", 0.08), (1, "#FF7A45", 0)], 0.8, 0.5, 0.6))
    wiper = any(k in brief.text for k in ("wiper", "esxi", "wipe"))

    rx0, rx1 = 70, 870
    doc.rect(rx0, 0, rx1 - rx0, H, "#0B0707")
    _rails(doc, rx0, rx1)
    ux, uw = rx0 + 80, rx1 - rx0 - 160
    y = 6 + _U * 0.5
    # 1U patch panel
    _ears(doc, ux, y, uw, _U)
    _panel(doc, ux, y, uw, _U)
    for k in range(16):
        _rj45(doc, ux + 24 + k * 40, y + 19, False)
    y += _U
    gw = Box(ux, y, uw, 2 * _U)
    wan = _gateway(doc, gw, p.danger, rng)
    y += 2 * _U
    # brush strip
    _ears(doc, ux, y, uw, _U)
    _panel(doc, ux, y, uw, _U, base="#1E1716")
    doc.rect(ux + 40, y + _U / 2 - 4, uw - 80, 8, "#0B0707", 4)
    y += _U
    # 1U switch
    _ears(doc, ux, y, uw, _U)
    _panel(doc, ux, y, uw, _U)
    for k in range(14):
        _rj45(doc, ux + 60 + k * 40, y + 19, rng.random() < 0.6)
    y += _U
    host = Box(ux, y, uw, 2 * _U)
    _server(doc, host, bays=8, hot=wiper, danger=p.danger, rng=rng)
    y += 2 * _U
    _server(doc, Box(ux, y, uw, 2 * _U), bays=8, hot=False, danger=p.danger, rng=rng)
    y += 2 * _U
    while y < H:
        _ears(doc, ux, y, uw, _U)
        _panel(doc, ux, y, uw, _U, base="#1E1716")
        y += _U

    # the rest of the rack recedes; the gateway carries the frame
    doc.rect(rx0, 0, rx1 - rx0, H, doc.lin([(0, "#000", 0.0), (0.55, "#000", 0.15), (1, "#000", 0.7)]))
    doc.rect(gw.x - 6, gw.y - 4, gw.w + 12, gw.h + 6, "none", 6, stroke=p.danger, sw=2.5)
    doc.glow(gw.cx, gw.cy, gw.w * 0.55, gw.h * 0.7, p.danger, 0.10)

    # exploded view to the right
    pnl = Box(1000, 140, 550, 560) if wiper else Box(1000, 200, 550, 360)
    src = host if wiper else gw
    doc.poly([(src.r + 34, src.y), (pnl.x, pnl.y + 30), (pnl.x, pnl.b - 30), (src.r + 34, src.b)], p.danger,
             opacity=0.07)
    doc.line((src.r + 34, src.y), (pnl.x, pnl.y + 30), p.danger, 1.2, 0.5)
    doc.line((src.r + 34, src.b), (pnl.x, pnl.b - 30), p.danger, 1.2, 0.5)
    if wiper:
        _vm_panel(doc, pnl, brief, p.danger, rng)
    else:
        _shell_panel(doc, pnl, brief, p.danger)

    # intrusion path: from outside -> WAN port -> (wiper) down to the host
    ent = "PHP2Shell" if "php2shell" in brief.text else "exploit"
    arrow(doc, [(wan[0], 0), (wan[0], wan[1] - 4)], p.danger, sw=4, head=18)
    pill(doc, wan[0] + 16, 20, ent, fg="#FFFFFF", bg=p.danger, size=16)
    if wiper:
        hx = rx1 + 40
        arrow(doc, [(gw.r + 40, gw.cy), (hx + 20, gw.cy), (hx + 20, host.cy), (host.r + 46, host.cy)], p.danger,
              sw=4, head=18, dash="12 8")
        pill(doc, hx + 20, (gw.cy + host.cy) / 2 - 15, "wiper", fg="#FFFFFF", bg=p.danger, size=15,
             anchor="middle")

    doc.rect(0, 0, W, H, doc.rad([(0.55, "#000", 0), (1, "#000", 0.5)], 0.5, 0.5, 0.78))
    doc.focus = Box(60, 60, 1490, 838)
