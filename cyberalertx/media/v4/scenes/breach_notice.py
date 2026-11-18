"""Breach notifications as one object. Two compositions, chosen by what the
sources say:

* notification: a large airmail envelope, the affected count printed across
  its face (only when `brief.facts` states it, with the sources' qualifier),
  personal record cards rising out of it;
* provider: the data sat with a cloud provider, so the subject is a dark
  cloud with a tear in it, record cards falling out.

Record cards are silhouettes: a portrait placeholder and redacted bars. No
field names (the sources rarely list which fields), no letter text, no legal
wording, no card numbers. A supplier is named only when the sources call that
entity the supplier; a generic token ("IT provider") is never a name.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

from .. import type as T
from ..brief import EditorialBrief, mentions
from ..kit import Box, Doc, f, icon
from . import scene
from ._editorial import fit_size, product_groups

_PAPER = "#FFFDF8"


def count_label(brief: EditorialBrief) -> tuple[str, str]:
    """(figure, noun) for the affected count, or ("", "")."""
    fx = brief.facts
    for key, noun in (("people", "people"), ("records", "records"), ("accounts", "accounts")):
        v = fx.get(key)
        if not v:
            continue
        v = str(v)
        if "." in v and not re.search(r"[0-9][MKB]$", v):   # "37.6" only makes sense with its unit
            m = re.search(re.escape(v) + r"\d*\s*(m\b|million|млн)", brief.text or "")
            if not m:
                continue
            v += "M"
        if fx.get(key + "_approx"):
            v = "~" + v
        elif fx.get(key + "_plus"):
            v += "+"
        return v, noun
    if brief.facts.get("orgs"):
        return str(brief.facts["orgs"]), str(brief.facts.get("orgs_noun") or "organizations")
    return "", ""


def _kind(text: str) -> str:
    if re.search(r"payment card|credit card|card details|платіжн\w* карт", text):
        return "payment"
    if re.search(r"\bdrivers?\b|водії", text):
        return "driver"
    if re.search(r"employee|staff|співробітник|працівник", text):
        return "employee"
    if re.search(r"email address|newsletter|subscriber", text):
        return "email"
    return "customer"


# ---------------------------------------------------------------- record cards (drawn at 0,0)

def _redact(doc: Doc, x: float, y: float, w: float, h: float = 14) -> None:
    doc.rect(x, y, w, h, "#24252B", 2)


def _portrait(doc: Doc, x: float, y: float, w: float, h: float, bg: str) -> None:
    doc.rect(x, y, w, h, bg, 4)
    with doc.g(clip=doc.clip_rect(x, y, w, h, 4)):
        doc.circle(x + w / 2, y + h * 0.4, w * 0.22, "#9AA0AD")
        doc.add(f'<ellipse cx="{f(x + w / 2)}" cy="{f(y + h * 1.02)}" rx="{f(w * 0.45)}" ry="{f(h * 0.38)}" '
                f'fill="#9AA0AD"/>')


def _wheel(doc: Doc, cx: float, cy: float, r: float, color: str) -> None:
    doc.circle(cx, cy, r, "none", color, r * 0.16)
    doc.circle(cx, cy, r * 0.22, color)
    for a in ((-r * 0.9, r * 0.1), (r * 0.9, r * 0.1), (0, r * 0.92)):
        doc.line((cx, cy), (cx + a[0], cy + a[1]), color, r * 0.16)


def _record_card(doc: Doc, kind: str, w: float, h: float, rng: random.Random, front: bool,
                 accent: str, danger: str) -> None:
    doc.rect(0, 0, w, h, _PAPER, 10, stroke="#CFC6B5", sw=1.2)
    band = "#1F2430" if kind == "driver" else "#E4DCCB"
    doc.rect(0, 0, w, 44, band, 10)
    doc.rect(0, 30, w, 14, band)
    if kind == "driver":
        _wheel(doc, 26, 22, 12, "#FFFFFF")
    else:
        icon(doc, "mail" if kind == "email" else "user", 26, 22, 22, "#17181C", 2)
    _redact(doc, 52, 16, w * 0.32, 12)
    _portrait(doc, 20, 62, 92, 112, "#E3DED3")
    for i in range(4):
        _redact(doc, 132, 74 + i * 28, rng.uniform(w * 0.3, w - 170), 13)
    if front:
        doc.rect(0, 0, w, h, "none", 10, stroke=danger, sw=3)


def _badge(doc: Doc, w: float, h: float, rng: random.Random, front: bool, accent: str, danger: str) -> None:
    """Employee ID badge, portrait orientation, on a lanyard clip."""
    doc.rect(0, 0, w, h, _PAPER, 12, stroke="#CFC6B5", sw=1.2)
    doc.rect(w / 2 - 26, 16, 52, 10, "#D8D1C2", 5)                # slot
    doc.rect(0, 44, w, 40, accent, 0)
    doc.text("EMPLOYEE", w / 2, 71, 18, "#FFFFFF", "ui_bold", anchor="middle", tracking=3)
    _portrait(doc, w / 2 - 56, 104, 112, 132, "#E3DED3")
    _redact(doc, 24, 256, w - 48, 16)
    _redact(doc, 46, 284, w - 92, 11)
    for i in range(22):                                           # barcode
        bw = rng.choice((2, 3, 5))
        doc.rect(26 + i * ((w - 52) / 22), h - 50, bw, 30, "#24252B")
    if front:
        doc.rect(0, 0, w, h, "none", 12, stroke=danger, sw=3)
    # clip and strap
    doc.rect(w / 2 - 14, -34, 28, 40, doc.lin([(0, "#9AA1AB", 1), (0.5, "#F2F4F6", 1), (1, "#8A919B", 1)], 0, 0, 1, 0),
             5)


def _payment(doc: Doc, w: float, h: float, rng: random.Random, front: bool, danger: str) -> None:
    base = rng.choice(("#2B3448", "#3A2E4F", "#24453F", "#4A3426"))
    doc.rect(0, 0, w, h, doc.lin([(0, base, 1), (1, "#111317", 1)], 0, 0, 1, 1), 14)
    doc.rect(28, 64, 50, 38, doc.lin([(0, "#E9D49A", 1), (1, "#A88A45", 1)], 0, 0, 1, 1), 6)
    doc.path("M28 83H78M45 64V102M61 64V102", stroke="#8A7038", sw=1.2)
    for k in range(4):
        doc.rect(28 + k * 74, 132, 60, 16, "#FFFFFF", 4, opacity=0.6)
    doc.rect(28, 172, 70, 10, "#FFFFFF", 3, opacity=0.4)
    doc.circle(w - 64, h - 40, 16, "#FFFFFF", opacity=0.25)
    doc.circle(w - 44, h - 40, 16, "#FFFFFF", opacity=0.18)
    if front:
        doc.rect(-4, -4, w + 8, h + 8, "none", 16, stroke=danger, sw=3)


# ---------------------------------------------------------------- objects

def _card_size(kind: str) -> tuple[float, float]:
    return {"employee": (250.0, 360.0), "payment": (360.0, 226.0)}.get(kind, (420.0, 200.0))


def _card(doc: Doc, kind: str, x: float, y: float, rot: float, rng: random.Random, front: bool,
          scale: float = 1.0) -> None:
    """One record card, its top-left at (x, y), turned by `rot` degrees."""
    p = doc.pal
    cw, ch = _card_size(kind)
    doc.add(f'<g transform="translate({f(x)} {f(y)}) scale({scale}) rotate({f(rot)} {f(cw / 2)} {f(ch / 2)})">')
    doc.rect(6, 16, cw, ch, "#000", 10, opacity=0.2, extra=f' filter="{doc.blur(10)}"')
    if kind == "employee":
        _badge(doc, cw, ch, rng, front, p.accent, p.danger)
    elif kind == "payment":
        _payment(doc, cw, ch, rng, front, p.danger)
    else:
        _record_card(doc, kind, cw, ch, rng, front, p.accent, p.danger)
    doc.add("</g>")


def _airmail(doc: Doc, x: float, y: float, w: float, h: float, red: str, blue: str) -> None:
    """The airmail border: alternating diagonal red and blue dashes."""
    band = 22.0
    d_red, d_blue = "", ""
    step = 34.0
    k = 0
    t = -h
    while t < w + h:
        seg = f"M{f(x + t)} {f(y)}l{f(-band)} {f(band)}h{f(step / 2)}l{f(band)} {f(-band)}Z"
        segb = f"M{f(x + t)} {f(y + h - band)}l{f(-band)} {f(band)}h{f(step / 2)}l{f(band)} {f(-band)}Z"
        if k % 2 == 0:
            d_red += seg + segb
        else:
            d_blue += seg + segb
        t += step
        k += 1
    with doc.g(clip=doc.clip_rect(x, y, w, h, 8)):
        doc.path(d_red, fill=red)
        doc.path(d_blue, fill=blue)


def _stamp(doc: Doc, cx: float, cy: float, top: str, name: str) -> None:
    """A rubber stamp on the envelope's face: how the data got out (the
    breached supplier), with the supplier's name when the sources give it."""
    p = doc.pal
    s1, s2 = 30.0, 46.0
    w1 = T.measure(T.supported(top, "ui_bold"), s1, "ui_bold", tracking=s1 * 0.14)
    w2 = T.measure(T.supported(name, "ui_bold"), s2, "ui_bold") if name else 0.0
    w = max(w1, w2) + 56
    h = 120.0 if name else 76.0
    with doc.g(transform=f"rotate(-7 {f(cx)} {f(cy)})"):
        doc.rect(cx - w / 2, cy - h / 2, w, h, "#FBF7EE", 8, stroke=p.danger, sw=5, opacity=0.96)
        ty = cy - h / 2 + 22 + T.cap_height(s1, "ui_bold")
        doc.text(top, cx, ty, s1, p.danger, "ui_bold", anchor="middle", tracking=s1 * 0.14)
        if name:
            doc.text(name, cx, ty + 22 + T.cap_height(s2, "ui_bold"), s2, p.ink, "ui_bold", anchor="middle")


