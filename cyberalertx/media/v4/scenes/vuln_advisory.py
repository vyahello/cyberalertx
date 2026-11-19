"""Generic vulnerability / patch story: a security advisory for the affected
product, built from the story's own identifiers — the product named in the
headline, its CVE IDs, the flaw count the sources state, the severity word the
sources use, and the status the evidence supports (exploited / patch
available / disclosed) — next to a drawing of the kind of product affected
(rack server, gateway appliance, CPU package, phone, browser, database,
laptop, repository, 3D printer).

Built for the 176 px feed first: one large product drawing, the product name
as the biggest type, and the advisory status told by form as well as colour,
both in a badge and as a mark on the product itself:

* exploited          - solid square-cornered red badge; a red impact burst
                       with cracks on the product
* proof of concept   - dashed amber outline badge; a targeting reticle
* patch available    - rounded green pill with a tick; an adhesive patch
                       stuck over the marked part
* disclosed          - outlined blue pill; a magnifying lens over the part

Two treatments, chosen by seed, so thirty advisories in a row do not look
alike: a dark stage (the product lit, the name above it) and a light printed
bulletin with the product drawn as its figure. CISA catalogue additions get
a catalogue ledger instead.

Status comes only from the evidence and the source wording (`_facts`), the
severity only from the source's own words, figures only from brief.facts."""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, Palette, background, f, icon, pill, vignette
from . import scene
from ._editorial import fit_size, grid, primary_product
from ._objects import ASPECT, DRAW, handset, server

Pt = tuple[float, float]
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
    #: KEV additions the headline counts ("Adds Six ..."); 0 when it gives none.
    kev_total: int = 0
    #: Patching is urged, but no source states that a fix is available.
    urged: bool = False


