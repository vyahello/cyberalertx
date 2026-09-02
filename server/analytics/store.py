"""Persistent local analytics store — SQLite, stdlib only, additive forever.

logrotate keeps fourteen days of nginx logs. The user asked for "stats for all
time, by month, by days", so a stateless log reader can never answer the
question that was actually asked: by the time a month is interesting, the lines
that made it are gone. This module is the long-term memory, and everything about
it is shaped by one rule — **it may only ever add**. It never deletes, rewrites,
signals or rotates a log file; `purge()` removes database rows and nothing else,
and it is never called automatically.

IDEMPOTENCY — both mechanisms, layered, because neither alone is correct here:

* `source_files`, keyed on a content-derived `file_key`, is the FAST path. A file
  whose key, size and mtime are unchanged is skipped without being opened, which
  covers the immutable rotated archives — almost all of the work on a re-run.
* A per-line `line_hash` with a UNIQUE index is the CORRECTNESS path, because the
  live `cyberalertx-access.jsonl` grows all day: its size and mtime differ on
  every ingest, so a file-level check alone would re-insert the whole day, every
  day.

`line_hash = blake2b(file_key | lineno | raw_line)`. The POSITION is part of the
hash on purpose: byte-identical duplicate lines are real and legitimate — the
production sample contains two identical iPhone requests in the same second — so
hashing content alone would silently drop a genuine request. The identity is
`file_key` (the sha256 of the first 64 KiB decompressed) rather than the
filename, because `archive-daily.sh` copies `access.log.1.gz` to
`access-2026-09-01.log.gz` and the same stream under two names must not be
counted twice. Because the key hashes only the FIRST 64 KiB, a growing file keeps
its key as it grows, which is exactly what makes an append-only re-ingest of
today's log land on the same hashes and be rejected by the UNIQUE index.

MIGRATIONS are additive only: new columns arrive via `ALTER TABLE ... ADD COLUMN`
with a default, never a destructive rewrite and never a `DROP`. A future nginx
format version adds columns; it never invalidates rows already stored.

SCOPE: reads only cyberalertx's own dedicated log plus the shared legacy
archive, filtered to the cyberalertx vhost. The three other vhosts on this
box keep writing to /var/log/nginx/access.log untouched, and nothing here
writes to any log file, ever.

PRIVACY: nothing leaves the box. No network calls at runtime, no third-party
analytics, no dependency outside the stdlib. Raw IPs are never persisted or
printed — only salted hashes, with the salt rotated daily and retained 14 days.
The User-Agent string is likewise stored only as a salted hash (`meta.ua_salt`,
minted once per database), so the table cannot be mined for fingerprints.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import DEFAULT_DB_PATH, SESSION_GAP_MINUTES, __version__
from .logread import EXTENDED, LEGACY, LogFileInfo
from .sessionize import Event

logger = logging.getLogger("analytics.store")

SCHEMA_VERSION: int = 2
DEFAULT_BATCH_SIZE: int = 2000

# The rollup row that answers "how many pageviews on day X" without touching the
# events table. Month and all-time queries read only these rows, so their cost is
# proportional to the number of DAYS, not to the number of requests.
TOTAL_DIMENSION: str = "__total__"
TOTAL_VALUE: str = "all"

ROLLUP_DIMENSIONS: tuple[str, ...] = (
    "country",
    "browser",
    "os",
    "device",
    "channel",
    "locale",
    "language",
    "article",
    "vendor",
    "model",
    "in_app",
    "status",
    "hour",
    "klass",
    "category",
    "bot",
)

_SCHEMA: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """
    CREATE TABLE IF NOT EXISTS events (
        id            INTEGER PRIMARY KEY,
        line_hash     TEXT NOT NULL UNIQUE,
        utc_epoch     INTEGER NOT NULL,
        local_date    TEXT NOT NULL,
        local_hour    INTEGER NOT NULL,
        weekday       INTEGER NOT NULL,
        host          TEXT,
        method        TEXT,
        path          TEXT NOT NULL,
        locale        TEXT,
        page_kind     TEXT NOT NULL,
        article_id    TEXT,
        nav           TEXT NOT NULL,
        is_pageview   INTEGER NOT NULL,
        status        INTEGER,
        body_bytes    INTEGER,
        total_bytes   INTEGER,
        request_time  REAL,
        upstream_time REAL,
        referer_host  TEXT,
        channel       TEXT NOT NULL,
        campaign      TEXT,
        ua_hash       TEXT,
        browser       TEXT,
        browser_ver   TEXT,
        os            TEXT,
        os_ver        TEXT,
        os_ver_ok     INTEGER,
        device_type   TEXT,
        vendor        TEXT,
        model         TEXT,
        model_source  TEXT,
        in_app        TEXT,
        country       TEXT,
        language      TEXT,
        lang_region   TEXT,
        klass         TEXT NOT NULL,
        category      TEXT NOT NULL,
        bot_label     TEXT,
        subclass      TEXT,
        subscribers   INTEGER,
        rule          TEXT NOT NULL,
        visitor       TEXT,
        log_format    TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_events_date     ON events(local_date)",
    "CREATE INDEX IF NOT EXISTS ix_events_visitor  ON events(local_date, visitor)",
    "CREATE INDEX IF NOT EXISTS ix_events_pageview ON events(local_date, is_pageview, klass)",
    """
    CREATE TABLE IF NOT EXISTS rollup (
        local_date  TEXT NOT NULL,
        dimension   TEXT NOT NULL,
        value       TEXT NOT NULL,
        pageviews   INTEGER NOT NULL DEFAULT 0,
        sessions    INTEGER NOT NULL DEFAULT 0,
        visitors    INTEGER NOT NULL DEFAULT 0,
        events      INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (local_date, dimension, value)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS capabilities (
        local_date          TEXT PRIMARY KEY,
        log_format          TEXT NOT NULL,
        has_host            INTEGER NOT NULL,
        has_client_ip       INTEGER NOT NULL,
        has_country         INTEGER NOT NULL,
        has_accept_language INTEGER NOT NULL,
        has_client_hints    INTEGER NOT NULL,
        has_rsc_headers     INTEGER NOT NULL,
        has_timing          INTEGER NOT NULL,
        events              INTEGER NOT NULL,
        first_seen          TEXT NOT NULL,
        last_seen           TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_files (
        file_key       TEXT PRIMARY KEY,
        last_path      TEXT NOT NULL,
        size           INTEGER NOT NULL,
        mtime          REAL NOT NULL,
        first_line     TEXT NOT NULL,
        lines_ingested INTEGER NOT NULL,
        bytes_ingested INTEGER NOT NULL,
        ingested_at    TEXT NOT NULL
    )
    """,
)