def _envelope(doc: Doc, brief: EditorialBrief, kind: str, figure: str, noun: str, sender: str,
              rng: random.Random, opened: bool, stamp: tuple[str, str] | None = None) -> None:
    p = doc.pal
    ex, ey, ew, eh = 300.0, 330.0, 1000.0, 500.0
    cw, ch = _card_size(kind)
    # back of the envelope and its open flap
    doc.rect(ex + 14, ey + 40, ew, eh, "#000", 12, opacity=0.25, extra=f' filter="{doc.blur(24)}"')
    doc.rect(ex, ey, ew, eh, "#E6DCC6", 10)
    if opened:
        doc.poly([(ex, ey + 6), (ex + ew / 2, ey - 250), (ex + ew, ey + 6)], "#EFE7D6", stroke="#D3C6AB", sw=2)
        doc.poly([(ex + 40, ey + 6), (ex + ew / 2, ey - 200), (ex + ew - 40, ey + 6)], "#E2D7BF")
        # the records rising out of it
        n = 4
        for i in range(n):
            front = i == n - 1
            rot = -9 + i * 6 + rng.uniform(-1.2, 1.2)
            cx = ex + ew * (0.3 + i * 0.13)
            cy = ey - ch * 0.42 + abs(i - 1.5) * 18
            _card(doc, kind, cx - cw / 2, cy - ch / 2 + 40, rot, rng, front)
    # front pocket
    doc.path(f"M{f(ex)} {f(ey + 30)}L{f(ex + ew * 0.5)} {f(ey + eh * 0.58)}L{f(ex + ew)} {f(ey + 30)}V{f(ey + eh)}"
             f"H{f(ex)}Z", fill=doc.lin([(0, "#FBF7EE", 1), (1, "#EFE7D6", 1)]), stroke="#D3C6AB", sw=2)
    doc.path(f"M{f(ex)} {f(ey + eh)}L{f(ex + ew * 0.5)} {f(ey + eh * 0.58)}L{f(ex + ew)} {f(ey + eh)}",
             stroke="#D8CCB3", sw=2)
    _airmail(doc, ex, ey + eh - 22, ew, 22, p.danger, p.accent)
    # what the envelope is about: the count, else the company the sources name
    # with a stamp on the left, the label moves right so the two never touch
    tx, room = (ex + ew * 0.66, ew * 0.56) if stamp else (ex + ew / 2, ew - 120)
    if figure:
        size = 200.0
        tw = T.measure(T.supported(figure, "display"), size, "display")
        size = min(size, size * room / tw)
        doc.text(figure, tx, ey + eh * 0.62 + 60, size, p.ink, "display", anchor="middle")
        doc.text(noun, tx, ey + eh - 60, fit_size(noun, 50, room, "ui_bold"), p.danger, "ui_bold", anchor="middle")
    elif sender:
        size = 150.0
        tw = T.measure(T.supported(sender, "display"), size, "display")
        size = min(size, size * (room - 40) / max(tw, 1))
        doc.text(sender, tx, ey + eh * 0.62 + 50, size, p.ink, "display", anchor="middle")
        doc.text(noun, tx, ey + eh - 60, fit_size(noun, 50, room, "ui_bold"), p.danger, "ui_bold", anchor="middle")
    if stamp:
        _stamp(doc, ex + 190, ey + eh * 0.64, *stamp)


