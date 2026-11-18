"""Fallback when no catalogue scene is supported strongly enough: an honest
editorial case file. A kraft folder with a typed file sheet clipped to it,
carrying only what the story itself provides — the names in the headline,
a neutral seeded file number, the category, the evidence status, any figure
from `brief.facts` and any domain the sources name. The body of the sheet is
left as blank ruled lines: the details were not published, and the image
does not pretend otherwise."""
from __future__ import annotations

import random

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene
from ._editorial import ascii_ids, fit_size, product_groups, stamp

_CATEGORY = {"breach": "Breach", "exploit": "Exploitation", "malware": "Malware", "scam": "Fraud",
             "phishing": "Phishing", "ransomware": "Ransomware", "vulnerability": "Vulnerability",
             "zero-day": "Zero-day", "other": "Report"}
_STATUS = {"confirmed": ("CONFIRMED", "danger"), "exploited": ("EXPLOITED", "danger"),
           "compromise": ("COMPROMISE", "danger"), "attacks_observed": ("ATTACKS OBSERVED", "warn"),
           "suspected": ("SUSPECTED", "warn"), "not_reported": ("", "")}


def _clip(doc: Doc, x: float, y: float, h: float = 120) -> None:
    """A steel paper clip seen from the front (two nested loops)."""
    w = 34
    d = (f"M{f(x + 8)} {f(y + h * 0.75)}V{f(y + 14)}A{f(9)} {f(9)} 0 0 1 {f(x + 26)} {f(y + 14)}"
         f"V{f(y + h - 14)}A{f(13)} {f(13)} 0 0 1 {f(x)} {f(y + h - 14)}V{f(y + 6)}"
         f"A{f(w / 2)} {f(w / 2)} 0 0 1 {f(x + w)} {f(y + 6)}V{f(y + h * 0.82)}")
    doc.path(d, stroke="#000", sw=6, opacity=0.25, extra=f' transform="translate(3 5)" filter="{doc.blur(2)}"')
    doc.path(d, stroke="#8E96A3", sw=5)
    doc.path(d, stroke="#E6EAF0", sw=2, opacity=0.8)


@scene("dossier")
def dossier(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.45, 0.2))
    names = product_groups(brief)
    category = _CATEGORY.get(brief.category, "Report")
    st_label, st_key = _STATUS.get(brief.status, ("", ""))
    st_col = getattr(p, st_key) if st_key else p.muted
    ids = ascii_ids(brief.text, 2)
    # A neutral file number (seeded, not our internal story key).
    file_no = f"{rng.randrange(100, 999)}-{rng.randrange(1000, 9999)}"

    flip = rng.random() < 0.5
    ang = rng.uniform(-2.6, -1.0) if not flip else rng.uniform(0.8, 2.2)
    # ---- the folder: back cover with tab, kraft board, opening to the right
    fx, fy, fw, fh = (360, 96, 1180, 900) if not flip else (60, 96, 1180, 900)
    with doc.g(transform=f"rotate({ang * 0.5:.2f} 800 520)"):
        tab_x = fx + fw - 380
        doc.shadow(fx, fy, fw, fh, 10, 1.3)
        kraft = doc.lin([(0, "#BFA77A", 1), (1, "#9C8660", 1)], 0, 0, 0.4, 1)
        doc.path(f"M{f(fx)} {f(fy + 10)}Q{f(fx)} {f(fy)} {f(fx + 10)} {f(fy)}H{f(tab_x)}L{f(tab_x + 24)} {f(fy - 56)}"
                 f"H{f(tab_x + 296)}L{f(tab_x + 320)} {f(fy)}H{f(fx + fw - 10)}Q{f(fx + fw)} {f(fy)} {f(fx + fw)} "
                 f"{f(fy + 10)}V{f(fy + fh)}H{f(fx)}Z", fill=kraft)
        doc.text(category.upper(), tab_x + 160, fy - 18, 24, "#33291A", "ui_bold", anchor="middle", tracking=3)
        doc.line((fx, fy + 3), (fx + fw, fy + 3), "#FFFFFF", 1.5, 0.25)
    # a second sheet underneath, slightly fanned
    sx, sy, sw, sh = (200, 150, 980, 820) if not flip else (420, 150, 980, 820)
    paper, ink, muted, rule = "#F6F3EC", "#15171C", "#77736A", "#DAD4C8"
    with doc.g(transform=f"rotate({ang * 1.9:.2f} {sx + sw / 2} {sy + 360})"):
        doc.shadow(sx, sy, sw, sh, 3, 0.6)
        doc.rect(sx, sy, sw, sh, "#E7E2D7", 3)
    # ---- the file sheet
    with doc.g(transform=f"rotate({ang:.2f} {sx + sw / 2} {sy + 360})"):
        doc.shadow(sx, sy, sw, sh, 3, 0.9)
        doc.rect(sx, sy, sw, sh, paper, 3)
        doc.rect(sx, sy, sw, sh, doc.rad([(0, "#FFFFFF", 0.5), (1, "#FFFFFF", 0)], 0.3, 0.2, 0.7), 3)
        doc.text("FILE", sx + 72, sy + 84, 20, muted, "ui_bold", tracking=4)
        doc.text(file_no, sx + 146, sy + 84, 24, ink, "mono")
        doc.line((sx + 72, sy + 110), (sx + sw - 72, sy + 110), ink, 3)
        # subject
        y: float = sy + 146
        subject = names[:3] if names else []
        lead = subject[0] if subject else category
        size = fit_size(lead, 124, sw - 150)
        y += T.cap_height(size, "display")
        doc.text(lead, sx + 66, y, size, ink, "display")
        if len(subject) > 1:
            y += 58
            doc.text(T.fit(" / ".join(subject[1:]), 34, sw - 150, "ui"), sx + 72, y, 34, muted, "ui")
        y += 48
        doc.line((sx + 72, y), (sx + sw - 72, y), rule, 1.5)
        # typed fields: only what the story provides
        fields: list[tuple[str, str, str]] = [("CATEGORY", brief.category or "other", ink)]
        fields.append(("STATUS", st_label.lower(), st_col) if st_label else ("STATUS", "not established", muted))
        if brief.facts.get("money"):
            fields.append(("AMOUNT", str(brief.facts["money"]), ink))
        for d in ids:
            fields.append(("DOMAIN", d, ink))
        fields.append(("DETAIL", "not published", muted))
        y += 62
        for lab, val, col in fields[:5]:
            doc.text(lab, sx + 72, y, 18, muted, "ui_bold", tracking=2.5)
            doc.text(val, sx + 290, y, 28, col, "mono_bold" if col != muted else "mono")
            y += 54
        # blank ruled body: the part of the story no source describes
        y += 6
        while y < sy + sh - 40:
            doc.line((sx + 72, y), (sx + sw - 72, y), rule, 1.2)
            y += 44
        doc.rect(sx, sy, 7, sh, st_col if st_label else rule)
        _clip(doc, sx + sw - 130, sy - 44)
        if st_label:
            stamp(doc, sx + sw - 250, sy + sh - 190, st_label, st_col, size=30 if len(st_label) > 11 else 38,
                  angle=-8)
    doc.focus = Box(sx - 20, 80, 1040, 585)
    vignette(doc, 0.5)
