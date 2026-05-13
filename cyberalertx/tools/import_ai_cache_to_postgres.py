"""Backfill the JSON AI-cache (`data/threat_posts.json`) into Postgres.

Usage:
    export CYBERALERTX_PG_URL="postgresql://..."
    python -m cyberalertx.tools.pg_migrate           # ensure schema (incl 003)
    python -m cyberalertx.tools.import_ai_cache_to_postgres --dry-run
    python -m cyberalertx.tools.import_ai_cache_to_postgres

Idempotent: each (fingerprint, locale) goes through
`PgThreatPostStore.set()`, which does ON CONFLICT DO UPDATE on the
composite PK. Re-running after a partial import never duplicates.

Why a one-shot tool: the dual-write factory writes new renders to PG
as they happen from now on; this CLI catches the existing backlog of
threat_posts.json that was accumulated before dual-write was activated.
"""
from __future__ import annotations

import argparse
import logging
import sys

from ..ai.cache import ThreatPostCache
from ..ai.config import AI_SETTINGS
from ..storage.pg.threat_cache import PgThreatPostStore

logger = logging.getLogger(__name__)


def _iter_cache_entries(cache: ThreatPostCache):
    """Yield (fingerprint, locale, ThreatPost) for every entry in the JSON
    cache. Uses the private `_store` dict directly so we get the
    fingerprint+locale keys, not just the value list `all()` returns.
    """
    from ..ai.models import ThreatPost
    for raw_key, raw_val in cache._store.items():  # noqa: SLF001
        if ":" not in raw_key:
            continue
        fingerprint, _, locale = raw_key.partition(":")
        try:
            post = ThreatPost.from_dict(raw_val)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning(
                "skipping malformed cache entry %s/%s: %s",
                fingerprint, locale, exc,
            )
            continue
        yield fingerprint, locale, post


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cyberalertx.tools.import_ai_cache_to_postgres",
        description="Backfill JSON threat-post cache into Postgres.",
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="If >0, import only the first N entries.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be imported, no writes.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    json_cache = ThreatPostCache(AI_SETTINGS.cache_path)
    entries = list(_iter_cache_entries(json_cache))
    if args.limit and args.limit > 0:
        entries = entries[: args.limit]
    if not entries:
        print(
            f"Nothing to import — {AI_SETTINGS.cache_path} is empty or absent.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Read {len(entries)} (fingerprint, locale) entries from "
        f"{AI_SETTINGS.cache_path}.",
        file=sys.stderr,
    )
    if args.dry_run:
        # Show a small sample so the operator can sanity-check what's about
        # to be written.
        for fp, loc, post in entries[:5]:
            print(f"  would upsert {fp}/{loc}  title={post.title[:60]!r}",
                  file=sys.stderr)
        if len(entries) > 5:
            print(f"  ... and {len(entries) - 5} more", file=sys.stderr)
        print(f"[dry-run] would upsert {len(entries)} rows. Not writing.",
              file=sys.stderr)
        return 0

    pg = PgThreatPostStore()
    failed = 0
    for fp, loc, post in entries:
        try:
            pg.set(fp, loc, post)
        except Exception as exc:
            failed += 1
            logger.warning("upsert failed for %s/%s: %s", fp, loc, exc)
    ok = len(entries) - failed
    print(
        f"Done. Upserted {ok} of {len(entries)} entries"
        f"{f' ({failed} failed)' if failed else ''}.",
        file=sys.stderr,
    )
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
