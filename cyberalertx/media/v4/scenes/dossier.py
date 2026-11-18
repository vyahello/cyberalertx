"""Fallback when no catalogue scene is supported strongly enough: an editorial
cover built only from the story's own identifiers.

It does not pretend to show a mechanism. Instead it sets the story's subject
large, the way a magazine opens a section: the name the headline gives (or a
domain the sources name, or a topic word taken from the headline itself), the
category as a kicker, the evidence status when one is established, and a
figure from `brief.facts` when there is one. A large category emblem in the
background is visibly a symbol, not a depiction. Colour follows the
category, and one of three layouts is chosen per story, so a run of fallback
stories does not look like one repeated card."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, icon, vignette
from . import scene
from ._editorial import ascii_ids, fit_size, headline_main, product_groups


@dataclass(frozen=True)
class _Look:
    word: str          # kicker
    icon: str          # kit icon used as the background emblem
    field0: str        # background, light end
    field1: str        # background, dark end
    accent: str


_LOOKS = {
    "malware": _Look("MALWARE", "terminal", "#123236", "#081518", "#5EEAD4"),
    "botnet": _Look("BOTNET", "globe", "#1F1D3D", "#0C0B1C", "#A5B4FC"),
    "phishing": _Look("PHISHING", "mail", "#132B4A", "#08121F", "#60A5FA"),
    "breach": _Look("BREACH", "unlock", "#35161A", "#16080A", "#FF7A6B"),
    "exploit": _Look("EXPLOITATION", "shieldx", "#33240E", "#140E05", "#F5A524"),
    "vulnerability": _Look("VULNERABILITY", "warn", "#33240E", "#140E05", "#F5A524"),
    "zero-day": _Look("ZERO-DAY", "warn", "#3A1A0C", "#160904", "#FF8A3D"),
    "scam": _Look("FRAUD", "user", "#33142F", "#140712", "#F472B6"),
    "ransomware": _Look("RANSOMWARE", "lock", "#3A0F10", "#150505", "#FF4D4D"),
    "other": _Look("REPORT", "file", "#1E242C", "#0B0E12", "#E9D29A"),
}
_STATUS = {"confirmed": "CONFIRMED", "exploited": "EXPLOITED", "compromise": "COMPROMISE CONFIRMED",
           "attacks_observed": "ATTACKS OBSERVED", "suspected": "SUSPECTED"}
# Headline words that are adjectives or periods, not the story's subject.
_NOT_SUBJECT = {"German", "Russian", "Ukrainian", "Chinese", "Iranian", "North", "Korean", "American", "European",
                "IT", "Q1", "Q2", "Q3", "Q4", "Non-mobile", "CAs", "Police", "Hackers", "Hacker", "Fake", "New"}
# Topic words read from the headline when it names nothing in Latin script.
# Ordered: the first match wins. Each is a plain description of the
# headline's subject, never a claim about it.
_TOPICS: tuple[tuple[str, str], ...] = (
    (r"\bebpf\b", "eBPF"), (r"\bddos\b", "DDoS"), (r"\bq([1-4])\s+(20\d\d)\b", "Q{0} {1}"),
    (r"дрон|drone", "DRONES"), (r"камер|camera", "CAMERAS"), (r"wiper|вайпер", "WIPER"),
    (r"rootkit|руткіт", "ROOTKITS"), (r"радіолокац|radar", "RADAR"), (r"\bcas\b|certificate|сертифікат",
                                                                       "CERTIFICATES"),
    (r"оприлюдн|leak|злив", "LEAK"), (r"застосун|\bapp\b", "APP"), (r"\bші\b|штучн\w* інтел|\bai\b", "AI"),
    (r"сайт|website", "WEBSITE"), (r"кібератак|cyberattack", "CYBERATTACK"),
    (r"кібербезпек|cybersecurity", "CYBERSECURITY"), (r"шахрай|fraud|scam", "FRAUD"),
    (r"хакер|hacker|злам", "HACKERS"),
)


def _subject(brief: EditorialBrief) -> tuple[str, list[str]]:
    """(lead identifier, secondary identifiers), all from the story itself."""
    names = [g for g in product_groups(brief) if g not in _NOT_SUBJECT and g.split()[0] not in _NOT_SUBJECT]
    if names:
        return names[0], names[1:3]
    ids = ascii_ids(brief.text, 2)
    if ids:
        return ids[0], ids[1:]
    # Headline first: the main clause, then the whole headline. A word that
    # appears only in the article body never becomes the subject (an AI tool
    # mentioned in passing must not turn a police story into an "AI" cover).
    headline = (brief.headline or "").lower()
    main = headline_main(brief.text) if not headline else headline_main_of(headline)
    for scope in (main, headline or main):
        for pat, word in _TOPICS:
            m = re.search(pat, scope)
            if m:
                return word.format(*m.groups()), []
    return "", []


def headline_main_of(headline: str) -> str:
    from ..brief import main_clause
    return main_clause(headline).lower()


def _figure(brief: EditorialBrief) -> tuple[str, str]:
    for key, label in (("accounts", "accounts"), ("people", "people"), ("records", "records"), ("money", ""),
                       ("videos", "videos")):
        v = brief.facts.get(key)
        if v:
            pre = "~" if brief.facts.get(key + "_approx") else ""
            post = "+" if brief.facts.get(key + "_plus") else ""
            return f"{pre}{v}{post}", label
    return "", ""


def _emblem(doc: Doc, name: str, cx: float, cy: float, size: float, color: str, sw: float,
            opacity: float) -> None:
    """The category symbol, very large; a second, offset impression gives it
    the slight misregistration of a print run."""
    icon(doc, name, cx + size * 0.012, cy + size * 0.012, size, "#000", sw, opacity * 0.9)
    icon(doc, name, cx, cy, size, color, sw, opacity)


def _field(doc: Doc, look: _Look, light: tuple[float, float]) -> None:
    doc.rect(0, 0, 1600, 900, doc.lin([(0, look.field0, 1), (1, look.field1, 1)], 0, 0, 0.35, 1))
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#FFFFFF", 0.10), (1, "#FFFFFF", 0)], light[0], light[1], 0.7))


def _kicker(doc: Doc, x: float, y: float, look: _Look, color: str, size: float = 30) -> float:
    doc.rect(x, y - size * 0.74, 14, size * 0.74, look.accent)
    return x + 34 + doc.text(look.word, x + 34, y, size, color, "ui_bold", tracking=size * 0.24)


def _tb(s: str, x: float, base: float, size: float, font: str, anchor: str = "start") -> Box:
    """Bounding box of a text run (cap height up, a descender down)."""
    w = T.measure(T.supported(s, font), size, font)
    x0 = x - w if anchor == "end" else x - w / 2 if anchor == "middle" else x
    cap = T.cap_height(size, font)
    return Box(x0, base - cap, w, cap * 1.3)


def _focus_on(doc: Doc, boxes: list[Box], margin: float = 50, min_w: float = 900) -> None:
    """A 16:9 feed crop that contains every box in `boxes` (lead, figure,
    status) with a margin; the kit centres it and clamps it to the frame."""
    x0 = min(b.x for b in boxes) - margin
    y0 = min(b.y for b in boxes) - margin
    x1 = max(b.r for b in boxes) + margin
    y1 = max(b.b for b in boxes) + margin
    w = max(min_w, x1 - x0, (y1 - y0) * 16 / 9)
    h = w * 9 / 16
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    doc.focus = Box(cx - w / 2, cy - h / 2, w, h)


def _status(doc: Doc, x: float, y: float, label: str, color: str, size: float = 24, anchor: str = "start") -> Box:
    if not label:
        return Box(x, y, 0, 0)
    w = T.measure(label, size, "ui_bold", tracking=size * 0.16) + size * 1.4
    if anchor == "end":
        x -= w
    doc.rect(x, y - size * 1.25, w, size * 1.9, "none", 4, stroke=color, sw=2.5)
    doc.text(label, x + size * 0.7, y - size * 0.3 + T.cap_height(size, "ui_bold") / 2, size, color, "ui_bold",
             tracking=size * 0.16)
    return Box(x, y - size * 1.25, w, size * 1.9)


# ---------------------------------------------------------------- layouts

def _poster(doc: Doc, look: _Look, lead: str, rest: list[str], status: str, fig: tuple[str, str],
            rng: random.Random) -> None:
    """Lead set huge along the bottom left; emblem cropped by the top right."""
    _field(doc, look, (0.2, 0.15))
    _emblem(doc, look.icon, 1250, 290, 980, look.accent, 64, 0.20)
    kx = _kicker(doc, 110, 200, look, "#F3F1EC")
    size = fit_size(lead, 330, 1340)
    base = 600 if not rest and not fig[0] else 560
    doc.text(lead, 100, base, size, "#FFFFFF", "display")
    keep = [_tb(lead, 100, base, size, "display"), Box(110, 170, kx - 110, 34)]
    y = base + 90
    if rest:
        doc.text(T.fit("  /  ".join(rest), 50, 1100, "ui"), 112, y, 50, look.accent, "ui")
    if fig[0]:
        fy = y if rest else base + 110
        doc.text(fig[0], 1500, fy, 110, look.accent, "display", anchor="end")
        keep.append(_tb(fig[0], 1500, fy, 110, "display", "end"))
        if fig[1]:
            doc.text(fig[1], 1500, fy + 54, 36, "#D8DDE4", "ui", anchor="end")
            keep.append(_tb(fig[1], 1500, fy + 54, 36, "ui", "end"))
    st = _status(doc, 112, 300, status, look.accent)
    if status:
        keep.append(st)
    doc.line((110, 790), (1490, 790), "#FFFFFF", 1.5, 0.25)
    _focus_on(doc, keep)


def _band(doc: Doc, look: _Look, lead: str, rest: list[str], status: str, fig: tuple[str, str],
          rng: random.Random) -> None:
    """A paper label band across a dark field, the emblem showing above and
    below it."""
    _field(doc, look, (0.7, 0.1))
    _emblem(doc, look.icon, 1200, 450, 900, look.accent, 70, 0.28)
    ang = rng.uniform(-3.0, -1.5)
    paper, ink = "#F4F0E8", "#14161B"
    with doc.g(transform=f"rotate({ang:.2f} 800 450)"):
        doc.rect(-40, 318, 1680, 300, "#000", opacity=0.45, extra=f' filter="{doc.blur(18)}"')
        doc.rect(-40, 300, 1680, 300, paper)
        doc.rect(-40, 300, 1680, 10, look.accent)
        size = fit_size(lead, 300, 1340 if not fig[0] else 960)
        cap = T.cap_height(size, "display")
        doc.text(lead, 110, 450 + cap / 2, size, ink, "display")
        keep = [_tb(lead, 110, 450 + cap / 2, size, "display")]
        if fig[0]:
            doc.text(fig[0], 1500, 470, 120, ink, "display", anchor="end")
            keep.append(_tb(fig[0], 1500, 470, 120, "display", "end"))
            if fig[1]:
                doc.text(fig[1], 1500, 530, 36, "#5A5D66", "ui", anchor="end")
                keep.append(_tb(fig[1], 1500, 530, 36, "ui", "end"))
    kx = _kicker(doc, 120, 240, look, "#F3F1EC", 32)
    keep.append(Box(120, 208, kx - 120, 36))
    if rest:
        doc.text(T.fit("  /  ".join(rest), 48, 1100, "ui"), 120, 730, 48, look.accent, "ui")
    st = _status(doc, 1490, 240, status, look.accent, anchor="end")
    if status:
        keep.append(st)
    # the band is rotated by up to 3 degrees: a wider margin covers the tilt
    _focus_on(doc, keep, margin=70)


def _split(doc: Doc, look: _Look, lead: str, rest: list[str], status: str, fig: tuple[str, str],
           rng: random.Random) -> None:
    """A solid accent panel holding the emblem; the lead identifier set beside it."""
    _field(doc, look, (0.75, 0.2))
    pw = 560
    doc.rect(0, 0, pw, 900, look.accent)
    doc.rect(0, 0, pw, 900, doc.lin([(0, "#FFFFFF", 0.18), (1, "#000", 0.18)], 0, 0, 0.4, 1))
    _emblem(doc, look.icon, pw / 2, 450, 500, look.field1, 40, 0.92)
    x = pw + 90
    kx = _kicker(doc, x, 210, look, "#F3F1EC")
    size = fit_size(lead, 300, 1600 - x - 90)
    cap = T.cap_height(size, "display")
    base = 450 + cap / 2
    doc.text(lead, x - 6, base, size, "#FFFFFF", "display")
    keep = [_tb(lead, x - 6, base, size, "display"), Box(pw * 0.5 - 60, 390, 120, 120), Box(x, 180, kx - x, 34)]
    y = base + 96
    if rest:
        doc.text(T.fit("  /  ".join(rest), 46, 1600 - x - 90, "ui"), x, y, 46, look.accent, "ui")
        y += 90
    if fig[0]:
        w = doc.text(fig[0], x, y + 30, 100, look.accent, "display")
        keep.append(_tb(fig[0], x, y + 30, 100, "display"))
        if fig[1]:
            doc.text(fig[1], x + w + 20, y + 30, 36, "#D8DDE4", "ui")
            keep.append(_tb(fig[1], x + w + 20, y + 30, 36, "ui"))
    st = _status(doc, x, 800, status, look.accent)
    if status:
        keep.append(st)
    _focus_on(doc, keep)


@scene("dossier")
def dossier(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    look = _LOOKS.get(brief.category, _LOOKS["other"])
    lead, rest = _subject(brief)
    if not lead:
        lead = look.word.capitalize()
    status = _STATUS.get(brief.status, "")
    fig = _figure(brief)
    layout = rng.choice((_poster, _band, _split))
    layout(doc, look, lead, rest, status, fig, rng)
    vignette(doc, 0.45)

