"""Law-enforcement actions, drawn by role (O56): the acting authority, the
arrested group, the seized object and the action are kept apart.

* Seizure or takedown the headline states, of named infrastructure or a
  stated count: a dark server rack under barrier tape carrying the
  headline's own action (SEIZED / TAKEN DOWN), the seized operations on
  evidence tags. Only names that follow the seizure verb are tags; a
  country, a nationality or an agency is never a seized object.
* Arrest, charge or exposure: the arrested group as a case file labelled as
  the headline describes it (or the phone when calls are the stated
  channel), under tape with the action word; the acting authorities, the
  reported figure and secondary context on evidence tags.

No seal, badge, mugshot or document text is drawn."""
from __future__ import annotations

import math
import random
import re
from typing import Callable

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, background, f, vignette
from . import scene
from ._editorial import fit_size, headline_main, product_groups

_TAPE = "#F2B705"
_TAPE_INK = "#14161A"
_TAG = ("#E9D3A1", "#D6B977")
_TAG_INK = "#2A2116"
# Headline words that are not what was seized.
_NOT_SEIZED = {"Police", "Operation Endgame", "Operation", "Endgame", "Europol", "FBI", "Servers", "Logins",
               "Stolen", "Seizes", "Takes", "Down", "Dismantle", "Takedown"}


#: Places and nationalities: an acting authority or a location, never a seized object.
_PLACES = {"Ukraine", "US", "USA", "UK", "Britain", "Germany", "France", "Netherlands", "Poland", "Spain",
           "Italy", "Brazil", "India", "China", "Russia", "Iran", "Japan", "Korea", "Canada", "Australia",
           "Romania", "Moldova", "Georgia", "Europe", "EU", "Latin", "America", "Asia", "Africa"}
_SEIZE_VERB = re.compile(r"seiz\w*|confiscat\w*|take[sn]? down|took down|takedown|dismantl\w*|shut(?:s)? down|"
                         r"disrupt\w*|вилуч\w*|ліквідува\w*|заблокува\w*", re.I)


def _not_an_object(name: str) -> bool:
    from ..brief import DEMONYMS
    first = name.split()[0]
    return (name in _NOT_SEIZED or first in {"Police", "Operation", "Europol"} or first in _PLACES
            or name in _PLACES or first in DEMONYMS
            or any(re.search(pat, name.lower()) for pat, _ in _ACTORS))


def _seized_names(brief: EditorialBrief) -> list[str]:
    """What the headline says was seized or taken down: names that follow a
    seizure/takedown verb. An arrest seizes nothing; a country or agency is
    never an object."""
    if _action(brief) not in ("SEIZED", "TAKEN DOWN"):
        return []
    head = brief.headline or headline_main(brief.text)
    m = _SEIZE_VERB.search(head)
    if not m:
        return []
    after = head[m.start():]
    out: list[str] = []
    for g in product_groups(brief):
        # "Endgame Takes Down Gootloader" -> "Gootloader": action words and operation names are not objects
        name = " ".join(w for w in g.split() if w not in _NOT_SEIZED)
        if name and name in after and not _not_an_object(name) and name not in out:
            out.append(name)
    return out[:4]


def _authorities(brief: EditorialBrief) -> list[str]:
    """Who acted: the agencies named in the headline, and a country named
    before the action verb ("Ukraine, FBI arrest ...")."""
    head = brief.headline or headline_main(brief.text)
    verb = re.search(r"arrest|detain|charg|expos|uncover|bust|seiz|take[sn]? down|dismantl|заарешту|затрима|"
                     r"викри|вилучи|ліквідува", head, re.I)
    lead = head[:verb.start()] if verb else ""
    places = [w for w in re.findall(r"[A-Z][a-zA-Z]+", lead) if w in _PLACES]
    named = []
    for place in places:
        adj = _DEMONYM_OF.get(place, "")
        m = re.search(rf"\b{adj.lower()} (authorities|police|law enforcement|prosecutors)\b", brief.text) if adj else None
        named.append(f"{adj} {m.group(1)}" if m else place)
    return list(dict.fromkeys(named + _actors(brief)))


