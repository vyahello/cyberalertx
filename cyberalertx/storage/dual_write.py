"""Dual-write wrapper: primary store is authoritative; secondary is shadow.

Writes fan out to BOTH stores in order. Secondary exceptions are caught
and logged — they NEVER propagate. The production ingest pipeline must
not break because Postgres is down, the SSL handshake timed out, the
schema migration is mid-flight, or any other transient PG hiccup.

Reads come from PRIMARY only. The read-path migration is a separate PR.

Why a wrapper instead of two parallel stores in the pipeline:
  * one `upsert_many()` call from the orchestrator, two writes — keeps
    the orchestrator unaware of the migration in progress
  * the new-vs-existing return value comes from the PRIMARY, which is
    what every downstream consumer is already coded against
  * a single place to add per-write telemetry (failure counts, latency)
    when the migration matures
"""
from __future__ import annotations

import logging
import time
from typing import Iterable, List, Optional, Protocol

from ..ai.models import ThreatPost
from ..models import NewsItem
from .base import NewsRepository

logger = logging.getLogger(__name__)


class ThreatPostStore(Protocol):
    """ThreatPostCache-compatible interface — the contract both JSON cache
    and PG store satisfy. Lives here so the dual-write wrapper can type-
    check both backends without circular imports with ai.cache."""

    def get(self, fingerprint: str, locale: str = "en") -> Optional[ThreatPost]: ...
    def set(self, fingerprint: str, locale: str, post: ThreatPost) -> None: ...
    def all(self) -> Iterable[ThreatPost]: ...
    def __len__(self) -> int: ...


class DualWriteNewsStore(NewsRepository):
    """`NewsRepository` that writes to two backends, reads from primary."""

    def __init__(
        self,
        primary: NewsRepository,
        secondary: NewsRepository,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        # Telemetry counters — readable by ops scripts without dragging in a
        # full metrics dependency. Reset on process restart.
        self._secondary_failures: int = 0
        self._secondary_successes: int = 0

    # ----- reads come from primary only ------------------------------

    def known_fingerprints(self) -> set[str]:
        return self._primary.known_fingerprints()

    def all(self) -> List[NewsItem]:
        return self._primary.all()

    # ----- writes fan out --------------------------------------------

    def upsert_many(self, items: Iterable[NewsItem]) -> List[NewsItem]:
        # Materialize once — `items` may be a single-use iterator.
        items_list = list(items)
        # Primary is authoritative: its result is what we return. Errors
        # from primary DO propagate (that's the current JSON-only behavior).
        result = self._primary.upsert_many(items_list)
        # Secondary is shadow: any error is swallowed.
        t0 = time.monotonic()
        try:
            self._secondary.upsert_many(items_list)
            self._secondary_successes += 1
            logger.debug(
                "dual-write: secondary upsert ok (n=%d, ms=%.1f)",
                len(items_list), (time.monotonic() - t0) * 1000,
            )
        except Exception as exc:
            self._secondary_failures += 1
            logger.warning(
                "dual-write: secondary upsert FAILED (n=%d, ms=%.1f, "
                "%s: %s) — primary write succeeded, continuing.",
                len(items_list), (time.monotonic() - t0) * 1000,
                type(exc).__name__, exc,
            )
        return result

    # ----- diagnostics -----------------------------------------------

    @property
    def shadow_stats(self) -> dict[str, int]:
        """Returns {'successes': N, 'failures': M} since process start."""
        return {
            "successes": self._secondary_successes,
            "failures": self._secondary_failures,
        }


class DualWriteThreatPostCache:
    """ThreatPost cache that writes to both stores, reads JSON-first with PG fallback.

    Read strategy:
      * Primary read = JSON cache. It's an in-memory dict mirrored to PG via
        dual-write — reads cost nothing (one mtime stat + dict lookup) so the
        feed render loop never pays Supabase latency on a cache hit.
      * Fallback = PG. Catches the rare case where JSON misses a key that PG
        has (a peer instance wrote it, or JSON file got partially corrupted).
        Also the path used by ops tooling that has a fresh process without
        a warm JSON cache.

    Note: an earlier draft of this wrapper tried PG first to match a
    surface-level reading of the PR-2 spec ("feed reads from PG"). In
    practice, that meant a Supabase round-trip per item in every feed
    render — 2-3 seconds of added latency per locale switch over eu-west-1.
    The PR-2 spec also says "primary read source remains JSON during
    migration" (item 2). JSON-first is the reconciliation: JSON is the
    fast in-memory primary, PG is the source-of-truth fallback. Both stay
    in sync via dual-write; reading either is correct.

    Write strategy: JSON write is authoritative (raises on error). PG write
    is shadow (logged on error, never raised).
    """

    def __init__(
        self,
        primary: "ThreatPostStore",
        secondary: "ThreatPostStore",
    ) -> None:
        # `primary` is the JSON cache (write-authoritative + fast read).
        # `secondary` is the PG store (shadow write + fallback read).
        self._json = primary
        self._pg = secondary
        self._secondary_failures: int = 0
        self._secondary_successes: int = 0
        self._read_fallbacks: int = 0

    def get(self, fingerprint: str, locale: str = "en") -> Optional[ThreatPost]:
        # Fast path: in-memory JSON cache. ~microseconds.
        post = self._json.get(fingerprint, locale)
        if post is not None:
            return post
        # JSON miss — try PG. Costs a Supabase round-trip but rare:
        # JSON has every entry that dual-write produced. A miss here means
        # PG has something JSON doesn't (peer instance, manual import).
        try:
            return self._pg.get(fingerprint, locale)
        except Exception as exc:
            logger.warning(
                "PG fallback read failed for %s/%s (%s: %s) — returning miss.",
                fingerprint, locale, type(exc).__name__, exc,
            )
            self._read_fallbacks += 1
            return None

    def set(self, fingerprint: str, locale: str, post: ThreatPost) -> None:
        # JSON write is authoritative — any error propagates.
        self._json.set(fingerprint, locale, post)
        # PG write is shadow — failure is logged, never raised.
        t0 = time.monotonic()
        try:
            self._pg.set(fingerprint, locale, post)
            self._secondary_successes += 1
            logger.debug(
                "dual-write: PG threat-post set ok (%s/%s, ms=%.1f)",
                fingerprint, locale, (time.monotonic() - t0) * 1000,
            )
        except Exception as exc:
            self._secondary_failures += 1
            logger.warning(
                "dual-write: PG threat-post set FAILED (%s/%s, ms=%.1f, "
                "%s: %s) — JSON write succeeded, continuing.",
                fingerprint, locale, (time.monotonic() - t0) * 1000,
                type(exc).__name__, exc,
            )

    def all(self) -> Iterable[ThreatPost]:
        # Delegate to JSON — `all()` is used by ops tooling, not the
        # request path, and JSON is fast for that scan.
        return self._json.all()

    def __len__(self) -> int:
        try:
            return len(self._json)
        except TypeError:
            return sum(1 for _ in self._json.all())

    @property
    def shadow_stats(self) -> dict[str, int]:
        return {
            "successes": self._secondary_successes,
            "failures": self._secondary_failures,
            "read_fallbacks": self._read_fallbacks,
        }


__all__ = [
    "DualWriteNewsStore",
    "DualWriteThreatPostCache",
    "ThreatPostStore",
]
