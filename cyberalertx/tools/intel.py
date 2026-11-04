"""Shadow evaluation of the intelligence layer.

    python -m cyberalertx.tools.intel evaluate [--now 2026-11-02T18:00:00+00:00] [--no-write]
    python -m cyberalertx.tools.intel explain STORY_KEY

`evaluate` runs relevance → clusters → scores → Top 10 / Trending / Breaking
over the current item store, writes results under data/intel/ (unless
--no-write), and prints them next to what the site does today:

  * homepage today: newest AI-rendered items, then the frontend's
    significance ordering;
  * `/posts/trending` today: a severity sort (threat level, actionability,
    date) with no time window and no corroboration.

It makes no AI calls, changes no published output and starts no scheduler.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from ..config import DATA_DIR
from ..storage.json_store import JsonNewsStore

_LEVEL = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}


def _stores() -> tuple[object, object]:
    from ..ai.cache import ThreatPostCache
    from ..ai.fact_sheet import FactSheetCache

    sheets_path = DATA_DIR / "fact_sheets.json"
    return (FactSheetCache(sheets_path) if sheets_path.exists() else None,
            ThreatPostCache(DATA_DIR / "threat_posts.json"))


def cmd_evaluate(args: argparse.Namespace) -> int:
    from ..intel.engine import run

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    items = JsonNewsStore(DATA_DIR / "items.json").all()
    sheets, posts = _stores()
    res = run(items, now=now, sheets=sheets, posts=posts, write=not args.no_write)
    summary = res.summary()
    print(f"stories {summary['stories']} · recalculated {res.recalculated} · relevance {summary['relevance']}")
    print(f"\nDaily Top 10 — edition {res.edition} ({len(res.picks)} picks)")
    for p in res.picks:
        print(f"  {p['rank']:>2}. [{p['selection_score']:5.1f}] {p['title'][:80]}")
        print(f"      {p['verification']} · confidence {p['confidence']} · exploitation {p['exploitation']}"
              f" · sources {', '.join(p['sources'])}")
    print("\nTrending (24 h)")
    for t in [t for t in res.trending if t["trending"]][:10]:
        print(f"  [{t['trend_score']:5.1f}] {t['title'][:80]}  ({', '.join(t['signals'])})")
    print("\nBreaking candidates")
    for b in res.breaking:
        print(f"  {b['alert']:>9} {', '.join(b['rules'])}: {b['title'][:80]}")
    if not res.breaking:
        print("  none")

    # Current behaviour, for comparison.
    rendered = []
    for i in items:
        post = posts.get(i.fingerprint, "en") or posts.get(i.fingerprint, "ua")  # type: ignore[attr-defined]
        if post is not None:
            rendered.append((i, post))
    rendered.sort(key=lambda ip: ip[0].published_at, reverse=True)
    print("\nToday's homepage feed (newest rendered, first 10)")
    for i, p in rendered[:10]:
        print(f"  {p.threat_level:<8} {p.title[:80]}")
    danger = sorted(rendered, key=lambda ip: (_LEVEL.get(ip[1].threat_level, 0), ip[0].actionability_score,
                                              ip[0].published_at), reverse=True)
    print("\nToday's /posts/trending (severity sort, first 5)")
    for i, p in danger[:5]:
        print(f"  {p.threat_level:<8} {i.published_at:%m-%d} {p.title[:76]}")
    if res.failures:
        print(f"\n{len(res.failures)} processing failures — see data/intel/latest.json")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    from ..intel.engine import load_scores

    rec = load_scores().get(args.story_key)
    if not rec:
        print(f"no evaluation for {args.story_key}; run `evaluate` first", file=sys.stderr)
        return 1
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cyberalertx.tools.intel", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ev = sub.add_parser("evaluate", help="shadow run over the current store")
    ev.add_argument("--now", help="evaluate as of this ISO time (reproducible runs)")
    ev.add_argument("--no-write", action="store_true", help="print only; write nothing")
    ex = sub.add_parser("explain", help="print a story's score, components, reasons and history")
    ex.add_argument("story_key")
    args = ap.parse_args(argv)
    return cmd_evaluate(args) if args.cmd == "evaluate" else cmd_explain(args)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
