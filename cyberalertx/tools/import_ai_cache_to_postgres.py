"""Backfill the JSON AI-cache (`data/threat_posts.json`) into Postgres.

Usage:
    export CYBERALERTX_PG_URL="postgresql://..."
    python -m cyberalertx.tools.pg_migrate           # ensure schema (incl 003)
    python -m cyberalertx.tools.import_ai_cache_to_postgres --dry-run
    python -m cyberalertx.tools.import_ai_cache_to_postgres

Idempotent: each (fingerprint, locale) goes through
`PgThreatPostStore.set()`, which does ON CONFLICT DO UPDATE on the
composite PK. Re-running after a partial import never duplicates, and
only entries that differ from PG are written.

Reconciliation (O28): JSON is authoritative, so the import also carries
JSON's review decisions (review_status / reviewed_by / reviewed_at /
quality) into PG. `--dry-run` compares with PG read-only and prints the
plan: inserts, updates, review-status transitions, and PG-only rows. PG-only
rows are never deleted here; deciding them is a separate, reviewed step.
After writing, the tool re-reads PG and fails (exit 2) unless every JSON
entry matches.

Why a one-shot tool: the dual-write factory writes new renders to PG
as they happen from now on; this CLI catches the existing backlog of
threat_posts.json that was accumulated before dual-write was activated.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from ..ai.cache import ThreatPostCache
from ..ai.config import AI_SETTINGS
from ..storage.pg.threat_cache import PgThreatPostStore

if TYPE_CHECKING:
    from ..ai.models import ThreatPost

logger = logging.getLogger(__name__)


def _iter_cache_entries(cache: ThreatPostCache) -> Iterator[tuple[str, str, "ThreatPost"]]:
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


def _pg_payloads() -> dict[tuple[str, str], dict[str, Any]]:
    """Every PG row's payload in one read-only query."""
    from sqlalchemy import select

    from ..storage.pg.engine import get_engine
    from ..storage.pg.schema import threat_posts
    with get_engine().connect() as conn:
        rows = conn.execute(select(threat_posts.c.fingerprint, threat_posts.c.locale, threat_posts.c.payload))
        return {(str(fp), str(loc)): dict(payload) for fp, loc, payload in rows}


def _status(payload: dict[str, Any] | None) -> str:
    return str((payload or {}).get("review_status") or "auto")


