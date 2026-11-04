"""Editorial benchmark: re-render a fixed set of stories through the current
pipeline WITHOUT touching the live cache, then write a before/after report.

    python -m cyberalertx.tools.benchmark                 # the 16-story set
    python -m cyberalertx.tools.benchmark --fp 0f81648bf5c6b707 --fp ...
    python -m cyberalertx.tools.benchmark --dry-run       # list, no AI calls

Cost: one fact-sheet call per story plus one render per locale it is shown
in (≈3 calls for a bilingual story). The default set is ≈40 Claude CLI
calls, on the same subscription the hourly `generate` timer uses, so run it
when that matters least.

Writes only under data/editorial/benchmark/:
  * threat_posts.json  — the new renders (separate cache, never served)
  * fact_sheets.json   — their fact sheets
  * REPORT.md          — before (live cache) vs after, per field, plus the
                         scorecard and fact-check findings for each side
Nothing is published; the API and Telegram never read these files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..config import DATA_DIR
from ..storage.json_store import JsonNewsStore

# docs/editorial/CONTENT_AUDIT.md — chosen to cover each failure class plus
# two positive controls.
DEFAULT_SET = [
    "0f81648bf5c6b707", "62af280b86d2c33a", "f635e51b46992649", "68f2c8a7a2b64fb9",
    "02aa5589116e9160", "76da600891769837", "690940732ff7fbfe", "30de94b7338e400a",
    "9406dd2ee53324ce", "8e48377fa4e2c01a", "51db3aa02d6f157a", "1acc7714f97ae941",
    "526db699eaf589d6", "4dec087390da4de4", "115437b12ee0299e", "321db785508b91ec",
]
FIELDS = ["title", "plain_summary", "short_summary", "why_it_matters", "severity_reason",
          "detail_body", "what_to_do", "what_not_to_do", "quick_facts"]
OUT = DATA_DIR / "editorial" / "benchmark"


def _fmt(value: object) -> str:
    if isinstance(value, list):
        return "\n".join(f"- {v}" for v in value) or "_(empty)_"
    text = str(value or "").strip()
    return text or "_(empty)_"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fp", action="append", help="fingerprint (repeatable)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    fps = args.fp or DEFAULT_SET

    items = {i.fingerprint: i for i in JsonNewsStore(DATA_DIR / "items.json").all()}
    live = json.loads((DATA_DIR / "threat_posts.json").read_text())["posts"]
    missing = [fp for fp in fps if fp not in items]
    todo = [fp for fp in fps if fp in items]
    print(f"{len(todo)} stories to render; {len(missing)} without a source item: {missing}")
    if args.dry_run:
        for fp in todo:
            print(" ", fp, items[fp].source, "|", items[fp].title[:80])
        return 0

    # Imported late so --dry-run works without the AI stack configured.
    from ..ai.cache import ThreatPostCache
    from ..ai.fact_sheet import FactSheetCache
    from ..ai.generator import build_default_generator
    from ..ai.scorecard import score_post

    OUT.mkdir(parents=True, exist_ok=True)
    gen = build_default_generator(use_llm=True)
    gen._cache = ThreatPostCache(OUT / "threat_posts.json")  # noqa: SLF001 — isolate from live cache
    gen._fact_sheets = FactSheetCache(OUT / "fact_sheets.json")  # noqa: SLF001

    lines = ["# Editorial benchmark — before / after", "",
             "Before = live cache. After = current pipeline (fact sheet + new prompts + checks).",
             "Not published. Review, then approve or reject per story.", ""]
    for fp in todo:
        item = items[fp]
        locales = ["ua"] if item.language == "ua" else ["en", "ua"]
        lines += [f"## {item.title}", f"`{fp}` · {item.source} · {item.url}", ""]
        for loc in locales:
            before = live.get(f"{fp}:{loc}", {})
            after = gen.generate(item, language=loc).to_dict()
            lines += [f"### {loc.upper()}", ""]
            for f in FIELDS:
                lines += [f"**{f}**", "", "_Before:_", _fmt(before.get(f)), "",
                          "_After:_", _fmt(after.get(f)), ""]
            try:
                lines += [f"Scorecard before → after: "
                          f"{score_post(before, language=loc, item=item).score} → "
                          f"{score_post(after, language=loc, item=item).score}", ""]
            except Exception as exc:  # scorecard is advisory; never block the report
                lines += [f"_(scorecard unavailable: {exc})_", ""]
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote", OUT / "REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
