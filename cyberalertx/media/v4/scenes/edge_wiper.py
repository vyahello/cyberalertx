"""Edge-device intrusion, drawn as two objects: the security gateway as a
large appliance in three-quarter view (a product shot, not a rack diagram)
and, when the sources describe a wiper, the virtualisation host behind it as
a stack of virtual machines whose upper layers come apart into loose blocks.

Evidence decides the drama: exploitation on record cracks the gateway and a
red channel leaves it (to the host when there is a wiper); an advisory shows
the gateway intact with the flaw count from `brief.facts`. Nothing is a
screenshot: no hostnames, no VM names, no "wiped/running" states, no LED
labels, no shell. Product and exploit names only as plain text from the
sources."""
from __future__ import annotations

import random

from ..brief import EditorialBrief, mentions
from ..kit import Box, Doc, W, H, f
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")
_VENDORS = ("Check Point", "FortiGate", "Fortinet", "Palo Alto", "Ivanti", "Citrix", "NetScaler", "SonicWall",
            "Cisco")
_EXPLOITS = ("PHP2Shell", "CitrixBleed")


def _slab(doc: Doc, x: float, y: float, w: float, h: float, dx: float, dy: float, front: str, top: str,
          side: str) -> None:
    """A box in oblique projection: front face at (x, y, w, h), depth (dx, -dy)."""
    doc.poly([(x, y), (x + dx, y - dy), (x + w + dx, y - dy), (x + w, y)], top)
    doc.poly([(x + w, y), (x + w + dx, y - dy), (x + w + dx, y + h - dy), (x + w, y + h)], side)
    doc.rect(x, y, w, h, front)


def _gateway(doc: Doc, x: float, y: float, w: float, h: float, rng: random.Random, red: str,
             cracked: bool) -> tuple[float, float]:
    """The appliance. Returns the point where the breach is."""
    dx, dy = 150.0, 110.0
    doc.add(f'<ellipse cx="{f(x + w / 2 + 60)}" cy="{f(y + h + 18)}" rx="{f(w * 0.62)}" ry="34" fill="#000" '
            f'opacity="0.65" filter="{doc.blur(20)}"/>')
    _slab(doc, x, y, w, h, dx, dy, doc.lin([(0, "#7A6D68", 1), (1, "#4E4440", 1)]),
          doc.lin([(0, "#A39590", 1), (1, "#7C6F6A", 1)], 0, 0, 1, 0), "#3A302D")
    doc.rect(x, y, w, 4, "#FFFFFF", opacity=0.25)
    # front panel: vent grille, port block, two blank module bays
    gx, gy = x + 34, y + 28
    for r in range(4):
        for c in range(12):
            doc.rect(gx + c * 16, gy + r * 24, 9, 16, "#120D0C", 2)
    px = x + 300
    for r in range(2):
        for c in range(8):
            cx, cy = px + c * 46, y + 34 + r * 54
            doc.rect(cx, cy, 36, 30, "#0D0909", 3, stroke="#2A2220", sw=1.2)
            doc.rect(cx + 10, cy + 22, 16, 8, "#2A201E")
    for k in range(2):
        doc.rect(x + w - 190 + k * 86, y + 30, 70, h - 60, "#5E5350", 4, stroke="#3A302D", sw=1.5)
    bx, by = px + 7 * 46 + 18, y + 49
    if cracked:
        # the breach: a jagged split through the front panel, lit from inside
        zig = [(bx - 40, y - 2), (bx - 8, y + h * 0.3), (bx - 34, y + h * 0.55), (bx + 4, y + h * 0.8),
               (bx - 16, y + h + 2)]
        d = "M" + "L".join(f"{f(a)} {f(b)}" for a, b in zig)
        doc.glow(bx - 16, y + h / 2, 130, h * 0.8, red, 0.45)
        doc.path(d, stroke="#0A0505", sw=16)
        doc.path(d, stroke=red, sw=6)
        doc.path(d, stroke="#FFD2C8", sw=1.5)
    return bx - 16, y + h / 2


