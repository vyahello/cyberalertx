"""Espionage backdoors that use a legitimate cloud service as their command
channel: a government workstation inside its network polls an ordinary
cloud-storage folder; the operator drops command files into that folder and
picks up the results. To the network it is routine traffic to a known cloud
service. Generic storage interface, `.example` domain, no map."""
from __future__ import annotations

import random
import re

from ..brief import EditorialBrief
from ..kit import Box, Doc, arrow, f, icon, pill
from . import scene


def _monitor(doc: Doc, x: float, y: float, w: float, h: float, accent: str, danger: str) -> Box:
    """A desktop monitor on a stand, front elevation. Returns the screen box."""
    doc.add(f'<ellipse cx="{f(x + w / 2)}" cy="{f(y + h + 118)}" rx="{f(w * 0.36)}" ry="16" fill="#000" '
            f'opacity="0.45" filter="{doc.blur(10)}"/>')
    # stand + base
    doc.path(f"M{f(x + w / 2 - 34)} {f(y + h)}L{f(x + w / 2 - 46)} {f(y + h + 96)}H{f(x + w / 2 + 46)}"
             f"L{f(x + w / 2 + 34)} {f(y + h)}Z", fill=doc.lin([(0, "#2A3346", 1), (1, "#141A26", 1)], 0, 0, 1, 0))
    doc.rect(x + w / 2 - 130, y + h + 92, 260, 20, doc.lin([(0, "#3A4560", 1), (1, "#1A2130", 1)]), 8)
    # bezel
    doc.rect(x, y, w, h, doc.lin([(0, "#2C3448", 1), (1, "#161C29", 1)]), 16)
    doc.rect(x + 1, y + 1, w - 2, 3, "#FFFFFF", 2, opacity=0.12)
    s = Box(x + 18, y + 18, w - 36, h - 50)
    doc.rect(s.x, s.y, s.w, s.h, doc.lin([(0, "#20304A", 1), (1, "#141F33", 1)]), 4)
    doc.circle(x + w / 2, y + h - 16, 3.5, "#4ADE80", opacity=0.8)
    return s


def _desktop(doc: Doc, s: Box, rng: random.Random, danger: str) -> tuple[float, float]:
    """An ordinary office desktop; the backdoor runs as one quiet process.
    Returns the anchor of the backdoor's row."""
    # a document window
    d = Box(s.x + 24, s.y + 24, s.w * 0.62, s.h - 70)
    doc.rect(d.x, d.y, d.w, d.h, "#EEF1F6", 6)
    doc.rect(d.x, d.y, d.w, 24, "#D5DBE5", 6)
    doc.rect(d.x, d.y + 18, d.w, 6, "#D5DBE5")
    doc.rect(d.x + 26, d.y + 46, d.w * 0.5, 10, "#55617A", 3)
    for k in range(8):
        doc.rect(d.x + 26, d.y + 72 + k * 20, (d.w - 52) * rng.uniform(0.6, 1.0), 7, "#B9C2D2", 3)
    # process list, small, on the right
    pl = Box(d.r + 16, s.y + 24, s.r - d.r - 40, s.h - 70)
    doc.rect(pl.x, pl.y, pl.w, pl.h, "#0D1524", 6, stroke="#2A3650")
    doc.text("processes", pl.x + 12, pl.y + 22, 13, "#8191AD", "ui_bold")
    names = ("explorer", "outlook", "svc-sync", "winword", "runtime")
    hit = (0.0, 0.0)
    for k, n in enumerate(names):
        yy = pl.y + 48 + k * 28
        bad = n == "svc-sync"
        if bad:
            doc.rect(pl.x + 4, yy - 16, pl.w - 8, 24, danger, 3, opacity=0.25)
            hit = (pl.r, yy - 4)
            pill(doc, pl.x + 8, pl.b - 40, "backdoor", fg="#FFFFFF", bg=danger, size=13, font="ui_bold")
        doc.text(n, pl.x + 12, yy, 13, danger if bad else "#C7D0E0", "mono_bold" if bad else "mono")
    # taskbar
    doc.rect(s.x, s.b - 30, s.w, 30, "#0D1524")
    for k in range(5):
        doc.rect(s.x + 16 + k * 30, s.b - 22, 18, 14, "#3A4A66", 3)
    return hit


