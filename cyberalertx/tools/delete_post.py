"""Remove one or more posts from every store (idempotent).

Wipes the fingerprint from:
  * data/items.json
  * data/threat_posts.json (both `:en` and `:ua` entries)
  * Postgres news_items
  * Postgres threat_posts

Accepts fingerprints directly OR full post URLs (cyberalertx.com/{en,ua}/threat/<fp>);
URLs are parsed to extract the fingerprint, so you can paste straight from
the browser address bar.

Usage:
    # By fingerprint
    python -m cyberalertx.tools.delete_post 97ef5824aababb5e
    python -m cyberalertx.tools.delete_post 97ef5824aababb5e 1e80b9662a6d9493

    # By URL (locale path is ignored)
    python -m cyberalertx.tools.delete_post https://cyberalertx.com/ua/threat/97ef5824aababb5e

    # Mixed
    python -m cyberalertx.tools.delete_post 97ef5824aababb5e https://cyberalertx.com/en/threat/1e80b9662a6d9493

    # Preview without writing
    python -m cyberalertx.tools.delete_post --dry-run <fp>

Idempotent: passing an already-deleted fingerprint is a no-op (reports
"0 removed"). Exit code 0 even if nothing matched — the END STATE is what
the caller wants. Non-zero exit only when an actual error occurred (e.g.,
PG unreachable).

Use case: an item slipped through the relevance filter and is showing up
on the site. You see the URL, you paste it here, it's gone. The 60-second
ISR window will refresh the page; Cloudflare might serve cached HTML for
a few minutes longer.
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import re
import sys
from typing import Iterable

from ..ai.config import AI_SETTINGS
from ..config import SETTINGS

logger = logging.getLogger("delete_post")

# Matches the 16-hex-char fingerprint that NewsItem produces.
_FP_RE = re.compile(r"\b([0-9a-f]{16})\b")


def _parse_arg_as_fingerprint(raw: str) -> str | None:
    """Accept either a bare fingerprint or a /threat/<fp> URL. Return the
    fingerprint, or None if the input doesn't match the shape."""
    raw = raw.strip()
    # Plain fingerprint
    if _FP_RE.fullmatch(raw):
        return raw
    # URL — pull the last 16-hex segment.
    matches = _FP_RE.findall(raw)
    if matches:
        return matches[-1]
    return None


def _remove_from_items_json(fingerprints: set[str], *, dry_run: bool) -> int:
    """Strip rows from items.json. Returns the count actually removed."""
    items_path = pathlib.Path(SETTINGS.storage_path)
    if not items_path.exists():
        return 0
    data = json.loads(items_path.read_text())
    before = len(data.get("items", []))
    kept = [i for i in data["items"] if i.get("fingerprint") not in fingerprints]
    removed = before - len(kept)
    if not dry_run and removed:
        data["items"] = kept
        items_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return removed


def _remove_from_threat_posts_json(fingerprints: set[str], *, dry_run: bool) -> int:
    """Strip (fingerprint, locale) keys from threat_posts.json. Returns count removed."""
    cache_path = pathlib.Path(AI_SETTINGS.cache_path)
    if not cache_path.exists():
        return 0
    data = json.loads(cache_path.read_text())
    posts = data.get("posts", {})
    keys_to_drop = [
        k for k in posts.keys()
        if k.split(":", 1)[0] in fingerprints
    ]
    if not dry_run and keys_to_drop:
        for k in keys_to_drop:
            posts.pop(k, None)
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return len(keys_to_drop)


def _remove_from_pg(fingerprints: set[str], *, dry_run: bool) -> tuple[int, int]:
    """Delete from PG news_items and threat_posts. Returns (news_rows, post_rows).

    Raises if PG is configured-but-unreachable. Returns (0, 0) silently
    when PG isn't wired (json-only backend or missing CYBERALERTX_PG_URL).
    """
    try:
        from sqlalchemy import text
        from ..storage.pg.engine import get_engine
        engine = get_engine()
    except Exception as exc:
        logger.info("PG not configured (%s) — skipping PG cleanup", exc)
        return (0, 0)
    if dry_run:
        # Count what would be deleted without writing.
        with engine.connect() as conn:
            n_news = conn.execute(
                text("SELECT count(*) FROM news_items WHERE fingerprint = ANY(:fps)"),
                {"fps": list(fingerprints)},
            ).scalar() or 0
            n_post = conn.execute(
                text("SELECT count(*) FROM threat_posts WHERE fingerprint = ANY(:fps)"),
                {"fps": list(fingerprints)},
            ).scalar() or 0
        return (int(n_news), int(n_post))
    with engine.begin() as conn:
        n_news = conn.execute(
            text("DELETE FROM news_items WHERE fingerprint = ANY(:fps)"),
            {"fps": list(fingerprints)},
        ).rowcount or 0
        n_post = conn.execute(
            text("DELETE FROM threat_posts WHERE fingerprint = ANY(:fps)"),
            {"fps": list(fingerprints)},
        ).rowcount or 0
    return (int(n_news), int(n_post))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n", 1)[0],
    )
    parser.add_argument(
        "targets",
        nargs="+",
        help="Fingerprints or /threat/<fp> URLs to remove.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts that would change without writing.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    fingerprints: set[str] = set()
    bad: list[str] = []
    for raw in args.targets:
        fp = _parse_arg_as_fingerprint(raw)
        if fp is None:
            bad.append(raw)
        else:
            fingerprints.add(fp)

    if bad:
        print(
            f"Could not extract a fingerprint from: {bad!r}",
            file=sys.stderr,
        )
        return 2
    if not fingerprints:
        print("No targets to delete.", file=sys.stderr)
        return 2

    print(f"[delete_post] targets: {sorted(fingerprints)}")
    if args.dry_run:
        print("[delete_post] --dry-run (no writes)")

    n_items = _remove_from_items_json(fingerprints, dry_run=args.dry_run)
    print(f"[delete_post] items.json:        {n_items} rows")

    n_tp = _remove_from_threat_posts_json(fingerprints, dry_run=args.dry_run)
    print(f"[delete_post] threat_posts.json: {n_tp} keys")

    try:
        n_pg_news, n_pg_post = _remove_from_pg(fingerprints, dry_run=args.dry_run)
    except Exception as exc:
        print(f"[delete_post] PG cleanup FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[delete_post] PG news_items:     {n_pg_news} rows")
    print(f"[delete_post] PG threat_posts:   {n_pg_post} rows")

    if args.dry_run:
        print("[delete_post] no changes made (dry-run).")
    else:
        print("[delete_post] done. ISR will refresh the live page within ~60s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
