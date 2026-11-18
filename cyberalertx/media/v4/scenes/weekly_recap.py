"""Weekly roundup: a board of product tiles, one per product the roundup names,
each flagged with what the headline says about it (0-day, exploited,
takeover...). The tile set comes from the story text (a remote-management
console for N-able, an OS window for Windows, a browser for Chrome, a smart
fridge for a fridge...), in the order the headline names them; generic tiles
fill in only when fewer than four are named. No logos."""
from __future__ import annotations

import random
import re
from typing import Callable

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, icon, vignette
from . import scene
from ._objects import browser as _browser_obj
from ._objects import server as _server_obj

Draw = Callable[[Doc, Box, str, random.Random], None]

# kind, pattern in the text, default label
_TILES: tuple[tuple[str, str, str], ...] = (
    ("rmm", r"n-able|n-central|\brmm\b|screenconnect|remote[- ]management", "RMM"),
    ("os", r"windows", "Windows"),
    ("browser", r"chrome|browser|firefox|safari", "Browser"),
    ("fridge", r"fridge|refrigerat", "Fridge"),
    ("ssh", r"sshole|\bssh\b|openssh", "SSH"),
    ("robot", r"robot", "Robots"),
    ("sites", r"hacked sites|websites|wordpress|\bsites\b", "Websites"),
    ("update", r"trusted update|update tools?|booby-trapped .{0,20}update|hijacked update", "Update"),
    ("password", r"default password|blank password|admin:admin", "Password"),
)
_FALLBACK = ("server", "browser", "os", "password")


def _pick(brief: EditorialBrief) -> list[tuple[str, str, str]]:
    """Up to four (kind, label, flag) in the order the text names them."""
    t = brief.text
    found: list[tuple[int, str, str, str]] = []
    for kind, pat, label in _TILES:
        m = re.search(pat, t)
        if not m:
            continue
        ent = next((e for e in brief.entities if re.fullmatch(pat, e.lower())), "")
        if not ent:
            ent = next((e for e in brief.entities if re.search(pat, e.lower())), "")
        found.append((m.start(), kind, ent or label, _flag(t, m.start(), m.end())))
    found.sort()
    out = [(k, lab, fl) for _, k, lab, fl in found][:4]
    for k in _FALLBACK:
        if len(out) >= 4:
            break
        if all(k != o[0] for o in out):
            out.append((k, k.capitalize() if k != "os" else "OS", ""))
    return out


def _flag(t: str, a: int, b: int) -> str:
    near = t[a:b + 26]
    for pat, lab in ((r"0-days?|zero-days?", "0-DAY"), (r"exploit", "EXPLOITED"), (r"takeover", "TAKEOVER"),
                     (r"hacked", "HACKED"), (r"malware|booby", "TROJANIZED"), (r"open|blank|default", "OPEN")):
        if re.search(pat, near):
            return lab
    return "FLAW"


# ---------------------------------------------------------------- tile drawings (zone b, ink on dark)

def _rmm(doc: Doc, b: Box, mark: str, rng: random.Random) -> None:
    x, y, w, h = b.x + 18, b.y + 40, b.w - 36, b.h - 70
    doc.rect(x, y, w, h, "#0E1522", 10, stroke="#33415C", sw=1.5)
    doc.rect(x, y, w, 30, "#1A2438", 10)
    doc.rect(x, y + 20, w, 10, "#1A2438")
    for i in range(3):
        doc.circle(x + 16 + i * 13, y + 15, 4, "#5A6884")
    doc.rect(x, y + 30, 64, h - 30, "#131C2C")
    for i in range(5):
        doc.rect(x + 16, y + 52 + i * 30, 32, 8, "#33415C", 3)
    hit = rng.randrange(1, 5)
    for i in range(6):
        ry = y + 46 + i * 36
        if ry + 26 > y + h:
            break
        doc.rect(x + 76, ry, w - 88, 28, mark if i == hit else "#162033", 5, opacity=0.25 if i == hit else 1)
        icon(doc, "monitor", x + 94, ry + 14, 18, "#8FA0BF", 1.6)
        doc.rect(x + 112, ry + 10, w * 0.32, 8, "#4A5872", 4)
        doc.circle(x + w - 26, ry + 14, 5, mark if i == hit else "#4ADE80")


