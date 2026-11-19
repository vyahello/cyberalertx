"""Media Engine CLI: branded cards for every eligible story, illustrations for a few.

    python -m cyberalertx.tools.media run [--dry-run]     record cards, generate due illustrations
    python -m cyberalertx.tools.media status              counts, provider, failures
    python -m cyberalertx.tools.media regenerate STORY    clear a story's illustration so the next run redoes it
    python -m cyberalertx.tools.media brief STORY [--svg F] the V4 visual brief of a story (read-only)
    python -m cyberalertx.tools.media validate-cards URL  fetch every card variant from a running site and check it
    python -m cyberalertx.tools.media candidates ACTION   V4.1 canary in quarantine (start, collect, gallery,
                                                          review, promote approved only, cleanup)

No scheduler is added: run it after `generate`, by hand or from the existing
timer. With no image provider configured (CYBERALERTX_IMAGE_PROVIDER unset or
"none") `run` records branded cards only and makes no network calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any, Callable

from ..config import DATA_DIR
from ..storage.json_store import JsonNewsStore


def _stores() -> tuple[object, object]:
    from ..ai.cache import ThreatPostCache
    from ..ai.fact_sheet import FactSheetCache

    sheets_path = DATA_DIR / "fact_sheets.json"
    return (FactSheetCache(sheets_path) if sheets_path.exists() else None,
            ThreatPostCache(DATA_DIR / "threat_posts.json"))


def cmd_run(args: argparse.Namespace) -> int:
    from ..media.engine import run

    items = JsonNewsStore(DATA_DIR / "items.json").all()
    sheets, posts = _stores()
    res = run(items, sheets=sheets, posts=posts, dry_run=args.dry_run,
              max_calls=args.max_calls, now=datetime.now(timezone.utc))
    print(json.dumps(res.summary(), ensure_ascii=False, indent=2))
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    """Historical illustrations: plan (default) or generate in budgeted batches."""
    from ..media.engine import backfill_plan, run

    items = JsonNewsStore(DATA_DIR / "items.json").all()
    sheets, posts = _stores()
    plan = backfill_plan(items, sheets=sheets, posts=posts)
    print(json.dumps({"plan": plan}, ensure_ascii=False, indent=2))
    if args.dry_run or not args.batch:
        return 0
    # The explicit step that replaces images made by an older renderer.
    res = run(items, sheets=sheets, posts=posts, max_calls=args.batch, now=datetime.now(timezone.utc),
              upgrade_renderer=True)
    print(json.dumps({"batch": res.summary()}, ensure_ascii=False, indent=2))
    return 1 if res.failed and not res.generated else 0


def cmd_brief(args: argparse.Namespace) -> int:
    """Read-only: the structured V4 brief (and optionally its SVG) for a story."""
    from ..intel.engine import run as intel_run
    from ..media.v4.brief import alt_text, build

    items = JsonNewsStore(DATA_DIR / "items.json").all()
    sheets, posts = _stores()
    intel = intel_run(items, sheets=sheets, posts=posts, write=False)
    story = next((s for s in intel.stories if s.key == args.story), None)
    if story is None:
        print(f"unknown story {args.story}", file=sys.stderr)
        return 2
    b = build(story)
    print(json.dumps({"title": story.anchor.title, "brief": b.to_dict(), "alt": alt_text(b)},
                     ensure_ascii=False, indent=2, default=list))
    if args.svg:
        from ..media.v4.render import render
        with open(args.svg, "w", encoding="utf-8") as fh:
            fh.write(render(b))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    import os
    from collections import Counter

    from ..media.assets import MediaStore

    store = MediaStore()
    assets = store.all()
    by = Counter((a.asset_type, a.status) for a in assets)
    print(f"provider: {(os.getenv('CYBERALERTX_IMAGE_PROVIDER') or 'none')}")
    for (kind, status), n in sorted(by.items()):
        print(f"  {kind:24} {status:10} {n}")
    for a in assets:
        if a.status == "failed":
            print(f"  failed {a.story_key} (attempt {a.attempts}): {a.last_error}")
    return 0


def cmd_regenerate(args: argparse.Namespace) -> int:
    from ..media.assets import MediaStore

    store = MediaStore()
    asset = store.get(f"illus:{args.story}")
    if asset is None:
        print(f"no illustration recorded for {args.story}", file=sys.stderr)
        return 1
    # Status 'pending' + a cleared hash makes the next run treat it as new;
    # the stored file is kept (content-addressed, possibly shared).
    asset.status, asset.content_hash, asset.attempts, asset.last_error = "pending", "", 0, ""
    store.put(asset)
    print(f"{args.story}: queued for regeneration on the next run")
    return 0


def cmd_validate_cards(args: argparse.Namespace) -> int:
    """Fetch each recorded card variant from a running site (e.g. a local
    `next start`) and check MIME, dimensions and size."""
    import httpx

    from ..media.assets import MediaStore, sniff
    from ..media.cards import CARD_VARIANTS, site_url

    base = args.base_url.rstrip("/")
    cards = [a for a in MediaStore().all() if a.asset_type == "branded_card"][: args.limit]
    bad = 0
    with httpx.Client(timeout=30) as client:
        for a in cards:
            for variant, url in a.variants.items():
                local = url.replace(site_url(), base, 1)
                try:
                    r = client.get(local)
                    mime, w, h = sniff(r.content)
                    ok = r.status_code == 200 and (w, h) == CARD_VARIANTS[variant] and len(r.content) < 2_000_000
                except Exception as exc:  # noqa: BLE001 - report and continue
                    ok, mime, w, h = False, f"error {exc}", 0, 0
                if not ok:
                    bad += 1
                    print(f"FAIL {local}: {mime} {w}x{h}")
    print(f"checked {len(cards)} cards × {len(CARD_VARIANTS)} variants, {bad} failed")
    return 1 if bad else 0


def _story_set() -> tuple[list[Any], Any, Any, list[Any], Callable[[Any], bool]]:
    """(items, sheets, posts, stories, eligible) as the hourly run sees them."""
    from ..intel.engine import run as intel_run
    from ..media.illustrations import EligibilityConfig, eligibility

    items = JsonNewsStore(DATA_DIR / "items.json").all()
    sheets, posts = _stores()
    intel = intel_run(items, sheets=sheets, posts=posts, write=False)
    cfg = EligibilityConfig.from_env()

    def eligible(story: Any) -> bool:
        return bool(eligibility(story, intel.evals.get(story.key), cfg=cfg).eligible)
    return list(items), sheets, posts, list(intel.stories), eligible


def cmd_candidates(args: argparse.Namespace) -> int:
    """V4.1 canary in quarantine (see media/candidates.py). Never publishes,
    except `promote` for candidates approved in review.json."""
    from pathlib import Path

    from ..media import candidates as C
    from ..media.assets import MediaStore

    store = MediaStore()
    try:
        if args.action == "start":
            _, _, _, stories, eligible = _story_set()
            release = Path("RELEASE").read_text().splitlines()[0] if Path("RELEASE").exists() else ""
            path = C.start(Path(args.root), [s.key for s in stories if eligible(s)], store=store, hours=args.hours,
                           release=release)
            print(json.dumps({"session": str(path), **C.load(path)}, ensure_ascii=False, indent=2)[:1200])
        elif args.action == "collect":
            _, _, _, stories, eligible = _story_set()
            res = C.collect(Path(args.session), stories, store=store, eligible=eligible, recent=args.recent)
            C.gallery(Path(args.session))
            print(json.dumps(res, ensure_ascii=False, indent=2))
        elif args.action == "gallery":
            print(C.gallery(Path(args.session)))
        elif args.action == "review":
            if len(args.story) != 1:
                raise C.CandidateError("review takes exactly one --story")
            scores = {k: int(v) for k, v in (kv.split("=", 1) for kv in args.score)}
            print(json.dumps(C.review(Path(args.session), args.story[0], scores=scores, verdict=args.verdict,
                                      reviewer=args.reviewer, notes=args.notes), ensure_ascii=False, indent=2))
            C.gallery(Path(args.session))
        elif args.action == "promote":
            items, sheets, posts, _, _ = _story_set()
            print(json.dumps(C.promote(Path(args.session), args.story, items=items, store=store, sheets=sheets,
                                       posts=posts), ensure_ascii=False, indent=2))
        elif args.action == "cleanup":
            print(json.dumps({"removed": args.session, "index_sha256": C.cleanup(Path(args.session), store=store)}))
    except C.CandidateError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cyberalertx.tools.media", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="record cards and generate due illustrations")
    r.add_argument("--dry-run", action="store_true", help="report what would happen; write nothing")
    r.add_argument("--max-calls", type=int, default=None, help="provider calls this run (default env or 3)")
    r.set_defaults(fn=cmd_run)
    b = sub.add_parser("backfill", help="illustrations for existing public stories: plan, or --batch N to generate")
    b.add_argument("--dry-run", action="store_true", help="plan only (counts, cost); the default without --batch")
    b.add_argument("--batch", type=int, default=0, help="generate at most N images now (newest first, within budget)")
    b.set_defaults(fn=cmd_backfill)
    sub.add_parser("status", help="asset counts and failures").set_defaults(fn=cmd_status)
    g = sub.add_parser("regenerate", help="redo a story's illustration on the next run")
    g.add_argument("story")
    g.set_defaults(fn=cmd_regenerate)
    br = sub.add_parser("brief", help="show a story's V4 visual brief (read-only)")
    br.add_argument("story")
    br.add_argument("--svg", default="", help="also write the V4 rendering to this file")
    br.set_defaults(fn=cmd_brief)
    c = sub.add_parser("candidates", help="V4.1 canary in quarantine: collect, review, promote approved only")
    c.add_argument("action", choices=["start", "collect", "gallery", "review", "promote", "cleanup"])
    c.add_argument("--root", default="", help="start: directory for sessions (e.g. $REVIEW_DIR/v41-candidates)")
    c.add_argument("--hours", type=float, default=6.0, help="start: expiry of the session (secondary guard)")
    c.add_argument("--session", default="", help="the session directory")
    c.add_argument("--recent", type=int, default=0,
                   help="collect: also this many of the newest existing stories without a V4.1 image")
    c.add_argument("--story", action="append", default=[], help="review/promote: story key (repeatable for promote)")
    c.add_argument("--score", action="append", default=[], help="review: gate=score, e.g. accuracy=5")
    c.add_argument("--verdict", default="", help="review: approved | rejected")
    c.add_argument("--reviewer", default="", help="review: who decided")
    c.add_argument("--notes", default="")
    c.set_defaults(fn=cmd_candidates)
    v = sub.add_parser("validate-cards", help="fetch and check card variants from a running site")
    v.add_argument("base_url", help="e.g. http://127.0.0.1:3300")
    v.add_argument("--limit", type=int, default=10)
    v.set_defaults(fn=cmd_validate_cards)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