# Numbered migration steps applied in order. Version 0 (no meta table at all)
# means a fresh database and _SCHEMA creates everything. Every future entry must
# be an ALTER TABLE ... ADD COLUMN or a CREATE; a step that drops or rewrites
# data does not belong here.
_MIGRATIONS: dict[int, tuple[str, ...]] = {
    # v1 -> v2. The three-way agent split (self / reach / feed) and the
    # subscriber count a feed reader announces in its UA were computed at
    # ingest and then thrown away, because neither had a column. Every
    # store-backed report therefore rendered LINK SHARES (REACH) and FEED
    # SUBSCRIBERS as empty tables while --from-logs on the same data filled
    # them, which is precisely the silent divergence the rollup exists to
    # prevent. Additive: rows written before this step keep NULL and simply do
    # not contribute to those two tables until `ingest --reingest` rebuilds
    # them.
    2: (
        "ALTER TABLE events ADD COLUMN subclass TEXT",
        "ALTER TABLE events ADD COLUMN subscribers INTEGER",
    ),
}

_EVENT_COLUMNS: tuple[str, ...] = (
    "line_hash",
    "utc_epoch",
    "local_date",
    "local_hour",
    "weekday",
    "host",
    "method",
    "path",
    "locale",
    "page_kind",
    "article_id",
    "nav",
    "is_pageview",
    "status",
    "body_bytes",
    "total_bytes",
    "request_time",
    "upstream_time",
    "referer_host",
    "channel",
    "campaign",
    "ua_hash",
    "browser",
    "browser_ver",
    "os",
    "os_ver",
    "os_ver_ok",
    "device_type",
    "vendor",
    "model",
    "model_source",
    "in_app",
    "country",
    "language",
    "lang_region",
    "klass",
    "category",
    "bot_label",
    "subclass",
    "subscribers",
    "rule",
    "visitor",
    "log_format",
)

