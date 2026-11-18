"""Render an `EditorialBrief` to a 1600x900 SVG (deterministic: same brief,
same bytes)."""
from __future__ import annotations

import hashlib
import random

from .brief import FALLBACK, EditorialBrief
from .kit import PALETTES, Doc, signature
from .scenes import load_all


def rng_for(brief: EditorialBrief) -> random.Random:
    return random.Random(int(hashlib.sha256(brief.seed.encode()).hexdigest()[:16], 16))


def render_doc(brief: EditorialBrief) -> Doc:
    """The finished document; `doc.labels` lists the text it shows."""
    scenes = load_all()
    doc = Doc(PALETTES.get(brief.palette, PALETTES["midnight"]))
    fn = scenes.get(brief.scene) or scenes[FALLBACK.id]
    fn(doc, brief, rng_for(brief))
    doc.grain(0.06 if doc.pal.dark else 0.05)
    signature(doc)
    return doc


def render(brief: EditorialBrief) -> str:
    return render_doc(brief).svg()