#: How the sources name a country's authorities ("Ukrainian authorities").
_DEMONYM_OF = {"Ukraine": "Ukrainian", "Germany": "German", "France": "French", "Netherlands": "Dutch",
               "Poland": "Polish", "Spain": "Spanish", "Italy": "Italian", "Brazil": "Brazilian", "India": "Indian",
               "Canada": "Canadian", "Australia": "Australian", "Romania": "Romanian", "Moldova": "Moldovan",
               "Georgia": "Georgian", "Japan": "Japanese", "Britain": "British"}


_GROUPS: tuple[tuple[str, str], ...] = (
    (r"ransomware (?:gang|group|operation|crew|affiliate)", "RANSOMWARE GANG"),
    (r"ransomware", "RANSOMWARE SUSPECTS"),
    (r"(?:fraud|scam|scammer)\w*|шахра\w*", "FRAUD RING"),
    (r"botnet|ботнет", "BOTNET OPERATORS"),
    (r"phishing", "PHISHING GANG"),
    (r"hacker\w*|хакер\w*", "HACKERS"),
    (r"угрупован\w*|gang|group|ring|crew", "CRIMINAL GROUP"),
)


def _arrested(brief: EditorialBrief) -> str:
    """The arrested or exposed group as the headline describes it."""
    head = (brief.headline or headline_main(brief.text)).lower()
    for pat, label in _GROUPS:
        if re.search(pat, head):
            return label
    return "SUSPECTS"


def _headline_count(brief: EditorialBrief) -> tuple[str, str]:
    """(figure, what) when the headline itself states a seized count
    ("Seizes 6.4M Stolen Logins"); figures from `brief.facts` first."""
    for key, what in (("accounts", "accounts"), ("records", "records")):
        if brief.facts.get(key):
            return str(brief.facts[key]), what
    m = re.search(r"seiz\w*\s+(?:about\s+|over\s+|nearly\s+)?(\d+(?:[.,]\d+)?\s?(?:m|k|b|million|billion)?)\s+"
                  r"(?:stolen\s+)?(logins|credentials|accounts|passwords|domains|servers)", headline_main(brief.text))
    if not m:
        return "", ""
    fig = m.group(1).replace(" ", "").upper().replace("MILLION", "M").replace("BILLION", "B")
    what = ("stolen " if "stolen" in m.group(0) else "") + m.group(2)
    return fig, what


# ---------------------------------------------------------------- props

