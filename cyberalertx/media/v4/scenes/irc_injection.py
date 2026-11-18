"""IRC server command injection (delimiter handling): a chat message carrying
a delimiter the IRC daemon does not neutralise ends up as a command run on the
server.

Left (hero): a terminal IRC client in a channel, with one crafted line whose
delimiter is drawn as a marked token, not as a specific character: the
sources say "improper neutralization of delimiters", not which delimiter or
how the command is run. Right: the server, stating only what the sources
state (command executed by the IRC server; exploitation per the evidence).
The CVE identifier is drawn only from brief.facts."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from .. import type as T
from ..kit import Box, Doc, icon, arrow, background, pill, vignette, window
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")


@scene("irc_injection")
def irc_injection(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.3, 0.2))
    attack = brief.status in _ATTACK
    ts, nick_c, txt, sys_c = "#5C6B80", "#7FB4FF", "#D3DCE8", "#6E7F96"
    nicks = {"alice": "#E6A1FF", "bob": "#7FE0C4", "carol": "#FFC27A", "guest42": "#FF8E86"}

    # ---- the IRC client (terminal UI)
    cw = Box(40, 92, 1000, 700)
    body = window(doc, cw, title="irc  -  #lobby", surface="#0A0E14", chrome="#151B26")
    nl = Box(body.r - 200, body.y, 200, body.h - 78)
    doc.rect(nl.x, nl.y, 1.2, nl.h, "#243042")
    for i, n in enumerate(("@ops", "@chanserv", "+alice", "bob", "carol", "dave", "guest42", "erin")):
        doc.text(n, nl.x + 24, nl.y + 42 + i * 34, 17, "#E8EDF5" if n.startswith("@") else sys_c, "mono")

    size, lh = 18, 40
    x0 = body.x + 24
    y0 = body.y + 48
    feed = [
        ("13:58", "-!-", "alice [~a@client.example] has joined #lobby", sys_c),
        ("14:01", "alice", "is the new build on the test network?", ""),
        ("14:01", "bob", "since monday, links look stable", ""),
        ("14:02", "carol", "anyone seen lag on the hub?", ""),
        ("14:03", "-!-", "guest42 [~g@203.0.113.7] has joined #lobby", sys_c),
        ("14:03", "bob", "not here", ""),
    ]
    for i, (t, who, msg, col) in enumerate(feed):
        y = y0 + i * lh
        doc.text(t, x0, y, size, ts, "mono")
        cx = x0 + T.measure("00:00 ", size, "mono")
        if who == "-!-":
            doc.text("-!- " + msg, cx, y, size, col, "mono")
        else:
            cx += doc.text(f"<{who}> ", cx, y, size, nicks.get(who, nick_c), "mono_bold")
            doc.text(msg, cx, y, size, txt, "mono")

    # the crafted line (focal)
    cy = y0 + len(feed) * lh + 26
    doc.rect(body.x + 10, cy - 34, nl.x - body.x - 22, 54, p.danger, 6, opacity=0.14)
    doc.rect(body.x + 10, cy - 34, 4, 54, p.danger)
    doc.text("14:04", x0, cy, 20, ts, "mono")
    cx = x0 + T.measure("00:00 ", 20, "mono")
    cx += doc.text("<guest42> ", cx, cy, 20, nicks["guest42"], "mono_bold")
    cx += doc.text("ping lag", cx, cy, 20, txt, "mono") + 8
    # the delimiter: a marked token, no specific character (not published)
    d_w = T.measure("delim", 14, "mono_bold") + 18
    doc.rect(cx, cy - 22, d_w, 28, p.danger, 6)
    doc.text("delim", cx + 9, cy - 3, 14, "#FFFFFF", "mono_bold")
    d_x = cx + d_w / 2
    cx += d_w + 8
    cmd_x = cx
    doc.text("<command>", cx, cy, 20, "#FFB4AD", "mono_bold")
    doc.path(f"M{d_x:.1f} {cy + 10:.1f}V{cy + 40:.1f}H{d_x - 36:.1f}", stroke=p.danger, sw=1.5)
    doc.text("delimiter not neutralised", d_x - 46, cy + 46, 16, p.danger, "mono", anchor="end")

    # input line + status bar, as in a terminal client
    sb = Box(body.x, body.b - 78, body.w, 36)
    doc.rect(sb.x, sb.y, sb.w, sb.h, "#1E3A66")
    doc.text("[14:04] [me(+i)] [2:net/#lobby(+nt)] [Act: 3]", sb.x + 20, sb.y + 24, 16, "#DCE7F7", "mono")
    doc.text("[#lobby]", body.x + 20, body.b - 14, 17, txt, "mono")
    doc.rect(body.x + 112, body.b - 30, 10, 20, txt, opacity=0.8)

    # ---- the server's shell
    sw = Box(980, 420, 580, 330)
    sbody = window(doc, sw, title="chat server", surface="#120B0C", chrome="#21171A", depth=1.2)
    doc.rect(sw.x, sw.y, sw.w, sw.h, "none", 14, stroke=p.danger if attack else p.line, sw=2)
    lines = [("unrealircd", sys_c, "mono_bold"),
             ("delimiter-handling flaw", "#F3D58A", "mono")]
    if attack:
        lines += [("", txt, "mono"),
                  ("command executed by", "#FFB4AD", "mono_bold"),
                  ("the IRC server", "#FFB4AD", "mono_bold"),
                  ("", txt, "mono"),
                  ("execution details not published", sys_c, "mono")]
    else:
        lines += [("delimiters in messages: not neutralised", "#F3D58A", "mono")]
    for i, (s_, col, font) in enumerate(lines):
        doc.text(s_, sbody.x + 24, sbody.y + 44 + i * 36, 18, col, font)
    if attack:
        icon(doc, "terminal", sbody.r - 64, sbody.y + 150, 56, p.danger, 2.4)

    # message -> server
    sx = cmd_x + 12
    arrow(doc, [(sx, cy + 14), (sx, sbody.y + 82 - 6), (sbody.x - 14, sbody.y + 82 - 6)], p.danger, sw=4,
          head=16, smooth=False)

    # identifiers from the sources only
    cves = list(brief.facts.get("cves", []))[:1]
    tag_y = 112
    for c in cves:
        pill(doc, 1540, tag_y, str(c), fg="#FFFFFF", bg=p.danger, size=17, anchor="end")
        tag_y += 48
    if attack:
        pill(doc, 1540, tag_y, "exploited in the wild", fg=p.danger, bg="#2A1416", size=15, font="ui_bold",
             anchor="end", stroke=p.danger)

    vignette(doc, 0.45)
    doc.focus = Box(160, 260, 1300, 731)
