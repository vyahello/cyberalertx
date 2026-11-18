"""An AI security-testing tool used against real targets (ARTEX).

What the sources state, and nothing more: the tool's name (plain text), that it
is an AI penetration-testing framework built to help companies test their own
defences, and what it was used against — per story:
  * an FBI warning that attackers use it to break into corporate networks;
  * a company's cloud breach tied to a stolen cloud access key and the tool.
No attack stages, no console, no capabilities the sources do not state, no
logos; the company name only when the headline names it.

Alternatives:
  a  the reticle: the tool as a large sighting ring, swung away from a faded
     practice target onto the real one (the breached cloud, or the corporate
     network the warning names);
  b  the U-turn: the defender's shield with the tool's arrow leaving it and
     turning back out toward the real target; the name set large.
"""
from __future__ import annotations

import math
import random
import re
from typing import Callable

from .. import type as T
from ..brief import EditorialBrief, mentions
from ..kit import H, W, Box, Doc, f, icon
from . import scene

_BG0, _BG1 = "#0C0A16", "#1A1430"


def _facts(brief: EditorialBrief) -> dict[str, str]:
    """What the story states: tool name, who warns, the target, the entry."""
    t = brief.text or ""
    head = t[:200]
    tool = "ARTEX" if "artex" in t else "AI TOOL"
    cloud = bool(re.search(r"cloud (environment|breach)|breach of its cloud|хмар", t))
    key = bool(re.search(r"(stolen|leaked|compromised) cloud (access )?key|cloud access key", t))
    company = ""
    for e in brief.entities:
        if mentions(e, head) and e.upper() != tool and e not in ("AI-powered", "FBI") and \
                T.supported(e, "ui_bold") == e and re.fullmatch(r"[A-Z][A-Za-z]+", e):
            company = e
            break
    warner = "FBI" if re.search(r"\bfbi\b|фбр", head) else ""
    if cloud:
        target = "cloud"
    elif re.search(r"corporate network|корпоративн\w* мереж", t):
        target = "network"
    else:
        target = "network"
    return {"tool": tool, "target": target, "key": "1" if key else "", "company": company, "warner": warner}


