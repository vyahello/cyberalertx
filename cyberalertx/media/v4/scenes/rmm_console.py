"""Remote monitoring and management (RMM) as a marionette: the management
server is the control bar, every managed computer hangs on one of its strings.
Whoever works the bar works the fleet. That is the whole mechanism the sources
state ("flaws in the management server; payload deployed through it"), so the
image shows nothing else: no console screenshot, no device names, no load
figures, no invented task.

Evidence decides the drama. With exploitation on record, some strings are
pulled and the machines on them show a token for what the sources say was
deployed (a coin with a pick for crypto miners, otherwise a plain foreign
block). Without it the strings hang slack and the bar carries the patch tag.
The product name appears only as plain text and only when the sources name
it; a flaw count only from `brief.facts`."""
from __future__ import annotations

import random

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, W, H, f
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")
_PRODUCTS = ("N-central", "ScreenConnect", "SimpleHelp", "Kaseya", "ConnectWise", "N-able")


def _product(brief: EditorialBrief) -> str:
    text = brief.text or ""
    for name in _PRODUCTS:
        if name.lower() in text and any(e.lower() == name.lower() for e in brief.entities):
            return name
    for name in _PRODUCTS:
        if name.lower() in text[:200]:
            return name
    return ""


def _coin(doc: Doc, cx: float, cy: float, r: float, color: str, ink: str) -> None:
    """A coin with a pick across it: the conventional mark for mining. A symbol,
    not a currency logo."""
    doc.circle(cx, cy, r, color)
    doc.circle(cx, cy, r * 0.78, "none", ink, max(1.5, r * 0.07), 0.55)
    k = r / 30
    # pick: handle + curved head
    doc.path(f"M{f(cx - 13 * k)} {f(cy + 14 * k)}L{f(cx + 10 * k)} {f(cy - 9 * k)}", stroke=ink, sw=5 * k)
    doc.path(f"M{f(cx - 4 * k)} {f(cy - 17 * k)}Q{f(cx + 13 * k)} {f(cy - 13 * k)} {f(cx + 17 * k)} {f(cy + 4 * k)}",
             stroke=ink, sw=5 * k)


def _foreign(doc: Doc, cx: float, cy: float, r: float, color: str) -> None:
    doc.rect(cx - r * 0.7, cy - r * 0.7, r * 1.4, r * 1.4, color, r * 0.18)


def _endpoint(doc: Doc, cx: float, top: float, w: float, *, kind: str, hot: bool, miner: bool, danger: str,
              gold: str, dim: float) -> None:
    """A managed computer in front elevation: monitor on a stand, or a laptop.
    `top` is where its string attaches."""
    h = w * 0.62
    x = cx - w / 2
    body = "#2B3447" if not hot else "#33293A"
    edge = "#465169" if not hot else danger
    screen = "#0C1220"
    with doc.g(opacity=dim):
        doc.add(f'<ellipse cx="{f(cx)}" cy="{f(top + h + w * 0.2)}" rx="{f(w * 0.42)}" ry="{f(w * 0.035)}" '
                f'fill="#000" opacity="0.55" filter="{doc.blur(5)}"/>')
        if kind == "laptop":
            doc.rect(x + w * 0.04, top, w * 0.92, h * 0.92, body, w * 0.035, stroke=edge, sw=2)
            sx, sy, sw_, sh = x + w * 0.09, top + w * 0.05, w * 0.82, h * 0.92 - w * 0.09
            doc.path(f"M{f(x - w * 0.04)} {f(top + h * 0.92)}H{f(x + w * 1.04)}L{f(x + w * 0.98)} "
                     f"{f(top + h * 0.92 + w * 0.06)}H{f(x + w * 0.02)}Z", fill="#3A4459")
        else:
            doc.path(f"M{f(cx - w * 0.06)} {f(top + h - 4)}H{f(cx + w * 0.06)}L{f(cx + w * 0.08)} "
                     f"{f(top + h + w * 0.17)}H{f(cx - w * 0.08)}Z", fill="#232B3B")
            doc.rect(cx - w * 0.22, top + h + w * 0.16, w * 0.44, w * 0.04, "#2E3749", w * 0.02)
            doc.rect(x, top, w, h, body, w * 0.04, stroke=edge, sw=2)
            sx, sy, sw_, sh = x + w * 0.05, top + w * 0.05, w * 0.9, h - w * 0.1
        doc.rect(sx, sy, sw_, sh, screen if not hot else "#1A0F16", w * 0.015)
        if hot:
            doc.rect(sx, sy, sw_, sh, doc.rad([(0, danger, 0.35), (1, danger, 0)], 0.5, 0.5, 0.6), w * 0.015)
            r = min(sw_, sh) * 0.34
            if miner:
                _coin(doc, sx + sw_ / 2, sy + sh / 2, r, gold, "#2A1A05")
            else:
                _foreign(doc, sx + sw_ / 2, sy + sh / 2, r, danger)
        doc.path(f"M{f(sx)} {f(sy)}H{f(sx + sw_ * 0.5)}L{f(sx + sw_ * 0.22)} {f(sy + sh)}H{f(sx)}Z",
                 fill="#FFFFFF", opacity=0.04)


