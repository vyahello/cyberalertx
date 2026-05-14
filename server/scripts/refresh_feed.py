"""One-shot feed-refresh procedure.

What this does, in order:
  1. Reads the current items.json store and PG news_items.
  2. Keeps only the newest `KEEP` items (default 20) by published_at.
     Everything else is deleted from BOTH stores.
  3. Wipes the entire ThreatPost AI cache (JSON + PG). The next
     `generate --use-llm` repopulates with the current prompt.
  4. Optionally runs `generate --use-llm` over the survivors.

Designed for one-time editorial resets after a prompt change. After this
runs, the feed reflects the latest prompt rules end-to-end.

USAGE (on the VPS — see server/README.md):

    cd ~/cax
    source venv/bin/activate
    python -m server.scripts.refresh_feed           # prune only, no AI
    python -m server.scripts.refresh_feed --regen   # prune + AI regen
    python -m server.scripts.refresh_feed --keep 15 # custom cap

SAFETY: this DELETES items from PG. Snapshot/backup first if you want a
rollback path. The intent is destructive: we're resetting the feed.

DUAL-WRITE NOTE: this script writes to whichever stores the running config
uses. If `CYBERALERTX_STORAGE_BACKEND=dual`, both JSON and PG are updated.
If `=json`, only JSON. Cache (threat_posts) follows the same backend.
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import subprocess
import sys

logger = logging.getLogger("refresh_feed")


def _prune_json_items(items_path: pathlib.Path, keep_fingerprints: set[str]) -> int:
    """Rewrite items.json keeping only fingerprints in `keep_fingerprints`.
    Returns the count of items dropped."""
    data = json.loads(items_path.read_text())
    items = data.get("items", [])
    before = len(items)
    items = [i for i in items if i.get("fingerprint") in keep_fingerprints]
    data["items"] = items
    items_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return before - len(items)


def _prune_pg_items(keep_fingerprints: set[str]) -> int:
    """Delete PG news_items rows whose fingerprint isn't in the keep set.
    Returns rowcount of deleted rows. No-op if PG isn't configured."""
    try:
        from sqlalchemy import text
        from cyberalertx.storage.pg.engine import get_engine
        engine = get_engine()
    except Exception as exc:
        logger.info("PG not configured (%s) — skipping PG prune", exc)
        return 0
    fps = list(keep_fingerprints)
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM news_items WHERE fingerprint <> ALL(:fps)"),
            {"fps": fps},
        )
        return result.rowcount or 0


def _wipe_threat_posts_json(cache_path: pathlib.Path) -> int:
    """Empty the threat_posts.json cache file. Returns count wiped."""
    if not cache_path.exists():
        return 0
    data = json.loads(cache_path.read_text())
    n = len(data.get("posts", {}))
    data["posts"] = {}
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return n


def _wipe_threat_posts_pg() -> int:
    """Truncate-by-delete the threat_posts table. Returns rowcount."""
    try:
        from sqlalchemy import text
        from cyberalertx.storage.pg.engine import get_engine
        engine = get_engine()
    except Exception as exc:
        logger.info("PG not configured (%s) — skipping PG cache wipe", exc)
        return 0
    with engine.begin() as conn:
        result = conn.execute(text("DELETE FROM threat_posts"))
        return result.rowcount or 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--keep", type=int, default=20,
        help="How many newest items to retain (default: 20).",
    )
    parser.add_argument(
        "--regen", action="store_true",
        help="After pruning, run `generate --use-llm` over the survivors.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would change without writing.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Load — re-use the live store class so it dedupes / sorts identically
    # to the pipeline.
    from cyberalertx.config import SETTINGS
    from cyberalertx.storage.json_store import JsonNewsStore

    store = JsonNewsStore(SETTINGS.storage_path, max_items=10_000)
    all_items = store.all()
    all_items.sort(key=lambda i: i.published_at, reverse=True)
    keep = all_items[: args.keep]
    drop = all_items[args.keep:]
    keep_fps = {i.fingerprint for i in keep}

    print(f"[refresh] store has {len(all_items)} items")
    print(f"[refresh] keeping newest {len(keep)} (cap={args.keep})")
    print(f"[refresh] dropping {len(drop)} older items")
    if keep:
        print(
            f"[refresh] newest kept: {keep[0].published_at.isoformat()} "
            f"-> {keep[-1].published_at.isoformat()}"
        )

    if args.dry_run:
        print("[refresh] --dry-run: no changes made")
        return 0

    # 1. Prune items.json.
    n_json = _prune_json_items(SETTINGS.storage_path, keep_fps)
    print(f"[refresh] items.json: removed {n_json} rows")

    # 2. Prune PG news_items (only if configured).
    n_pg = _prune_pg_items(keep_fps)
    print(f"[refresh] PG news_items: removed {n_pg} rows")

    # 3. Wipe threat_posts cache (JSON + PG). The next `generate` rebuilds
    #    from the current prompt rather than serving stale Stage-1 content.
    from cyberalertx.ai.config import AI_SETTINGS
    n_cache_json = _wipe_threat_posts_json(AI_SETTINGS.cache_path)
    n_cache_pg = _wipe_threat_posts_pg()
    print(f"[refresh] threat_posts.json: wiped {n_cache_json} entries")
    print(f"[refresh] PG threat_posts: wiped {n_cache_pg} entries")

    # 4. Regenerate. Subprocess so we re-import the AI layer cleanly after
    #    the cache wipe (avoids any cached path inside the same process).
    if args.regen:
        print(f"[refresh] regenerating {len(keep)} items via Anthropic...")
        result = subprocess.run(
            [
                sys.executable, "-m", "cyberalertx.main", "generate",
                "--limit", str(len(keep)), "--use-llm",
            ],
            check=False,
        )
        if result.returncode != 0:
            print(f"[refresh] generate exited with code {result.returncode}",
                  file=sys.stderr)
            return result.returncode

    print("[refresh] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
