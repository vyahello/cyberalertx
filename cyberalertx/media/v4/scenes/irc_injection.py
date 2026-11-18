"""IRC server command injection: a chat message carrying shell delimiters is
handed on by the IRC daemon without being neutralised, and the part after the
delimiter runs as a command on the server.

Left (hero): a terminal IRC client in a channel, with one crafted line. Right:
the server's shell, where the same text shows up as a command run by the
daemon's account. The payload is a harmless placeholder (`id`), not the real
exploit; the CVE identifier is drawn only from brief.facts."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from .. import type as T
from ..kit import Box, Doc, arrow, background, pill, vignette, window
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
    cx += doc.text("ping lag", cx, cy, 20, txt, "mono")
    d_x = cx
    cx += doc.text(";", cx, cy, 26, "#FFFFFF", "mono_bold") + 4
    cmd_x = cx
    doc.text("id", cx, cy, 20, "#FFB4AD", "mono_bold")
    # mark the delimiter
    doc.rect(d_x - 5, cy - 26, T.measure(";", 26, "mono_bold") + 10, 34, "none", 5, stroke=p.danger, sw=2)
    doc.path(f"M{d_x + 6:.1f} {cy + 10:.1f}V{cy + 40:.1f}H{d_x - 30:.1f}", stroke=p.danger, sw=1.5)
    doc.text("shell delimiter", d_x - 40, cy + 46, 16, p.danger, "mono", anchor="end")

    # input line + status bar, as in a terminal client
    sb = Box(body.x, body.b - 78, body.w, 36)
    doc.rect(sb.x, sb.y, sb.w, sb.h, "#1E3A66")
    doc.text("[14:04] [me(+i)] [2:net/#lobby(+nt)] [Act: 3]", sb.x + 20, sb.y + 24, 16, "#DCE7F7", "mono")
    doc.text("[#lobby]", body.x + 20, body.b - 14, 17, txt, "mono")
    doc.rect(body.x + 112, body.b - 30, 10, 20, txt, opacity=0.8)

    # ---- the server's shell
    sw = Box(980, 420, 580, 330)
    sbody = window(doc, sw, title="chat-server  shell", surface="#120B0C", chrome="#21171A", depth=1.2)
    doc.rect(sw.x, sw.y, sw.w, sw.h, "none", 14, stroke=p.danger if attack else p.line, sw=2)
    lines = [("ircd  1187  unrealircd -F", sys_c, "mono")]
    if attack:
        lines += [("ircd  2291   \\_ sh -c \"... lag;id\"", "#FFB4AD", "mono_bold"),
                  ("ircd  2292       \\_ id", "#FFB4AD", "mono_bold"),
                  ("", txt, "mono"),
                  ("uid=1001(ircd) gid=1001(ircd)", "#FFFFFF", "mono_bold")]
    else:
        lines += [("delimiters in messages: not neutralised", "#F3D58A", "mono")]
    for i, (s, col, font) in enumerate(lines):
        doc.text(s, sbody.x + 24, sbody.y + 44 + i * 38, 18, col, font)

    # message -> shell
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
