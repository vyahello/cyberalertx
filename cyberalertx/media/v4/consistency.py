"""Alt text must describe the image that was drawn (V4.1.2).

`check(alt, labels)` compares each locale's alt text with the strings the
scene actually set as type (`Doc.labels`). It reports, per locale:

* a **number** in the alt text that no label shows ("the number of people
  affected" with no figure drawn, "178 websites" without "178");
* a **quoted label** ('exposed', «Wellington IT») in Latin script that is not
  drawn. Ukrainian quotes in Cyrillic translate a drawn English label and are
  not compared;
* a **name** (a capitalised Latin-script word other than the leading
  "Illustration") that no label shows: a sender, organisation or product the
  image does not name;
* a **count claim** ("number of", "figures", "кількість", "цифр") when no
  label contains a digit.

Subjects that are shown rather than named (the photographed machine of a
library image) are allowed through `subjects`; a library photo's credit line
("Photo: author, licence") is not compared.

The check is pure and cheap; tests run it over every scene and the full
eligible inventory, and `ops/media/alt_audit.py` runs it on production data.
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping

from .brief import GENERIC_TERMS

_QUOTED = re.compile(r"'([^']+)'|«([^»]+)»|\"([^\"]+)\"")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_NAME = re.compile(r"(?<![\w'])[A-Z][A-Za-z0-9]*(?:[.+-][A-Za-z0-9]+)*")
_COUNT_CLAIM = re.compile(r"\bnumbers? of\b|\bcounts?\b|\bfigures?\b|\btotal\b|кількіст|цифр", re.I)
#: Capitalised words that describe, not name ("Illustration: ...", "a USB
#: flash drive", "a DIN rail"). The O54 generic terms can never be names.
_PLAIN = {"Illustration", "Ілюстрація", "Photograph", "Фотографія", "DIN"} | set(GENERIC_TERMS)
#: The photo credit of a library image names its author and licence, not
#: something in the picture.
_CREDIT = re.compile(r"\s(?:Photo|Фото):.*$", re.S)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _num(s: str) -> str:
    """'40,5' == '40.5'; '1,200' == '1200' (thousands); '$40.5M' -> '40.5'."""
    if re.fullmatch(r"\d{1,3}(?:[,. ]\d{3})+", s):
        return re.sub(r"[,. ]", "", s)
    return s.replace(",", ".")


def check(alt: Mapping[str, str], labels: Iterable[str], subjects: Iterable[str] = ()) -> list[str]:
    drawn = [str(x) for x in labels if str(x).strip()]
    # Lines are compared one by one and as the sequence they are drawn in, so
    # a figure and its caption on two lines ("40" / "Irish credit unions")
    # match the quoted "40 Irish credit unions".
    visible = " | ".join(_norm(x) for x in drawn) + " || " + _norm(" ".join(drawn))
    numbers = {_num(n) for x in drawn for n in _NUMBER.findall(x)}
    allowed = {_norm(x) for x in subjects} | {w.lower() for x in subjects for w in re.findall(r"[\w-]+", x)}
    problems: list[str] = []
    for loc, text in alt.items():
        body = _CREDIT.sub("", text or "")
        for n in _NUMBER.findall(body):
            if _num(n) not in numbers:
                problems.append(f"{loc}: number '{n}' is not drawn")
        for q in _QUOTED.finditer(body):
            label = next(g for g in q.groups() if g is not None)
            if label.isascii() and not re.search(r"(?<!\w)" + re.escape(_norm(label)) + r"(?!\w)", visible) \
                    and _norm(label) not in allowed:
                problems.append(f"{loc}: quoted label '{label}' is not drawn")
        for m in _NAME.finditer(body):
            name = m.group(0)
            if name in _PLAIN or (loc == "en" and m.start() == 0):
                continue
            if not re.search(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", visible) \
                    and name.lower() not in allowed:
                problems.append(f"{loc}: name '{name}' is not drawn")
        if _COUNT_CLAIM.search(body) and not numbers:
            problems.append(f"{loc}: claims a figure but no number is drawn")
    return sorted(set(problems))


def check_brief(brief: object, labels: Iterable[str]) -> list[str]:
    """`check` for a V4 brief: its alt text against the labels it drew, with
    a library photograph's subject counted as shown."""
    from . import library
    from .brief import EditorialBrief, alt_text
    assert isinstance(brief, EditorialBrief)
    subjects: list[str] = []
    entry = library.get(brief.library_id) if brief.library_id else None
    if entry is not None:
        subjects += [entry.subject, entry.subject_ua]
    return check(alt_text(brief), labels, subjects)


def story_specific(brief: object, labels: Iterable[str]) -> bool:
    """True when the drawing names something of this story: an entity, a
    figure or an identifier from the sources. A picture with no such label
    (unlabelled gears, a bare mast) cannot be recognised as this story at
    feed size, so the hybrid policy leaves it to V3."""
    from .brief import EditorialBrief
    assert isinstance(brief, EditorialBrief)
    drawn = " | ".join(_norm(x) for x in labels)
    # an acting authority the headline names (police, FBI, Europol) is sourced and specific
    from .scenes.police_takedown import _ACTORS, _PLACES
    names = [n for _, n in _ACTORS] + ["Police"] + sorted(_PLACES)
    if any(re.search(r"(?<!\w)" + re.escape(n.lower()) + r"(?!\w)", drawn) for n in names):
        return True
    for e in brief.entities:
        if len(e) >= 2 and re.search(r"(?<!\w)" + re.escape(e.lower()) + r"(?!\w)", drawn):
            return True
    for k, v in brief.facts.items():
        if k.endswith(("_plus", "_approx", "_noun")):
            continue
        for item in (v if isinstance(v, (list, tuple)) else [v]):
            digits = re.sub(r"[^\d]", "", str(item))
            if digits and digits in re.sub(r"[^\d|]", "", drawn):
                return True
    return False