def _cloud_path(cx: float, cy: float, s: float) -> str:
    """A cloud silhouette: flat base, three domes."""
    return (f"M{f(cx - 1.0 * s)} {f(cy + 0.32 * s)}"
            f"A{f(0.3 * s)} {f(0.3 * s)} 0 0 1 {f(cx - 0.78 * s)} {f(cy - 0.12 * s)}"
            f"A{f(0.36 * s)} {f(0.36 * s)} 0 0 1 {f(cx - 0.2 * s)} {f(cy - 0.34 * s)}"
            f"A{f(0.44 * s)} {f(0.44 * s)} 0 0 1 {f(cx + 0.58 * s)} {f(cy - 0.1 * s)}"
            f"A{f(0.3 * s)} {f(0.3 * s)} 0 0 1 {f(cx + 1.0 * s)} {f(cy + 0.32 * s)}Z")


def _cloud(doc: Doc, kind: str, sender: str, noun: str, rng: random.Random, leaking: bool) -> None:
    p = doc.pal
    cx, cy, s = 1010.0, 250.0, 430.0
    cw, ch = _card_size(kind)
    k = 0.72
    base = cy + 0.32 * s
    # falling records first: they come out of the tear in the cloud's base
    if leaking:
        spots = [(0.0, 0.0, -8.0, 1.0), (-0.42, 0.55, 16.0, 0.85), (0.4, 0.62, -20.0, 0.8),
                 (-0.02, 1.15, 28.0, 0.6), (0.8, 1.3, 34.0, 0.45)]
        for dx, dy, rot, op in reversed(spots):
            x = cx + dx * s - cw * k / 2
            y = base - 60 + dy * 300
            with doc.g(opacity=op):
                _card(doc, kind, x, y, rot + rng.uniform(-3, 3), rng, dx == 0.0, k)
    d = _cloud_path(cx, cy, s)
    doc.path(d, fill="#000", opacity=0.3, extra=f' transform="translate(10 26)" filter="{doc.blur(20)}"')
    doc.path(d, fill=doc.lin([(0, "#3A4256", 1), (1, "#1B2030", 1)]))
    doc.path(_cloud_path(cx - 0.1 * s, cy - 0.06 * s, s * 0.6), fill="#FFFFFF", opacity=0.05)
    doc.text("cloud provider", cx, cy + 0.16 * s, 56, "#F4EFE6", "ui_bold", anchor="middle")
    if leaking:
        # the tear in the base
        doc.path(f"M{f(cx - 150)} {f(base)}l34 -30l30 18l36 -34l32 26l40 -30l34 24l40 -20l24 46Z", fill=p.danger)
    # the company and what was exposed, as plain type on the desk
    if sender:
        size = 190.0
        tw = T.measure(T.supported(sender, "display"), size, "display")
        size = min(size, size * 560 / max(tw, 1))
        doc.text(sender, 90, 600, size, p.ink, "display")
    doc.text(noun, 96, 690 if sender else 600, 56, p.danger, "ui_bold")