def _stage(doc: Doc, light: tuple[float, float]) -> None:
    doc.rect(0, 0, W, H, doc.lin([(0, _BG1, 1), (1, _BG0, 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#B69CFF", 0.16), (0.5, "#B69CFF", 0.04), (1, "#B69CFF", 0)], light[0],
                                 light[1], 0.55))


def _cloud(doc: Doc, cx: float, cy: float, s: float, fill: str, stroke: str) -> None:
    """A solid cloud silhouette (three lobes on a flat base)."""
    d = (f"M{f(cx - 230 * s)} {f(cy + 90 * s)}"
         f"A{f(90 * s)} {f(90 * s)} 0 0 1 {f(cx - 170 * s)} {f(cy - 40 * s)}"
         f"A{f(130 * s)} {f(130 * s)} 0 0 1 {f(cx + 60 * s)} {f(cy - 90 * s)}"
         f"A{f(110 * s)} {f(110 * s)} 0 0 1 {f(cx + 200 * s)} {f(cy - 10 * s)}"
         f"A{f(100 * s)} {f(100 * s)} 0 0 1 {f(cx + 230 * s)} {f(cy + 90 * s)}Z")
    doc.path(d, fill="#000000", opacity=0.45, extra=f' transform="translate(10 24)" filter="{doc.blur(18)}"')
    doc.path(d, fill=fill, stroke=stroke, sw=4)


def _keyhole_key(doc: Doc, cx: float, cy: float, s: float, col: str) -> None:
    """A key inserted into the cloud from the left: the stolen access key."""
    doc.circle(cx, cy - 18 * s, 26 * s, "#0C0A16")
    doc.path(f"M{f(cx - 14 * s)} {f(cy - 6 * s)}L{f(cx - 22 * s)} {f(cy + 50 * s)}H{f(cx + 22 * s)}"
             f"L{f(cx + 14 * s)} {f(cy - 6 * s)}Z", fill="#0C0A16")
    # key: bow outside on the left, blade into the keyhole
    by = cy + 6 * s
    doc.rect(cx - 210 * s, by - 9 * s, 200 * s, 18 * s, col, 6 * s)
    doc.rect(cx - 120 * s, by + 6 * s, 16 * s, 22 * s, col, 3 * s)
    doc.rect(cx - 90 * s, by + 6 * s, 14 * s, 16 * s, col, 3 * s)
    doc.circle(cx - 250 * s, by, 52 * s, col)
    doc.circle(cx - 250 * s, by, 22 * s, "#1A1430")
    doc.rect(cx - 200 * s, by - 7 * s, 180 * s, 4 * s, "#FFFFFF", 2 * s, opacity=0.35)


def _towers(doc: Doc, cx: float, base: float, s: float, fill: str, edge: str) -> None:
    """Corporate buildings: three office towers with a lit window grid."""
    specs = ((-190, 300, 150), (-20, 420, 170), (160, 250, 140))
    for dx, h, w in specs:
        x = cx + dx * s
        doc.rect(x - w * s / 2 + 12, base - h * s + 26, w * s, h * s, "#000", 4, opacity=0.4,
                 extra=f' filter="{doc.blur(14)}"')
        doc.rect(x - w * s / 2, base - h * s, w * s, h * s, fill, 4, stroke=edge, sw=3)
        cols, rows = 4, int(h / 34)
        win = []
        for r in range(rows):
            for c in range(cols):
                wx = x - w * s / 2 + 16 * s + c * (w * s - 32 * s) / cols
                wy = base - h * s + 22 * s + r * 34 * s
                win.append(f'<rect x="{f(wx)}" y="{f(wy)}" width="{f((w * s - 32 * s) / cols - 8 * s)}" '
                           f'height="{f(16 * s)}" rx="2"/>')
        doc.add(f'<g fill="#B69CFF" opacity="0.28">{"".join(win)}</g>')
    doc.rect(cx - 330 * s, base, 660 * s, 6, edge, 3, opacity=0.6)


def _target(doc: Doc, info: dict[str, str], cx: float, cy: float, s: float, red: str) -> None:
    if info["target"] == "cloud":
        _cloud(doc, cx, cy, s, "#2A2148", "#8E86A8")
        if info["key"]:
            _keyhole_key(doc, cx + 40 * s, cy + 10 * s, s, "#F2C14E")
        if info["company"]:
            doc.text(info["company"].upper(), cx + 20 * s, cy + 150 * s, 40, "#EEEAFB", "ui_bold", anchor="middle",
                     tracking=5)
        # breach mark: a crack through the cloud's base
        doc.path(f"M{f(cx + 150 * s)} {f(cy - 40 * s)}l{f(-26 * s)} {f(40 * s)}l{f(30 * s)} {f(18 * s)}"
                 f"l{f(-22 * s)} {f(60 * s)}", stroke=red, sw=7)
    else:
        _towers(doc, cx, cy + 190 * s, s, "#251C40", "#8E86A8")


def _reticle(doc: Doc, cx: float, cy: float, r: float, col: str, label: str) -> None:
    doc.circle(cx, cy, r, "none", col, 7)
    ticks = []
    for k in range(72):
        a = math.radians(k * 5)
        l1 = r + (22 if k % 6 == 0 else 10)
        ticks.append(f"M{f(cx + math.cos(a) * (r + 4))} {f(cy + math.sin(a) * (r + 4))}"
                     f"L{f(cx + math.cos(a) * l1)} {f(cy + math.sin(a) * l1)}")
    doc.path("".join(ticks), stroke=col, sw=2.5, opacity=0.8)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        doc.line((cx + dx * (r - 34), cy + dy * (r - 34)), (cx + dx * (r + 64), cy + dy * (r + 64)), col, 7)
    # name plate on the ring
    w = T.measure(label, 88, "display", 5) + 60
    doc.rect(cx - w / 2 + 6, cy - r - 52 + 12, w, 112, "#000", 10, opacity=0.4, extra=f' filter="{doc.blur(10)}"')
    doc.rect(cx - w / 2, cy - r - 52, w, 112, col, 10)
    doc.text(label, cx, cy - r + 4 + T.cap_height(88, "display") / 2, 88, "#120E22", "display", anchor="middle",
             tracking=5)


def _practice(doc: Doc, cx: float, cy: float, r: float) -> None:
    """The practice target the tool was built for: concentric rings, faded."""
    with doc.g(opacity=0.35):
        for k, c in enumerate(("#EEEAFB", "#1B1530", "#EEEAFB", "#1B1530", "#EEEAFB")):
            doc.circle(cx, cy, r * (1 - k * 0.19), c, stroke="#8E86A8", sw=1.5)
    doc.text("PENTEST", cx, cy + r + 50, 26, "#8E86A8", "ui_bold", anchor="middle", tracking=5)


def _kicker(doc: Doc, info: dict[str, str], x: float, y: float, red: str) -> None:
    doc.rect(x, y - 40, 56, 7, red)
    s = (info["warner"] + " WARNING") if info["warner"] else ("CLOUD BREACH" if info["target"] == "cloud"
                                                             else "AI PENTEST TOOL")
    doc.text(s, x, y, 28, "#C9C1E6", "ui_bold", tracking=4)


def _comp_reticle(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    info = _facts(brief)
    red = p.danger
    _stage(doc, (0.68, 0.45))
    # faded practice target, upper left, and the swing of the sight away from it
    _practice(doc, 220, 620, 90)
    doc.path("M330 560Q520 420 760 470", stroke=p.accent, sw=3, dash="14 12", opacity=0.6)
    tc = (1070.0, 500.0)
    _target(doc, info, tc[0], tc[1], 1.0, red)
    _reticle(doc, tc[0], tc[1], 250, red, info["tool"])
    _kicker(doc, info, 80, 110, red)
    doc.text("AI pentest tool", 80, 170, 40, "#EEEAFB", "ui_bold")
    lines = (("linked to the", "cloud breach") if info["target"] == "cloud"
             else ("used to break into", "corporate networks"))
    doc.text(lines[0], 80, 222, 40, "#8E86A8", "ui")
    doc.text(lines[1], 80, 274, 40, "#8E86A8", "ui")
    doc.focus = Box(560, 150, 1040, 585)
    _ = rng


def _shield(doc: Doc, cx: float, cy: float, s: float, fill: str, edge: str) -> None:
    d = (f"M{f(cx)} {f(cy - 200 * s)}L{f(cx + 165 * s)} {f(cy - 140 * s)}V{f(cy + 10 * s)}"
         f"C{f(cx + 165 * s)} {f(cy + 120 * s)} {f(cx + 80 * s)} {f(cy + 190 * s)} {f(cx)} {f(cy + 230 * s)}"
         f"C{f(cx - 80 * s)} {f(cy + 190 * s)} {f(cx - 165 * s)} {f(cy + 120 * s)} {f(cx - 165 * s)} {f(cy + 10 * s)}"
         f"V{f(cy - 140 * s)}Z")
    doc.path(d, fill="#000", opacity=0.45, extra=f' transform="translate(10 22)" filter="{doc.blur(16)}"')
    doc.path(d, fill=fill, stroke=edge, sw=6)
    doc.path(f"M{f(cx)} {f(cy - 200 * s)}V{f(cy + 230 * s)}", stroke="#FFFFFF", sw=2, opacity=0.12)


def _comp_uturn(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    info = _facts(brief)
    red = p.danger
    _stage(doc, (0.3, 0.55))
    sc = (380.0, 600.0)
    tc = (1210.0, 470.0)
    _shield(doc, sc[0], sc[1], 0.9, doc.lin([(0, "#3B2E66", 1), (1, "#221A3E", 1)], 0, 0, 1, 1), p.accent)
    icon(doc, "check", sc[0], sc[1] - 10, 120, p.accent, 3, 0.5)
    # the arrow: born inside the shield, it turns and leaves toward the target
    end = (tc[0] - 300, tc[1] + 30)
    d = (f"M{f(sc[0] + 40)} {f(sc[1] + 90)}C{f(sc[0] + 240)} {f(sc[1] + 300)} {f(end[0] - 260)} {f(end[1] + 260)} "
         f"{f(end[0] - 80)} {f(end[1] + 20)}")
    doc.path(d, stroke="#000", sw=34, opacity=0.35, extra=f' filter="{doc.blur(10)}"')
    doc.path(d, stroke=red, sw=26, cap="butt")
    tip = (end[0] + 10, end[1] - 50)
    ang = math.atan2(tip[1] - (end[1] + 20), tip[0] - (end[0] - 80))
    hd = 92
    doc.poly([tip, (tip[0] - hd * math.cos(ang - 0.5), tip[1] - hd * math.sin(ang - 0.5)),
              (tip[0] - hd * math.cos(ang + 0.5), tip[1] - hd * math.sin(ang + 0.5))], red)
    _target(doc, info, tc[0], tc[1], 0.72, red)
    doc.text(info["tool"], 80, 190, 150, "#EEEAFB", "display", tracking=6)
    _kicker(doc, info, 84, 290, red)
    doc.text("AI pentest tool", 84, 340, 36, "#8E86A8", "ui")
    doc.focus = Box(50, 40, 1500, 844)
    _ = rng


ALTERNATIVES: dict[str, Callable[[Doc, EditorialBrief, random.Random], None]] = {
    "a": _comp_reticle, "b": _comp_uturn}


@scene("ai_offensive_tool")
def ai_offensive_tool(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    _comp_reticle(doc, brief, rng)