def _os(doc: Doc, b: Box, mark: str, rng: random.Random) -> None:
    x, y, w, h = b.x + 18, b.y + 40, b.w - 36, b.h - 70
    doc.rect(x, y, w, h, doc.lin([(0, "#2B5797", 1), (1, "#16294A", 1)], 0, 0, 1, 1), 8)
    doc.rect(x, y + h - 30, w, 30, "#0D1626", opacity=0.92)
    for i in range(5):
        doc.rect(x + w / 2 - 70 + i * 30, y + h - 22, 18, 14, "#3D5378", 3)
    wx, wy, ww, wh = x + 26, y + 30, w - 52, h - 90
    doc.rect(wx + 4, wy + 8, ww, wh, "#000", 6, opacity=0.35, extra=f' filter="{doc.blur(6)}"')
    doc.rect(wx, wy, ww, wh, "#F2F4F7", 6)
    doc.rect(wx, wy, ww, 26, "#E0E5EC", 6)
    # minimise / maximise / close at the right
    cx = wx + ww - 18
    doc.path(f"M{f(cx - 5)} {f(wy + 8)}l10 10M{f(cx + 5)} {f(wy + 8)}l-10 10", stroke=mark, sw=2)
    doc.rect(cx - 33, wy + 8, 10, 10, "none", 1, stroke="#6B7686", sw=1.6)
    doc.line((cx - 60, wy + 17), (cx - 50, wy + 17), "#6B7686", 1.6)
    icon(doc, "shieldx", wx + 40, wy + 70, 40, mark, 2.4)
    doc.rect(wx + 72, wy + 56, ww * 0.42, 9, "#8C97A6", 4)
    doc.rect(wx + 72, wy + 76, ww * 0.3, 7, "#C3CCD8", 3)
    doc.rect(wx + ww - 96, wy + wh - 38, 78, 24, mark, 4)


def _browser(doc: Doc, b: Box, mark: str, rng: random.Random) -> None:
    _browser_obj(doc, b.cx, b.cy + 10, b.w - 30, mark, rng)


def _fridge(doc: Doc, b: Box, mark: str, rng: random.Random) -> None:
    """A two-door smart fridge in front elevation with a door display."""
    w, h = b.w * 0.56, b.h * 0.9
    x, y = b.cx - w / 2, b.y + (b.h - h) / 2 + 6
    doc.add(f'<ellipse cx="{f(b.cx)}" cy="{f(y + h + 4)}" rx="{f(w * 0.62)}" ry="8" fill="#000" opacity="0.5" '
            f'filter="{doc.blur(6)}"/>')
    steel = doc.lin([(0, "#AEB5BE", 1), (0.35, "#E4E8EC", 1), (0.7, "#C3C9D0", 1), (1, "#8E959F", 1)], 0, 0, 1, 0)
    doc.rect(x, y, w, h, steel, 10, stroke="#6E7580", sw=1.5)
    split = y + h * 0.62
    doc.line((x + w / 2, y + 4), (x + w / 2, split), "#6E7580", 2)
    doc.line((x + 2, split), (x + w - 2, split), "#6E7580", 2)
    doc.rect(x + w / 2 - 14, y + h * 0.18, 5, h * 0.3, "#5D646E", 2)
    doc.rect(x + w / 2 + 9, y + h * 0.18, 5, h * 0.3, "#5D646E", 2)
    doc.rect(x + w * 0.2, split + 14, w * 0.6, 5, "#5D646E", 2)
    # display on the left door
    dx, dy, dw, dh = x + 12, y + h * 0.16, w / 2 - 34, h * 0.24
    doc.rect(dx, dy, dw, dh, "#0B1420", 5)
    for i in range(3):
        doc.rect(dx + 8, dy + dh * (0.22 + i * 0.24), (dw - 16) * (0.8 - 0.25 * i), dh * 0.12, "#7CC4FF", 2,
                 opacity=0.85 - 0.2 * i)
    doc.rect(dx - 3, dy - 3, dw + 6, dh + 6, "none", 6, stroke=mark, sw=2.5)
    icon(doc, "globe", dx + dw - 10, dy + 10, 12, mark, 1.6)
    doc.rect(x + 8, y + h - 8, 14, 10, "#2C3036", 2)
    doc.rect(x + w - 22, y + h - 8, 14, 10, "#2C3036", 2)