def _rack(doc: Doc, x: float, y: float, w: float, h: float, rng: random.Random) -> list[tuple[float, float]]:
    """A 42U rack in front elevation, all units dark. Returns handle points
    (where tags can be tied) down the right rail."""
    doc.shadow(x, y, w, h, 6, 1.6)
    # the rack's side panel, turned slightly away (depth)
    sd = 70
    doc.poly([(x - sd, y + 40), (x, y), (x, y + h), (x - sd, y + h - 30)],
             doc.lin([(0, "#1A1F25", 1), (1, "#262C34", 1)], 0, 0, 1, 0))
    for k in range(int(h // 60)):
        doc.line((x - sd + 12, y + 70 + k * 60), (x - 12, y + 40 + k * 60), "#11151A", 2, 0.8)
    doc.rect(x, y, w, h, doc.lin([(0, "#2B323B", 1), (1, "#161A20", 1)], 0, 0, 1, 0), 6, stroke="#0B0D10", sw=2)
    rail = 34
    for rx in (x + 10, x + w - 10 - rail):
        doc.rect(rx, y + 10, rail, h - 20, "#1D2228", 3)
        for k in range(int((h - 40) // 22)):
            doc.rect(rx + 12, y + 24 + k * 22, 10, 7, "#0C0E11", 1.5)
    inner = Box(x + 10 + rail, y + 18, w - 20 - 2 * rail, h - 36)
    doc.rect(inner.x, inner.y, inner.w, inner.h, "#0B0D10")
    kinds = ["switch", "server", "server", "storage", "server", "server", "storage", "server", "server",
             "switch", "server", "storage", "server", "server", "server", "storage"]
    yy = inner.y + 6
    i = 0
    handles: list[tuple[float, float]] = []
    while yy < inner.b - 20:
        kind = kinds[i % len(kinds)]
        uh: float = 44 if kind == "switch" else 74 if kind == "storage" else 56 if rng.random() < 0.6 else 88
        if yy + uh > inner.b - 4:
            uh = inner.b - 4 - yy
            if uh < 40:
                break
        doc.rect(inner.x - 2, yy, inner.w + 4, uh - 4, "#000", 2, opacity=0.35)
        # every light off: the operation is down
        _unit(doc, inner.x, yy, inner.w, uh - 6, kind, i)
        handles.append((inner.r - 8, yy + uh / 2))
        yy += uh
        i += 1
    # key light from the upper left across the rack face, rim on the right rail
    doc.rect(x, y, w, h, doc.lin([(0, "#FFFFFF", 0.16), (0.45, "#FFFFFF", 0.0), (1, "#000", 0.25)], 0, 0, 0.6, 1), 6)
    doc.rect(x + w - 4, y, 4, h, "#C9D3DE", opacity=0.45)
    return handles


def _unit(doc: Doc, x: float, y: float, w: float, h: float, kind: str, i: int) -> None:
    face = "#434C58" if i % 2 else "#3B434E"
    doc.rect(x, y, w, h, doc.lin([(0, face, 1), (1, "#1B2026", 1)]), 3, stroke="#0E1014", sw=1)
    doc.rect(x, y, w, 2, "#FFFFFF", opacity=0.10)
    for ex in (x + 4, x + w - 18):
        doc.rect(ex, y + 3, 14, h - 6, "#3A414B", 2)
        doc.circle(ex + 7, y + h / 2, 2.6, "#11141A")
    if kind == "switch":
        n = int((w - 120) // 24)
        for k in range(n):
            px = x + 36 + k * 24
            doc.rect(px, y + h / 2 - 8, 18, 15, "#0C0E12", 2)
    elif kind == "storage":
        n = int((w - 80) // 52)
        for k in range(n):
            px = x + 30 + k * 52
            doc.rect(px, y + 6, 46, h - 12, "#20252C", 3, stroke="#0E1014", sw=1)
            doc.rect(px + 6, y + h / 2 - 2, 34, 4, "#14171C", 2)
    else:
        for k in range(int((w * 0.42) // 10)):
            doc.rect(x + 30 + k * 10, y + 7, 5, h - 14, "#14171C", 2)
        bx = x + w * 0.56
        for k in range(3):
            doc.rect(bx + k * (w * 0.1), y + 6, w * 0.085, h - 12, "#20252C", 2, stroke="#0E1014", sw=1)
        doc.circle(x + w - 36, y + h / 2, 4, "#151820", stroke="#3D4550", sw=1.5)


def _tape(doc: Doc, x0: float, y0: float, x1: float, y1: float, hgt: float = 74, word: str = "SEIZED",
          phase: float = 0.0) -> None:
    """Barrier tape from (x0, y0) to (x1, y1) with the word repeated."""
    ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
    ln = math.hypot(x1 - x0, y1 - y0)
    with doc.g(transform=f"translate({f(x0)} {f(y0)}) rotate({ang:.2f})"):
        doc.rect(4, -hgt / 2 + 18, ln, hgt, "#000", opacity=0.45, extra=f' filter="{doc.blur(10)}"')
        doc.rect(0, -hgt / 2, ln, hgt, doc.lin([(0, "#FFD43B", 1), (0.5, _TAPE, 1), (1, "#D99A00", 1)]))
        doc.rect(0, -hgt / 2 + 6, ln, 7, _TAPE_INK)
        doc.rect(0, hgt / 2 - 13, ln, 7, _TAPE_INK)
        size = hgt * 0.46
        unit = T.measure(word, size, "ui_bold", tracking=size * 0.18) + size * 2.2
        cx = -phase * unit
        while cx < ln:
            doc.text(word, cx, T.cap_height(size, "ui_bold") / 2, size, _TAPE_INK, "ui_bold", tracking=size * 0.18)
            doc.rect(cx + unit - size * 1.45, -size * 0.18, size * 0.7, size * 0.36, _TAPE_INK, 2)
            cx += unit
        # creases
        for k in range(1, int(ln // 260) + 1):
            doc.rect(k * 260 + (k * 37) % 90, -hgt / 2, 3, hgt, "#FFFFFF", opacity=0.22)


def _tag(doc: Doc, x: float, y: float, w: float, h: float, anchor: tuple[float, float], lines: list[tuple[str, float,
         str]], rot: float) -> None:
    """A manila evidence tag tied by a string to `anchor`; `lines` = (text,
    size, font) set left-aligned."""
    ex, ey = x + 30, y + h / 2
    a = math.radians(rot)
    # string: anchor -> eyelet (rotated position)
    cx, cy = x + w / 2, y + h / 2
    rx = cx + (ex - cx) * math.cos(a) - (ey - cy) * math.sin(a)
    ry = cy + (ex - cx) * math.sin(a) + (ey - cy) * math.cos(a)
    mx, my = (anchor[0] + rx) / 2, max(anchor[1], ry) + 26
    doc.path(f"M{f(anchor[0])} {f(anchor[1])}Q{f(mx)} {f(my)} {f(rx)} {f(ry)}", stroke="#000", sw=4, opacity=0.3,
             extra=' transform="translate(2 6)"')
    doc.path(f"M{f(anchor[0])} {f(anchor[1])}Q{f(mx)} {f(my)} {f(rx)} {f(ry)}", stroke="#D9D2C3", sw=3)
    doc.circle(anchor[0], anchor[1], 6, "#D9D2C3")
    with doc.g(transform=f"rotate({rot:.2f} {f(cx)} {f(cy)})"):
        shape = (f"M{f(x + 36)} {f(y)}H{f(x + w - 8)}Q{f(x + w)} {f(y)} {f(x + w)} {f(y + 8)}V{f(y + h - 8)}"
                 f"Q{f(x + w)} {f(y + h)} {f(x + w - 8)} {f(y + h)}H{f(x + 36)}L{f(x)} {f(y + h - 30)}"
                 f"V{f(y + 30)}Z")
        doc.path(shape, fill="#000", opacity=0.45, extra=f' transform="translate(8 18)" filter="{doc.blur(9)}"')
        doc.path(shape, fill=doc.lin([(0, _TAG[0], 1), (1, _TAG[1], 1)], 0, 0, 0.3, 1))
        doc.path(shape, fill="none", stroke="#FFFFFF", sw=1.5, opacity=0.35)
        doc.circle(ex, ey, 15, "#C9A964", stroke="#A88B4C", sw=3)
        doc.circle(ex, ey, 7, "#1B1F25")
        doc.rect(x + 60, y, 6, h, "#B0915A", opacity=0.45)
        ty = y + 22
        tot = sum(T.cap_height(s, fn) for _, s, fn in lines) + 18 * (len(lines) - 1)
        ty = y + (h - tot) / 2
        for txt, s, fn in lines:
            ty += T.cap_height(s, fn)
            doc.text(txt, x + 86, ty, s, _TAG_INK, fn)
            ty += 18


# ---------------------------------------------------------------- compositions

def _comp_rack(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """A: the taped-off rack, its operations on evidence tags."""
    background(doc, light=(0.30, 0.10), floor=780)
    # backlight on the wall behind the rack: a clear silhouette at feed size
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#8FA3B8", 0.42), (0.6, "#56677A", 0.12), (1, "#000", 0)], 0.36, 0.38,
                                      0.55))
    names = _seized_names(brief)
    fig, what = _headline_count(brief)
    rx, rw = 270, 580
    handles = _rack(doc, rx, -30, rw, 880, rng)
    # floor shadow line
    doc.rect(rx - 40, 846, rw + 80, 20, "#000", 10, opacity=0.5, extra=f' filter="{doc.blur(12)}"')
    word = _action(brief)                 # SEIZED or TAKEN DOWN: the headline's own action
    _tape(doc, -40, 250, 1640, 470, word=word, phase=0.15)
    _tape(doc, -40, 690, 1100, 520, hgt=60, word=word, phase=0.55)
    # evidence tags down the right rail
    tags: list[list[tuple[str, float, str]]] = []
    for nm in names:
        tags.append([(nm, fit_size(nm, 64, 520, "ui_bold"), "ui_bold")])
    if fig:
        tags.append([(fig, 104, "display"), (what, 34, "ui")])
    if not tags:
        tags.append([("servers", 64, "ui_bold")])
    n = len(tags)
    top, gap = 70, 34
    hs: list[float] = [190 if len(t) > 1 else 104 for t in tags]
    avail = 840 - top - gap * (n - 1)
    k = min(1.0, avail / sum(hs))
    hs = [h_ * k for h_ in hs]
    y = top + (840 - top - sum(hs) - gap * (n - 1)) / 2
    for i, (t, h_) in enumerate(zip(tags, hs)):
        hp = handles[min(len(handles) - 1, max(0, int((y + h_ / 2 - 20) / 880 * len(handles))))]
        tx = 930 + (i % 2) * 44
        rot = (-3.5 if i % 2 else 2.5) + rng.uniform(-1.0, 1.0)
        if len(t) > 1:
            t = [(t[0][0], t[0][1] * k, t[0][2]), (t[1][0], t[1][1] * max(k, 0.8), t[1][2])]
        else:
            t = [(t[0][0], t[0][1] * max(k, 0.85), t[0][2])]
        _tag(doc, tx, y, 560, h_, hp, t, rot)
        y += h_ + gap
    doc.focus = Box(150, 40, 1360, 765)
    vignette(doc, 0.5)


def _evidence_bag(doc: Doc, b: Box) -> None:
    """Clear plastic over whatever was drawn in `b` (call after the contents)."""
    d = (f"M{f(b.x)} {f(b.y + 20)}Q{f(b.x)} {f(b.y)} {f(b.x + 20)} {f(b.y)}H{f(b.r - 20)}Q{f(b.r)} {f(b.y)} "
         f"{f(b.r)} {f(b.y + 20)}L{f(b.r - 6)} {f(b.b - 30)}Q{f(b.r - 8)} {f(b.b)} {f(b.r - 36)} {f(b.b - 2)}"
         f"H{f(b.x + 30)}Q{f(b.x + 4)} {f(b.b)} {f(b.x + 6)} {f(b.b - 30)}Z")
    doc.path(d, fill=doc.lin([(0, "#E8F0F8", 0.20), (0.5, "#E8F0F8", 0.06), (1, "#E8F0F8", 0.16)], 0, 0, 1, 1))
    doc.path(d, fill="none", stroke="#EEF4FA", sw=4, opacity=0.6)
    # creases: soft specular streaks where the film folds
    for u, v, du, dv, wd in ((0.04, 0.30, 0.30, -0.10, 18), (0.55, 0.12, 0.40, 0.06, 12),
                             (0.20, 0.82, 0.35, 0.04, 14), (0.70, 0.70, 0.26, 0.16, 10)):
        x0, y0 = b.x + b.w * u, b.y + b.h * v
        doc.path(f"M{f(x0)} {f(y0)}q{f(b.w * du * 0.5)} {f(b.h * dv - 14)} {f(b.w * du)} {f(b.h * dv)}",
                 stroke="#FFFFFF", sw=wd, opacity=0.16)
    # heat-seal strip with a red tamper band
    doc.rect(b.x + 4, b.y + 18, b.w - 8, 40, "#E8EEF4", opacity=0.25)
    doc.rect(b.x + 4, b.y + 28, b.w - 8, 18, "#C7362B")
    doc.rect(b.x + 4, b.y + 34, b.w - 8, 3, "#8E1E16")


def _comp_bag(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """B: one server from the rack, sealed in an evidence bag on a steel
    bench, its label listing what was seized."""
    background(doc, light=(0.45, 0.0))
    # the bench seen from above, lit by one overhead lamp
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#5A6573", 0.55), (1, "#0E1115", 0)], 0.45, 0.42, 0.62))
    names = _seized_names(brief)
    fig, what = _headline_count(brief)
    with doc.g(transform=f"rotate({rng.uniform(-6.0, -4.0):.2f} 760 450)"):
        bag = Box(130, 150, 1300, 640)
        doc.rect(bag.x + 20, bag.y + 50, bag.w, bag.h, "#000", 24, opacity=0.55, extra=f' filter="{doc.blur(26)}"')
        # contents: a 2U server, front elevation, every light off
        sv = Box(bag.x + 70, bag.y + 100, bag.w - 140, 150)
        doc.rect(sv.x + 8, sv.y + 16, sv.w, sv.h, "#000", 4, opacity=0.5, extra=f' filter="{doc.blur(8)}"')
        _unit(doc, sv.x, sv.y, sv.w, sv.h / 2, "server", 1)
        _unit(doc, sv.x, sv.y + sv.h / 2, sv.w, sv.h / 2, "storage", 0)
        # write-on evidence label, printed on the bag
        lb = Box(bag.x + 70, sv.b + 40, 760, bag.b - sv.b - 70)
        doc.rect(lb.x, lb.y, lb.w, lb.h, "#F4F1EA", 6)
        doc.rect(lb.x, lb.y, lb.w, 76, "#C7362B", 6)
        doc.rect(lb.x, lb.y + 60, lb.w, 16, "#C7362B")
        doc.text("SEIZED", lb.x + 32, lb.y + 56, 52, "#FFFFFF", "ui_bold", tracking=9)
        rows = names or ["servers and domains"]
        ry = lb.y + 76
        rh = (lb.h - 76) / max(1, len(rows))
        for k, n in enumerate(rows):
            sz = min(56.0, rh * 0.62)
            doc.text(n, lb.x + 32, ry + rh / 2 + T.cap_height(sz, "ui_bold") / 2, sz, "#1B1F26", "ui_bold")
            if k < len(rows) - 1:
                doc.line((lb.x + 32, ry + rh), (lb.r - 32, ry + rh), "#C9C2B5", 2)
            ry += rh
        if fig:
            fx = lb.r + 50
            doc.text(fig, fx, lb.y + 120, 110, "#F2F4F7", "display")
            doc.text(what, fx + 4, lb.y + 172, 36, "#B9C2CD", "ui")
        _evidence_bag(doc, bag)
    doc.focus = Box(140, 120, 1300, 731)
    vignette(doc, 0.6)


# ---------------------------------------------------------------- exposure / arrest

#: The action the headline states, in the order a stronger action wins. Read
#: from the headline only.
_ACTIONS: tuple[tuple[str, str], ...] = (
    (r"seiz|вилучи", "SEIZED"), (r"take[sn]? down|takedown|dismantl|ліквідува", "TAKEN DOWN"),
    (r"arrest|detain|заарешту|затрима", "ARRESTED"), (r"charg(?:ed|es)\b|повідомили про підозру", "CHARGED"),
    (r"expos|uncover|bust|викри", "EXPOSED"),
)
#: Law-enforcement bodies named in a headline, set in English (image text is
#: ASCII and serves both editions).
_ACTORS: tuple[tuple[str, str], ...] = (
    (r"нацполіц|national police", "National Police"), (r"кіберполіц|cyber ?police", "Cyber Police"),
    (r"\bфбр\b|\bfbi\b", "FBI"), (r"європол|europol", "Europol"), (r"інтерпол|interpol", "Interpol"),
    (r"\bсбу\b", "SBU"), (r"прокурат|prosecutor", "Prosecutors"), (r"\bdoj\b|justice department", "US DOJ"),
)


def _head(brief: EditorialBrief) -> str:
    return (brief.headline or headline_main(brief.text)).lower()


def _action(brief: EditorialBrief) -> str:
    for pat, word in _ACTIONS:
        if re.search(pat, _head(brief)):
            return word
    return "EXPOSED"


def _actors(brief: EditorialBrief) -> list[str]:
    named = [name for pat, name in _ACTORS if re.search(pat, _head(brief))]
    if not named and re.search(r"\bpolice\b|поліці|правоохорон|law enforcement", _head(brief)):
        named = ["Police"]                    # the headline names police, no specific body
    return named


def _ai_calls(brief: EditorialBrief) -> bool:
    """The source states an AI platform or tool used for calls (secondary context)."""
    return re.search(r"(?:ші|ai)[- ]?(?:платформ\w*|platform|tool|інструмент\w*)\W+(?:\w+\W+){0,2}"
                     r"(?:дзвін\w*|дзвінк\w*|call\w*)|ai[- ]powered call", brief.text) is not None


def _seizure(brief: EditorialBrief) -> bool:
    """The seized-rack composition: only for a seizure or takedown the
    headline states, with a seized object or count to tag."""
    return _action(brief) in ("SEIZED", "TAKEN DOWN") and bool(_seized_names(brief) or _headline_count(brief)[0])


def _contact(brief: EditorialBrief) -> bool:
    """The sources name the group's channel of contact: calls."""
    return _support(brief) or re.search(r"\bcalls?\b|phone|vishing|дзвін\w*|дзвінк\w*|телефон\w*",
                                        brief.text) is not None


def _support(brief: EditorialBrief) -> bool:
    return re.search(r"it[- ]support|tech(?:nical)? support|іт-підтрим|техпідтрим|служб\w* підтрим",
                     brief.text) is not None


def _money_tag(brief: EditorialBrief) -> tuple[str, str]:
    """(figure as drawn, caption) or ("", "")."""
    fig = str(brief.facts.get("money") or "")
    if not fig:
        return "", ""
    if brief.facts.get("money_plus"):
        fig = f"OVER {fig}"                   # the sources' own qualifier ("over $40.5M", "понад")
    elif brief.facts.get("money_approx"):
        fig = f"NEARLY {fig}"
    if re.search(r"ransom|викуп", _head(brief)):
        return fig, "in ransoms"
    lost = re.search(r"виманил|stole|stolen|викрал|lost|збит|defraud", brief.text) is not None
    return fig, ("reported losses" if lost else "reported")


def _exposed_tags(brief: EditorialBrief) -> list[list[tuple[str, float, str]]]:
    """The evidence tags `_comp_exposed` draws (at most three), in order."""
    tags: list[list[tuple[str, float, str]]] = []
    actors = _authorities(brief)
    if actors:
        line = " + ".join(actors)
        tags.append([(line, fit_size(line, 58, 430, "ui_bold"), "ui_bold")])
    fig, cap = _money_tag(brief)
    if fig:
        tags.append([(fig, fit_size(fig, 96, 440), "display"), (cap, 30, "ui")])     # text runs x+86..x+526
    if _ai_calls(brief):
        tags.append([("AI calling platform", 44, "ui_bold")])
    return tags[:3]


def _comp_exposed(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    """Exposure or arrest without a stated seizure: the group's tool of contact
    (a phone taking a call that poses as IT support, when the sources say so)
    under police tape; actors, the reported figure and secondary context on
    evidence tags."""
    background(doc, light=(0.32, 0.12), floor=790)
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#8FA3B8", 0.34), (0.6, "#56677A", 0.10), (1, "#000", 0)], 0.32, 0.40,
                                      0.55))
    px, py, pw, ph = 330, 110, 380, 730
    if not _contact(brief):
        _case_file(doc, 250, 150, 560, 640, _arrested(brief))
        px, pw = 250, 560
    else:
        _phone(doc, brief, px, py, pw, ph)
    word = _action(brief)
    _tape(doc, -40, 300, 1640, 520, word=word, phase=0.2)
    _tape(doc, -40, 770, 1000, 610, hgt=60, word=word, phase=0.6)
    tags = _exposed_tags(brief)
    y = 110.0
    for i, t in enumerate(tags[:3]):
        h_ = 190.0 if len(t) > 1 else 110.0
        _tag(doc, 900 + (i % 2) * 40, y, 560, h_, (px + pw, py + 200 + i * 160), t, (2.5 if i % 2 else -2.0))
        y += h_ + 40
    doc.focus = Box(180, 60, 1340, 754)
    vignette(doc, 0.5)


def _case_file(doc: Doc, x: float, y: float, w: float, h: float, label: str) -> None:
    """The arrested group as a manila case file, its label the group as the
    headline describes it. No names, photos, documents or seals are drawn."""
    doc.rect(x + 20, y + 36, w, h, "#000", 14, opacity=0.5, extra=f' filter="{doc.blur(22)}"')
    doc.path(f"M{f(x)} {f(y + 40)}V{f(y + 10)}Q{f(x)} {f(y)} {f(x + 10)} {f(y)}H{f(x + w * 0.38)}"
             f"L{f(x + w * 0.44)} {f(y + 40)}Z", fill="#C9A869")
    doc.rect(x, y + 36, w, h - 36, doc.lin([(0, "#E3C88E", 1), (1, "#C7A465", 1)], 0, 0, 0.4, 1), 12)
    doc.rect(x + 36, y + 120, w - 72, 4, "#9C7E45", 2, opacity=0.6)
    size = fit_size(label, 64, w - 90, "display")
    doc.text(label, x + w / 2, y + h * 0.56, size, "#2A2116", "display", anchor="middle")


def _phone(doc: Doc, brief: EditorialBrief, px: float, py: float, pw: float, ph: float) -> None:
    """The group's tool of contact: a phone taking a call (IT support when stated)."""
    doc.rect(px + 18, py + 34, pw, ph, "#000", 54, opacity=0.5, extra=f' filter="{doc.blur(22)}"')
    doc.rect(px, py, pw, ph, doc.lin([(0, "#2B313A", 1), (1, "#12161C", 1)], 0, 0, 1, 1), 54, stroke="#4A5260", sw=3)
    doc.rect(px + 18, py + 18, pw - 36, ph - 36, doc.lin([(0, "#1D2A3A", 1), (1, "#0D131C", 1)]), 40)
    doc.rect(px + pw / 2 - 52, py + 34, 104, 20, "#0A0D12", 10)
    cx = px + pw / 2
    support = _support(brief)
    doc.text("incoming call", cx, py + 140, 24, "#9FB0C4", "ui", anchor="middle")
    doc.circle(cx, py + 260, 76, "#2E4057")
    doc.circle(cx, py + 238, 28, "#9FB0C4")
    doc.path(f"M{f(cx - 48)} {f(py + 308)}Q{f(cx)} {f(py + 252)} {f(cx + 48)} {f(py + 308)}", fill="#9FB0C4")
    if support:
        doc.text("IT SUPPORT", cx, py + 410, 46, "#FFFFFF", "display", anchor="middle")
    doc.circle(cx - 90, py + ph - 120, 44, "#D64545")
    doc.circle(cx + 90, py + ph - 120, 44, "#3BA55C")


# ---------------------------------------------------------------- compositions

ALTERNATIVES: dict[str, Callable[[Doc, EditorialBrief, random.Random], None]] = {"a": _comp_rack, "b": _comp_bag,
                                                                                  "exposed": _comp_exposed}


@scene("police_takedown")
def police_takedown(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    # Seizures and takedowns of named infrastructure: the taped-off rack.
    # Exposure or arrest with no seizure stated: the group's operation, exposed.
    if _seizure(brief):
        _comp_rack(doc, brief, rng)
    else:
        _comp_exposed(doc, brief, rng)


def alt_for(brief: EditorialBrief) -> tuple[str, str]:
    """Describes the composition exactly as drawn: the seized rack with its
    tags, or the arrested group (case file, or the phone when calls are the
    stated channel) with the acting authorities and the reported figure."""
    word = _action(brief).lower()
    if _seizure(brief):
        tags = list(_seized_names(brief))
        fig, what = _headline_count(brief)
        if fig:
            tags.append(f"'{fig} {what}'")
        return (f"Illustration: a dark server rack under police tape marked '{word}', with evidence tags: "
                f"{'; '.join(tags)}.",
                f"Ілюстрація: темна серверна стійка під поліцейською стрічкою з написом «{word}», бирки: "
                f"{'; '.join(tags)}.")
    parts_en: list[str] = []
    parts_ua: list[str] = []
    actors = _authorities(brief)
    if actors:
        parts_en.append(" and ".join(actors))
        parts_ua.append(" і ".join(actors))
    fig, cap = _money_tag(brief)
    if fig:
        parts_en.append(f"'{fig} {cap}'")
        parts_ua.append(f"«{fig} {cap}»")
    if _ai_calls(brief):
        parts_en.append("'AI calling platform'")
        parts_ua.append("«AI calling platform»")
    if _contact(brief):
        call_en = "an incoming call from 'IT support'" if _support(brief) else "an incoming call"
        call_ua = "вхідним дзвінком «IT support»" if _support(brief) else "вхідним дзвінком"
        en = f"Illustration: a phone showing {call_en}, under police tape marked '{word}'"
        ua = f"Ілюстрація: телефон із {call_ua} під поліцейською стрічкою з написом «{word}»"
    else:
        group = _arrested(brief)
        en = f"Illustration: a case file labelled '{group}' under police tape marked '{word}'"
        ua = f"Ілюстрація: тека справи з написом «{group}» під поліцейською стрічкою з написом «{word}»"
    if parts_en:
        en += ", with evidence tags: " + "; ".join(parts_en)
        ua += ", бирки з написами: " + "; ".join(parts_ua)
    return en + ".", ua + "."