def _facts(brief: EditorialBrief) -> _Adv:
    t = brief.text
    in_wild = bool(
        re.search(r"(actively|known) exploited|exploited (in|bug|zero|outlook|flaw)|zero-day exploited|"
                  r"in the wild|under (active )?attack|експлуатують|активно використов", t))
    # A researcher's claim or proof of concept is not exploitation: unless the
    # sources report use in the wild, it is drawn as a proof of concept.
    research = bool(re.search(r"researchers? (claim|demonstrat|show|found|develop|publish)|proof[- ]of[- ]concept|"
                              r"\bPoC\b|дослідник\w* (показал|продемонстр|заявля)", t, re.I))
    in_wild = in_wild or bool(re.search(
        r"(hackers|attackers|threat actors|cybercriminals|criminals|gangs?) (now )?(target|exploit|abuse|hijack|breach)",
        t))
    proof = research and not in_wild
    exploited = not proof and (brief.status in _EXPLOITED or in_wild)
    # A fix counts only when the sources say it exists ("patches", "fixed in",
    # "updates released"); "fixes coming", "no patch yet" and "unpatched" do not.
    pending = bool(re.search(
        r"fix(?:es)? (?:are |is )?(?:coming|expected|planned|scheduled|due)|patch(?:es)? (?:are |is )?(?:coming|"
        r"expected|planned|scheduled|due|not yet)|no (?:patch|fix)|not yet (?:patched|fixed)|unpatched|"
        r"yet to (?:be )?(?:patch|fix)|will (?:be )?(?:patch|fix|releas)|виправлення (?:вийде|очікує)|"
        r"без (?:патча|виправлення)|не виправлен", t))
    urged = bool(re.search(r"urg\w* (?:\w+ ){0,4}(?:to )?(?:immediate(?:ly)? )?patch|immediate(?:ly)? patch|"
                           r"patch(?:ing)? (?:now|immediately)", t))
    patched = not pending and bool(re.search(
        r"\bpatch(?:es|ed)\b|\bfix(?:es|ed)\b|fixed in|fixed versions?|hotfix|security updates?|cumulative update|"
        r"(?:update|upgrade) to (?:version )?\d|apply (?:the )?(?:patch|update|fix)|"
        r"updates? (?:released|available|issued|out)|released (?:a |an )?(?:patch|fix|update)|patch(?:es)? "
        r"(?:is |are )?(?:now )?(?:available|released|out)|виправ|оновлен", t))
    sev = ""
    if re.search(r"maximum[- ]severity|cvss 10|critical|критичн", t):
        sev = "CRITICAL"
    elif re.search(r"high[- ]severity|високого рівня", t):
        sev = "HIGH"
    name, others = primary_product(brief)
    head = (brief.headline or "").lower()
    # A third party that warns OF someone else's flaw is not the product
    # ("Binance warns of iOS flaw"); a vendor warning about its own product
    # names that product next ("F5 Warns 6 Critical BIG-IP Flaws") and stays.
    warner = re.match(r"([\w.-]+(?: [\w.-]+)?) (?:warns|alerts) (?:\w+ )?(?:of|about) (\S+(?: \S+)?)",
                      brief.headline or "", re.I)
    if warner and name and name.lower() == warner.group(1).lower() and not others and _names_product(warner.group(2)):
        name = ""
    kev_text = bool(re.search(r"\bkev\b|known exploited vulnerabilities", t))
    # A KEV addition that lists several vendors is drawn as the catalogue: no
    # single vendor may carry CVEs that belong to others.
    kev = kev_text and (not name or name.startswith("CISA") or "Adds" in brief.entities or bool(others)
                        or bool(re.search(r"\badds?\b.*known exploited|to (?:its )?(?:kev|known exploited "
                                          r"vulnerabilities) catalog", head)))
    if not name:
        name = "Advisory"
    if kev:
        name = "CISA KEV"
        others = []
    others = [o for o in others if not o.startswith("CISA")]
    # Secondary products only when the source headline names them: a product named
    # only in our summary may belong to another subject (Oracle's separate patch set).
    others = [o for o in others if not brief.headline or o.split()[0].lower() in brief.headline.lower()]
    flaws = str(brief.facts.get("flaws", ""))
    if flaws and not _flaws_stated(t, flaws):
        flaws = ""                       # e.g. "CVSS 10.0" read as a count: never draw it
    cves = [str(c) for c in brief.facts.get("cves", [])][:4]
    if cves and others and not kev and not _cve_near(t, cves[0], name):
        cves = []                        # several products, CVE not tied to the named one: never attribute it
    words = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    tm = re.search(r"\badds? (\w+) (?:new )?(?:known exploited|vulnerabilit|flaws)", head)
    kev_total = (int(tm.group(1)) if tm.group(1).isdigit() else words.get(tm.group(1), 0)) if tm else 0
    return _Adv(name=name, others=others[:3], cves=cves, kev_total=kev_total if kev else 0, urged=urged,
                flaws=flaws, flaws_approx=bool(brief.facts.get("flaws_approx")), exploited=exploited,
                patched=patched, proof=proof, sev=sev, kind=_kind(t, name), kev=kev,
                wallet=bool(re.search(r"wallet|crypto|seed phrase|гаманц", t)))


#: Words after "warns of" that describe the flaw, not another product.
_FLAW_WORDS = {"critical", "security", "severe", "serious", "new", "multiple", "high", "zero-day", "zero-days",
               "flaw", "flaws", "bug", "bugs", "vulnerability", "vulnerabilities", "two", "three", "four", "five",
               "six", "seven", "eight", "nine", "ten", "a", "an", "the", "actively", "exploited", "unpatched", "rce"}


def _names_product(words: str) -> bool:
    """`words` (just after "warns of") name a product of their own: "iOS flaw",
    not "Critical Security Flaws" or "zero-day flaw"."""
    return any(w.lower().strip(",.:") not in _FLAW_WORDS and re.search(r"[A-Z]", w) for w in words.split())