def _ssh(doc: Doc, b: Box, mark: str, rng: random.Random) -> None:
    x, y, w, h = b.x + 18, b.y + 40, b.w - 36, b.h - 70
    doc.rect(x, y, w, h, "#05080D", 10, stroke="#33415C", sw=1.5)
    lines = [("$ ssh root@host.example", "#C9D3E3"), ("Last login: ...", "#5A6884"), ("root@host:~# id", mark),
             ("uid=0(root)", mark), ("root@host:~# _", "#C9D3E3")]
    for i, (s, c) in enumerate(lines):
        doc.text(T.fit(s, 17, w - 30, "mono"), x + 16, y + 44 + i * 34, 17, c, "mono")


def _robot(doc: Doc, b: Box, mark: str, rng: random.Random) -> None:
    """An industrial robot arm in side elevation: base, shoulder, two links,
    wrist and gripper."""
    bx, by = b.cx - 50, b.b - 30
    doc.add(f'<ellipse cx="{f(bx)}" cy="{f(by + 4)}" rx="80" ry="9" fill="#000" opacity="0.5" '
            f'filter="{doc.blur(6)}"/>')
    paint = doc.lin([(0, "#F5A524", 1), (1, "#C67B0E", 1)], 0, 0, 1, 1)
    doc.rect(bx - 60, by - 22, 120, 22, "#3A404A", 4)
    doc.rect(bx - 40, by - 60, 80, 40, paint, 8)
    sx, sy = bx, by - 70
    ex, ey = bx + 70, by - 190
    wx, wy = bx + 160, by - 130
    doc.path(f"M{sx} {sy}L{ex} {ey}", stroke="#C67B0E", sw=40, cap="round")
    doc.path(f"M{sx} {sy}L{ex} {ey}", stroke="#F5A524", sw=30, cap="round")
    doc.path(f"M{ex} {ey}L{wx} {wy}", stroke="#C67B0E", sw=30, cap="round")
    doc.path(f"M{ex} {ey}L{wx} {wy}", stroke="#F5A524", sw=22, cap="round")
    for (jx, jy, r) in ((sx, sy, 24), (ex, ey, 20), (wx, wy, 14)):
        doc.circle(jx, jy, r, "#2A2F37")
        doc.circle(jx, jy, r * 0.45, "#8C929B")
    doc.path(f"M{wx} {wy + 10}V{wy + 40}M{wx - 14} {wy + 40}H{wx + 14}M{wx - 14} {wy + 40}V{wy + 62}"
             f"M{wx + 14} {wy + 40}V{wy + 62}", stroke="#B7BDC6", sw=6, cap="square")
    doc.circle(bx + 26, by - 40, 6, mark)


def _sites(doc: Doc, b: Box, mark: str, rng: random.Random) -> None:
    cols, rows = 3, 3
    cw, ch = (b.w - 60) / cols, (b.h - 80) / rows
    hit = set(rng.sample(range(9), 5))
    for k in range(9):
        i, j = k % cols, k // cols
        x, y = b.x + 22 + i * (cw + 8), b.y + 40 + j * (ch + 8)
        doc.rect(x, y, cw, ch, "#E9EDF2", 6)
        doc.rect(x, y, cw, 12, "#C9D1DC", 6)
        doc.rect(x + 8, y + 22, cw * 0.6, 7, "#8C97A6", 3)
        doc.rect(x + 8, y + 36, cw * 0.8, 5, "#C3CCD8", 2)
        if k in hit:
            doc.rect(x, y, cw, ch, "none", 6, stroke=mark, sw=3)
            doc.circle(x + cw - 12, y + ch - 12, 6, mark)


