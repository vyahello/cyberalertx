"""Generic vulnerability / patch story: a security advisory for the affected
product, built from the story's own identifiers — the product named in the
headline, its CVE IDs, the flaw count the sources state, the severity word the
sources use, and the status the evidence supports (exploited / patch
available / disclosed) — next to a drawing of the kind of product affected
(rack server, gateway appliance, CPU package, phone, browser, database,
laptop, repository, 3D printer).

Three treatments, chosen by seed, so thirty advisories in a row do not look
alike: a printed bulletin sheet, a Swiss-style type poster and a spotlight
(status panel + the product lit on a stage, built to read at feed size). CISA
catalogue additions get a catalogue ledger instead.
Nothing here invents a number."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, Palette, background, pill, vignette, window
from . import scene
from ._editorial import fit_size, grid, primary_product, stamp
from ._objects import ASPECT, DRAW, SCALE, handset

_EXPLOITED = {"exploited", "confirmed", "attacks_observed", "compromise"}


@dataclass
class _Adv:
    name: str
    others: list[str]
    cves: list[str]
    flaws: str
    flaws_approx: bool
    exploited: bool
    patched: bool
    proof: bool
    sev: str
    kind: str
    kev: bool
    wallet: bool = False
    extra: dict[str, str] = field(default_factory=dict)


def _facts(brief: EditorialBrief) -> _Adv:
    t = brief.text
    in_wild = bool(
        re.search(r"(actively|known) exploited|exploited (in|bug|zero|outlook|flaw)|zero-day exploited|"
                  r"in the wild|under (active )?attack|експлуатують|активно використов", t))
    # A researcher's claim or proof of concept is not exploitation: unless the
    # sources report use in the wild, it is drawn as a proof of concept.
    research = bool(re.search(r"researchers? (claim|demonstrat|show|found|develop|publish)|proof[- ]of[- ]concept|"
                              r"\bPoC\b|дослідник\w* (показал|продемонстр|заявля)", t, re.I))
    proof = research and not in_wild
    exploited = not proof and (brief.status in _EXPLOITED or in_wild)
    patched = bool(re.search(r"\bpatch|\bfix|hotfix|security update|cumulative update|виправ|оновлен", t))
    sev = ""
    if re.search(r"maximum[- ]severity|cvss 10|critical|критичн", t):
        sev = "CRITICAL"
    elif re.search(r"high[- ]severity|високого рівня", t):
        sev = "HIGH"
    name, others = primary_product(brief)
    kev = bool(re.search(r"\bkev\b|known exploited vulnerabilities", t)) and (not name or name.startswith("CISA")
                                                                             or "Adds" in brief.entities)
    if not name:
        name = "Advisory"
    if kev:
        name = "CISA KEV"
        others = []
    others = [o for o in others if not o.startswith("CISA")]
    flaws = str(brief.facts.get("flaws", ""))
    return _Adv(name=name, others=others[:3], cves=[str(c) for c in brief.facts.get("cves", [])][:4],
                flaws=flaws, flaws_approx=bool(brief.facts.get("flaws_approx")), exploited=exploited,
                patched=patched, proof=proof, sev=sev, kind=_kind(t, name), kev=kev,
                wallet=bool(re.search(r"wallet|crypto|seed phrase|гаманц", t)))


_KINDS: tuple[tuple[str, str], ...] = (
    ("printer", r"3d[- ]print|prusa|принтер"),
    ("browser", r"chrome|firefox|safari|browser|браузер"),
    ("cpu", r"\bcpu|processor|turin|epyc|процесор"),
    ("phone", r"\bios\b|iphone|android|imessage|telegram|smartphone|смартфон|wallet"),
    ("database", r"postgres|mysql|mongodb|database|бази даних"),
    ("code", r"\bgit\b|repositor"),
    ("appliance", r"\besg\b|email (security )?gateway|broadworks|freeswitch|openwave|voip|appliance|firewall|"
                  r"router|gateway"),
    ("os", r"windows|clfs|kb\d{6}|macos|zoom workplace|laptop|microsoft|patch tuesday|outlook"),
    ("server", r"server|apache|http|openssh|nginx|backup|ahsay|orchestra|\bsap\b|windchill|quay|registry|ssh"),
)


def _kind(text: str, name: str) -> str:
    for src in (name.lower(), text[:500]):
        for kind, pat in _KINDS:
            if re.search(pat, src):
                return kind
    return "server"


def _status(a: _Adv, p: Palette) -> tuple[str, str]:
    if a.exploited:
        return "EXPLOITED", p.danger
    if a.proof:
        return "PROOF OF CONCEPT", p.warn
    if a.patched:
        return "PATCH AVAILABLE", p.safe
    return "DISCLOSED", p.warn


def _hex(rng: random.Random, n: int = 6) -> str:
    return "".join(rng.choice("0123456789ABCDEF") for _ in range(n))


def _product(doc: Doc, a: _Adv, slot: Box, rng: random.Random, col: str) -> tuple[float, float]:
    """The product drawing centred in `slot`; returns its marked point."""
    w = min(slot.w * SCALE[a.kind], slot.h * 0.92 / ASPECT[a.kind])
    if a.kind == "phone" and a.wallet:
        return handset(doc, slot.cx, slot.cy, w, col, rng, mode="wallet")
    return DRAW[a.kind](doc, slot.cx, slot.cy, w, col, rng)


def _tag(doc: Doc, anchor: tuple[float, float], slot: Box, label: str, sub: str, col: str) -> None:
    """A label hung off the marked part of the product by a leader line: above
    the product when the mark is near its top, beside and below otherwise, so
    the leader never cuts across the drawing."""
    p = doc.pal
    ax, ay = anchor
    w = max(T.measure(label, 22, "mono_bold"), T.measure(sub, 16, "ui_bold", 1.5)) + 40
    if ay < slot.y + slot.h * 0.45:
        ty = max(40, slot.y - 130)
        bx = min(ax + 40, 1500 - w)
        path = f"M{ax:.1f} {ay:.1f}V{ty + 34:.1f}H{bx:.1f}"
    else:
        ty = slot.b + 20
        bx = min(slot.r - w, 1480 - w)
        ex = slot.r + 10
        path = f"M{ax:.1f} {ay:.1f}H{ex:.1f}V{ty + 34:.1f}H{bx + w:.1f}"
    doc.path(path, stroke=col, sw=2)
    doc.circle(ax, ay, 6, col)
    doc.circle(ax, ay, 13, "none", col, 2, 0.5)
    doc.rect(bx, ty, w, 68, "#0B111C" if p.dark else "#FFFFFF", 8, stroke=col, sw=2)
    doc.text(sub, bx + 20, ty + 26, 16, col, "ui_bold", tracking=1.5)
    doc.text(label, bx + 20, ty + 53, 22, p.ink if p.dark else p.on_surface, "mono_bold")


# ---------------------------------------------------------------- A: printed bulletin sheet

def _sheet(doc: Doc, a: _Adv, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.3, 0.2))
    paper, ink, muted, rule = "#F4F1EA", "#14161B", "#6E6A62", "#D6D0C4"
    sx, sy, sw, sh = 96, 70, 780, 900
    ang = rng.choice((-1.4, -0.9, 0.8))
    st_label, st_col = _status(a, p)
    with doc.g(transform=f"rotate({ang} {sx + sw / 2} {sy + 400})"):
        doc.shadow(sx, sy, sw, sh, 4, 1.2)
        doc.rect(sx, sy, sw, sh, paper, 4)
        doc.rect(sx, sy, sw, 12, st_col)
        doc.text("SECURITY ADVISORY", sx + 60, sy + 78, 19, ink, "ui_bold", tracking=4)
        doc.text("ADV-" + _hex(rng), sx + sw - 60, sy + 78, 19, muted, "mono", anchor="end")
        doc.line((sx + 60, sy + 100), (sx + sw - 60, sy + 100), ink, 3)
        size = fit_size(a.name, 112, sw - 120)
        cap = T.cap_height(size, "display")
        doc.text(a.name, sx + 56, sy + 130 + cap, size, ink, "display")
        y = sy + 130 + cap
        if a.others:
            doc.text(" / ".join(a.others), sx + 60, y + 50, 26, muted, "ui")
            y += 44
        y += 40
        doc.line((sx + 60, y), (sx + sw - 60, y), rule, 1.5)
        y += 52
        rows: list[tuple[str, str]] = []
        if a.sev:
            rows.append(("Severity", a.sev))
        rows.append(("Status", st_label))
        if a.flaws:
            rows.append(("Fixes", ("~" if a.flaws_approx else "") + a.flaws + " flaws"))
        for lab, val in rows:
            doc.text(lab.upper(), sx + 60, y, 16, muted, "ui_bold", tracking=2.5)
            if lab == "Severity":
                n = 4 if val == "CRITICAL" else 3
                for i in range(4):
                    doc.rect(sx + 250 + i * 32, y - 18, 26, 20, (p.danger if n == 4 else ink) if i < n else rule, 3)
                doc.text(val, sx + 390, y, 23, p.danger if n == 4 else ink, "mono_bold")
            else:
                doc.text(val, sx + 250, y, 23, st_col if lab == "Status" else ink, "mono_bold")
            y += 48
        doc.line((sx + 60, y - 16), (sx + sw - 60, y - 16), rule, 1.5)
        y += 36
        doc.text("IDENTIFIERS", sx + 60, y, 16, muted, "ui_bold", tracking=2.5)
        if a.cves:
            for i, c in enumerate(a.cves):
                cy = y + 56 + i * 54
                doc.rect(sx + 60, cy - 32, 10, 42, st_col if i == 0 else rule, 2)
                doc.text(c, sx + 88, cy, 34, ink, "mono_bold" if i == 0 else "mono")
        else:
            doc.text("no CVE in the report", sx + 88, y + 54, 26, muted, "mono")
    slot = Box(930, 210, 600, 480)
    anchor = _product(doc, a, slot, rng, st_col)
    _tag(doc, anchor, slot, a.cves[0] if a.cves else T.fit(a.name, 22, 300, "mono_bold"), st_label, st_col)
    doc.focus = Box(70, 40, 1380, 776)            # include the sheet's left edge (name)
    vignette(doc, 0.4)


# ---------------------------------------------------------------- B: Swiss type poster

def _poster(doc: Doc, a: _Adv, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.8, 0.15))
    grid(doc, 80, 0.22)
    st_label, st_col = _status(a, p)
    b = pill(doc, 80, 80, st_label, fg="#0A0F1A", bg=st_col, size=24, font="ui_bold", pad=18)
    if a.sev:
        pill(doc, b.r + 14, 80, a.sev, fg=p.ink, bg="#0000", size=24, font="ui_bold", pad=18, stroke=p.ink)
    size = fit_size(a.name, 190, 1440)
    base = 210 + T.cap_height(size, "display")
    doc.text(a.name, 72, base, size, p.ink, "display", tracking=-size * 0.015)
    y = base + 60
    doc.rect(80, y, 760, 4, st_col)
    y += 70
    if a.others:
        doc.text(" + ".join(a.others), 80, y, 32, p.muted, "ui")
        y += 66
    if a.cves:
        for i, c in enumerate(a.cves):
            doc.text(c, 80, y + 20 + i * 62, 40, p.ink if i == 0 else p.muted, "mono_bold" if i == 0 else "mono")
    elif a.flaws:
        n = ("~" if a.flaws_approx else "") + a.flaws
        w = doc.text(n, 76, y + 120, 140, st_col, "display")
        doc.text("flaws", 76 + w + 24, y + 120, 48, p.ink, "ui")
    else:
        doc.text("ADV-" + _hex(rng), 80, y + 30, 36, p.muted, "mono")
    slot = Box(860, 400, 640, 420) if (a.cves or a.flaws) else Box(560, 330, 900, 500)
    anchor = _product(doc, a, slot, rng, st_col)
    doc.circle(anchor[0], anchor[1], 7, st_col)
    doc.circle(anchor[0], anchor[1], 16, "none", st_col, 2, 0.6)
    doc.focus = Box(60, 60, 1440, 810)
    vignette(doc, 0.45)


# ---------------------------------------------------------------- C: spotlight

_DARKEN = {"EXPLOITED": "#5A1410", "PROOF OF CONCEPT": "#4A3410", "PATCH AVAILABLE": "#0F3A24",
           "DISCLOSED": "#3E3010"}


def _spotlight(doc: Doc, a: _Adv, rng: random.Random) -> None:
    """Built for the feed thumbnail: a solid status panel carrying the product
    name and the evidence status, and the product itself lit on a stage."""
    p = doc.pal
    background(doc, light=(0.78, 0.35))
    st_label, st_col = _status(a, p)
    # ---- the stage (right): light cone, floor, the product
    doc.add(f'<ellipse cx="1110" cy="430" rx="560" ry="420" fill="{doc.rad([(0, st_col, 0.20), (1, st_col, 0)])}"/>')
    doc.rect(700, 700, 900, 200, doc.lin([(0, "#000", 0.0), (1, "#000", 0.45)]))
    doc.add(f'<ellipse cx="1110" cy="742" rx="380" ry="34" fill="#000" opacity="0.55" '
            f'filter="{doc.blur(14)}"/>')
    # The product fills the stage (by height for tall objects like a phone).
    slot = Box(790, 130, 640, 610)
    w = min(slot.w * 0.9, slot.h * 0.95 / ASPECT[a.kind])
    if a.kind == "phone" and a.wallet:
        anchor = handset(doc, slot.cx, slot.cy, w, st_col, rng, mode="wallet")
    else:
        anchor = DRAW[a.kind](doc, slot.cx, slot.cy, w, st_col, rng)
    doc.circle(anchor[0], anchor[1], 9, st_col)
    doc.circle(anchor[0], anchor[1], 22, "none", st_col, 3, 0.7)
    doc.circle(anchor[0], anchor[1], 40, "none", st_col, 2, 0.3)
    # ---- the status panel (left), full height
    pw = 660
    doc.rect(0, 0, pw, 900, doc.lin([(0, _DARKEN.get(st_label, "#2A2F3A"), 1), (1, "#0B0F18", 1)], 0, 0, 0.3, 1))
    doc.rect(pw - 6, 0, 6, 900, st_col)
    doc.text("SECURITY ADVISORY", 72, 112, 20, "#FFFFFF", "ui_bold", tracking=4, opacity=0.75)
    name = a.name
    size = fit_size(name, 120, pw - 130)
    base = 160 + T.cap_height(size, "display")
    doc.text(name, 68, base, size, "#FFFFFF", "display", tracking=-size * 0.015)
    y = base + 40
    if a.others:
        doc.text(T.fit("+ " + ", ".join(a.others), 26, pw - 140, "ui"), 72, y + 10, 26, "#FFFFFF", "ui",
                 opacity=0.75)
        y += 50
    # status band: the one thing that must read at 176 px
    band_y = max(y + 30, 430)
    doc.rect(0, band_y, pw - 6, 118, st_col)
    st_size = fit_size(st_label, 58, pw - 140)
    doc.text(st_label, 72, band_y + 59 + T.cap_height(st_size, "display") / 2, st_size, "#0A0F1A", "display")
    y = band_y + 190
    if a.cves:
        for i, c in enumerate(a.cves[:2]):
            doc.text(c, 72, y + i * 52, 34 if i == 0 else 26, "#FFFFFF", "mono_bold" if i == 0 else "mono",
                     opacity=1 if i == 0 else 0.7)
    elif a.flaws:
        n = ("~" if a.flaws_approx else "") + a.flaws
        w = doc.text(n, 72, y + 20, 72, "#FFFFFF", "display")
        doc.text("flaws", 72 + w + 18, y + 20, 32, "#FFFFFF", "ui", opacity=0.8)
    else:
        doc.text("no CVE in the report", 72, y, 26, "#FFFFFF", "mono", opacity=0.65)
    if a.sev:
        pill(doc, 72, 800, a.sev, fg="#FFFFFF", bg="#0000", size=20, font="ui_bold", pad=16, stroke="#FFFFFF")
    doc.focus = Box(0, 60, 1300, 731)
    vignette(doc, 0.35)


def _catalogue(doc: Doc, a: _Adv, rng: random.Random) -> None:
    """KEV additions: a catalogue ledger whose newest rows are the story's CVEs."""
    p = doc.pal
    background(doc, light=(0.5, 0.15))
    win = Box(150, 90, 1300, 740)
    body = window(doc, win, title="known exploited vulnerabilities catalog", surface="#0D1320", chrome="#172033")
    x0 = body.x + 50
    doc.text("CISA KEV", x0, body.y + 92, 64, p.ink, "display")
    pill(doc, body.r - 50, body.y + 50, "ACTIVELY EXPLOITED", fg="#0A0F1A", bg=p.danger, size=20, font="ui_bold",
         anchor="end", pad=16)
    cols = (x0, x0 + 470, x0 + 820)
    hy = body.y + 150
    for cx, lab in zip(cols, ("CVE ID", "VENDOR / PRODUCT", "ADDED")):
        doc.text(lab, cx, hy, 16, p.muted, "ui_bold", tracking=2)
    doc.line((x0, hy + 16), (body.r - 50, hy + 16), p.line, 1.5)
    new = a.cves or ["CVE-" + "-" * 9]
    n_rows = 9
    rh = (body.b - hy - 50) / n_rows
    for i in range(n_rows):
        y = hy + 16 + i * rh
        is_new = i < len(new)
        if is_new:
            doc.rect(x0 - 20, y + 4, body.w - 60, rh - 8, p.danger, 6, opacity=0.13)
            doc.rect(x0 - 20, y + 4, 5, rh - 8, p.danger)
            doc.text(new[i], cols[0], y + rh / 2 + 10, 28, p.ink, "mono_bold")
            doc.rect(cols[1], y + rh / 2 - 6, 160 + rng.randrange(120), 12, p.ink, 6, opacity=0.5)
            pill(doc, cols[2], y + rh / 2 - 15, "new", fg="#0A0F1A", bg=p.danger, size=16, font="ui_bold")
        else:
            doc.rect(cols[0], y + rh / 2 - 6, 300, 12, p.line, 6)
            doc.rect(cols[1], y + rh / 2 - 6, 140 + rng.randrange(160), 12, p.line, 6)
            doc.rect(cols[2], y + rh / 2 - 6, 110, 12, p.line, 6)
        doc.line((x0, y + rh), (body.r - 50, y + rh), p.line, 1, 0.6)
    doc.focus = Box(140, 80, 1320, 742)
    vignette(doc, 0.45)


@scene("vuln_advisory")
def vuln_advisory(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    a = _facts(brief)
    if a.kev and a.cves:
        _catalogue(doc, a, rng)
        return
    rng.choice((_sheet, _poster, _spotlight))(doc, a, rng)
