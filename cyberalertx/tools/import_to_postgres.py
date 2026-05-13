"""One-shot backfill from JSON → Postgres.

Usage:
    export CYBERALERTX_PG_URL="postgresql://..."
    python -m cyberalertx.tools.pg_migrate          # ensure schema first
    python -m cyberalertx.tools.import_to_postgres

Idempotent: uses `PgNewsStore.upsert_many`, which does ON CONFLICT
DO UPDATE. Re-running after a partial import never duplicates rows.

This tool is intentionally **NOT** wired into `cmd_once` / `cmd_run` —
those use the dual-write factory from now on, which writes new items
to both stores as they arrive. This one-shot is for the existing
backlog of items already on disk before dual-write was switched on.
"""
from __future__ import annotations

import argparse
import logging
import sys

from ..config import SETTINGS
from ..storage.json_store import JsonNewsStore
from ..storage.pg.news_store import PgNewsStore

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cyberalertx.tools.import_to_postgres",
        description="Backfill news_items from JSON to Postgres.",
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="If >0, import only the first N items "
                             "(useful for smoke-testing a fresh DB).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be imported, no writes.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    json_store = JsonNewsStore(
        SETTINGS.storage_path, max_items=SETTINGS.max_items_retained,
    )
    items = json_store.all()
    if args.limit and args.limit > 0:
        items = items[: args.limit]
    if not items:
        print("Nothing to import — JSON store is empty.", file=sys.stderr)
        return 1

    print(f"Read {len(items)} items from {SETTINGS.storage_path}.", file=sys.stderr)
    if args.dry_run:
        print(f"[dry-run] would upsert {len(items)} rows. Not writing.", file=sys.stderr)
        return 0

    try:
        pg_store = PgNewsStore()
        new_items = pg_store.upsert_many(items)
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(
        f"Done. Inserted {len(new_items)} new, "
        f"updated {len(items) - len(new_items)}.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