def build_plan(entries: list[tuple[str, str, "ThreatPost"]],
               pg: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    """What an import would do. JSON is authoritative; PG rows JSON lacks are
    reported, never deleted (an import must not decide deletions)."""
    from ..ai.models import ThreatPost
    insert: list[tuple[str, str]] = []
    update: list[tuple[str, str]] = []
    normalize = 0          # PG payload older-format only (fields added since); same content
    unchanged = 0
    transitions: Counter[str] = Counter()
    changes: list[dict[str, str]] = []
    json_keys = set()
    for fp, loc, post in entries:
        key = (fp, loc)
        json_keys.add(key)
        want = post.to_dict()
        have = pg.get(key)
        if have is None:
            insert.append(key)
        elif have != want:
            update.append(key)
            try:
                same = ThreatPost.from_dict(have).to_dict() == want
            except (KeyError, ValueError, TypeError):
                same = False
            if same:
                normalize += 1
            if _status(have) != _status(want):
                transitions[f"{_status(have)}->{_status(want)}"] += 1
                changes.append({"key": f"{fp}:{loc}", "pg": _status(have), "json": _status(want)})
        else:
            unchanged += 1
    pg_only = sorted(k for k in pg if k not in json_keys)
    return {
        "json_entries": len(entries), "pg_rows": len(pg),
        "insert": insert, "update": update, "update_format_only": normalize, "unchanged": unchanged,
        "status_transitions": dict(transitions), "status_changes": changes,
        "pg_only": [{"key": f"{fp}:{loc}", "pg": _status(pg[(fp, loc)])} for fp, loc in pg_only],
    }


def _summary(plan: dict[str, Any]) -> str:
    pg_only_status = Counter(r["pg"] for r in plan["pg_only"])
    return (
        f"JSON entries {plan['json_entries']}, PG rows {plan['pg_rows']}: "
        f"insert {len(plan['insert'])}, update {len(plan['update'])} "
        f"({plan['update_format_only']} only add fields the PG copy predates) "
        f"(review status changes {plan['status_transitions'] or 'none'}), unchanged {plan['unchanged']}; "
        f"PG-only rows {len(plan['pg_only'])} {dict(pg_only_status) or ''} (reported, not deleted)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cyberalertx.tools.import_ai_cache_to_postgres",
        description="Backfill / reconcile the JSON threat-post cache into Postgres (JSON wins).",
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="If >0, import only the first N entries.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compare with Postgres (read-only) and report the plan. No writes.")
    parser.add_argument("--offline", action="store_true",
                        help="With --dry-run: do not contact Postgres; only count JSON entries.")
    parser.add_argument("--cache", type=Path, default=None,
                        help="JSON cache to read (default: the configured data/threat_posts.json).")
    parser.add_argument("--report", type=Path, default=None,
                        help="Write the plan (keys and review statuses only, no content) as JSON.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    cache_path = args.cache or AI_SETTINGS.cache_path
    json_cache = ThreatPostCache(cache_path)
    if json_cache.unreadable:
        print(f"REFUSED: {cache_path} exists but cannot be parsed; nothing imported.", file=sys.stderr)
        return 3
    entries = list(_iter_cache_entries(json_cache))
    if args.limit and args.limit > 0:
        entries = entries[: args.limit]
    if not entries:
        print(
            f"Nothing to import — {cache_path} is empty or absent.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Read {len(entries)} (fingerprint, locale) entries from "
        f"{cache_path}.",
        file=sys.stderr,
    )
    if args.dry_run and args.offline:
        for fp, loc, post in entries[:5]:
            print(f"  would upsert {fp}/{loc}  title={post.title[:60]!r}",
                  file=sys.stderr)
        if len(entries) > 5:
            print(f"  ... and {len(entries) - 5} more", file=sys.stderr)
        print(f"[dry-run, offline] would upsert up to {len(entries)} rows. Not writing.",
              file=sys.stderr)
        return 0

    plan = build_plan(entries, _pg_payloads())
    if args.report:
        args.report.write_text(json.dumps(
            {**plan, "insert": [f"{fp}:{loc}" for fp, loc in plan["insert"]],
             "update": [f"{fp}:{loc}" for fp, loc in plan["update"]]}, indent=1), encoding="utf-8")
    print(("[dry-run] " if args.dry_run else "") + _summary(plan), file=sys.stderr)
    for change in plan["status_changes"][:10]:
        print(f"  status {change['key']}: PG {change['pg']} -> JSON {change['json']}", file=sys.stderr)
    if args.dry_run:
        print("[dry-run] Not writing.", file=sys.stderr)
        return 0

    pg = PgThreatPostStore()
    by_key = {(fp, loc): post for fp, loc, post in entries}
    todo = plan["insert"] + plan["update"]
    failed = 0
    for key in todo:
        try:
            pg.set(key[0], key[1], by_key[key])
        except Exception as exc:
            failed += 1
            logger.warning("upsert failed for %s/%s: %s", key[0], key[1], exc)
    # Verify: every JSON entry now matches PG exactly.
    after = build_plan(entries, _pg_payloads())
    mismatched = len(after["insert"]) + len(after["update"])
    print(
        f"Done. Upserted {len(todo) - failed} of {len(todo)} changed entries"
        f"{f' ({failed} failed)' if failed else ''}; "
        f"verify: {mismatched} JSON entries still differ from PG; "
        f"{len(after['pg_only'])} PG-only rows left untouched.",
        file=sys.stderr,
    )
    return 2 if failed or mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