def _update(doc: Doc, b: Box, mark: str, rng: random.Random) -> None:
    x, y, w, h = b.x + 24, b.y + 60, b.w - 48, b.h - 120
    doc.rect(x, y, w, h, "#F2F4F7", 10)
    icon(doc, "download", x + 50, y + 56, 46, "#2F6FDB", 2.6)
    doc.rect(x + 92, y + 40, w * 0.5, 10, "#5B6577", 5)
    doc.rect(x + 92, y + 60, w * 0.35, 7, "#AEB8C5", 3)
    doc.rect(x + 24, y + h - 70, w - 48, 14, "#DCE2EA", 7)
    doc.rect(x + 24, y + h - 70, (w - 48) * 0.72, 14, mark, 7)
    icon(doc, "warn", x + w - 40, y + h - 28, 26, mark, 2.4)


def _password(doc: Doc, b: Box, mark: str, rng: random.Random, blank: bool = False) -> None:
    x, y, w = b.x + 30, b.y + 70, b.w - 60
    doc.rect(x - 10, y - 30, w + 20, 250, "#F2F4F7", 10)
    icon(doc, "user", x + 18, y + 4, 26, "#5B6577", 2)
    doc.rect(x + 2, y + 30, w - 4, 44, "#FFFFFF", 6, stroke="#C3CCD8", sw=1.5)
    doc.text("admin", x + 16, y + 59, 20, "#1B2333", "mono")
    doc.rect(x + 2, y + 92, w - 4, 44, "#FFFFFF", 6, stroke=mark, sw=2.5)
    if blank:
        doc.rect(x + 16, y + 102, 2.5, 24, mark)
    else:
        doc.text("admin", x + 16, y + 121, 20, mark, "mono_bold")
    doc.rect(x + 2, y + 156, w - 4, 40, "#2F6FDB", 6)


def _server(doc: Doc, b: Box, mark: str, rng: random.Random) -> None:
    _server_obj(doc, b.cx + 10, b.cy, b.w * 0.62, mark, rng)


_DRAW: dict[str, Draw] = {"rmm": _rmm, "os": _os, "browser": _browser, "fridge": _fridge, "ssh": _ssh,
                          "robot": _robot, "sites": _sites, "update": _update, "password": _password,
                          "server": _server}


@scene("weekly_recap")
def weekly_recap(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.5, 0.0))
    tiles = _pick(brief)
    n = len(tiles)
    gap, x0, top, th = 26.0, 70.0, 122.0, 640.0
    tw = (1600 - 2 * x0 - gap * (n - 1)) / n
    for i, (kind, label, flag) in enumerate(tiles):
        x = x0 + i * (tw + gap)
        y = top + (18 if i % 2 else 0)
        doc.shadow(x, y, tw, th, 18, 0.9)
        doc.rect(x, y, tw, th, doc.lin([(0, "#1A2438", 1), (1, "#121A2A", 1)]), 18, stroke="#2A3650", sw=1.2)
        zone = Box(x + 10, y + 34, tw - 20, 380)
        doc.rect(zone.x, zone.y, zone.w, zone.h, "#0F1624", 12)
        with doc.g(clip=doc.clip_rect(zone.x, zone.y, zone.w, zone.h, 12)):
            if kind == "password":
                _password(doc, zone, p.danger if flag else p.warn, rng, blank="blank password" in brief.text)
            else:
                _DRAW[kind](doc, zone, p.danger if flag else p.warn, rng)
        # name and flag
        size = 46.0
        while size > 24 and T.measure(T.supported(label, "display"), size, "display") > tw - 56:
            size -= 2
        doc.text(label, x + 28, y + th - 140, size, p.ink, "display")
        doc.line((x + 28, y + th - 112), (x + tw - 28, y + th - 112), p.line, 1.5)
        if flag:
            fw = T.measure(flag, 22, "ui_bold", 2) + 36
            doc.rect(x + 28, y + th - 88, fw, 42, p.danger, 6)
            doc.text(flag, x + 46, y + th - 59, 22, "#FFFFFF", "ui_bold", tracking=2)
        else:
            doc.text("no flag reported", x + 28, y + th - 58, 18, p.muted, "ui")
        # pin
        doc.circle(x + tw / 2, y + 16, 7, p.danger if flag else p.muted)
        doc.circle(x + tw / 2 - 2, y + 14, 2.5, "#FFFFFF", opacity=0.6)
    doc.focus = Box(60, 100, 1480, 832)
    vignette(doc, 0.45)
