"""Remote monitoring and management (RMM): the MSP's console and the fleet it
manages. The mechanism is the subject: one console can push a task to every
managed machine, so whoever controls the console controls the fleet.

Evidence decides the drama. With exploitation on record the pushed task has
landed and several endpoints run an unwanted process at full load (a miner,
when the sources say so); otherwise the console shows the exposure: a
pending security update on the management server and a fleet still intact.
Generic interface, no vendor UI, `.example` domain only."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from .. import type as T
from ..kit import Box, Doc, arrow, background, icon, pill, vignette, window
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")


def _monitor(doc: Doc, x: float, y: float, w: float, h: float, *, hot: bool, rng: random.Random,
             name: str) -> tuple[float, float]:
    """A desktop monitor in elevation (bezel, screen, neck, foot, contact shadow).
    Returns the point where an incoming task line meets it."""
    p = doc.pal
    base_y = y + h + 46
    # contact + cast shadow on the floor
    doc.add(f'<ellipse cx="{x + w / 2:.1f}" cy="{base_y + 6:.1f}" rx="{w * 0.36:.1f}" ry="9" fill="#000" '
            f'opacity="0.55" filter="{doc.blur(6)}"/>')
    # stand: neck + foot
    nx = x + w / 2
    doc.path(f"M{nx - 13:.1f} {y + h - 4:.1f}L{nx + 13:.1f} {y + h - 4:.1f}L{nx + 17:.1f} {base_y - 6:.1f}"
             f"L{nx - 17:.1f} {base_y - 6:.1f}Z", fill=doc.lin([(0, "#3A4458", 1), (1, "#202838", 1)], 0, 0, 1, 0))
    doc.path(f"M{nx - w * 0.22:.1f} {base_y:.1f}Q{nx - w * 0.22:.1f} {base_y - 10:.1f} {nx - w * 0.16:.1f} "
             f"{base_y - 10:.1f}H{nx + w * 0.16:.1f}Q{nx + w * 0.22:.1f} {base_y - 10:.1f} {nx + w * 0.22:.1f} "
             f"{base_y:.1f}Z", fill=doc.lin([(0, "#4A5569", 1), (1, "#262E3D", 1)]))
    # bezel
    doc.rect(x, y, w, h, doc.lin([(0, "#2C3546", 1), (1, "#141A26", 1)]), 10, stroke="#3F4A60", sw=1.2)
    s = Box(x + 9, y + 9, w - 18, h - 26)
    doc.rect(s.x, s.y, s.w, s.h, "#0B111C" if not hot else "#1A0D10", 4)
    doc.circle(x + w / 2, y + h - 8.5, 2.2, "#4ADE80" if not hot else p.danger, opacity=0.9)
    # screen content: a CPU graph of the endpoint
    gx, gy, gw, gh = s.x + 14, s.y + 42, s.w - 28, s.h - 56
    doc.text(name, s.x + 14, s.y + 26, 15, p.muted, "mono")
    for i in range(1, 4):
        doc.line((gx, gy + gh * i / 4), (gx + gw, gy + gh * i / 4), "#FFFFFF", 1, 0.06)
    n = 24
    pts = []
    for i in range(n + 1):
        t = i / n
        if hot and t > 0.3:
            v = 0.97 - rng.random() * 0.03
        elif hot and t > 0.22:
            v = 0.35 + (t - 0.22) / 0.08 * 0.6
        else:
            v = 0.08 + rng.random() * 0.14
        pts.append((gx + gw * t, gy + gh * (1 - v)))
    line = "M" + "L".join(f"{px:.1f} {py:.1f}" for px, py in pts)
    col = p.danger if hot else "#5B6F8F"
    doc.path(line + f"L{gx + gw:.1f} {gy + gh:.1f}L{gx:.1f} {gy + gh:.1f}Z", fill=col, opacity=0.22)
    doc.path(line, stroke=col, sw=2.4)
    if hot:
        doc.text("100%", gx + gw - 4, gy + gh * 0.62, 26, "#FFD9D5", "mono_bold", anchor="end")
    # glass reflection
    doc.path(f"M{s.x:.1f} {s.y:.1f}H{s.x + s.w * 0.55:.1f}L{s.x + s.w * 0.25:.1f} {s.b:.1f}H{s.x:.1f}Z",
             fill="#FFFFFF", opacity=0.035)
    return x - 4, y + h / 2


def _cpu_meter(doc: Doc, x: float, y: float, w: float, v: float, hot: bool) -> None:
    p = doc.pal
    doc.rect(x, y, w, 12, "#24304A", 6)
    doc.rect(x, y, max(12, w * v), 12, p.danger if hot else "#5B6F8F", 6)


@scene("rmm_console")
def rmm_console(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.32, 0.18))
    text = brief.text or ""
    attack = brief.status in _ATTACK
    miner = attack and any(k in text for k in ("miner", "mining", "cryptomin", "майнер", "майнінг"))
    rogue = attack and not miner and any(k in text for k in ("rogue", "remote access", "client"))

    # ---- the console (hero)
    win = Box(56, 92, 1000, 736)
    body = window(doc, win, url="rmm.msp-portal.example/devices", lock=True, surface="#111A2B", chrome="#18223A")
    # sidebar
    side = Box(body.x, body.y, 196, body.h)
    doc.add(f'<path d="M{side.x:.1f} {side.y:.1f}H{side.r:.1f}V{side.b:.1f}H{side.x + 14:.1f}'
            f'Q{side.x:.1f} {side.b:.1f} {side.x:.1f} {side.b - 14:.1f}Z" fill="#0D1422"/>')
    nav = [("monitor", "Devices"), ("play", "Tasks"), ("terminal", "Scripts"), ("download", "Patches"),
           ("file", "Reports")]
    for i, (ic, label) in enumerate(nav):
        ny = side.y + 46 + i * 50
        if i == 0:
            doc.rect(side.x + 12, ny - 22, side.w - 24, 42, "#1E2A44", 8)
        icon(doc, ic, side.x + 36, ny - 1, 20, p.ink if i == 0 else p.muted, 1.8)
        doc.text(label, side.x + 58, ny + 6, 18, p.ink if i == 0 else p.muted, "ui")

    m = Box(side.r + 32, body.y, body.r - side.r - 60, body.h)
    doc.text("Devices", m.x, m.y + 56, 34, p.ink, "display")
    doc.text("all customers / all sites", m.x + 140, m.y + 55, 16, p.muted, "ui")

    # security-update banner on the management server itself
    flaws = str(brief.facts.get("flaws", "")).strip()
    by = m.y + 80
    doc.rect(m.x, by, m.w, 46, "#2A2412", 8, stroke="#5C4A16", sw=1)
    icon(doc, "warn", m.x + 24, by + 23, 20, p.warn, 2)
    msg = "Server security update available" + (f": {flaws} flaws fixed" if flaws.isdigit() else "")
    doc.text(msg, m.x + 46, by + 29, 17, "#F3D58A", "ui")
    pill(doc, m.r - 12, by + 9, "update server", fg="#1A1405", bg=p.warn, size=13, font="ui_bold", anchor="end")

    # device table
    cols = (m.x + 34, m.x + 236, m.x + 380, m.x + 560)
    hy = by + 88
    for cx, h in zip(cols, ("DEVICE", "OS", "LAST TASK", "CPU")):
        doc.text(h, cx, hy, 13, p.muted, "ui_bold", tracking=1.2)
    doc.line((m.x, hy + 14), (m.r, hy + 14), p.line, 1)
    names = ["FIN-WS-0142", "FIN-WS-0157", "HQ-SRV-DC01", "HQ-WS-0211", "OPS-WS-0089", "OPS-SRV-FS02",
             "HQ-WS-0230"]
    oses = ["Windows 11", "Windows 11", "Server 2022", "Windows 10", "Windows 11", "Server 2019", "Windows 11"]
    hot_rows = (set(rng.sample(range(6), 3)) | {6}) if attack else set()
    rh = 52
    for i, (nm, os_) in enumerate(zip(names, oses)):
        y = hy + 22 + i * rh
        hot = i in hot_rows
        if hot:
            doc.rect(m.x, y + 3, m.w, rh - 6, p.danger, 6, opacity=0.12)
            doc.rect(m.x, y + 3, 4, rh - 6, p.danger, 2)
        doc.rect(m.x + 12, y + rh / 2 - 7, 14, 14, "none", 3, stroke=p.ink if attack else p.muted, sw=1.4)
        if attack:  # every device was selected as the task's target
            icon(doc, "check", m.x + 19, y + rh / 2, 14, p.ink, 2.2)
        doc.text(nm, cols[0], y + rh / 2 + 6, 17, p.ink, "mono")
        doc.text(os_, cols[1], y + rh / 2 + 6, 16, p.muted, "ui")
        verb = "run script" if attack else "patch scan"
        doc.text(verb, cols[2], y + rh / 2 + 6, 16, p.danger if hot else p.muted, "mono")
        icon(doc, "check", cols[2] + 120, y + rh / 2, 15, p.danger if hot else p.muted, 2)
        v = 1.0 if hot else 0.05 + rng.random() * 0.18
        _cpu_meter(doc, cols[3], y + rh / 2 - 6, 116, v, hot)
        if hot:
            doc.text("100%", m.r - 10, y + rh / 2 + 6, 16, p.danger, "mono_bold", anchor="end")
        doc.line((m.x, y + rh), (m.r, y + rh), p.line, 1, 0.6)

    # ---- the fleet: physical endpoints the console manages (the first six rows)
    fl = Box(1118, 96, 466, 704)
    doc.rect(fl.x, fl.y, fl.w, fl.h, "none", 18, stroke=p.muted, sw=1.4, opacity=0.45, extra=' stroke-dasharray="4 8"')
    doc.text("MANAGED ENDPOINTS", fl.x + 22, fl.y + 30, 13, p.muted, "ui_bold", tracking=1.6)
    mw, mh = 196, 134
    for i in range(6):
        x = fl.x + 18 + (i % 2) * 230
        y = fl.y + 52 + (i // 2) * 222
        _monitor(doc, x, y, mw, mh, hot=i in hot_rows, rng=rng, name=names[i])

    # ---- the pushed task: console -> fleet
    if attack:
        task = Box(win.r - 400, win.b - 122, 386, 96)
        doc.shadow(task.x, task.y, task.w, task.h, 12, 0.7)
        doc.rect(task.x, task.y, task.w, task.h, "#1B1416", 12, stroke=p.danger, sw=2)
        icon(doc, "terminal", task.x + 34, task.y + 36, 26, p.danger, 2)
        doc.text("REMOTE TASK", task.x + 62, task.y + 31, 13, p.danger, "ui_bold", tracking=1.2)
        label = "deploy miner" if miner else ("install remote client" if rogue else "deploy payload")
        doc.text(label, task.x + 62, task.y + 58, 21, p.ink, "mono_bold")
        doc.text("targets: all devices   run as: SYSTEM", task.x + 24, task.y + 83, 14, p.muted, "mono")
        arrow(doc, [(task.r + 6, task.cy), (fl.x - 8, task.cy)], p.danger, sw=5, head=20)
    else:
        # exposure only: the management link exists, nothing has been pushed
        card = Box(win.r - 400, win.b - 122, 386, 96)
        doc.shadow(card.x, card.y, card.w, card.h, 12, 0.7)
        doc.rect(card.x, card.y, card.w, card.h, "#1F1A0E", 12, stroke=p.warn, sw=2)
        icon(doc, "server", card.x + 34, card.y + 36, 26, p.warn, 2)
        doc.text("MANAGEMENT SERVER", card.x + 62, card.y + 31, 13, p.warn, "ui_bold", tracking=1.2)
        doc.text("update pending", card.x + 62, card.y + 58, 21, p.ink, "mono_bold")
        doc.text("reach: all managed devices", card.x + 24, card.y + 83, 14, p.muted, "mono")
        arrow(doc, [(card.r + 6, card.cy), (fl.x - 8, card.cy)], p.warn, sw=3, head=16, dash="6 7")

    vignette(doc, 0.45)
    doc.focus = Box(600, 330, 960, 540)
