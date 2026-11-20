"""Read-only V4 label and alt-text audit of the eligible stories (O54).

    venv/bin/python ops/media/alt_audit.py [--json OUT.json] [--svg DIR]

For every story currently eligible for an illustration, builds the V4.1
(`cax-editorial-4`) brief from the live stores and renders it in memory: a
catalogue scene, or the V4.1 editorial cover (`dossier`) when no scene is
supported. Every story is checked; covers and generic scenes are counted
separately (V4.1 draws all of them, there is no V3 fallback):

* **alt**: `v4.consistency.check_brief` problems (a number, quoted label or
  name in the alt text that the image does not draw; a figure claimed but
  none drawn);
* **review**: a drawn label that is a bare generic term or nationality
  ("AI", "GPU", "Irish"). Entities can no longer be such terms, so these come
  from a scene's own topic or object word ("AI" as the subject of an AI
  story, "GPU" on a drawn graphics card). Each must be checked by eye: as a
  topic or object it is fine; as an organisation, sender or product it is
  the O54 defect.

Exit code 1 when any story has an alt problem. Writes nothing to the media store;
`--json` saves the full table (scene, entities, facts, labels, alt) and
`--svg` the rendered files, for visual review.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(ROOT))
    from cyberalertx.api.app import _PostService
    from cyberalertx.intel.engine import run as intel_run
    from cyberalertx.media.renderer import v4_applies
    from cyberalertx.media.illustrations import EligibilityConfig, eligibility
    from cyberalertx.media.v4.brief import DEMONYMS, GENERIC_TERMS, alt_text, build
    from cyberalertx.media.v4.consistency import check_brief
    from cyberalertx.media.v4.render import render_doc
    from cyberalertx.tools.media import _stores

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", default="", help="write the full table here")
    ap.add_argument("--svg", default="", help="write each rendering into this directory")
    args = ap.parse_args(argv)

    sheets, posts = _stores()
    intel = intel_run(list(_PostService().list_items()), write=False, sheets=sheets, posts=posts)
    cfg = EligibilityConfig.from_env()
    bare = {t.lower() for t in GENERIC_TERMS | DEMONYMS}
    rows: dict[str, dict[str, Any]] = {}
    routed: list[str] = []
    for st in intel.stories:
        if not eligibility(st, intel.evals.get(st.key), cfg=cfg).eligible:
            continue
        b = build(st)
        if not v4_applies(b):
            routed.append(st.key)          # drawn by V4.1 without a story-specific scene (cover / generic)
        doc = render_doc(b)
        problems = check_brief(b, doc.labels)
        review = [x for x in doc.labels if x.lower() in bare]
        rows[st.key] = {"title": st.anchor.title, "scene": b.scene, "entities": list(b.entities),
                        "facts": b.facts, "labels": doc.labels, "alt": alt_text(b), "problems": problems,
                        "review": review}
        if args.svg:
            out = Path(args.svg)
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{st.key.removeprefix('s:')}.svg").write_text(doc.svg(), encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    bad = {k: r for k, r in rows.items() if r["problems"]}
    print(f"{len(rows)} eligible stories audited (all drawn by V4.1), {len(bad)} with problems; "
          f"{len(rows) - len(routed)} story-specific scenes, {len(routed)} covers or generic scenes")
    print("by scene:", dict(Counter(str(r["scene"]) for r in rows.values()).most_common()))
    for k, r in bad.items():
        for p in r["problems"]:
            print(f"  {k} [{r['scene']}] {p}")
    for k, r in rows.items():
        if r["review"]:
            print(f"  review {k} [{r['scene']}] generic label {r['review']}: {str(r['title'])[:70]}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