# ---------------------------------------------------------------- scene

_EXPOSED = ("exploited", "confirmed", "attacks_observed", "compromise")
_DENIED = re.compile(r"\bden(?:y|ies|ied)\b|not (?:been )?breached|спростов|запереч")
_ALLEGED = re.compile(r"\balleged|\bclaims?\b|\bclaimed\b|нібито|заяв\w* хакер")


def _disputed(doc: Doc, sender: str, denied: bool) -> None:
    """A breach that is only claimed (or denied): the envelope stays sealed, a
    question mark stands in for the data, and the claim's state is stamped on
    it. Nothing leaves the envelope and no count or data type is shown."""
    p = doc.pal
    ex, ey, ew, eh = 330.0, 250.0, 940.0, 520.0
    doc.rect(ex + 14, ey + 40, ew, eh, "#000", 12, opacity=0.22, extra=f' filter="{doc.blur(24)}"')
    doc.rect(ex, ey, ew, eh, doc.lin([(0, "#FBF7EE", 1), (1, "#EFE7D6", 1)]), 10, stroke="#D3C6AB", sw=2)
    doc.path(f"M{f(ex)} {f(ey + eh)}L{f(ex + ew * 0.5)} {f(ey + eh * 0.5)}L{f(ex + ew)} {f(ey + eh)}",
             stroke="#D8CCB3", sw=2)
    # the closed flap and its intact seal
    doc.poly([(ex, ey), (ex + ew / 2, ey + eh * 0.52), (ex + ew, ey)], "#E9DFCB", stroke="#D3C6AB", sw=2)
    doc.circle(ex + ew / 2, ey + eh * 0.52, 84, "#5B6470")
    doc.text("?", ex + ew / 2, ey + eh * 0.52 + 44, 130, "#F4EFE6", "display", anchor="middle")
    _airmail(doc, ex, ey + eh - 22, ew, 22, p.muted, p.line)
    if sender:
        size = 120.0
        tw = T.measure(T.supported(sender, "display"), size, "display")
        size = min(size, size * (ew * 0.7) / max(tw, 1))
        doc.text(sender, ex + ew / 2, ey + eh * 0.86, size, p.ink, "display", anchor="middle")
    # the claim's state, as a rubber stamp across the corner
    label = "BREACH DENIED" if denied else "ALLEGED"
    size = 44.0
    w = T.measure(T.supported(label, "ui_bold"), size, "ui_bold", tracking=size * 0.12) + size * 1.2
    cx, cy = ex + ew - w / 2 - 20, ey + 90
    with doc.g(transform=f"rotate(-8 {f(cx)} {f(cy)})"):
        doc.rect(cx - w / 2, cy - size, w, size * 2, "#FBF7EE", 6, stroke=p.accent, sw=5)
        doc.text(label, cx, cy + T.cap_height(size, "ui_bold") / 2, size, p.accent, "ui_bold", anchor="middle",
                 tracking=size * 0.12)