def _string(doc: Doc, a: tuple[float, float], b: tuple[float, float], color: str, sw: float, slack: float,
            opacity: float) -> None:
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + slack
    doc.path(f"M{f(a[0])} {f(a[1])}Q{f(mx)} {f(my)} {f(b[0])} {f(b[1])}", stroke=color, sw=sw, opacity=opacity)


def _bar(doc: Doc, x0: float, x1: float, y: float, th: float, tilt: float) -> list[tuple[float, float]]:
    """The control bar: a horizontal beam with a short cross beam, lit from
    above. Returns the string anchor points along the beam."""
    p = doc.pal
    cx = (x0 + x1) / 2
    wood = doc.lin([(0, "#56627A", 1), (0.45, "#323C51", 1), (1, "#1A2130", 1)])
    with doc.g(transform=f"rotate({tilt} {f(cx)} {f(y)})"):
        doc.rect(x0 + 10, y + th * 0.9, x1 - x0, th * 0.6, "#000", th * 0.3, opacity=0.45,
                 extra=f' filter="{doc.blur(10)}"')
        doc.rect(x0, y - th / 2, x1 - x0, th, wood, th / 2, stroke="#5F6B84", sw=1.5)
        doc.rect(x0 + th * 0.4, y - th / 2 + 3, x1 - x0 - th * 0.8, th * 0.18, "#FFFFFF", th * 0.09, opacity=0.18)
        # cross beam (seen end-on: a short vertical bar)
        doc.rect(cx - th * 0.55, y - th * 1.9, th * 1.1, th * 3.8, wood, th * 0.5, stroke="#5F6B84", sw=1.5)
        for ex in (x0 + th * 0.55, x1 - th * 0.55):
            doc.circle(ex, y, th * 0.2, p.bg0, "#7C88A2", 1.5)
    return [(x0 + (x1 - x0) * t, y + th / 2) for t in (0.04, 0.2, 0.36, 0.64, 0.8, 0.96)]


