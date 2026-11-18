"""An AI-driven security tool run against a real target: the tool's console
shows its own plan — reconnaissance and intrusion steps it works through on
its own — and the company's cloud tenant on the right shows which resource
each step reaches. The step running now (privilege escalation) is the focal
point (shown as requested, not as obtained). When the sources say a stolen cloud access key opened the way, the key
appears as the entry point. No robots, no glowing brains."""
from __future__ import annotations

import random
import re

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, arrow, background, icon, pill, vignette, window
from . import scene


def _status_glyph(doc: Doc, x: float, y: float, state: str, col: str, muted: str) -> None:
    if state == "done":
        doc.circle(x, y, 13, col, opacity=0.18)
        icon(doc, "check", x, y, 18, col, 2.6)
    elif state == "run":
        doc.circle(x, y, 12, "none", muted, 3, 0.4)
        doc.path(f"M{x} {y - 12}A12 12 0 0 1 {x + 12} {y}", stroke=col, sw=3.5)
    else:
        doc.circle(x, y, 11, "none", muted, 2, 0.7)


def _bucket(doc: Doc, cx: float, cy: float, w: float, col: str) -> None:
    h = w * 0.8
    doc.path(f"M{cx - w / 2} {cy - h / 2}L{cx - w * 0.38} {cy + h / 2}A{w * 0.38} {w * 0.1} 0 0 0 "
             f"{cx + w * 0.38} {cy + h / 2}L{cx + w / 2} {cy - h / 2}Z", fill=doc.lin([(0, "#3B2E66", 1),
                                                                                       (1, "#251C40", 1)], 0, 0, 1, 0),
             stroke=col, sw=1.6)
    doc.add(f'<ellipse cx="{cx}" cy="{cy - h / 2}" rx="{w / 2}" ry="{w * 0.13}" fill="#4A3B80" stroke="{col}" '
            f'stroke-width="1.6"/>')