def _host(doc: Doc, cx: float, base: float, red: str, rng: random.Random, wiped: bool) -> tuple[float, float]:
    """The virtualisation host as a stack of VM layers. The upper layers break
    up into loose blocks when a wiper is described."""
    w, h, dx, dy = 300.0, 46.0, 110.0, 80.0
    x = cx - w / 2
    layers = 6
    doc.add(f'<ellipse cx="{f(cx + 50)}" cy="{f(base + 14)}" rx="{f(w * 0.75)}" ry="26" fill="#000" '
            f'opacity="0.6" filter="{doc.blur(16)}"/>')
    for i in range(layers):
        y = base - (i + 1) * (h + 14)
        broken = wiped and i >= 3
        if broken:
            # loose cells drifting off the layer
            n = 10
            for k in range(n):
                cw = w / n
                lift = (i - 2) * 30 * rng.random() + rng.uniform(-8, 8)
                if rng.random() < 0.25 + 0.2 * (i - 3):
                    continue
                _slab(doc, x + k * cw + rng.uniform(-6, 6) + (i - 3) * 14, y - lift, cw - 6, h * 0.8,
                      dx * 0.18, dy * 0.18, red if rng.random() < 0.4 else "#5A2A26", "#8A3A32", "#3A1A18")
        else:
            _slab(doc, x, y, w, h, dx, dy * 0.6,
                  doc.lin([(0, "#3E3330", 1), (1, "#2A2220", 1)]), "#5A4A46", "#1E1716")
            for k in range(5):
                doc.rect(x + 22 + k * 30, y + h / 2 - 4, 18, 8, "#1A1312", 2)
    return x - 10, base - 2.5 * (h + 14)


def _label(doc: Doc, s: str, x: float, y: float, size: float, color: str, anchor: str = "start") -> None:
    doc.text(s, x, y, size, color, "ui_bold", anchor=anchor)


@scene("edge_wiper")
def edge_wiper(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    red = p.danger
    attacked = brief.status in _ATTACK
    wiper = attacked and any(k in text for k in ("wiper", "wipe", "вайпер"))
    esxi = "esxi" in text
    vendor = next((v for v in _VENDORS if mentions(v, text[:160])), "")
    exploit = next((e for e in _EXPLOITS if mentions(e, text)), "")

    doc.rect(0, 0, W, H, doc.lin([(0, "#1C1211", 1), (1, "#080505", 1)]))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FF7A45", 0.14), (1, "#FF7A45", 0)], 0.35, 0.45, 0.55))
    doc.rect(0, 690, W, H - 690, doc.lin([(0, "#000", 0.0), (1, "#000", 0.45)]))

    if wiper:
        gx, gy, gw, gh = 90.0, 470.0, 860.0, 170.0
    else:
        gx, gy, gw, gh = 250.0, 420.0, 980.0, 190.0
    breach = _gateway(doc, gx, gy, gw, gh, rng, red, attacked)

    if wiper:
        hx, hy = _host(doc, 1270, 700, red, rng, True)
        # the channel from the breach, over the appliance, to the host
        ch = (f"M{f(breach[0] + 20)} {f(gy - 6)}C{f(breach[0] + 220)} {f(gy - 190)} {f(hx - 170)} {f(hy - 150)} "
              f"{f(hx)} {f(hy)}")
        doc.path(ch, stroke=red, sw=14, opacity=0.2)
        doc.path(ch, stroke=red, sw=5)
        doc.circle(hx, hy, 9, red)
        if esxi:
            _label(doc, "VMware ESXi" if "vmware" in text else "ESXi", 1270 + 55, 790, 48, p.ink, "middle")
    if exploit and attacked:
        lx, ly = (90.0, 170.0) if wiper else (250.0, 230.0)
        _label(doc, exploit, lx, ly, 84, red)
        doc.path(f"M{f(lx + 200)} {f(ly + 28)}Q{f(breach[0] - 60)} {f(ly + 60)} {f(breach[0] - 24)} {f(gy - 4)}",
                 stroke=red, sw=4)
        doc.circle(breach[0] - 24, gy - 4, 8, red)
    if vendor:
        _label(doc, vendor, gx, gy + gh + 92, 56, p.ink)
    flaws = str(brief.facts.get("flaws", "")).strip()
    if not attacked and flaws.isdigit():
        _label(doc, f"{flaws} flaws", gx + gw + 150, gy - 160, 84, p.warn, "end")
    elif attacked and not wiper and "root" in text:
        _label(doc, "root access", gx + gw + 150, gy - 160, 72, red, "end")

    doc.rect(0, 0, W, H, doc.rad([(0.6, "#000", 0), (1, "#000", 0.5)], 0.5, 0.5, 0.78))
    doc.focus = Box(40, 80, 1480, 833) if wiper else Box(180, 150, 1220, 686)