@scene("rmm_console")
def rmm_console(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    attack = brief.status in _ATTACK
    miner = attack and any(k in text for k in ("miner", "mining", "cryptomin", "майнер", "майнінг"))
    danger, gold = p.danger, "#F5B83D"

    # stage: a single cone of light from above, falling on the bar and the fleet
    doc.rect(0, 0, W, H, doc.lin([(0, "#0E1524", 1), (1, "#06090F", 1)]))
    doc.path(f"M{W * 0.36:.0f} 0H{W * 0.64:.0f}L{W * 0.98:.0f} {H}H{W * 0.02:.0f}Z",
             fill=doc.lin([(0, "#9FB4D8", 0.16), (1, "#9FB4D8", 0.02)]))
    doc.add(f'<ellipse cx="{W / 2}" cy="{H - 70}" rx="760" ry="120" fill="#5D7096" opacity="0.10" '
            f'filter="{doc.blur(30)}"/>')

    bar_y, th = 196.0, 50.0
    tilt = -3.0 if attack else 0.0
    anchors = _bar(doc, 440, 1160, bar_y, th, tilt)

    # the fleet: a back row (smaller, dimmer) and a front row of three
    back = [(330.0, 372.0, 140.0), (640.0, 362.0, 130.0), (960.0, 362.0, 130.0), (1270.0, 372.0, 140.0)]
    front = [(470.0, 462.0, 290.0), (800.0, 482.0, 300.0), (1130.0, 462.0, 290.0)]
    kinds_b = ["laptop", "monitor", "monitor", "laptop"]
    kinds_f = ["monitor", "laptop", "monitor"]
    hot_f = {1, rng.choice((0, 2))} if attack else set()
    hot_b = set(rng.sample(range(4), 2)) if attack else set()
    a_back, a_front = (0, 2, 3, 5), (1, 2, 4)

    # strings first (behind the machines)
    for row, hot, idx, dim, sw in ((back, hot_b, a_back, 0.5, 2.0), (front, hot_f, a_front, 1.0, 3.0)):
        for i, (cx, top, _w) in enumerate(row):
            taut = i in hot
            _string(doc, anchors[idx[i]], (cx, top), danger if taut else "#8E9AB2", sw * (1.2 if taut else 1),
                    0 if taut else 30, (0.95 if taut else 0.5) * dim)
    for row, hot, dim, kinds in ((back, hot_b, 0.55, kinds_b), (front, hot_f, 1.0, kinds_f)):
        for i, (cx, top, w) in enumerate(row):
            _endpoint(doc, cx, top, w, kind=kinds[i], hot=i in hot, miner=miner, danger=danger, gold=gold, dim=dim)
            doc.circle(cx, top, 6 if row is front else 3.5, danger if i in hot else "#8E9AB2", opacity=dim)

    # the name plate on the cross beam: the management platform the sources name
    name = _product(brief)
    flaws = str(brief.facts.get("flaws", "")).strip()
    if name:
        size = 60.0
        tw = T.measure(T.supported(name, "ui_bold"), size, "ui_bold")
        doc.rect(800 - tw / 2 - 26, bar_y - 168, tw + 52, 84, "#E8EDF5", 10)
        doc.text(name, 800, bar_y - 105, size, "#0E1524", "ui_bold", anchor="middle")
    if flaws.isdigit():
        # the patch the vendor shipped: a tag hanging from the bar's right end
        ex, ey = 1160 - th * 0.55, bar_y + (1160 - 800 - th * 0.55) * -0.0524 * (1 if attack else 0)
        tx, ty = 1100.0, bar_y + 56
        doc.path(f"M{f(ex)} {f(ey)}L{f(tx - 8)} {f(ty + 30)}", stroke="#C9D2E3", sw=2, opacity=0.8)
        lab = f"{flaws} flaws patched"
        tw = T.measure(T.supported(lab, "ui_bold"), 30, "ui_bold")
        doc.path(f"M{f(tx)} {f(ty)}H{f(tx + tw + 46)}V{f(ty + 60)}H{f(tx)}L{f(tx - 18)} {f(ty + 30)}Z",
                 fill=p.warn)
        doc.circle(tx + 4, ty + 30, 5, "#0E1524")
        doc.text(lab, tx + 24, ty + 41, 30, "#1A1405", "ui_bold")

    doc.rect(0, 0, W, H, doc.rad([(0.6, "#000", 0), (1, "#000", 0.55)], 0.5, 0.45, 0.78))
    doc.focus = Box(190, 40, 1240, 698)