def _cve_near(text: str, cve: str, name: str) -> bool:
    """The sources tie `cve` to `name`: both within one short span."""
    t, c, n = text.lower(), cve.lower(), name.lower()
    return any(abs(i.start() - j.start()) < 90 for i in re.finditer(re.escape(c), t)
               for j in re.finditer(re.escape(n), t)) if n else False


def _flaws_stated(text: str, n: str) -> bool:
    """The count is drawn only where the text uses it as a count of flaws
    ("35 vulnerabilities", "1,235 flaws", "23 вразливості"), not as a score."""
    num = re.escape(n) + "|" + re.escape(n.replace(",", ""))
    if not re.search(rf"(?<![\d.,])(?:{num})(?![\d.,]\d)\s+(?:[\w-]+\s+){{0,2}}"
                     r"(flaws?|vulnerabilit|bugs?|security (flaws|bugs|vulnerab|fixes)|cves|вразлив|дефект)", text):
        return False
    return not re.search(rf"cvss(?: score)?:?\s*(?:{num})\b", text) or bool(
        re.search(rf"(?:{num})\s+(flaws|vulnerabilities|вразлив)", text))


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




# ---------------------------------------------------------------- status: colour and form

_DISCLOSED_DARK, _DISCLOSED_LIGHT = "#7FB4FF", "#1E4FD8"
# Darker inks of the four status colours for the light (paper) treatment.
_ON_PAPER = {"EXPLOITED": "#D7372B", "PROOF OF CONCEPT": "#B86E00", "PATCH AVAILABLE": "#1F8A4C",
             "PATCHING URGED": "#B86E00", "DISCLOSED": _DISCLOSED_LIGHT}


def _status(a: _Adv, p: Palette) -> tuple[str, str]:
    if a.exploited:
        return "EXPLOITED", p.danger
    if a.proof:
        return "PROOF OF CONCEPT", p.warn
    if a.patched:
        return "PATCH AVAILABLE", p.safe
    if a.urged:
        return "PATCHING URGED", p.warn
    return "DISCLOSED", _DISCLOSED_DARK if p.dark else _DISCLOSED_LIGHT


def _burst(r: float, cx: float, cy: float, rng: random.Random, n: int = 9, inner: float = 0.5) -> list[Pt]:
    pts: list[Pt] = []
    for i in range(n * 2):
        a = -math.pi / 2 + i * math.pi / n
        rr = r * (1.0 if i % 2 == 0 else inner) * (1 + rng.uniform(-0.12, 0.12))
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def _mark(doc: Doc, label: str, x: float, y: float, r: float, col: str, rng: random.Random) -> None:
    """The status as a mark on the product's affected part (form, not only colour)."""
    if label == "EXPLOITED":
        # impact: cracks running out of a burst
        for k in range(5):
            a = rng.uniform(0, 2 * math.pi)
            px, py = x, y
            d = f"M{f(px)} {f(py)}"
            for seg in range(3):
                a += rng.uniform(-0.5, 0.5)
                ln = r * rng.uniform(0.6, 0.9)
                px, py = px + ln * math.cos(a), py + ln * math.sin(a)
                d += f"L{f(px)} {f(py)}"
            doc.path(d, stroke=col, sw=4.5)
        doc.glow(x, y, r * 1.6, r * 1.6, col, 0.45)
        doc.poly(_burst(r, x, y, rng), col, stroke="#FFFFFF", sw=3)
        doc.rect(x - r * 0.07, y - r * 0.36, r * 0.14, r * 0.42, "#FFFFFF", r * 0.05)
        doc.circle(x, y + r * 0.25, r * 0.08, "#FFFFFF")
    elif label == "PROOF OF CONCEPT":
        doc.circle(x, y, r * 1.3, col, opacity=0.12)
        doc.circle(x, y, r, "none", col, 6)
        doc.circle(x, y, r * 0.38, "none", col, 4)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            doc.line((x + dx * r * 0.55, y + dy * r * 0.55), (x + dx * r * 1.55, y + dy * r * 1.55), col, 6)
        doc.circle(x, y, 6, col)
    elif label == "PATCH AVAILABLE":
        ang = rng.choice((-24, -16, 18))
        with doc.g(transform=f"rotate({ang} {f(x)} {f(y)})"):
            doc.rect(x - r * 1.55 + 4, y - r * 0.6 + 10, r * 3.1, r * 1.2, "#000", r * 0.6, opacity=0.35,
                     extra=f' filter="{doc.blur(6)}"')
            doc.rect(x - r * 1.55, y - r * 0.6, r * 3.1, r * 1.2, col, r * 0.6, stroke="#FFFFFF", sw=3)
            doc.rect(x - r * 0.55, y - r * 0.44, r * 1.1, r * 0.88, "#FFFFFF", r * 0.18, opacity=0.4)
            for sx in (-1, 1):
                for i in range(2):
                    for j in range(2):
                        doc.circle(x + sx * r * (0.85 + i * 0.32), y - r * 0.18 + j * r * 0.36, r * 0.06, "#FFFFFF",
                                   opacity=0.7)
            icon(doc, "check", x, y, r * 0.8, "#FFFFFF", 4)
    else:
        doc.circle(x, y, r, col, opacity=0.14)
        doc.line((x + r * 0.72, y + r * 0.72), (x + r * 1.55, y + r * 1.55), col, 16)
        doc.circle(x, y, r, "none", col, 9)
        doc.path(f"M{f(x - r * 0.6)} {f(y - r * 0.15)}A{f(r * 0.62)} {f(r * 0.62)} 0 0 1 {f(x - r * 0.1)} "
                 f"{f(y - r * 0.6)}", stroke="#FFFFFF", sw=5, opacity=0.8)