_SUPPLIER = re.compile(r"\b(?:(it|software|technology|managed service|third[- ]party|payroll|hr) "
                       r"(?:provider|supplier|vendor|contractor)|supplier|contractor)\b|"
                       r"(?:it-)?постачальник\w*|підрядник\w*")
_HACK = re.compile(r"hack\w*|breach\w*|cyberattack|attack\w*|compromis\w*|ransomware|зламан\w*|атак\w*|витік\w*")
_EVENT = (("hack", "HACK"), ("зламан", "HACK"), ("breach", "BREACH"), ("витік", "BREACH"), ("cyberattack", "ATTACK"),
          ("attack", "ATTACK"), ("атак", "ATTACK"), ("ransomware", "ATTACK"), ("compromis", "COMPROMISE"))
_KIND_EN = {"payment": "payment card", "employee": "employee", "driver": "driver", "email": "subscriber",
            "customer": "customer"}
_KIND_UA = {"payment": "платіжних карток", "employee": "працівників", "driver": "водіїв",
            "email": "підписників", "customer": "клієнтів"}


@dataclass(frozen=True)
class _Plan:
    mode: str              # "denied" | "alleged" | "cloud" | "envelope"
    kind: str
    opened: bool
    figure: str
    noun: str
    sender: str
    stamp: tuple[str, str] | None