@scene("ai_offensive_tool")
def ai_offensive_tool(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.35, 0.15))
    t = brief.text
    tool = "artex" if "artex" in t else "agent"
    stolen_key = bool(re.search(r"(stolen|leaked|compromised) (cloud )?(access )?key|access key", t))

    # ---- identity: a security-testing tool, pointed at a real target
    if tool == "artex":
        doc.text("ARTEX", 64, 82, 46, p.ink, "display")
        nx = 64 + T.measure("ARTEX", 46, "display") + 28
        b = pill(doc, nx, 50, "security-testing tool", fg=p.muted, bg="#00000000", size=15, stroke=p.line)
        arrow(doc, [(b.r + 12, 68), (b.r + 62, 68)], p.danger, sw=2.5, head=11)
        pill(doc, b.r + 74, 50, "run against a real target", fg="#FFFFFF", bg=p.danger, size=15)
    # ---- the tool's console (left)
    win = Box(64, 110, 790, 680)
    body = window(doc, win, title=f"{tool} - autonomous run", surface="#120E22", chrome="#1D1636")
    x0 = body.x + 40
    doc.text("target", x0, body.y + 54, 18, p.muted, "mono")
    doc.text("tenant: company.example", x0 + 110, body.y + 54, 18, p.ink, "mono_bold")
    doc.text("mode", x0, body.y + 84, 18, p.muted, "mono")
    doc.text("autonomous", x0 + 110, body.y + 84, 18, p.accent, "mono_bold")
    doc.line((x0, body.y + 112), (body.r - 40, body.y + 112), p.line, 1.5)
    doc.text("PLAN", x0, body.y + 150, 16, p.muted, "ui_bold", tracking=3)
    steps = [
        ("recon", "enumerate users and apps", "done"),
        ("access", "sign in with cloud access key" if stolen_key else "obtain initial access", "done"),
        ("discover", "list storage and compute", "done"),
        ("escalate", "request privileged role", "run"),
        ("lateral", "reach connected systems", "todo"),
    ]
    if re.search(r"breach|зламал|викрал", t) and re.search(r"cloud|хмар", t):
        # The cloud-breach report: the run got as far as the data.
        steps[3] = ("escalate", "request privileged role", "done")
        steps[4] = ("collect", "copy data out of storage", "run")
    rows_y: list[float] = []
    for i, (k, desc, state) in enumerate(steps):
        y = body.y + 200 + i * 78
        rows_y.append(y)
        if state == "run":
            doc.rect(body.x + 16, y - 36, body.w - 32, 66, p.danger, 8, opacity=0.13)
            doc.rect(body.x + 16, y - 36, 5, 66, p.danger)
        col = p.danger if state == "run" else (p.accent if state == "done" else p.muted)
        _status_glyph(doc, x0 + 14, y - 3, state, col, p.muted)
        doc.text(f"{i + 1:02d}", x0 + 46, y + 4, 18, p.muted, "mono")
        doc.text(k, x0 + 92, y + 4, 24, p.ink if state != "todo" else p.muted, "mono_bold")
        doc.text(T.fit(desc, 19, body.w - 330, "mono"), x0 + 260, y + 3, 19,
                 p.ink if state == "run" else p.muted, "mono")
    yb = rows_y[-1] + 70
    doc.text("> next step chosen by model", x0, yb, 17, p.muted, "mono")
    doc.rect(x0 + T.measure("> next step chosen by model ", 17, "mono"), yb - 15, 10, 19, p.accent, opacity=0.8)

    # ---- the cloud tenant (right)
    tb = Box(960, 120, 580, 660)
    doc.rect(tb.x, tb.y, tb.w, tb.h, "#1A1430", 26, opacity=0.6)
    doc.rect(tb.x, tb.y, tb.w, tb.h, "none", 26, stroke=p.ink, sw=2, opacity=0.5,
             extra=' stroke-dasharray="10 9"')
    icon(doc, "globe", tb.x + 40, tb.y + 42, 26, p.ink, 2)
    doc.text("cloud tenant", tb.x + 66, tb.y + 50, 22, p.ink, "ui_bold")
    doc.text("company.example", tb.r - 30, tb.y + 50, 18, p.muted, "mono", anchor="end")

    # identity directory
    idb = Box(tb.x + 36, tb.y + 96, 240, 168)
    doc.rect(idb.x, idb.y, idb.w, idb.h, "#221A3E", 12, stroke=p.line, sw=1.5)
    doc.text("identity", idb.x + 18, idb.y + 32, 16, p.muted, "ui_bold", tracking=1.5)
    for i in range(3):
        icon(doc, "user", idb.x + 32, idb.y + 62 + i * 34, 22, p.ink, 1.8)
        doc.rect(idb.x + 54, idb.y + 56 + i * 34, 110 + (i * 37) % 60, 9, "#4A3B80", 4)
    # storage
    stb = Box(tb.x + 304, tb.y + 96, 240, 168)
    doc.rect(stb.x, stb.y, stb.w, stb.h, "#221A3E", 12, stroke=p.line, sw=1.5)
    doc.text("storage", stb.x + 18, stb.y + 32, 16, p.muted, "ui_bold", tracking=1.5)
    for i in range(3):
        _bucket(doc, stb.x + 52 + i * 68, stb.y + 106, 50, p.muted)
    # compute
    cpb = Box(tb.x + 36, tb.y + 296, 508, 150)
    doc.rect(cpb.x, cpb.y, cpb.w, cpb.h, "#221A3E", 12, stroke=p.line, sw=1.5)
    doc.text("compute", cpb.x + 18, cpb.y + 32, 16, p.muted, "ui_bold", tracking=1.5)
    for i in range(4):
        vx = cpb.x + 22 + i * 120
        doc.rect(vx, cpb.y + 54, 104, 70, "#2D2350", 8, stroke=p.line, sw=1.2)
        doc.rect(vx + 12, cpb.y + 68, 60, 8, "#5B4C99", 4)
        doc.rect(vx + 12, cpb.y + 84, 40, 6, "#46397A", 3)
        doc.circle(vx + 88, cpb.y + 108, 5, "#5EE6A8")
    # admin role (focal)
    adb = Box(tb.x + 36, tb.y + 480, 508, 140)
    doc.shadow(adb.x, adb.y, adb.w, adb.h, 12, 0.5)
    doc.rect(adb.x, adb.y, adb.w, adb.h, "#2A1631", 12, stroke=p.danger, sw=3)
    collect = steps[4][0] == "collect"
    icon(doc, "download" if collect else "key", adb.x + 58, adb.cy, 52, p.danger, 2.6)
    doc.text("data copied out" if collect else "privileged role", adb.x + 110, adb.y + 64, 30, p.ink, "display")
    doc.text("target of step 05" if collect else "target of step 04", adb.x + 112, adb.y + 100, 18, p.muted, "mono")
    pill(doc, adb.r - 24, adb.y + 22, "in progress", fg="#FFFFFF", bg=p.danger, size=15, anchor="end")

    # ---- step -> resource links
    ex = win.r + 10
    arrow(doc, [(ex, rows_y[0] - 4), (920, rows_y[0] - 4), (idb.x - 10, idb.y + 60)], p.accent, sw=2.5, head=12,
          opacity=0.7)
    arrow(doc, [(ex, rows_y[2] - 4), (930, rows_y[2] - 4), (cpb.x - 10, cpb.y + 70)], p.accent, sw=2.5, head=12,
          opacity=0.7)
    hot = rows_y[4] if collect else rows_y[3]
    arrow(doc, [(ex, hot - 4), (910, hot - 4), (910, adb.cy), (adb.x - 12, adb.cy)], p.danger, sw=4.5,
          head=18)
    if stolen_key:
        kx, ky = 900, rows_y[1] - 4
        doc.line((ex, ky), (kx - 34, ky), p.accent, 2.5, 0.7)
        doc.rect(kx - 34, ky - 22, 68, 44, "#2A1F4A", 10, stroke=p.accent, sw=2)
        icon(doc, "key", kx, ky, 28, p.accent, 2.2)
        arrow(doc, [(kx + 34, ky), (tb.x - 8, ky)], p.accent, sw=2.5, head=12, opacity=0.7)
    doc.focus = Box(60, 90, 1490, 838)
    vignette(doc, 0.5)