def _file_row(doc: Doc, x: float, y: float, w: float, name: str, meta: str, color: str, up: bool) -> None:
    doc.rect(x, y, w, 64, "#FFFFFF", 8, stroke=color, sw=2)
    doc.path(f"M{f(x + 22)} {f(y + 14)}h18l8 8v28h-26z", fill="#FFFFFF", stroke=color, sw=2)
    doc.path(f"M{f(x + 40)} {f(y + 14)}v8h8", stroke=color, sw=2)
    doc.text(name, x + 66, y + 30, 19, "#0F1B2A", "mono_bold")
    doc.text(meta, x + 66, y + 52, 14, "#5B6B7D", "ui")
    icon(doc, "upload" if up else "download", x + w - 30, y + 32, 24, color, 2.4)


@scene("espionage_backdoor")
def espionage_backdoor(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    doc.rect(0, 0, 1600, 900, doc.lin([(0, "#0E1626", 1), (1, "#070B14", 1)], 0, 0, 0.4, 1))
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#5EEAD4", 0.10), (1, "#5EEAD4", 0)], 0.55, 0.35, 0.55))
    cmd_c, res_c = "#F2C14E", p.danger

    # ---- the government network (left): a dashed perimeter around a workstation
    net = Box(40, 120, 560, 690)
    doc.rect(net.x, net.y, net.w, net.h, "#FFFFFF", 22, opacity=0.025)
    doc.rect(net.x, net.y, net.w, net.h, "none", 22, stroke="#5B6B87", sw=2, extra=' stroke-dasharray="9 8"')
    doc.rect(net.x + 28, net.y - 18, 236, 36, "#0E1626", 18)
    icon(doc, "shieldx", net.x + 50, net.y, 22, "#8C9BB5", 1.8)
    doc.text("government network", net.x + 70, net.y + 7, 19, "#C9D3E3", "ui_bold")
    scr = _monitor(doc, net.x + 40, net.y + 120, net.w - 80, 330, p.accent, p.danger)
    hit = _desktop(doc, scr, rng, p.danger)
    doc.text("WS-0214  |  ministry workstation", net.x + net.w / 2, net.y + 92, 16, "#8C9BB5", "mono",
             anchor="middle")
    pill(doc, net.x + net.w / 2, net.b - 70, "egress to cloud storage: allowed", fg="#C9F2DF", bg="#123227",
         size=15, font="ui", anchor="middle", stroke="#1F5A43")

    # ---- the cloud storage folder (hero, centre-right): light, ordinary, trusted
    cf = Box(720, 150, 520, 600)
    doc.shadow(cf.x, cf.y, cf.w, cf.h, 18, 1.3)
    doc.rect(cf.x, cf.y, cf.w, cf.h, "#F8FAFC", 18)
    doc.rect(cf.x, cf.y, cf.w, 66, "#E8EEF4", 18)
    doc.rect(cf.x, cf.y + 50, cf.w, 16, "#E8EEF4")
    # cloud glyph + address
    cx, cy = cf.x + 44, cf.y + 34
    doc.path(f"M{f(cx - 20)} {f(cy + 11)}H{f(cx + 20)}A11 11 0 0 0 {f(cx + 18)} {f(cy - 9)}A15 15 0 0 0 "
             f"{f(cx - 9)} {f(cy - 12)}A11 11 0 0 0 {f(cx - 20)} {f(cy + 11)}Z", stroke="#0B6BCB", sw=2.6)
    icon(doc, "lock", cf.x + 86, cy, 16, "#13804B", 2)
    doc.text("storage.cloud.example", cf.x + 102, cy + 6, 18, "#0F1B2A", "mono")
    doc.text("My files  /  sync  /  tmp", cf.x + 32, cf.y + 112, 22, "#0F1B2A", "display")
    doc.line((cf.x + 32, cf.y + 132), (cf.r - 32, cf.y + 132), "#D5DEE8", 1.5)
    # ordinary contents
    for k, (n, m) in enumerate((("notes.docx", "2 days ago"), ("photos/", "last week"))):
        yy = cf.y + 158 + k * 50
        doc.path(f"M{f(cf.x + 36)} {f(yy)}h14l6 6v18h-20z", fill="none", stroke="#9AAABD", sw=1.8)
        doc.text(n, cf.x + 72, yy + 18, 17, "#45556A", "mono")
        doc.text(m, cf.r - 36, yy + 18, 14, "#8495A8", "ui", anchor="end")
    # the command channel: a command file in, a result file out
    rw = cf.w - 64
    _file_row(doc, cf.x + 32, cf.y + 290, rw, "c_7f3a.tmp", "uploaded by operator  -  command", cmd_c,
              False)
    _file_row(doc, cf.x + 32, cf.y + 380, rw, "r_7f3a.tmp", "uploaded by WS-0214  -  command output", res_c, True)
    doc.text("To the network: routine traffic to a known cloud service.", cf.x + 32, cf.b - 40, 17, "#5B6B7D",
             "ui")

    # ---- the operator (right edge): a terminal that only talks to the cloud folder
    op = Box(1330, 300, 240, 260)
    doc.shadow(op.x, op.y, op.w, op.h, 12, 1.0)
    doc.rect(op.x, op.y, op.w, op.h, "#05080F", 12, stroke="#26324A")
    doc.text("operator", op.x + 20, op.y + 34, 16, "#8C9BB5", "ui_bold")
    lines = [("$ put cmd", cmd_c), ("  c_7f3a.tmp", "#C9D3E3"), ("$ get result", res_c), ("  r_7f3a.tmp", "#C9D3E3"),
             ("$ _", "#C9D3E3")]
    for k, (t, c) in enumerate(lines):
        doc.text(t, op.x + 20, op.y + 76 + k * 32, 17, c, "mono")

    # ---- flows. Commands: operator -> folder -> workstation; results: back the other way.
    c_row, r_row = cf.y + 322, cf.y + 412
    arrow(doc, [(op.x - 8, op.y + 90), (cf.r + 50, op.y + 90), (cf.r + 50, c_row), (cf.r + 10, c_row)], cmd_c,
          sw=3, head=14)
    mx = net.x + net.w - 40 + 8                          # the monitor's right edge
    arrow(doc, [(cf.x - 10, c_row), (net.r + 74, c_row), (net.r + 74, hit[1] - 6), (mx, hit[1] - 6)],
          cmd_c, sw=3, head=14)
    arrow(doc, [(mx, hit[1] + 22), (net.r + 40, hit[1] + 22), (net.r + 40, r_row), (cf.x - 10, r_row)],
          res_c, sw=3.5, head=15)
    arrow(doc, [(cf.r + 10, r_row), (cf.r + 80, r_row), (cf.r + 80, op.y + 160), (op.x - 8, op.y + 160)], res_c,
          sw=3.5, head=15)
    pill(doc, net.r - 20, hit[1] - 60, "commands in", fg="#0E1626", bg=cmd_c, size=14, font="ui_bold")
    pill(doc, net.r + 10, r_row + 22, "results out", fg="#FFFFFF", bg=res_c, size=14, font="ui_bold")

    # region, only as the sources state it
    if re.search(r"\basia\b", text) and re.search(r"\bafrica\b", text):
        doc.text("targets: government networks in Asia and Africa", 720, 830, 18, "#8C9BB5", "ui")
    doc.focus = Box(40, 110, 1260, 709)
