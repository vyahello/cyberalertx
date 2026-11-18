"""Supercomputer stories.

With a verified library photograph of the named system (Tier A), the image is
that photograph (cropped and graded, never altered in content) set as a news
graphic: what the sources state appears as type beside or over it. There is
no marker on a rack: nothing may suggest where in the hall, or that
physically, anything happened. Without a photo, `hpc_drawn` draws a hall.

Two compositions (ALTERNATIVES):

* "a" spread: a solid type column on the left, the photograph cropped to the
  machine on the right. With an account figure the column holds the number
  over person tokens scaled from it (40 tokens x 100 accounts for 4,000).
* "b" full bleed: the photograph fills the frame under a heavy grade; the
  number sits in the dark ceiling and the tokens run as a band along the floor.

"a" is the default: the column gives the figure a clean, high-contrast ground
at feed size, the tokens stay separate shapes in the feed thumbnail, and the photo
keeps the machine's printed name in frame.
"""
from __future__ import annotations

import random
from typing import Callable

from .. import library
from .. import type as T
from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f
from . import SCENES, scene
from ._hpc import (account_count, account_label, fit_size, legend, mode, state_type, token_field, token_scale,
                   type_column)


def _photo(doc: Doc, lib: library.LibraryAsset, x: float, y: float, s: float, clip: str = "",
           grey: float = 0.0) -> None:
    """The library photograph at scale `s` with its top-left at (x, y);
    `grey` desaturates it (editorial grade only)."""
    filt = ""
    if grey:
        fid = doc._def(f"sat{grey}", f'<filter id="{{id}}"><feColorMatrix type="saturate" '
                                     f'values="{1 - grey:.2f}"/></filter>')
        filt = f' filter="url(#{fid})"'
    cl = f' clip-path="{clip}"' if clip else ""
    doc.add(f'<g{cl}><image x="{f(x)}" y="{f(y)}" width="{f(W * s)}" height="{f(H * s)}" '
            f'preserveAspectRatio="xMidYMid slice"{filt} href="{lib.data_uri()}"/></g>')


def _spread(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    lib = library.get(brief.library_id) if brief.library_id else None
    if lib is None:
        SCENES["hpc_drawn"](doc, brief, rng)
        return
    m = mode(brief)
    col = 600                                        # width of the type column
    # The machine, cropped so the cabinet carrying the printed name and the
    # receding row fill the right side.
    s = 1.12
    _photo(doc, lib, col - 600 * s, -70, s, clip=doc.clip_rect(col, 0, W - col, H),
           grey=0.55 if m == "offline" else 0.0)
    doc.rect(col, 0, W - col, H, "#06101F", opacity=0.42 if m == "offline" else 0.14)
    doc.rect(col, 0, 260, H, doc.lin([(0, "#0A1322", 0.85), (1, "#0A1322", 0)], 0, 0, 1, 0))
    doc.rect(col, H - 220, W - col, 220, doc.lin([(0, "#050A14", 0), (1, "#050A14", 0.55)]))
    type_column(doc, brief, m, col)
    doc.focus = Box(0, 0, W, H)


def _bleed(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    lib = library.get(brief.library_id) if brief.library_id else None
    if lib is None:
        SCENES["hpc_drawn"](doc, brief, rng)
        return
    p = doc.pal
    m = mode(brief)
    _photo(doc, lib, -40, -18, 1.06, grey=0.55 if m == "offline" else 0.0)
    doc.rect(0, 0, W, H, "#06101F", opacity=0.30 if m == "offline" else 0.10)
    # Heavy grade: the ceiling becomes a dark field for the type.
    doc.rect(0, 0, W, H, doc.lin([(0, "#040912", 0.92), (0.34, "#040912", 0.55), (0.55, "#040912", 0.0)]))
    doc.rect(0, 0, W, H, doc.lin([(0, "#040912", 0.55), (0.45, "#040912", 0.0)], 0, 0, 1, 0))
    if m == "accounts":
        label = account_label(brief) or "accounts"
        sz = fit_size(label, 760, 190)
        doc.text(label, 56, 50 + sz * 0.7, sz, "#FFFFFF", "display")
        if label != "accounts":
            doc.text("accounts", 74 + T.measure(T.supported(label, "display"), sz, "display"), 50 + sz * 0.7,
                     52, "#C9D3E3", "ui")
        tokens, unit = token_scale(account_count(brief))
        if tokens:
            # One band of person tokens along the floor, across the frame.
            band = 210
            doc.rect(0, H - band, W, band, doc.lin([(0, "#040912", 0), (0.35, "#040912", 0.85),
                                                   (1, "#040912", 0.94)]))
            rows = 1 if tokens <= 20 else 2
            cols = (tokens + rows - 1) // rows
            px = (W - 112) / cols
            token_field(doc, 56, H - 156, cols, tokens, px, 66, min(px, 66) * 0.82, p.danger)
            legend(doc, W - 330, H - 168, unit, p.danger, "#C9D3E3")
    else:
        state_type(doc, m, 64, 64, 720, 150)
    doc.focus = Box(0, 0, W, H)


ALTERNATIVES: dict[str, Callable[[Doc, EditorialBrief, random.Random], None]] = {"a": _spread, "b": _bleed}


@scene("hpc_hall")
def hpc_hall(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    _spread(doc, brief, rng)


def alt_for(brief: EditorialBrief) -> tuple[str, str] | None:
    """The drawn hall (no library photo) is annotated only with what the
    sources state; say exactly that. Library photos keep their own alt text."""
    from ._hpc import stated
    if brief.library_id:
        return None
    what = stated(brief)
    if what == "accounts":
        return None
    if what == "offline":
        return ("Illustration: a drawn supercomputer machine hall, marked 'OFFLINE' after a security breach.",
                "Ілюстрація: намальована зала суперкомп'ютера з написом «OFFLINE» після порушення безпеки.")
    if what == "breach":
        return ("Illustration: a drawn supercomputer machine hall, marked 'BREACH'.",
                "Ілюстрація: намальована зала суперкомп'ютера з написом «BREACH».")
    return ("Illustration: a drawn supercomputer machine hall.", "Ілюстрація: намальована зала суперкомп'ютера.")