def _badge(doc: Doc, x: float, y: float, label: str, col: str, size: float, on_fill: str) -> Box:
    """Status badge; its shape carries the status as much as its colour."""
    pad = size * 0.6
    gw = size * 1.05                       # room for the glyph
    w = T.measure(T.supported(label, "ui_bold"), size, "ui_bold", tracking=size * 0.04) + 2 * pad + gw
    h = size * 1.8
    b = Box(x, y, w, h)
    gx, gy = x + pad + gw * 0.38, y + h / 2
    tc = on_fill
    if label == "EXPLOITED":
        doc.rect(x, y, w, h, col)
        doc.poly(_burst(size * 0.42, gx, gy, random.Random(1), 7, 0.5), on_fill)
    elif label == "PROOF OF CONCEPT":
        doc.rect(x, y, w, h, "none", 4, stroke=col, sw=size * 0.09, extra=f' stroke-dasharray="{f(size * 0.3)} '
                                                                            f'{f(size * 0.2)}"')
        doc.circle(gx, gy, size * 0.32, "none", col, size * 0.08)
        doc.line((gx - size * 0.5, gy), (gx + size * 0.5, gy), col, size * 0.07)
        doc.line((gx, gy - size * 0.5), (gx, gy + size * 0.5), col, size * 0.07)
        tc = col
    elif label == "PATCH AVAILABLE":
        doc.rect(x, y, w, h, col, h / 2)
        icon(doc, "check", gx + size * 0.05, gy, size * 0.9, on_fill, 3.6)
    else:
        doc.rect(x, y, w, h, "none", h / 2, stroke=col, sw=size * 0.09)
        doc.circle(gx, gy - size * 0.05, size * 0.27, "none", col, size * 0.08)
        doc.line((gx + size * 0.2, gy + size * 0.15), (gx + size * 0.42, gy + size * 0.37), col, size * 0.1)
        tc = col
    doc.text(label, x + pad + gw, y + h / 2 + T.cap_height(size, "ui_bold") / 2, size, tc, "ui_bold",
             tracking=size * 0.04)
    return b


# ---------------------------------------------------------------- product placement

_TALL = {"phone", "database", "printer"}
_WIDE = {"server", "appliance"}
# Share of the slot width a drawing may take: rack hardware recedes to the
# right (top and side faces), so it is drawn a little narrower than its slot.
_FILL = {"server": 0.84, "appliance": 0.86, "os": 0.84}