def _names(brief: EditorialBrief) -> list[str]:
    """Headline names with adjacent parts joined ("Baker Tilly")."""
    return product_groups(brief)


def _NOTIFIER(name: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)" + re.escape(name.lower()) + r"(?:\s+\w+){0,2},? (?:says|said|notif|is notifying|"
                      r"confirm|disclos|warn|announc|denies|told|повідомил|попередил)")


def _provider(brief: EditorialBrief, head: str) -> tuple[str, str] | None:
    """(stamp caption, supplier name) when the headline says the data was
    taken through a supplier. The name only when the sources call that
    entity the supplier ("supplier Wellington IT", "Acme, an IT provider")."""
    m = _SUPPLIER.search(head)
    if not m:
        return None
    role = "IT PROVIDER" if (m.group(1) or "") == "it" or "it-" in m.group(0) or re.search(
        r"\bit (?:provider|supplier|vendor)|постачальник\w* іт|it-постачальник", head) else "SUPPLIER"
    text = brief.text or ""
    name = ""
    for e in _names(brief):
        if _NOTIFIER(e).search(text):
            continue                  # the sources show it notifying: it is the sender, not the supplier
        el = re.escape(e.lower())
        if re.search(r"(?:provider|supplier|vendor|contractor|постачальник\w*|підрядник\w*)\s+" + el + r"(?!\w)",
                     text) or re.search(r"(?<!\w)" + el + r",? (?:an? |the )?(?:\w+ ){0,2}"
                                        r"(?:provider|supplier|vendor|contractor)", text):
            if T.supported(e, "ui_bold") == e and len(e) <= 24:
                name = e
                break
    # the sources' own word for what happened, the one nearest the supplier
    window = head[max(0, m.start() - 40):m.end() + 40]
    hits = [(abs(h.start() - (m.start() - max(0, m.start() - 40))), h.group(0)) for h in _HACK.finditer(window)]
    word = min(hits)[1] if hits else ""
    event = next((v for k, v in _EVENT if word.startswith(k)), "")
    return (f"{role} {event}" if event else f"VIA {role}"), name


def _plan(brief: EditorialBrief) -> _Plan:
    text = brief.text or ""
    kind = _kind(text)
    exposed = brief.status in _EXPOSED
    head = text[:200]
    stamp = _provider(brief, head)
    supplier = stamp[1] if stamp else ""
    named = [e for e in _names(brief) if mentions(e, head) and e != supplier
             and T.supported(e, "display") == e and len(e) <= 18]
    sender = next((e for e in named if _NOTIFIER(e).search(text) or re.search(
        r"\b" + re.escape(e.lower()) + r"\b,? (employee|customer|newsletter|members)", text)), "") or (
        named[0] if named else "")
    figure, noun = count_label(brief)
    who = {"driver": "drivers", "employee": "employees", "email": "subscribers", "payment": "customers"}.get(
        kind, "customers")
    if noun == "people":
        noun = f"{who} notified" if re.search(r"notif|повідом", text) else f"{who} affected"
    elif noun in ("records", "accounts"):
        noun = f"{who[:-1]} {noun}"
    elif not noun:
        noun = {"payment": "payment card data", "employee": "employee data", "driver": "driver data",
                "email": "email addresses"}.get(kind, "customer data")
    cloud = re.search(r"cloud (provider|service|storage)|хмарн\w* (провайдер|сервіс)", text) is not None
    if _DENIED.search(text[:160]):
        return _Plan("denied", kind, False, "", "", sender, None)
    if _ALLEGED.search(text[:160]) and not exposed:
        return _Plan("alleged", kind, False, "", "", sender, None)
    if cloud and not figure:
        return _Plan("cloud", kind, exposed, "", noun, sender, None)
    if not figure and not sender:
        noun = ""            # a lone data-type caption would read as a label for nobody
    return _Plan("envelope", kind, exposed, figure, noun, sender if not figure else "", stamp)