_INSERT_SQL = (
    "INSERT OR IGNORE INTO events (" + ", ".join(_EVENT_COLUMNS) + ") "
    "VALUES (" + ", ".join("?" * len(_EVENT_COLUMNS)) + ")"
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SourceFile:
    """One ingested log file, identified by content rather than by name."""

    file_key: str
    last_path: str
    size: int
    mtime: float
    first_line: str
    lines_ingested: int
    bytes_ingested: int
    ingested_at: str


@dataclass(frozen=True, slots=True)
class DayCapabilities:
    """Which dimensions actually existed on one calendar day.

    Reports MUST read this and LABEL periods where a dimension did not exist.
    Plotting a zero for "country" on a day when nginx was not yet logging
    CF-IPCountry is a lie about the world, not a fact about the traffic.
    """

    local_date: str
    log_format: str          # extended | legacy | mixed
    has_host: bool
    has_client_ip: bool
    has_country: bool
    has_accept_language: bool
    has_client_hints: bool
    has_rsc_headers: bool
    has_timing: bool
    events: int
    first_seen: str
    last_seen: str

    def dimensions(self) -> frozenset[str]:
        """The Coverage-vocabulary dimension names available on this day."""
        available: set[str] = set()
        if self.has_country:
            available.add("country")
        if self.has_client_ip:
            available.add("visitor")
        if self.has_accept_language:
            available.add("language")
        if self.has_client_hints:
            available.add("client_hints")
        if self.has_rsc_headers:
            available.add("rsc")
        if self.has_timing:
            available.add("timing")
        if self.has_host:
            available.add("host")
        return frozenset(available)


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What one `ingest` run did. Returned to the CLI, printed, then discarded."""

    files_seen: int
    files_ingested: int
    files_skipped: int
    lines_read: int
    events_inserted: int
    duplicates_skipped: int
    unparseable: int
    dates_touched: tuple[str, ...]
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class StoreStatus:
    """What the database holds right now — the `status` subcommand's payload."""

    path: str
    size_bytes: int
    schema_version: int
    first_date: str | None
    last_date: str | None
    days_present: int
    days_missing: tuple[str, ...]
    total_events: int
    total_pageviews: int
    last_ingest_at: str | None
    capabilities: tuple[DayCapabilities, ...]
    source_files: int


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------
class AnalyticsStore:
    """SQLite-backed event store with daily rollups and per-day capabilities."""

    def __init__(self, path: Path = DEFAULT_DB_PATH, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        self.touched_dates: set[str] = set()
        self._ua_salt: str | None = None
        if not read_only:
            # data/ is created defensively, matching JsonNewsStore and
            # QualityMetrics elsewhere in this repo.
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not self.path.exists()
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            if fresh:
                # The database holds salted visitor hashes and a full path
                # history. 0600 before the first row lands in it.
                self._chmod_private()
        else:
            uri = f"file:{self.path}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if not read_only:
            # WAL keeps a long ingest from blocking a concurrent report; NORMAL
            # is the right durability trade for data that can always be
            # re-ingested from the logs it came from. Both PRAGMAs write, so a
            # read-only connection must not attempt them.
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self.migrate()

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> AnalyticsStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:  # pragma: no cover - defensive
            logger.warning("Error closing %s", self.path, exc_info=True)

    def _chmod_private(self) -> None:
        try:
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover - defensive
            logger.warning("Could not chmod 0600 %s", self.path)

    # -- schema ------------------------------------------------------------
    def schema_version(self) -> int:
        try:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
        if row is None:
            return 0
        try:
            return int(row["value"])
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return 0

    def _apply_migration_step(self, statement: str) -> None:
        """Run one additive migration statement, tolerating an already-applied one.

        SQLite has no `ADD COLUMN IF NOT EXISTS`, and a migration must be safe to
        re-run: a fresh database gets the finished schema from `_SCHEMA` and then
        still walks the step list. Rather than special-casing "is this database
        new", ask the table what columns it has and skip the ones already
        present. Anything that is not an ADD COLUMN is executed as written.
        """
        head = statement.strip().upper()
        if head.startswith("ALTER TABLE") and " ADD COLUMN " in head:
            parts = statement.split()
            table, column = parts[2], parts[5]
            existing = {
                str(row["name"])
                for row in self._conn.execute(f"PRAGMA table_info({table})")
            }
            if column in existing:
                logger.debug("migration skipped, %s.%s already exists", table, column)
                return
        self._conn.execute(statement)

    def migrate(self) -> int:
        """Bring the schema up to SCHEMA_VERSION. Returns the resulting version.

        `_SCHEMA` always describes the CURRENT shape, so a database created here
        is born at SCHEMA_VERSION and needs no migration steps at all. An
        existing database reports a lower version and gets the steps above it.
        Each step is applied through `_add_column_if_missing`, which makes an
        `ADD COLUMN` a no-op when the column is already there — without that,
        the fresh-database path (version 0, but a table `_SCHEMA` just created
        complete) would immediately fail with 'duplicate column name'.
        """
        current = self.schema_version()
        with self._conn:
            for statement in _SCHEMA:
                self._conn.execute(statement)
            for step in sorted(_MIGRATIONS):
                if step > current:
                    for statement in _MIGRATIONS[step]:
                        self._apply_migration_step(statement)
            now = _utc_now_iso()
            self._conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('created_at', ?)", (now,)
            )
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('tool_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (__version__,),
            )
        self._chmod_private()
        return SCHEMA_VERSION

    def _meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def _set_meta(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def ua_salt(self) -> str:
        """Per-database salt for the User-Agent hash, minted once and kept.

        A raw UA string is a fingerprint component and is never stored. An
        UNSALTED hash would be trivially reversible by dictionary — there are
        only so many UA strings in the world — so the hash is salted with a
        value that never leaves this file. It is stable for the life of the
        database, which is what lets `ua_hash` be joined across days.
        """
        if self._ua_salt is None:
            existing = self._meta("ua_salt")
            if existing is None:
                existing = secrets.token_hex(16)
                self._set_meta("ua_salt", existing)
            self._ua_salt = existing
        return self._ua_salt

    # -- ingest ------------------------------------------------------------
    def needs_ingest(self, info: LogFileInfo, *, reingest: bool = False) -> bool:
        """Whether a file must be opened at all.

        The fast path: an archive whose content key, size and mtime all match a
        previous ingest cannot have changed, so it is skipped without being
        read. Today's live log fails this test every time — it grows — and falls
        through to the per-line UNIQUE index, which rejects the lines already
        stored and accepts only the new tail.
        """
        if reingest:
            return True
        row = self._conn.execute(
            "SELECT size, mtime FROM source_files WHERE file_key = ?", (info.file_key,)
        ).fetchone()
        if row is None:
            return True
        return not (int(row["size"]) == int(info.size) and float(row["mtime"]) == float(info.mtime))

    def ingest_events(
        self,
        events: Iterable[Event],
        *,
        source: LogFileInfo,
        batch_size: int = DEFAULT_BATCH_SIZE,
        dry_run: bool = False,
    ) -> tuple[int, int]:
        """Insert events from one source file. Returns (inserted, duplicates).

        Streams and batch-inserts: at most `batch_size` rows exist in memory at
        once, so a multi-hundred-megabyte log ingests without the process
        growing with the file. Per-day capability records are accumulated during
        the same pass and written at the end, so no second read of anything is
        needed.
        """
        ua_salt = self.ua_salt()
        batch: list[tuple[object, ...]] = []
        inserted = 0
        attempted = 0
        caps: dict[str, _CapabilityTally] = {}

        for event in events:
            attempted += 1
            batch.append(_event_row(event, ua_salt=ua_salt, source=source))
            self.touched_dates.add(event.date)
            caps.setdefault(event.date, _CapabilityTally(event.date)).observe(event)
            if len(batch) >= batch_size:
                inserted += self._flush(batch, dry_run=dry_run)
                batch.clear()
        if batch:
            inserted += self._flush(batch, dry_run=dry_run)
            batch.clear()

        if not dry_run:
            for tally in caps.values():
                self.record_capabilities(tally.build())
            self._set_meta("last_ingest_at", _utc_now_iso())
        return inserted, attempted - inserted

    def _flush(self, batch: Sequence[tuple[object, ...]], *, dry_run: bool) -> int:
        if dry_run:
            # A dry run must write nothing at all — not a row, not a source-file
            # record, not a meta timestamp. It still reports honestly by asking
            # the UNIQUE index which of these hashes it already holds.
            hashes = [row[0] for row in batch]
            placeholders = ",".join("?" * len(hashes))
            known = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM events WHERE line_hash IN ({placeholders})",
                hashes,
            ).fetchone()
            return len(batch) - int(known["n"])
        before = self._conn.total_changes
        with self._conn:
            self._conn.executemany(_INSERT_SQL, batch)
        return self._conn.total_changes - before

    def record_source(self, info: SourceFile) -> None:
        """Remember that a file was ingested, keyed on content, not on filename."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO source_files "
                "(file_key, last_path, size, mtime, first_line, lines_ingested, "
                " bytes_ingested, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(file_key) DO UPDATE SET "
                "  last_path = excluded.last_path, size = excluded.size, "
                "  mtime = excluded.mtime, first_line = excluded.first_line, "
                "  lines_ingested = source_files.lines_ingested + excluded.lines_ingested, "
                "  bytes_ingested = excluded.bytes_ingested, "
                "  ingested_at = excluded.ingested_at",
                (
                    info.file_key,
                    info.last_path,
                    int(info.size),
                    float(info.mtime),
                    info.first_line[:512],
                    int(info.lines_ingested),
                    int(info.bytes_ingested),
                    info.ingested_at,
                ),
            )

    def record_capabilities(self, cap: DayCapabilities) -> None:
        """Upsert one day's capability record, merging with what is already there.

        On a mixed day `log_format` becomes 'mixed' and each has_* flag is the OR
        across the day's rows: the nginx change lands mid-afternoon, and from
        that moment country and visitor data exist for part of the day. The
        report labels such a day partial rather than claiming the dimension for
        all of it.
        """
        existing = self._conn.execute(
            "SELECT * FROM capabilities WHERE local_date = ?", (cap.local_date,)
        ).fetchone()
        if existing is None:
            merged = cap
        else:
            fmt = existing["log_format"]
            log_format = fmt if fmt == cap.log_format else "mixed"
            merged = DayCapabilities(
                local_date=cap.local_date,
                log_format=log_format,
                has_host=bool(existing["has_host"]) or cap.has_host,
                has_client_ip=bool(existing["has_client_ip"]) or cap.has_client_ip,
                has_country=bool(existing["has_country"]) or cap.has_country,
                has_accept_language=bool(existing["has_accept_language"]) or cap.has_accept_language,
                has_client_hints=bool(existing["has_client_hints"]) or cap.has_client_hints,
                has_rsc_headers=bool(existing["has_rsc_headers"]) or cap.has_rsc_headers,
                has_timing=bool(existing["has_timing"]) or cap.has_timing,
                events=int(existing["events"]) + cap.events,
                first_seen=min(str(existing["first_seen"]), cap.first_seen),
                last_seen=max(str(existing["last_seen"]), cap.last_seen),
            )
        with self._conn:
            self._conn.execute(
                "INSERT INTO capabilities "
                "(local_date, log_format, has_host, has_client_ip, has_country, "
                " has_accept_language, has_client_hints, has_rsc_headers, has_timing, "
                " events, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(local_date) DO UPDATE SET "
                "  log_format = excluded.log_format, has_host = excluded.has_host, "
                "  has_client_ip = excluded.has_client_ip, has_country = excluded.has_country, "
                "  has_accept_language = excluded.has_accept_language, "
                "  has_client_hints = excluded.has_client_hints, "
                "  has_rsc_headers = excluded.has_rsc_headers, "
                "  has_timing = excluded.has_timing, events = excluded.events, "
                "  first_seen = excluded.first_seen, last_seen = excluded.last_seen",
                (
                    merged.local_date,
                    merged.log_format,
                    int(merged.has_host),
                    int(merged.has_client_ip),
                    int(merged.has_country),
                    int(merged.has_accept_language),
                    int(merged.has_client_hints),
                    int(merged.has_rsc_headers),
                    int(merged.has_timing),
                    int(merged.events),
                    merged.first_seen,
                    merged.last_seen,
                ),
            )

    # -- rollups -----------------------------------------------------------
    def rebuild_rollup(self, dates: Iterable[str]) -> int:
        """Recompute the daily rollup for the given dates. Returns rows written.

        Idempotent: DELETE then INSERT, one date per transaction. The rollup is
        what makes month and all-time queries cheap — they read one row per day
        per dimension value and never touch `events`.

        KNOWN APPROXIMATION: sessions are reconstructed per calendar day, so a
        session that spans local midnight is counted once in each day. On a
        news site with an evening peak this is a handful of sessions; the
        alternative (a global re-sessionization on every rebuild) costs a full
        table scan for a rounding difference.
        """
        written = 0
        for day in sorted(set(dates)):
            rows = self._rollup_for_date(day)
            with self._conn:
                self._conn.execute("DELETE FROM rollup WHERE local_date = ?", (day,))
                self._conn.executemany(
                    "INSERT INTO rollup "
                    "(local_date, dimension, value, pageviews, sessions, visitors, events) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                # Reconcile the day's capability event count against the rows
                # actually stored. `record_capabilities` ADDS on merge, which is
                # right when one day arrives from two files but wrong the moment
                # the same events are seen twice — a re-ingest, or two layers
                # both recording. Counting the table is authoritative and makes
                # the number self-correcting instead of accumulating drift that
                # only shows up as an inflated `status`.
                self._conn.execute(
                    "UPDATE capabilities SET events = "
                    "(SELECT COUNT(*) FROM events WHERE local_date = ?) "
                    "WHERE local_date = ?",
                    (day, day),
                )
            written += len(rows)
        return written

    def _rollup_for_date(self, day: str) -> list[tuple[str, str, str, int, int, int, int]]:
        events_by_dim: dict[tuple[str, str], int] = {}
        pageviews_by_dim: dict[tuple[str, str], int] = {}
        visitors_by_dim: dict[tuple[str, str], set[str]] = {}
        sessions_by_dim: dict[tuple[str, str], int] = {}

        total_events = 0
        total_pageviews = 0
        total_visitors: set[str] = set()
        # visitor -> list of (epoch, dimension values of the pageview)
        runs: dict[str, list[tuple[int, tuple[tuple[str, str], ...]]]] = {}

        cursor = self._conn.execute(
            "SELECT * FROM events WHERE local_date = ? ORDER BY utc_epoch", (day,)
        )
        for row in cursor:
            total_events += 1
            pairs = _dimension_pairs(row)
            for pair in pairs:
                events_by_dim[pair] = events_by_dim.get(pair, 0) + 1
            if row["is_pageview"]:
                total_pageviews += 1
                for pair in pairs:
                    pageviews_by_dim[pair] = pageviews_by_dim.get(pair, 0) + 1
                visitor = row["visitor"]
                if visitor:
                    total_visitors.add(str(visitor))
                    for pair in pairs:
                        visitors_by_dim.setdefault(pair, set()).add(str(visitor))
                    runs.setdefault(str(visitor), []).append((int(row["utc_epoch"]), pairs))

        gap = SESSION_GAP_MINUTES * 60
        total_sessions = 0
        for entries in runs.values():
            entries.sort(key=lambda item: item[0])
            previous: int | None = None
            for epoch, pairs in entries:
                if previous is None or (epoch - previous) > gap:
                    total_sessions += 1
                    # A session's dimension value is its ENTRY event's value: a
                    # reader who starts in EN and switches to UA is one EN
                    # session, not half of each.
                    for pair in pairs:
                        sessions_by_dim[pair] = sessions_by_dim.get(pair, 0) + 1
                previous = epoch

        rows: list[tuple[str, str, str, int, int, int, int]] = [
            (
                day,
                TOTAL_DIMENSION,
                TOTAL_VALUE,
                total_pageviews,
                total_sessions,
                len(total_visitors),
                total_events,
            )
        ]
        for (dimension, value), events in sorted(events_by_dim.items()):
            rows.append(
                (
                    day,
                    dimension,
                    value,
                    pageviews_by_dim.get((dimension, value), 0),
                    sessions_by_dim.get((dimension, value), 0),
                    len(visitors_by_dim.get((dimension, value), ())),
                    events,
                )
            )
        return rows

    # -- queries -----------------------------------------------------------
    def capabilities(
        self, *, since: date | None = None, until: date | None = None
    ) -> list[DayCapabilities]:
        sql = "SELECT * FROM capabilities"
        params: list[object] = []
        clauses: list[str] = []
        if since is not None:
            clauses.append("local_date >= ?")
            params.append(since.isoformat())
        if until is not None:
            clauses.append("local_date <= ?")
            params.append(until.isoformat())
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY local_date"
        return [_capability_from_row(row) for row in self._conn.execute(sql, params)]

    def date_range(self) -> tuple[date, date] | None:
        row = self._conn.execute(
            "SELECT MIN(local_date) AS lo, MAX(local_date) AS hi FROM events"
        ).fetchone()
        if row is None or row["lo"] is None:
            return None
        return date.fromisoformat(str(row["lo"])), date.fromisoformat(str(row["hi"]))

    def status(self) -> StoreStatus:
        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0
        totals = self._conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(is_pageview), 0) AS pv FROM events"
        ).fetchone()
        span = self.date_range()
        present = {
            str(row["local_date"])
            for row in self._conn.execute("SELECT DISTINCT local_date FROM events")
        }
        missing: list[str] = []
        if span is not None:
            cursor_day = span[0]
            while cursor_day <= span[1]:
                if cursor_day.isoformat() not in present:
                    missing.append(cursor_day.isoformat())
                cursor_day += timedelta(days=1)
        sources = self._conn.execute("SELECT COUNT(*) AS n FROM source_files").fetchone()
        return StoreStatus(
            path=str(self.path),
            size_bytes=size,
            schema_version=self.schema_version(),
            first_date=span[0].isoformat() if span else None,
            last_date=span[1].isoformat() if span else None,
            days_present=len(present),
            days_missing=tuple(missing),
            total_events=int(totals["n"]),
            total_pageviews=int(totals["pv"]),
            last_ingest_at=self._meta("last_ingest_at"),
            capabilities=tuple(self.capabilities()),
            source_files=int(sources["n"]),
        )

    def rollup_rows(
        self, dimension: str, *, since: date, until: date, limit: int | None = None
    ) -> list[tuple[str, str, int, int, int, int]]:
        """(local_date, value, pageviews, sessions, visitors, events)."""
        sql = (
            "SELECT local_date, value, pageviews, sessions, visitors, events "
            "FROM rollup WHERE dimension = ? AND local_date BETWEEN ? AND ? "
            "ORDER BY local_date, events DESC, value"
        )
        params: list[object] = [dimension, since.isoformat(), until.isoformat()]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [
            (
                str(row["local_date"]),
                str(row["value"]),
                int(row["pageviews"]),
                int(row["sessions"]),
                int(row["visitors"]),
                int(row["events"]),
            )
            for row in self._conn.execute(sql, params)
        ]

    def daily_totals(
        self, *, since: date, until: date, include_bots: bool = False
    ) -> list[tuple[str, int, int, int, int]]:
        """(local_date, pageviews, sessions, visitors, bot_events) per day.

        Answered entirely from `rollup`, so a month or an all-time query costs
        one row per day rather than a scan over every request ever stored.
        """
        totals = {
            str(row["local_date"]): row
            for row in self._conn.execute(
                "SELECT local_date, pageviews, sessions, visitors, events FROM rollup "
                "WHERE dimension = ? AND value = ? AND local_date BETWEEN ? AND ?",
                (TOTAL_DIMENSION, TOTAL_VALUE, since.isoformat(), until.isoformat()),
            )
        }
        bots = {
            str(row["local_date"]): int(row["events"])
            for row in self._conn.execute(
                "SELECT local_date, events FROM rollup "
                "WHERE dimension = 'klass' AND value = 'bot' AND local_date BETWEEN ? AND ?",
                (since.isoformat(), until.isoformat()),
            )
        }
        out: list[tuple[str, int, int, int, int]] = []
        for day in sorted(totals):
            row = totals[day]
            pageviews = int(row["pageviews"])
            if include_bots:
                # The bot-inclusive view counts every stored request, which is
                # what "--include-bots" means at day granularity.
                pageviews = int(row["events"])
            out.append(
                (
                    day,
                    pageviews,
                    int(row["sessions"]),
                    int(row["visitors"]),
                    bots.get(day, 0),
                )
            )
        return out

    def iter_events(
        self, *, since: date, until: date, include_bots: bool = False
    ) -> Iterator[sqlite3.Row]:
        """Streaming cursor over stored events for the detailed sections."""
        sql = "SELECT * FROM events WHERE local_date BETWEEN ? AND ?"
        params: list[object] = [since.isoformat(), until.isoformat()]
        if not include_bots:
            sql += " AND klass = 'human'"
        sql += " ORDER BY utc_epoch"
        cursor = self._conn.execute(sql, params)
        for row in cursor:
            yield row

    def purge(self, *, before: date) -> int:
        """Delete stored ROWS before a date. Never touches a log file.

        Never called automatically and never wired to a timer: the whole point
        of this store is that it outlives the logs. It exists so an operator who
        must reclaim space has a supported way to do it.
        """
        cutoff = before.isoformat()
        with self._conn:
            cursor = self._conn.execute("DELETE FROM events WHERE local_date < ?", (cutoff,))
            deleted = cursor.rowcount or 0
            self._conn.execute("DELETE FROM rollup WHERE local_date < ?", (cutoff,))
            self._conn.execute("DELETE FROM capabilities WHERE local_date < ?", (cutoff,))
        return deleted


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
class _CapabilityTally:
    """Accumulates one day's capability flags during the ingest pass."""

    __slots__ = ("date", "formats", "flags", "events", "first_seen", "last_seen")

    def __init__(self, day: str) -> None:
        self.date = day
        self.formats: set[str] = set()
        self.flags: dict[str, bool] = {
            "host": False,
            "client_ip": False,
            "country": False,
            "accept_language": False,
            "client_hints": False,
            "rsc": False,
            "timing": False,
        }
        self.events = 0
        self.first_seen = ""
        self.last_seen = ""

    def observe(self, event: Event) -> None:
        record = event.record
        self.events += 1
        self.formats.add(record.fmt)
        self.flags["host"] |= record.host is not None
        self.flags["client_ip"] |= bool(record.ip_is_visitor)
        self.flags["country"] |= record.cf_country is not None
        self.flags["accept_language"] |= bool(record.accept_language)
        self.flags["client_hints"] |= bool(record.ch_available)
        # The RSC/prefetch headers are a property of the FORMAT, not of the
        # individual line: an extended line without them means "this request was
        # not a prefetch", while a legacy line means "nobody can tell".
        self.flags["rsc"] |= record.fmt == EXTENDED
        self.flags["timing"] |= record.request_time is not None
        stamp = event.local_ts.isoformat()
        if not self.first_seen or stamp < self.first_seen:
            self.first_seen = stamp
        if stamp > self.last_seen:
            self.last_seen = stamp

    def build(self) -> DayCapabilities:
        if self.formats == {EXTENDED}:
            log_format = EXTENDED
        elif self.formats == {LEGACY}:
            log_format = LEGACY
        else:
            log_format = "mixed"
        return DayCapabilities(
            local_date=self.date,
            log_format=log_format,
            has_host=self.flags["host"],
            has_client_ip=self.flags["client_ip"],
            has_country=self.flags["country"],
            has_accept_language=self.flags["accept_language"],
            has_client_hints=self.flags["client_hints"],
            has_rsc_headers=self.flags["rsc"],
            has_timing=self.flags["timing"],
            events=self.events,
            first_seen=self.first_seen,
            last_seen=self.last_seen,
        )


def line_hash(*, file_key: str, lineno: int, raw: str) -> str:
    """The idempotency key. Position is part of it — see the module docstring."""
    digest = hashlib.blake2b(
        b"\x00".join(
            (
                file_key.encode("utf-8"),
                str(lineno).encode("ascii"),
                raw.encode("utf-8", "replace"),
            )
        ),
        digest_size=16,
    )
    return digest.hexdigest()


def ua_hash(user_agent: str | None, *, salt: str) -> str | None:
    """Salted, truncated hash of the UA string. The raw string is never stored."""
    if not user_agent:
        return None
    digest = hashlib.blake2b(
        salt.encode("utf-8") + b"\x00" + user_agent.encode("utf-8", "replace"),
        digest_size=8,
    )
    return digest.hexdigest()


def _event_row(event: Event, *, ua_salt: str, source: LogFileInfo) -> tuple[object, ...]:
    record = event.record
    agent = event.agent
    verdict = event.verdict
    key = record.file_key or source.file_key
    return (
        line_hash(file_key=key, lineno=record.lineno, raw=record.raw),
        int(record.ts.timestamp()),
        event.date,
        event.hour,
        event.weekday,
        record.host,
        record.method,
        record.path,
        event.locale,
        event.page_kind,
        event.article_id,
        event.nav,
        int(event.is_pageview),
        record.status,
        record.body_bytes,
        record.total_bytes,
        record.request_time,
        record.upstream_time,
        event.referer_host,
        event.channel,
        event.campaign,
        ua_hash(record.user_agent, salt=ua_salt),
        agent.browser_family,
        agent.browser_version,
        agent.os_family,
        agent.os_version,
        int(agent.os_version_reliable),
        agent.device_type,
        agent.device_vendor,
        agent.device_model,
        agent.model_source,
        agent.in_app,
        event.country,
        event.language,
        event.language_region,
        verdict.klass,
        verdict.category,
        verdict.label,
        verdict.subclass,
        verdict.subscribers,
        verdict.rule,
        event.visitor,
        record.fmt,
    )


def _dimension_pairs(row: sqlite3.Row) -> tuple[tuple[str, str], ...]:
    """The (dimension, value) pairs one stored event contributes to the rollup.

    Every dimension always produces a pair, with an explicit "unknown" value
    where the data is missing. A dimension that silently drops its blanks
    reports a distribution over the rows that happened to be complete, which is
    a different and much rosier population than the one that visited.
    """
    def text(column: str, fallback: str = "unknown") -> str:
        value = row[column]
        if value is None or value == "":
            return fallback
        return str(value)

    return (
        ("country", text("country")),
        ("browser", text("browser")),
        ("os", text("os")),
        ("device", text("device_type")),
        ("channel", text("channel")),
        ("locale", text("locale")),
        ("language", text("language")),
        ("article", text("article_id", "none")),
        ("vendor", text("vendor")),
        ("model", text("model")),
        ("in_app", text("in_app", "none")),
        ("status", text("status")),
        ("hour", f"{int(row['local_hour']):02d}"),
        ("klass", text("klass")),
        ("category", text("category")),
        ("bot", text("bot_label", "none")),
    )


def _capability_from_row(row: sqlite3.Row) -> DayCapabilities:
    return DayCapabilities(
        local_date=str(row["local_date"]),
        log_format=str(row["log_format"]),
        has_host=bool(row["has_host"]),
        has_client_ip=bool(row["has_client_ip"]),
        has_country=bool(row["has_country"]),
        has_accept_language=bool(row["has_accept_language"]),
        has_client_hints=bool(row["has_client_hints"]),
        has_rsc_headers=bool(row["has_rsc_headers"]),
        has_timing=bool(row["has_timing"]),
        events=int(row["events"]),
        first_seen=str(row["first_seen"]),
        last_seen=str(row["last_seen"]),
    )


def source_file_from_info(
    info: LogFileInfo, *, lines_ingested: int, bytes_ingested: int
) -> SourceFile:
    """Build the `source_files` record for a file that was just read."""
    return SourceFile(
        file_key=info.file_key,
        last_path=str(info.path),
        size=int(info.size),
        mtime=float(info.mtime),
        first_line=info.first_line,
        lines_ingested=int(lines_ingested),
        bytes_ingested=int(bytes_ingested),
        ingested_at=_utc_now_iso(),
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def elapsed_since(started: float) -> float:
    """Monotonic elapsed seconds, for IngestResult."""
    return max(0.0, time.monotonic() - started)
