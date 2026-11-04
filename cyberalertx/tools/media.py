"""Media Engine CLI: branded cards for every eligible story, illustrations for a few.

    python -m cyberalertx.tools.media run [--dry-run]     record cards, generate due illustrations
    python -m cyberalertx.tools.media status              counts, provider, failures
    python -m cyberalertx.tools.media regenerate STORY    clear a story's illustration so the next run redoes it
    python -m cyberalertx.tools.media validate-cards URL  fetch every card variant from a running site and check it

No scheduler is added: run it after `generate`, by hand or from the existing
timer. With no image provider configured (CYBERALERTX_IMAGE_PROVIDER unset or
"none") `run` records branded cards only and makes no network calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cyberalertx.tools.media", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="record cards and generate due illustrations")
    r.add_argument("--dry-run", action="store_true", help="report what would happen; write nothing")
    r.add_argument("--max-calls", type=int, default=None, help="provider calls this run (default env or 3)")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("status", help="asset counts and failures").set_defaults(fn=cmd_status)
    g = sub.add_parser("regenerate", help="redo a story's illustration on the next run")
    g.add_argument("story")
    g.set_defaults(fn=cmd_regenerate)
    v = sub.add_parser("validate-cards", help="fetch and check card variants from a running site")
    v.add_argument("base_url", help="e.g. http://127.0.0.1:3300")
    v.add_argument("--limit", type=int, default=10)
    v.set_defaults(fn=cmd_validate_cards)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
