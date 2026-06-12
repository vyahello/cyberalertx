"""Diff JSON vs Postgres state for news_items AND threat_posts.

Reports two sections:
  1. news_items — count, fingerprint set, per-field deep diff.
  2. threat_posts — count, (fingerprint, locale) set, per-field deep diff
     of localized AI content.

Exit code 0 = stores agree across both sections. Non-zero = at least one
divergence found — useful in CI as a guard before flipping the read path.

Usage:
    export CYBERALERTX_PG_URL="postgresql://..."
    python -m cyberalertx.tools.compare_storage           # summary
    python -m cyberalertx.tools.compare_storage --full    # per-field
    python -m cyberalertx.tools.compare_storage --news-only
    python -m cyberalertx.tools.compare_storage --ai-only
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict
from typing import Any, Iterable, Iterator

from ..ai.cache import ThreatPostCache
from ..ai.config import AI_SETTINGS
from ..ai.models import ThreatPost
from ..config import SETTINGS
from ..models import NewsItem
from ..storage.json_store import JsonNewsStore
from ..storage.pg.news_store import PgNewsStore
from ..storage.pg.threat_cache import PgThreatPostStore

logger = logging.getLogger(__name__)

# Fields excluded from per-item comparison because they are intrinsically
# volatile across stores:
#   * fetched_at — set per-process, drifts on re-import
#   * created_at / updated_at — generated server-side in PG
_VOLATILE_FIELDS = frozenset({"fetched_at"})


def _normalize_for_compare(item: NewsItem) -> dict[str, Any]:
    """Return a dict that removes volatile fields and normalizes list ordering.

    Lists like `tags` and `corroborating_sources` are conceptually sets;
    sort them for deterministic equality.
    """
    d = asdict(item)
    for k in _VOLATILE_FIELDS:
        d.pop(k, None)
    for k in ("tags", "corroborating_sources", "affected_platforms", "audience_targets"):
        if isinstance(d.get(k), list):
            d[k] = sorted(d[k])
    # ISO-format datetimes for stable string equality.
    d["published_at"] = item.published_at.astimezone().isoformat()
    return d


# IEEE 754 double precision has ~15-17 significant decimal digits; Python's
# `repr(float)` chooses the shortest unambiguous representation, while
# psycopg's text-formatted PG output may render the same bit-pattern with
# one fewer digit. Comparing as strings then flags every score as different
# even though the underlying floats are identical. Tolerance-based compare
# (1e-9) ignores any "diff" that's smaller than reasonable rounding noise.
_FLOAT_TOLERANCE = 1e-9


def _values_equal(a: object, b: object) -> bool:
    """Tolerant equality for float fields; exact for everything else."""
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) < _FLOAT_TOLERANCE
    return a == b


def _diff_items(json_item: NewsItem, pg_item: NewsItem) -> list[str]:
    a = _normalize_for_compare(json_item)
    b = _normalize_for_compare(pg_item)
    fields = []
    for k in sorted(a.keys() | b.keys()):
        if not _values_equal(a.get(k), b.get(k)):
            fields.append(f"  {k}: json={a.get(k)!r}  pg={b.get(k)!r}")
    return fields


def compare_news(full: bool = False) -> int:
    """Section 1: news_items parity."""
    json_store = JsonNewsStore(SETTINGS.storage_path, max_items=SETTINGS.max_items_retained)
    pg_store = PgNewsStore()
    json_items = {i.fingerprint: i for i in json_store.all()}
    pg_items = {i.fingerprint: i for i in pg_store.all()}

    print("=== news_items ===")
    print(f"JSON: {len(json_items)} items")
    print(f"PG  : {len(pg_items)} items")

    missing_in_pg = set(json_items) - set(pg_items)
    missing_in_json = set(pg_items) - set(json_items)
    common = set(json_items) & set(pg_items)

    print(f"In JSON not in PG  : {len(missing_in_pg)}")
    for fp in sorted(missing_in_pg):
        print(f"  - {fp}  {json_items[fp].title[:70]}")
    print(f"In PG not in JSON  : {len(missing_in_json)}")
    for fp in sorted(missing_in_json):
        print(f"  - {fp}  {pg_items[fp].title[:70]}")

    diff_count = 0
    if full:
        for fp in sorted(common):
            diffs = _diff_items(json_items[fp], pg_items[fp])
            if diffs:
                diff_count += 1
                print(f"\nField diffs for {fp} ({json_items[fp].title[:60]}):")
                for line in diffs:
                    print(line)
        print(f"\nField-level mismatches: {diff_count} / {len(common)} common items")
    else:
        for fp in common:
            if _diff_items(json_items[fp], pg_items[fp]):
                diff_count += 1
        print(f"Common with field diffs: {diff_count} / {len(common)}  "
              f"(re-run with --full for details)")

    any_diff = bool(missing_in_pg or missing_in_json or diff_count)
    return 1 if any_diff else 0


# ----- AI threat-posts comparison ------------------------------------------

# Fields that aren't expected to round-trip identically across stores even
# when content matches. Empty for now; reserved for future provenance / TS
# fields if we add them.
_AI_VOLATILE_FIELDS: frozenset[str] = frozenset()


def _diff_threat_posts(a: ThreatPost, b: ThreatPost) -> list[str]:
    """Per-field deep diff for a single (fingerprint, locale) pair."""
    da = asdict(a)
    db = asdict(b)
    for k in _AI_VOLATILE_FIELDS:
        da.pop(k, None)
        db.pop(k, None)
    # Normalize references (list of dataclasses → list of dicts already
    # via asdict()) and list orderings that are conceptually sets.
    fields = []
    for k in sorted(da.keys() | db.keys()):
        va, vb = da.get(k), db.get(k)
        if isinstance(va, float) and isinstance(vb, float):
            if abs(va - vb) >= _FLOAT_TOLERANCE:
                fields.append(f"  {k}: json={va!r}  pg={vb!r}")
            continue
        if va != vb:
            fields.append(f"  {k}: json={va!r}  pg={vb!r}")
    return fields


def _iter_json_ai_cache(cache: ThreatPostCache) -> Iterator[tuple[str, str, ThreatPost]]:
    """Yield (fingerprint, locale, ThreatPost) for every JSON cache entry."""
    for raw_key, raw_val in cache._store.items():  # noqa: SLF001
        if ":" not in raw_key:
            continue
        fp, _, loc = raw_key.partition(":")
        try:
            yield fp, loc, ThreatPost.from_dict(raw_val)
        except (KeyError, ValueError, TypeError):
            continue


def _iter_pg_ai_cache(pg: PgThreatPostStore) -> Iterator[tuple[str, str, ThreatPost]]:
    """Yield (fingerprint, locale, ThreatPost) by scanning threat_posts."""
    from sqlalchemy import select
    from ..storage.pg.engine import get_engine
    from ..storage.pg.schema import threat_posts
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(threat_posts.c.fingerprint, threat_posts.c.locale, threat_posts.c.payload)
        ).fetchall()
    for fp, loc, payload in rows:
        try:
            yield fp, loc, ThreatPost.from_dict(payload)
        except (KeyError, ValueError, TypeError):
            continue


def compare_ai_posts(full: bool = False) -> int:
    """Section 2: threat_posts parity. Keyed by (fingerprint, locale)."""
    json_cache = ThreatPostCache(AI_SETTINGS.cache_path)
    pg_cache = PgThreatPostStore()

    json_posts = {(fp, loc): post for fp, loc, post in _iter_json_ai_cache(json_cache)}
    pg_posts = {(fp, loc): post for fp, loc, post in _iter_pg_ai_cache(pg_cache)}

    print("\n=== threat_posts (AI cache) ===")
    print(f"JSON: {len(json_posts)} (fingerprint, locale) entries")
    print(f"PG  : {len(pg_posts)} (fingerprint, locale) entries")

    missing_in_pg = set(json_posts) - set(pg_posts)
    missing_in_json = set(pg_posts) - set(json_posts)
    common = set(json_posts) & set(pg_posts)

    print(f"In JSON not in PG  : {len(missing_in_pg)}")
    for fp, loc in sorted(missing_in_pg):
        print(f"  - {fp}/{loc}  {json_posts[(fp, loc)].title[:70]}")
    print(f"In PG not in JSON  : {len(missing_in_json)}")
    for fp, loc in sorted(missing_in_json):
        print(f"  - {fp}/{loc}  {pg_posts[(fp, loc)].title[:70]}")

    # Locale coverage summary — quick sanity check per locale.
    locales_json = {loc for _, loc in json_posts}
    locales_pg = {loc for _, loc in pg_posts}
    print(f"Locales (JSON): {sorted(locales_json)}")
    print(f"Locales (PG)  : {sorted(locales_pg)}")

    diff_count = 0
    if full:
        for key in sorted(common):
            fp, loc = key
            diffs = _diff_threat_posts(json_posts[key], pg_posts[key])
            if diffs:
                diff_count += 1
                print(f"\nField diffs for {fp}/{loc} ({json_posts[key].title[:60]}):")
                for line in diffs:
                    print(line)
        print(f"\nField-level mismatches: {diff_count} / {len(common)} common entries")
    else:
        for key in common:
            if _diff_threat_posts(json_posts[key], pg_posts[key]):
                diff_count += 1
        print(f"Common with field diffs: {diff_count} / {len(common)}  "
              f"(re-run with --full for details)")

    any_diff = bool(missing_in_pg or missing_in_json or diff_count)
    return 1 if any_diff else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cyberalertx.tools.compare_storage",
        description="Diff JSON vs Postgres state for news_items and threat_posts.",
    )
    parser.add_argument("--full", action="store_true",
                        help="Print per-field diffs for items present in both.")
    parser.add_argument("--news-only", action="store_true",
                        help="Skip the AI threat-posts comparison.")
    parser.add_argument("--ai-only", action="store_true",
                        help="Skip the news_items comparison.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    if args.news_only and args.ai_only:
        print("--news-only and --ai-only are mutually exclusive.", file=sys.stderr)
        return 64
    rc = 0
    if not args.ai_only:
        rc |= compare_news(full=args.full)
    if not args.news_only:
        rc |= compare_ai_posts(full=args.full)
    return 1 if rc else 0


if __name__ == "__main__":
    raise SystemExit(main())
