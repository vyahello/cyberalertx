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
import os
import threading
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
    def delete(self, fingerprint: str, locale: str) -> bool: ...
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


class SecondaryWriteError(RuntimeError):
    """The authoritative JSON write succeeded; the Postgres write did not."""

    def __init__(self, fingerprint: str, locale: str, cause: BaseException) -> None:
        super().__init__(
            f"saved in JSON, but the Postgres write failed for {fingerprint}:{locale} "
            f"({type(cause).__name__}: {cause}); retry the decision to sync"
        )
        self.fingerprint = fingerprint
        self.locale = locale


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return value if value >= 0 else default


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

    Fallback cost (O27): the fallback never queries per item. A key index
    of PG (one keys-only SELECT) is refreshed at most once per
    `CYBERALERTX_PG_INDEX_TTL_SECONDS` (default 60), and the payloads of the
    keys PG has but JSON lacks are loaded in the same refresh with one batch
    query. A JSON miss for a key PG does not hold returns at once. This
    process's own writes and deletes update the index immediately; rows a
    *peer* writes only to PG become visible within one TTL (a peer writing
    through this wrapper also writes JSON, which is read first).

    Write strategy: JSON write is authoritative (raises on error). PG write
    is shadow (logged on error, never raised).
    """

    def __init__(
        self,
        primary: "ThreatPostStore",
        secondary: "ThreatPostStore",
        *,
        index_ttl: Optional[float] = None,
    ) -> None:
        # `primary` is the JSON cache (write-authoritative + fast read).
        # `secondary` is the PG store (shadow write + fallback read).
        self._json = primary
        self._pg = secondary
        self._secondary_failures: int = 0
        self._secondary_successes: int = 0
        self._read_fallbacks: int = 0
        # O27: PG fallback index. A feed render calls `get` several times per
        # item; before this, every JSON miss cost one Supabase round-trip
        # (~70 ms), sequentially, so a 40-post feed spent seconds on misses.
        # Now: one keys-only query (plus at most one batch payload query for
        # keys JSON lacks) per refresh, and zero queries per request.
        self._index_ttl = index_ttl if index_ttl is not None else _env_float(
            "CYBERALERTX_PG_INDEX_TTL_SECONDS", 60.0)
        self._index_lock = threading.Lock()          # short critical sections only, never held over I/O
        self._index_ready = threading.Event()        # set after the first load attempt
        self._load_done = threading.Event()
        self._load_done.set()
        self._first_load_wait = 2.0                  # max seconds a read waits for the very first load
        self._loading = False
        self._last_load_ok = False
        self._pending: dict[tuple[str, str], bool] = {}
        self._pg_keys: Optional[frozenset[tuple[str, str]]] = None
        self._pg_only: dict[tuple[str, str], Optional[ThreatPost]] = {}
        self._index_next_refresh: float = 0.0
        self._index_loads: int = 0
        self._index_failures: int = 0

    def get(self, fingerprint: str, locale: str = "en") -> Optional[ThreatPost]:
        # Fast path: in-memory JSON cache. ~microseconds.
        post = self._json.get(fingerprint, locale)
        if post is not None:
            return post
        # JSON is authoritative. If its file is unreadable, a miss proves
        # nothing, and PG may hold an older editorial decision (the API runs
        # JSON-only during Stage C, O28): fail closed rather than resurrect it.
        if getattr(self._json, "unreadable", False):
            logger.warning("JSON post cache unreadable; not falling back to PG for %s/%s", fingerprint, locale)
            return None
        key = (fingerprint, locale)
        if not self._has_index():
            return self._pg_get(fingerprint, locale)       # store without keys(): legacy path
        self._ensure_index()
        keys = self._pg_keys
        if keys is None or key not in keys:
            return None                                    # PG does not have it either: no query
        if key in self._pg_only:
            return self._pg_only[key]                      # loaded by the batch query
        # Indexed in PG, absent from JSON, not in the batch (JSON lost it
        # after the refresh, or JSON cannot list its keys): one lookup, kept
        # until the next refresh so a feed never repeats it.
        try:
            post = self._pg.get(fingerprint, locale)
        except Exception as exc:
            logger.warning(
                "PG fallback read failed for %s/%s (%s: %s) — returning miss.",
                fingerprint, locale, type(exc).__name__, exc,
            )
            self._read_fallbacks += 1
            return None
        self._pg_only[key] = post                          # a miss is remembered too
        return post

    # ----- O27 index ----------------------------------------------------

    def _has_index(self) -> bool:
        return callable(getattr(self._pg, "keys", None))

    def _pg_get(self, fingerprint: str, locale: str) -> Optional[ThreatPost]:
        try:
            return self._pg.get(fingerprint, locale)
        except Exception as exc:
            logger.warning(
                "PG fallback read failed for %s/%s (%s: %s) — returning miss.",
                fingerprint, locale, type(exc).__name__, exc,
            )
            self._read_fallbacks += 1
            return None

    def _ensure_index(self) -> None:
        """Read path: start a background load when one is due; wait (bounded)
        only while the very first load is still running. A request never does
        Postgres I/O itself, so a slow or unreachable database cannot stall
        the feed."""
        if time.monotonic() >= self._index_next_refresh:
            self._start_load()
        if self._pg_keys is None:
            self._index_ready.wait(self._first_load_wait)

    def _start_load(self) -> bool:
        with self._index_lock:
            if self._loading or time.monotonic() < self._index_next_refresh:
                return False
            self._loading = True
            self._pending = {}
            self._load_done.clear()
        threading.Thread(target=self._load_index, name="pg-key-index", daemon=True).start()
        return True

    def _load_index(self) -> None:
        t0 = time.monotonic()
        try:
            pg_keys = frozenset(self._pg.keys())  # type: ignore[attr-defined]
            json_keys_fn = getattr(self._json, "keys", None)
            pg_only: dict[tuple[str, str], Optional[ThreatPost]] = {}
            if callable(json_keys_fn):
                missing = pg_keys - set(json_keys_fn())
                get_many = getattr(self._pg, "get_many", None)
                if missing and callable(get_many):
                    pg_only = dict(get_many(missing))
        except Exception as exc:
            with self._index_lock:
                self._loading = False
                self._last_load_ok = False
                self._index_failures += 1
                self._read_fallbacks += 1
                # Keep the previous index if there is one; otherwise misses
                # stay misses (as a failed per-item read did). Retry soon.
                self._index_next_refresh = time.monotonic() + min(self._index_ttl, 10.0)
            self._index_ready.set()      # readers must not wait for a failing database again
            self._load_done.set()
            logger.warning("PG key index load failed (%s: %s); misses stay misses, retrying in %.0f s.",
                           type(exc).__name__, exc, min(self._index_ttl, 10.0))
            return
        with self._index_lock:
            # Own writes and deletes made while the snapshot was being read
            # win over it: a delete must never be undone by a stale snapshot.
            keys = set(pg_keys)
            for key, present in self._pending.items():
                (keys.add if present else keys.discard)(key)
                pg_only.pop(key, None)
            first = self._pg_keys is None
            self._pg_keys, self._pg_only = frozenset(keys), pg_only
            self._pending = {}
            self._loading = False
            self._last_load_ok = True
            self._index_loads += 1
            self._index_next_refresh = time.monotonic() + self._index_ttl
        self._index_ready.set()
        self._load_done.set()
        (logger.info if first else logger.debug)(
            "PG key index loaded: %d keys, %d only in PG, ms=%.0f",
            len(keys), len(pg_only), (time.monotonic() - t0) * 1000)

    def _index_add(self, key: tuple[str, str]) -> None:
        # The write landed in JSON, which now wins for this key.
        with self._index_lock:
            if self._pg_keys is not None:
                self._pg_keys = self._pg_keys | {key}
            self._pg_only.pop(key, None)
            if self._loading:
                self._pending[key] = True

    def _index_discard(self, key: tuple[str, str]) -> None:
        with self._index_lock:
            if self._pg_keys is not None:
                self._pg_keys = self._pg_keys - {key}
            self._pg_only.pop(key, None)
            if self._loading:
                self._pending[key] = False

    def warm_index_async(self) -> None:
        """Start loading the index now, so the first feed request after a
        restart does not pay for it."""
        if self._has_index():
            self._start_load()

    def refresh_index(self, timeout: float = 30.0) -> bool:
        """Reload the index now and wait for it (ops tooling, tests).
        Returns False if the load failed or did not finish in time."""
        if not self._has_index():
            return False
        self._index_next_refresh = 0.0
        self._start_load()
        return self._load_done.wait(timeout) and self._last_load_ok

    def invalidate_index(self) -> None:
        """Make the next read start a reload (it keeps serving the old index meanwhile)."""
        self._index_next_refresh = 0.0

    def set(self, fingerprint: str, locale: str, post: ThreatPost) -> None:
        # JSON write is authoritative — any error propagates.
        self._json.set(fingerprint, locale, post)
        # PG write is shadow — failure is logged, never raised.
        t0 = time.monotonic()
        try:
            self._pg.set(fingerprint, locale, post)
            self._secondary_successes += 1
            self._index_add((fingerprint, locale))
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

    def set_strict(self, fingerprint: str, locale: str, post: ThreatPost) -> None:
        """Write both stores and RAISE if the PG half fails.

        Used for editorial decisions (review status). `set` treats PG as a
        shadow and only logs a failure, which is right for renders (the next
        render overwrites) but wrong for a human decision: PG would keep the
        old status, and any later PG-fallback read or PG-only consumer would
        silently resurrect it. JSON is still written first and stays
        authoritative; the caller gets `SecondaryWriteError` so it can tell
        the editor and retry (a retry rewrites both stores).
        """
        self._json.set(fingerprint, locale, post)
        try:
            self._pg.set(fingerprint, locale, post)
            self._secondary_successes += 1
            self._index_add((fingerprint, locale))
        except Exception as exc:
            self._secondary_failures += 1
            logger.error(
                "dual-write: PG write of an editorial decision FAILED (%s/%s, %s: %s) "
                "— saved in JSON only; retry the decision.",
                fingerprint, locale, type(exc).__name__, exc,
            )
            raise SecondaryWriteError(fingerprint, locale, exc) from exc

    def delete(self, fingerprint: str, locale: str) -> bool:
        """Forget one render in BOTH stores.

        Unlike `set`, the PG half is not merely a shadow here. `get` reads
        JSON first and falls back to PG on a miss, so a JSON-only delete
        would have the very next read resurrect the stale post — and
        `generate --refresh` would appear to work while changing nothing.

        The PG failure is still non-fatal, because a stale row there is
        recoverable (the next `set` overwrites it) and aborting the refresh
        would be worse. But it is logged loudly, since until PG catches up
        the fallback read can serve the old text.
        """
        removed = self._json.delete(fingerprint, locale)
        try:
            self._pg.delete(fingerprint, locale)
            self._index_discard((fingerprint, locale))
        except Exception as exc:
            self._secondary_failures += 1
            logger.warning(
                "dual-write: PG threat-post DELETE FAILED (%s/%s, %s: %s) — "
                "JSON entry is gone but a fallback read may still serve the "
                "stale post until it is re-rendered.",
                fingerprint, locale, type(exc).__name__, exc,
            )
        return removed

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

    @property
    def index_stats(self) -> dict[str, int]:
        """O27 PG key index: loads, failed loads, keys, PG-only payloads held."""
        keys = self._pg_keys
        return {
            "loads": self._index_loads,
            "failures": self._index_failures,
            "keys": len(keys) if keys is not None else -1,
            "pg_only": len(self._pg_only),
        }


__all__ = [
    "DualWriteNewsStore",
    "DualWriteThreatPostCache",
    "SecondaryWriteError",
    "ThreatPostStore",
]
