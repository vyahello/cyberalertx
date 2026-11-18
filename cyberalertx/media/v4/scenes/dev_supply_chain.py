"""Developer-tool supply chain: a publishing key leaks from a supplier, the key
is used to push an extension update through the marketplace, and every
editor that auto-updates installs the trojanised build.

Left: the leaked access key, then the marketplace release it authorises.
Right (hero): a generic code editor that has just updated the extension, with
the file the update added open. Product names appear only as plain text and
only when the headline names them; no logos, generic editor chrome."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from .. import type as T
from ..kit import Box, Doc, arrow, background, icon, pill, vignette, window
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
        # Only what the sources state: who the key was issued to. Its scope is
        # not published.
        if holder:
            doc.text(f"issued to: {holder}", b.x + 26, b.y + 160, 18, p.muted, "mono")
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
    # masked placeholder: the key's real format is not published
    key = "••••••••" + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4))

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

    # editor area: the update itself. The sources say a malicious version was
    # published through the marketplace with the leaked key; they do not
    # describe its code or how it ran, so the contents are shown redacted.
    ed = Box(side.r, body.y, body.r - side.r, body.h)
    doc.rect(ed.x, ed.y, ed.w, 42, "#121A2A")
    doc.text(f"{ext}: extension details", ed.x + 24, ed.y + 27, 15, p.ink, "ui_bold")
    x0, y0 = ed.x + 40, ed.y + 96
    doc.rect(x0, y0, 76, 76, "#24304A", 16)
    icon(doc, "terminal", x0 + 38, y0 + 38, 40, p.ink, 2.2)
    doc.text(ext, x0 + 100, y0 + 36, 34, p.ink, "display")
    doc.text("official listing", x0 + 102, y0 + 66, 16, p.muted, "ui")
    pill(doc, ed.r - 32, y0 + 14, "new version", fg="#FFFFFF", bg=p.danger, size=14, font="ui_bold", anchor="end")
    rows2 = [("enabled by", "the stolen access key", p.danger),
             ("channel", "the official marketplace listing", p.ink),
             ("status", "malicious version" if attack else "reported", p.danger if attack else p.warn)]
    for i, (k, v, col) in enumerate(rows2):
        ry = y0 + 132 + i * 44
        doc.line((x0, ry - 28), (ed.r - 32, ry - 28), p.line, 1)
        doc.text(k, x0, ry, 16, p.muted, "mono")
        doc.text(v, x0 + 190, ry, 17, col, "mono_bold")
    # contents: redacted on purpose
    cb = Box(x0, y0 + 278, ed.r - 32 - x0, 270)
    doc.rect(cb.x, cb.y, cb.w, cb.h, "#0A0F1A", 10, stroke=p.danger, sw=1.6)
    doc.text("PACKAGE CONTENTS", cb.x + 24, cb.y + 34, 13, p.muted, "ui_bold", tracking=1.6)
    with doc.g(clip=doc.clip_rect(cb.x + 24, cb.y + 54, cb.w - 48, 136, 6)):
        doc.rect(cb.x + 24, cb.y + 54, cb.w - 48, 136, "#1A1220")
        stripes = "".join(f"M{cb.x + 24 + i * 22:.0f} {cb.y + 190:.0f}l136 -136" for i in range(-6, int(cb.w / 22) + 2))
        doc.path(stripes, stroke=p.danger, sw=7, opacity=0.22)
    for i, w in enumerate((0.62, 0.48, 0.7, 0.4)):
        doc.rect(cb.x + 48, cb.y + 76 + i * 28, (cb.w - 96) * w, 12, "#2A1B2C", 4)
    doc.text("not described in the reports", cb.x + 24, cb.y + 226, 18, p.danger, "mono_bold")
    doc.text("the sources give no code or execution details", cb.x + 24, cb.y + 252, 14, p.muted, "ui")
    # status bar
    doc.rect(ew.x + 1, ew.b - 34, ew.w - 2, 33, "#1A2540")
    doc.text(f"{ext} updated", ew.x + 20, ew.b - 12, 14, p.ink, "ui")

    # marketplace -> editor
    arrow(doc, [(mb.r + 12, mb.y + 100), (ew.x - 12, mb.y + 100)], p.danger, sw=4, head=16)
    doc.text("update", (mb.r + ew.x) / 2, mb.y + 84, 15, p.ink, "mono", anchor="middle")

    vignette(doc, 0.45)
    doc.focus = Box(40, 100, 1180, 664)
