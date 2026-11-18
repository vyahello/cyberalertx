"""IRC server command injection through delimiter handling.

What the sources state (s:03d10b5fae4006): UnrealIRCd, an open-source IRC
server, has a delimiter-handling command injection flaw (improper
neutralisation of delimiters) tracked as a CVE; CISA added it to the KEV
catalogue after reports of active exploitation. They do not say which
delimiter, what is sent or how a command runs, so the image shows none of
it: no characters, no shell, no command text, no output.

One graphic metaphor for the feed: a chat message drawn as a long bar,
broken at a marked delimiter token; the part after the break drops out of
the message line and down into the server (a rack unit). The product name
and the evidence status are the only large type. The CVE comes only from
brief.facts."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from .. import type as T
from ..kit import Box, Doc, background, f, pill, vignette
from . import scene
from ._editorial import fit_size, grid
from ._objects import server

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")


@scene("irc_injection")
def irc_injection(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.3, 0.25))
    grid(doc, 60, 0.18)
    attack = brief.status in _ATTACK
    text = brief.text or ""
    name = next((e for e in brief.entities if "irc" in e.lower()), "IRC server")
    st_col = p.danger if attack else p.warn

    # ---- the product and the status: the only large type
    size = fit_size(name, 128, 760)
    base = 96 + T.cap_height(size, "display")
    doc.text(name, 76, base, size, "#FFFFFF", "display", tracking=-size * 0.015)
    doc.text("IRC server", 80, base + 52, 30, p.muted, "ui")
    if attack:
        b = pill(doc, 80, base + 86, "EXPLOITED", fg="#0A0F1A", bg=st_col, size=50, font="ui_bold", pad=26)
        x2 = b.r + 18
        if "kev" in text or "known exploited" in text:
            pill(doc, x2, base + 86, "CISA KEV", fg="#FFFFFF", bg="#0000", size=50, font="ui_bold", pad=26,
                 stroke="#FFFFFF")
    cves = [str(c) for c in brief.facts.get("cves", [])][:1]

    # ---- the server below, right
    server(doc, 1170, 790, 600, st_col, rng)

    # ---- the message line, broken at the delimiter
    my, mh = 420, 118
    x0, cut = 70, 700
    doc.shadow(x0, my, cut - x0, mh, mh / 2, 1.0)
    doc.rect(x0, my, cut - x0, mh, "#E8EDF5", mh / 2)
    doc.rect(cut - 40, my, 40, mh, "#E8EDF5")
    nick = "<guest>"
    nx = x0 + 52
    w = doc.text(nick, nx, my + mh / 2 + 18, 50, "#2F6FDB", "mono_bold")
    # ordinary message text: shapes, not words
    bx = nx + w + 30
    for k, ww in enumerate((120, 84, 150)):
        doc.rect(bx, my + mh / 2 - 11, ww, 22, "#9AA5B4", 11)
        bx += ww + 22
    # the delimiter: a marked token, no specific character (not published)
    dw = 86
    doc.rect(cut + 6, my - 26, dw, mh + 52, st_col, 14)
    # an unspecified character: an empty dashed glyph box
    doc.rect(cut + 6 + 20, my + 14, dw - 40, mh - 28, "none", 6, stroke="#0A0F1A", sw=5,
             extra=' stroke-dasharray="10 8"')
    doc.path(f"M{f(cut + 6 + dw / 2)} {f(my + mh + 30)}V{f(my + mh + 70)}H{f(x0 + 60)}", stroke=st_col, sw=2.5)
    doc.text("delimiter not neutralised", x0 + 52, my + mh + 112, 30, st_col, "mono_bold")
    # the remainder breaks off and drops into the server
    rx = cut + dw + 34
    ang = 30
    with doc.g(transform=f"rotate({ang} {f(rx)} {f(my)})"):
        rw = 400
        doc.shadow(rx, my, rw, mh, mh / 2, 1.0)
        doc.rect(rx, my, rw, mh, "#2A1416", mh / 2, stroke=st_col, sw=4)
        with doc.g(clip=doc.clip_rect(rx, my, rw, mh, mh / 2)):
            stripes = "".join(f"M{f(rx + i * 30)} {f(my + mh)}l{f(mh)} {f(-mh)}" for i in range(-5, 16))
            doc.path(stripes, stroke=st_col, sw=10, opacity=0.3, cap="butt")
        doc.text("command", rx + 48, my + mh / 2 + 17, 50, "#FFFFFF", "mono_bold")
    if cves:
        doc.text(cves[0], 80, 860, 30, p.muted, "mono")
    vignette(doc, 0.45)
    doc.focus = Box(30, 36, 1380, 776)