def _draw_product(doc: Doc, a: _Adv, slot: Box, col: str, rng: random.Random) -> Pt:
    w = min(slot.w * _FILL.get(a.kind, 1.0), slot.h / ASPECT[a.kind])
    if a.kind == "phone" and a.wallet:
        return handset(doc, slot.cx, slot.cy, w, col, rng, mode="wallet")
    if a.kind == "server":
        return server(doc, slot.cx, slot.cy, w, col, rng, style=rng.randrange(2))
    return DRAW[a.kind](doc, slot.cx, slot.cy, w, col, rng)


def _ident_line(doc: Doc, a: _Adv, x: float, y: float, ink: str, muted: str, col: str, big: float) -> None:
    """The story's identifiers: its first CVE (and how many more), else the
    stated flaw count, else nothing."""
    if a.cves:
        w = doc.text(a.cves[0], x, y, big * 0.42, ink, "mono_bold")
        if len(a.cves) > 1:
            doc.text(f"+{len(a.cves) - 1} more", x + w + 22, y, big * 0.3, muted, "mono")
    elif a.flaws:
        n = ("~" if a.flaws_approx else "") + a.flaws
        w = doc.text(n, x - 4, y + big * 0.3, big, col, "display", tracking=-big * 0.02)
        # the count belongs to the update that fixes them, not to the status
        doc.text("flaws fixed" if a.patched else "flaws", x + w + 18, y + big * 0.3, big * 0.36, ink, "ui")


# ---------------------------------------------------------------- A: stage (dark)

def _stage(doc: Doc, a: _Adv, rng: random.Random) -> None:
    """Dark stage. Wide hardware: name and status on top, the product across
    the lower two thirds. Tall objects (phone, database, printer): a type
    column on the left, the product standing on the right."""
    p = doc.pal
    st_label, st_col = _status(a, p)
    doc.rect(0, 0, 1600, 900, doc.lin([(0, "#151D2E", 1), (1, "#06080E", 1)], 0, 0, 0.35, 1))
    tall = a.kind in _TALL
    wide = a.kind in _WIDE
    grid(doc, 80, 0.10)
    size = fit_size(a.name, 150, 900 if tall else 1440)
    base = 86 + T.cap_height(size, "display")
    y = base + 30
    if a.others:
        y += 48
    if tall:
        slot = Box(1000, 70, 520, 760)
    elif wide:
        slot = Box(200, y + 150, 1340, 870 - (y + 150))
    else:
        slot = Box(720, max(230.0, y + 20), 840, 850 - max(230.0, y + 20))
    doc.add(f'<ellipse cx="{f(slot.cx)}" cy="{f(slot.cy)}" rx="{f(slot.w * 0.6)}" ry="{f(slot.h * 0.75)}" '
            f'fill="{doc.rad([(0, st_col, 0.26), (1, st_col, 0)])}"/>')
    doc.rect(0, 760, 1600, 140, doc.lin([(0, "#000", 0.0), (1, "#000", 0.5)]))
    doc.text(a.name, 74, base, size, "#FFFFFF", "display", tracking=-size * 0.015)
    if a.others:
        doc.text(T.fit("+ " + ", ".join(a.others), 30, 760, "ui"), 80, base + 60, 30, p.muted, "ui")
    b = _badge(doc, 80, y + 26, st_label, st_col, 58 if wide else 50, "#0A0F1A")
    if not wide:
        if a.sev:
            pill(doc, 80, b.b + 22, a.sev, fg="#FFFFFF", bg="#0000", size=30, font="ui_bold", pad=18,
                 stroke="#FFFFFF")
        _ident_line(doc, a, 80, b.b + (150 if a.sev else 84), "#FFFFFF", p.muted, st_col, 130)
    else:
        x = b.r + 28
        if a.sev:
            sp = pill(doc, x, b.y + (b.h - 30 * 1.9) / 2, a.sev, fg="#FFFFFF", bg="#0000", size=30, font="ui_bold",
                      pad=18, stroke="#FFFFFF")
            x = sp.r + 40
        big = 96
        _ident_line(doc, a, x, b.cy + (T.cap_height(big * 0.42, "mono_bold") / 2 if a.cves else 0), "#FFFFFF",
                    p.muted, st_col, big)
    anchor = _draw_product(doc, a, slot, st_col, rng)
    _mark(doc, st_label, anchor[0], anchor[1], 70, st_col, rng)
    doc.focus = Box(30, 30, 1540, 866)
    vignette(doc, 0.35)