@scene("breach_notice")
def breach_notice(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    doc.rect(0, 0, 1600, 900, doc.lin([(0, "#EEE8DC", 1), (1, "#D8CDB8", 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#FFFFFF", 0.6), (1, "#FFFFFF", 0)], 0.5, 0.2, 0.6))
    pl = _plan(brief)
    if pl.mode in ("denied", "alleged"):
        _disputed(doc, pl.sender, pl.mode == "denied")
        doc.focus = Box(240, 140, 1120, 630)
    elif pl.mode == "cloud":
        _cloud(doc, pl.kind, pl.sender, pl.noun, rng, pl.opened)
        doc.focus = Box(60, 30, 1480, 833)
    else:
        _envelope(doc, brief, pl.kind, pl.figure, pl.noun, pl.sender, rng, pl.opened, pl.stamp)
        doc.focus = Box(160, 110, 1280, 720)


def alt_for(brief: EditorialBrief) -> tuple[str, str]:
    """Describes exactly what `breach_notice` draws for this brief: the same
    plan decides both."""
    pl = _plan(brief)
    if pl.mode in ("denied", "alleged"):
        st_en, st_ua = ("breach denied", "витік заперечено") if pl.mode == "denied" else ("alleged", "нібито")
        who_en = f" bearing the name {pl.sender}," if pl.sender else ""
        who_ua = f" з назвою {pl.sender}" if pl.sender else ""
        return (f"Illustration: a sealed envelope{who_en} with a question mark, stamped '{st_en}'.",
                f"Ілюстрація: запечатаний конверт{who_ua} зі знаком питання і штампом «{st_ua}».")
    k_en, k_ua = _KIND_EN[pl.kind], _KIND_UA[pl.kind]
    if pl.mode == "cloud":
        en = "Illustration: a dark cloud labelled 'cloud provider'"
        ua = "Ілюстрація: темна хмара з написом «cloud provider»"
        if pl.opened:
            en += f", {k_en} record cards falling from a tear in it"
            ua += f", з розриву в ній випадають картки записів {k_ua}"
        lab = " ".join(x for x in (pl.sender, pl.noun) if x)
        return (f"{en}; beside it: '{lab}'.", f"{ua}; поруч напис «{lab}».")
    if pl.opened:
        en = f"Illustration: an opened envelope with {k_en} record cards rising out of it"
        ua = f"Ілюстрація: відкритий конверт, з якого виходять картки записів {k_ua}"
    else:
        en, ua = "Illustration: a sealed envelope", "Ілюстрація: запечатаний конверт"
    if pl.figure:
        en += f", marked '{pl.figure} {pl.noun}'"
        ua += f" з написом «{pl.figure} {pl.noun}»"
    elif pl.sender:
        en += f", addressed from {pl.sender}, '{pl.noun}'"
        ua += f" від {pl.sender}, «{pl.noun}»"
    if pl.stamp:
        top, name = pl.stamp
        en += f", and a stamp reading '{top}'" + (f" with the supplier's name, {name}" if name else "")
        ua += f" і штамп «{top}»" + (f" з назвою постачальника {name}" if name else "")
    return en + ".", ua + "."
