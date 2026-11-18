"""Which illustration renderer is active, and the one seam the engine uses.

Two renderers ship side by side:

  * `cax-svg-3`      — the V3 isometric renderer (media/svg_art.py). Default.
  * `cax-editorial-4` — the V4 editorial system (media/v4/): structured visual
    brief, scene library, verified photo library.

`CYBERALERTX_ILLUSTRATION_RENDERER=editorial-4` selects V4. Changing it never
replaces an existing image by itself: the engine keeps any validated image an
older/other renderer made until `tools.media backfill --batch` is run
explicitly (engine.run(upgrade_renderer=True)). Rolling back is the same
switch in the other direction; images V4 already made stay until they are
re-rendered one by one (`tools.media regenerate STORY`). Do NOT roll back with
`backfill --batch`: it replaces every image not made by the active renderer,
which on the current archive includes the cax-svg-2 images. Both renderers
are deterministic, so a V3 re-render of a story reproduces its earlier V3
file byte for byte (content-addressed: same storage key, still on disk).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

V3 = "cax-svg-3"
V4 = "cax-editorial-4"
_ALIASES = {"editorial-4": V4, "cax-editorial-4": V4, "v4": V4, "svg-3": V3, "cax-svg-3": V3, "v3": V3}


def active() -> str:
    raw = (os.getenv("CYBERALERTX_ILLUSTRATION_RENDERER") or "").strip().lower()
    return _ALIASES.get(raw, V3)


@dataclass
class Plan:
    renderer: str
    brief: Any
    alt: dict[str, str]
    inputs_hash: str
    #: Tier A provenance (empty for original illustrations).
    source: str = "generated:svg"
    license: str = "CyberAlertX (generated on our server)"
    credit: dict[str, str] = field(default_factory=dict)


def plan_for(story: Any, renderer: str | None = None) -> Plan:
    renderer = renderer or active()
    if renderer == V4:
        from .v4 import brief as v4
        from .v4 import library
        b = v4.build(story)
        plan = Plan(V4, b, v4.alt_text(b), v4.inputs_hash(b))
        lib = library.get(b.library_id) if b.library_id else None
        if lib is not None:
            plan.source = f"library:{lib.id}+generated:svg"
            plan.license = (f"Photo {lib.license} ({lib.author}, {lib.source_url}); "
                            "annotation CyberAlertX")
            plan.credit = {"en": lib.credit, "ua": lib.credit_ua}
        return plan
    from .illustrations import visual_brief
    vb, alt, h = visual_brief(story)
    return Plan(V3, vb, alt, h)


def render(plan: Plan) -> bytes:
    if plan.renderer == V4:
        from .v4.consistency import check_brief
        from .v4.render import render_doc
        doc = render_doc(plan.brief)
        problems = check_brief(plan.brief, doc.labels)
        if problems:
            # Tests and `ops/media/alt_audit.py` are the gate; at run time a
            # mismatch is reported, never silently published.
            logger.warning("media: alt text of %s does not match its image: %s",
                           getattr(plan.brief, "story_key", "?"), "; ".join(problems))
        return doc.svg().encode("utf-8")
    from .svg_art import render_svg
    return render_svg(plan.brief).encode("utf-8")