# ---------------------------------------------------------------- B: bulletin (light)

def _bulletin(doc: Doc, a: _Adv, rng: random.Random) -> None:
    p = doc.pal
    st_label, _ = _status(a, p)
    col = _ON_PAPER[st_label]
    ink, muted, rule = "#14161B", "#6E6A62", "#D6D0C4"
    doc.rect(0, 0, 1600, 900, doc.lin([(0, "#E4DED2", 1), (1, "#C9C1B2", 1)], 0, 0, 0.6, 1))
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#FFFFFF", 0.5), (1, "#FFFFFF", 0)], 0.25, 0.1, 0.7))
    tall = a.kind in _TALL
    sw = 820 if tall else 900
    sx, sy = 64, 52
    ang = rng.choice((-1.2, -0.7, 0.6))
    with doc.g(transform=f"rotate({ang} {sx + sw / 2} 450)"):
        doc.shadow(sx, sy, sw, 940, 4, 1.1)
        doc.rect(sx, sy, sw, 940, "#FBF8F2", 4)
        doc.rect(sx, sy, sw, 22, col)
        doc.text("SECURITY ADVISORY", sx + 56, sy + 92, 24, ink, "ui_bold", tracking=5)
        doc.line((sx + 56, sy + 116), (sx + sw - 56, sy + 116), ink, 3)
        size = fit_size(a.name, 136, sw - 112)
        cap = T.cap_height(size, "display")
        doc.text(a.name, sx + 52, sy + 150 + cap, size, ink, "display", tracking=-size * 0.015)
        y = sy + 150 + cap
        if a.others:
            doc.text(T.fit(" / ".join(a.others), 28, sw - 120, "ui"), sx + 56, y + 50, 28, muted, "ui")
            y += 44
        b = _badge(doc, sx + 56, y + 44, st_label, col, 54, "#FFFFFF")
        y = b.b + 40
        if a.sev:
            pill(doc, sx + 56, b.b + 20, a.sev, fg=ink, bg="#0000", size=28, font="ui_bold", pad=16, stroke=ink)
            y += 50
        doc.line((sx + 56, y), (sx + sw - 56, y), rule, 1.5)
        _ident_line(doc, a, sx + 56, y + 80, ink, muted, col, 112)
    # the product, as the bulletin's figure, beside the sheet
    slot = Box(1010, 90, 520, 740) if tall else Box(930, 230, 650, 500)
    doc.add(f'<ellipse cx="{f(slot.cx)}" cy="{f(slot.cy)}" rx="{f(slot.w * 0.7)}" ry="{f(slot.h * 0.7)}" '
            f'fill="{doc.rad([(0, "#1B2333", 0.22), (1, "#1B2333", 0)])}"/>')
    anchor = _draw_product(doc, a, slot, col, rng)
    _mark(doc, st_label, anchor[0], anchor[1], 64, col, rng)
    doc.focus = Box(30, 30, 1540, 866)
    vignette(doc, 0.3)


# ---------------------------------------------------------------- CISA KEV ledger

