"""Which illustration renderer is active, and the one seam the engine uses.

Two renderers ship side by side:

  * `cax-svg-3`      — the V3 isometric renderer (media/svg_art.py). Default.
  * `cax-editorial-4` — the V4 editorial system (media/v4/): structured visual
    brief, scene library, verified photo library.

`CYBERALERTX_ILLUSTRATION_RENDERER=editorial-4` selects V4 as a hybrid
policy: stories whose V4 brief found an evidence-backed scene are drawn by
V4, low-confidence ones (the generic `dossier` fallback) by V3 (`plan_for`).
Changing the setting never
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
    #: Why a V4 request was served by V3 ("" when it was not), see `plan_for`.
    routed: str = ""
    license: str = "CyberAlertX (generated on our server)"
    credit: dict[str, str] = field(default_factory=dict)


def plan_for(story: Any, renderer: str | None = None) -> Plan:
    """The image plan for `story` under `renderer` (default: the active one).

    Hybrid policy (V4.1.2): editorial-4 draws a story only when its brief
    found an evidence-backed scene. A low-confidence brief (the generic
    `dossier` fallback) is served by V3, so V4 coverage never grows through
    a weak generic card. The story key, asset id and URLs are the same either
    way; only the renderer that draws it differs."""
    renderer = renderer or active()
    if renderer == V4:
        from .v4 import brief as v4
        from .v4 import library
        b = v4.build(story)
        if not v4_applies(b):
            plan = _v3_plan(story)
            plan.routed = f"low-confidence V4 brief ({b.scene}): served by {V3}"
            return plan
        plan = Plan(V4, b, v4.alt_text(b), v4.inputs_hash(b))
        lib = library.get(b.library_id) if b.library_id else None
        if lib is not None:
            plan.source = f"library:{lib.id}+generated:svg"
            plan.license = (f"Photo {lib.license} ({lib.author}, {lib.source_url}); "
                            "annotation CyberAlertX")
            plan.credit = {"en": lib.credit, "ua": lib.credit_ua}
        return plan
    return _v3_plan(story)


def v4_applies(brief: Any) -> bool:
    """True when editorial-4 should draw this V4 brief: an evidence-backed
    scene, not the low-confidence `dossier` fallback."""
    from .v4.brief import FALLBACK
    return bool(brief.confidence != "low" and brief.scene != FALLBACK.id)


def _v3_plan(story: Any) -> Plan:
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