def _catalogue(doc: Doc, a: _Adv, rng: random.Random) -> None:
    """KEV additions: the catalogue's newest entries are the story's CVEs."""
    p = doc.pal
    background(doc, light=(0.3, 0.1))
    doc.rect(0, 0, 1600, 900, doc.rad([(0, p.danger, 0.14), (1, p.danger, 0)], 0.2, 0.15, 0.7))
    doc.text("CISA KEV", 74, 84 + T.cap_height(150, "display"), 150, "#FFFFFF", "display", tracking=-2)
    doc.text("Known Exploited Vulnerabilities catalog", 80, 250, 32, p.muted, "ui")
    _badge(doc, 1530 - 410, 92, "EXPLOITED", p.danger, 44, "#0A0F1A")
    x0, x1 = 80, 1530
    y = 320
    doc.line((x0, y), (x1, y), p.line, 2)
    rh = 104
    rows = max(len(a.cves), 1)
    for i in range(5):
        ry = y + i * rh
        if i < rows and a.cves:
            doc.rect(x0, ry + 10, x1 - x0, rh - 20, p.danger, 8, opacity=0.13)
            doc.rect(x0, ry + 10, 8, rh - 20, p.danger)
            doc.text(a.cves[i], x0 + 40, ry + rh / 2 + 19, 54, "#FFFFFF", "mono_bold")
            pill(doc, x1 - 30, ry + rh / 2 - 19, "added", fg="#0A0F1A", bg=p.danger, size=20, font="ui_bold",
                 anchor="end", pad=14)
        elif i == len(a.cves) and a.kev_total > len(a.cves):
            # the headline counts more additions than the sources list: say so, never pad
            doc.text(f"+{a.kev_total - len(a.cves)} more", x0 + 40, ry + rh / 2 + 17, 48, p.muted, "mono_bold")
        else:
            doc.rect(x0 + 40, ry + rh / 2 - 8, 420, 16, p.line, 8, opacity=0.8)
            doc.rect(x0 + 520, ry + rh / 2 - 8, 260 + rng.randrange(200), 16, p.line, 8, opacity=0.6)
        doc.line((x0, ry + rh), (x1, ry + rh), p.line, 1, 0.6)
    doc.focus = Box(30, 30, 1540, 866)
    vignette(doc, 0.4)


@scene("vuln_advisory")
def vuln_advisory(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    a = _facts(brief)
    if a.kev and a.cves:
        _catalogue(doc, a, rng)
        return
    rng.choice((_stage, _stage, _bulletin))(doc, a, rng)


_STATUS_UA = {"EXPLOITED": "EXPLOITED", "PROOF OF CONCEPT": "PROOF OF CONCEPT", "PATCH AVAILABLE": "PATCH AVAILABLE",
              "PATCHING URGED": "PATCHING URGED", "DISCLOSED": "DISCLOSED"}


def alt_for(brief: EditorialBrief) -> tuple[str, str]:
    """The advisory as drawn: product name, the status badge and the severity
    pill (the catalogue text said 'patch status' for every variant)."""
    from ..kit import PALETTES
    a = _facts(brief)
    status = _status(a, PALETTES["midnight"])[0]
    if a.kev and a.cves:
        ids = ", ".join(a.cves)          # every CVE the catalogue rows show
        more = a.kev_total - len(a.cves) if a.kev_total > len(a.cves) else 0
        return (f"Illustration: the CISA KEV catalogue marked 'EXPLOITED', listing {ids}"
                + (f", and a row reading '+{more} more'." if more else "."),
                f"Ілюстрація: каталог CISA KEV із позначкою «EXPLOITED», у ньому {ids}"
                + (f" і рядок «+{more} more»." if more else "."))
    what_en = f"a security advisory for {a.name}" if a.name != "Advisory" else "a security advisory"
    what_ua = f"бюлетень безпеки для {a.name}" if a.name != "Advisory" else "бюлетень безпеки"
    sev_en = f" and '{a.sev}'" if a.sev else ""
    sev_ua = f" і «{a.sev}»" if a.sev else ""
    return (f"Illustration: {what_en}, marked '{status}'{sev_en}.",
            f"Ілюстрація: {what_ua} з позначкою «{_STATUS_UA[status]}»{sev_ua}.")
