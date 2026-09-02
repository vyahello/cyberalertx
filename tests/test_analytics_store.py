"""The persistent store: idempotency, additive migration, and not touching logs.

Two properties matter more than everything else here, because both fail
silently:

* **Re-ingesting must never double-count.** A daily timer reads the same live
  log every night. If the second read inserts the same lines again, the store
  slowly and invisibly inflates until it is reporting three times the traffic
  the site actually gets, and nothing in the output says so.
* **Ingest must never modify a log file.** The store is downstream of nginx and
  of three other projects on the same box. It reads; it does not write, rotate,
  truncate or signal. That is asserted here against the file's mtime and
  content hash rather than trusted.

Fixtures are built from the shared `extended_line` / `legacy_line` builders in
`test_analytics_logread.py`, and every timestamp hangs off `datetime.now`, never
a literal date.

SCOPE: temporary databases under pytest's tmp_path. Never /var/log, never the
repository's data/ directory, never the network.
"""
from __future__ import annotations

import gzip
import hashlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.analytics.logread import (
    ParseStats,
    discover_logs,
    iter_records,
    log_file_info,
)
from server.analytics.sessionize import Ledger, SaltProvider, iter_events
from server.analytics.store import (
    SCHEMA_VERSION,
    AnalyticsStore,
    DayCapabilities,
    SourceFile,
)

from tests.test_analytics_logread import (
    CF_EDGE_IP,
    KYIV,
    extended_line,
    legacy_line,
    now_local,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def write_log(tmp_path: Path, lines: list[str], *, name: str = "access.log",
              gz: bool = False) -> Path:
    """Write a log file the way nginx would: one line each, newline-terminated."""
    path = tmp_path / name
    body = "".join(line + "\n" for line in lines)
    if gz:
        path.write_bytes(gzip.compress(body.encode("utf-8")))
    else:
        path.write_text(body, encoding="utf-8")
    return path


def ingest(store: AnalyticsStore, path: Path, *, tmp_path: Path,
           dry_run: bool = False) -> tuple[int, int]:
    """Run the real pipeline — read, parse, enrich, insert — over one file.

    Deliberately not a shortcut that hands `Event` objects straight to the
    store: the thing under test is the whole path a nightly ingest takes.
    """
    info = log_file_info(path)
    salts = SaltProvider(tmp_path / "salts.json")
    records = iter_records([info], stats=ParseStats())
    events = iter_events(records, tz=KYIV, salts=salts, ledger=Ledger())
    return store.ingest_events(events, source=info, dry_run=dry_run)


def sample_lines(count: int = 12) -> list[str]:
    """A day of mixed traffic, spread over distinct minutes."""
    base = now_local().replace(hour=12, minute=0, second=0)
    lines: list[str] = []
    for i in range(count):
        moment = base - timedelta(minutes=i)
        if i % 3 == 0:
            lines.append(legacy_line(ts=moment, path=f"/en/threat/{i:016x}"))
        else:
            lines.append(extended_line(ts=moment, u=f"/ua/threat/{i:016x}"))
    return lines


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# schema and migration
# --------------------------------------------------------------------------
def test_a_new_store_is_created_at_the_current_schema_version(tmp_path: Path) -> None:
    with AnalyticsStore(tmp_path / "a.sqlite3") as store:
        assert store.schema_version() == SCHEMA_VERSION


def test_the_database_file_is_private_to_its_owner(tmp_path: Path) -> None:
    """0600. The rows hold salted visitor ids and, once the nginx change lands,
    were derived from real client IPs."""
    path = tmp_path / "b.sqlite3"
    with AnalyticsStore(path):
        pass
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_reopening_an_existing_store_preserves_its_rows(tmp_path: Path) -> None:
    """Migration runs on every open, so it must be a no-op the second time."""
    path = tmp_path / "c.sqlite3"
    log = write_log(tmp_path, sample_lines())
    with AnalyticsStore(path) as store:
        inserted, _ = ingest(store, log, tmp_path=tmp_path)
        assert inserted > 0
    with AnalyticsStore(path) as store:
        assert store.schema_version() == SCHEMA_VERSION
        assert store.status().total_events == inserted


def test_migration_from_an_older_schema_is_additive(tmp_path: Path) -> None:
    """An old database keeps every row and gains the new columns.

    Simulates a v1 store by dropping the columns v2 added and rewinding the
    recorded version, then reopening. Rows written before the upgrade must
    survive it — the contract's migrations are ALTER TABLE ADD COLUMN and
    nothing else.
    """
    path = tmp_path / "d.sqlite3"
    log = write_log(tmp_path, sample_lines())
    with AnalyticsStore(path) as store:
        ingest(store, log, tmp_path=tmp_path)
        before = store.status().total_events

    # Rewind: rebuild `events` without the v2 columns, exactly as v1 had it.
    conn = sqlite3.connect(path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(events)")
               if row[1] not in ("subclass", "subscribers")]
    joined = ", ".join(columns)
    conn.executescript(
        f"CREATE TABLE events_v1 AS SELECT {joined} FROM events;"
        "DROP TABLE events;"
        "ALTER TABLE events_v1 RENAME TO events;"
        "UPDATE meta SET value = '1' WHERE key = 'schema_version';"
    )
    conn.commit()
    conn.close()

    with AnalyticsStore(path) as store:
        assert store.schema_version() == SCHEMA_VERSION
        assert store.status().total_events == before

    conn = sqlite3.connect(path)
    names = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    conn.close()
    assert {"subclass", "subscribers"} <= names


# --------------------------------------------------------------------------
# idempotency
# --------------------------------------------------------------------------
def test_reingesting_the_same_file_inserts_nothing_new(tmp_path: Path) -> None:
    """The property the nightly timer depends on."""
    log = write_log(tmp_path, sample_lines())
    with AnalyticsStore(tmp_path / "e.sqlite3") as store:
        first, _ = ingest(store, log, tmp_path=tmp_path)
        second, duplicates = ingest(store, log, tmp_path=tmp_path)
        assert first > 0
        assert second == 0
        assert duplicates == first
        assert store.status().total_events == first


def test_an_appended_log_ingests_only_the_new_lines(tmp_path: Path) -> None:
    """Today's live log grows all day, so its size and mtime always differ.

    A file-level check alone would re-insert the whole day on every run; the
    per-line hash is what makes the second read cost only the new lines.
    """
    lines = sample_lines(8)
    log = write_log(tmp_path, lines)
    with AnalyticsStore(tmp_path / "f.sqlite3") as store:
        first, _ = ingest(store, log, tmp_path=tmp_path)

        extra = now_local().replace(hour=13, minute=30, second=0)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(extended_line(ts=extra, u="/en/threat/" + "a" * 16) + "\n")

        second, duplicates = ingest(store, log, tmp_path=tmp_path)
        assert second == 1
        assert duplicates == first
        assert store.status().total_events == first + 1


def test_identical_lines_in_one_file_are_both_kept(tmp_path: Path) -> None:
    """Byte-identical duplicate requests are real traffic, not a parsing bug.

    Production shows two identical iPhone requests inside the same second.
    Hashing content alone would silently drop one of them, so the line's
    position is part of the hash.
    """
    moment = now_local()
    line = extended_line(ts=moment)
    log = write_log(tmp_path, [line, line])
    with AnalyticsStore(tmp_path / "g.sqlite3") as store:
        inserted, duplicates = ingest(store, log, tmp_path=tmp_path)
        assert inserted == 2
        assert duplicates == 0


def test_the_same_stream_under_two_names_is_ingested_once(tmp_path: Path) -> None:
    """archive-daily.sh copies access.log.1.gz to access-2026-09-01.log.gz.

    Identity is the content, not the filename, so the copy must be recognised
    as already held rather than counted a second time.
    """
    lines = sample_lines()
    original = write_log(tmp_path, lines, name="access.log.1.gz", gz=True)
    copy = write_log(tmp_path, lines, name="access-2026-09-01.log.gz", gz=True)
    assert log_file_info(original).file_key == log_file_info(copy).file_key

    # Discovery is the layer that drops the duplicate: same key, so the second
    # path never becomes a second source at all.
    found = discover_logs(log=[original, copy])
    assert [info.path for info in found] == [original]

    # And ingesting both anyway still cannot double-count, because the per-line
    # hashes are identical.
    with AnalyticsStore(tmp_path / "h.sqlite3") as store:
        first, _ = ingest(store, original, tmp_path=tmp_path)
        again, duplicates = ingest(store, copy, tmp_path=tmp_path)
        assert again == 0
        assert duplicates == first


def test_an_unchanged_file_is_skipped_without_being_reopened(tmp_path: Path) -> None:
    """The source_files fast path: key, size and mtime all unchanged -> skip.

    This is what keeps a nightly ingest over ~300 immutable archives cheap.
    `--reingest` overrides it.
    """
    lines = sample_lines()
    log = write_log(tmp_path, lines, name="access.log.1.gz", gz=True)
    info = log_file_info(log)
    with AnalyticsStore(tmp_path / "h2.sqlite3") as store:
        assert store.needs_ingest(info) is True
        inserted, _ = ingest(store, log, tmp_path=tmp_path)
        store.record_source(SourceFile(
            file_key=info.file_key, last_path=str(log), size=info.size,
            mtime=info.mtime, first_line=info.first_line,
            lines_ingested=inserted, bytes_ingested=info.size,
            ingested_at=datetime.now(timezone.utc).isoformat(),
        ))
        assert store.needs_ingest(log_file_info(log)) is False
        assert store.needs_ingest(log_file_info(log), reingest=True) is True


def test_dry_run_writes_absolutely_nothing(tmp_path: Path) -> None:
    """Not a row, not a source record, not a meta timestamp."""
    path = tmp_path / "i.sqlite3"
    log = write_log(tmp_path, sample_lines())
    with AnalyticsStore(path) as store:
        would_insert, _ = ingest(store, log, tmp_path=tmp_path, dry_run=True)
        assert would_insert > 0
        assert store.status().total_events == 0
        assert store.date_range() is None


# --------------------------------------------------------------------------
# the log file is never touched
# --------------------------------------------------------------------------
def test_ingest_leaves_the_log_file_byte_identical(tmp_path: Path) -> None:
    """The single most important safety property in the whole tool.

    Three other projects share this box and one of them owns the log nginx is
    still writing to. Reading it must not change its size, its mtime or a
    single byte of its content.
    """
    log = write_log(tmp_path, sample_lines())
    before_digest = digest(log)
    before_stat = log.stat()
    old_time = before_stat.st_mtime - 3600
    os.utime(log, (old_time, old_time))
    before_mtime = log.stat().st_mtime

    with AnalyticsStore(tmp_path / "j.sqlite3") as store:
        ingest(store, log, tmp_path=tmp_path)

    assert digest(log) == before_digest
    assert log.stat().st_mtime == before_mtime
    assert log.stat().st_size == before_stat.st_size


def test_purge_deletes_rows_and_never_files(tmp_path: Path) -> None:
    """`purge` is row-level, manual, and cannot reach a log file."""
    log = write_log(tmp_path, sample_lines())
    with AnalyticsStore(tmp_path / "k.sqlite3") as store:
        ingest(store, log, tmp_path=tmp_path)
        held = store.status().total_events
        removed = store.purge(before=(now_local() + timedelta(days=1)).date())
        assert removed == held
        assert store.status().total_events == 0
    assert log.exists()
    assert log.read_text(encoding="utf-8").strip()


# --------------------------------------------------------------------------
# capabilities, rollup and status
# --------------------------------------------------------------------------
def test_capabilities_record_what_each_day_could_measure(tmp_path: Path) -> None:
    """Country exists on extended lines and not on legacy ones.

    The report reads this to LABEL a period rather than plot a misleading zero,
    so the flags have to reflect the format actually seen that day.
    """
    moment = now_local().replace(hour=9, minute=0, second=0)
    legacy_day = write_log(tmp_path, [legacy_line(ts=moment - timedelta(days=1))],
                           name="legacy.log")
    extended_day = write_log(tmp_path, [extended_line(ts=moment)],
                             name="extended.log")
    with AnalyticsStore(tmp_path / "l.sqlite3") as store:
        ingest(store, legacy_day, tmp_path=tmp_path)
        ingest(store, extended_day, tmp_path=tmp_path)
        by_date = {cap.local_date: cap for cap in store.capabilities()}

    old = by_date[(moment - timedelta(days=1)).date().isoformat()]
    new = by_date[moment.date().isoformat()]
    assert old.log_format == "legacy"
    assert old.has_country is False
    assert old.has_client_ip is False
    assert new.log_format == "extended"
    assert new.has_country is True
    assert new.has_client_ip is True


def test_rollup_totals_agree_with_the_events_they_summarise(tmp_path: Path) -> None:
    """The rollup exists so month and all-time queries never rescan events.

    That is only safe while it says the same thing the events do, so the two
    are compared directly.
    """
    log = write_log(tmp_path, sample_lines(15))
    with AnalyticsStore(tmp_path / "m.sqlite3") as store:
        ingest(store, log, tmp_path=tmp_path)
        dates = sorted({row["local_date"] for row in store.iter_events(
            since=(now_local() - timedelta(days=2)).date(),
            until=(now_local() + timedelta(days=1)).date(),
            include_bots=True)})
        store.rebuild_rollup(dates)

        since = (now_local() - timedelta(days=2)).date()
        until = (now_local() + timedelta(days=1)).date()
        from_rollup = sum(row[1] for row in store.daily_totals(
            since=since, until=until))
        from_events = sum(
            1 for row in store.iter_events(since=since, until=until)
            if row["is_pageview"] and row["klass"] == "human"
        )
        assert from_rollup == from_events


def test_rebuilding_the_rollup_twice_does_not_double_it(tmp_path: Path) -> None:
    """Rollup rows are keyed (date, dimension, value) and replaced, not added."""
    log = write_log(tmp_path, sample_lines(15))
    since = (now_local() - timedelta(days=2)).date()
    until = (now_local() + timedelta(days=1)).date()
    with AnalyticsStore(tmp_path / "n.sqlite3") as store:
        ingest(store, log, tmp_path=tmp_path)
        dates = sorted({row["local_date"] for row in
                        store.iter_events(since=since, until=until,
                                          include_bots=True)})
        store.rebuild_rollup(dates)
        once = store.daily_totals(since=since, until=until)
        store.rebuild_rollup(dates)
        assert store.daily_totals(since=since, until=until) == once


def test_status_describes_what_the_store_holds(tmp_path: Path) -> None:
    """`status` is the user's answer to 'what is actually in there'."""
    path = tmp_path / "o.sqlite3"
    log = write_log(tmp_path, sample_lines(15))
    with AnalyticsStore(path) as store:
        ingest(store, log, tmp_path=tmp_path)
        status = store.status()
        # Measured inside the context: SQLite grows the file further on close.
        assert status.size_bytes == path.stat().st_size

    assert status.total_events > 0
    assert status.schema_version == SCHEMA_VERSION
    assert status.first_date is not None and status.last_date is not None
    assert status.first_date <= status.last_date
    assert status.days_present >= 1


def test_an_empty_store_reports_emptiness_rather_than_guessing(tmp_path: Path) -> None:
    """No data is a valid state and must not read as zero traffic."""
    with AnalyticsStore(tmp_path / "p.sqlite3") as store:
        status = store.status()
        assert status.total_events == 0
        assert status.first_date is None
        assert status.last_date is None
        assert store.date_range() is None
        assert store.capabilities() == []


def test_record_capabilities_is_upsert_not_append(tmp_path: Path) -> None:
    """Re-ingesting a day must refresh its record, never duplicate it."""
    day = now_local().date().isoformat()
    cap = DayCapabilities(
        local_date=day, log_format="legacy", has_host=False, has_client_ip=False,
        has_country=False, has_accept_language=False, has_client_hints=False,
        has_rsc_headers=False, has_timing=False, events=10,
        first_seen=f"{day}T00:00:00+03:00", last_seen=f"{day}T10:00:00+03:00",
    )
    with AnalyticsStore(tmp_path / "q.sqlite3") as store:
        store.record_capabilities(cap)
        store.record_capabilities(cap)
        rows = store.capabilities()
        assert len(rows) == 1


def test_events_outside_the_window_are_not_returned(tmp_path: Path) -> None:
    """`iter_events` is the report's only door into the events table."""
    recent = now_local().replace(hour=8, minute=0, second=0)
    old = recent - timedelta(days=40)
    log = write_log(tmp_path, [extended_line(ts=old, u="/en"),
                               extended_line(ts=recent, u="/ua")])
    with AnalyticsStore(tmp_path / "r.sqlite3") as store:
        ingest(store, log, tmp_path=tmp_path)
        window = list(store.iter_events(
            since=(recent - timedelta(days=7)).date(),
            until=recent.date(), include_bots=True))
        assert len(window) == 1
        assert window[0]["local_date"] == recent.date().isoformat()


def test_raw_addresses_are_never_stored(tmp_path: Path) -> None:
    """PRIVACY. The store keeps salted hashes, never an IP.

    Asserted by scanning every text column of every row for the addresses the
    fixtures used — the check that would actually catch a regression, rather
    than trusting the column list.
    """
    moment = now_local()
    log = write_log(tmp_path, [
        extended_line(ts=moment, ip="192.0.2.10", pip=CF_EDGE_IP),
        legacy_line(ts=moment - timedelta(minutes=1), ip=CF_EDGE_IP),
    ])
    with AnalyticsStore(tmp_path / "s.sqlite3") as store:
        ingest(store, log, tmp_path=tmp_path)

    blob = (tmp_path / "s.sqlite3").read_bytes()
    assert b"192.0.2.10" not in blob
    assert CF_EDGE_IP.encode() not in blob


@pytest.mark.parametrize("gz", [False, True])
def test_plain_and_gzipped_logs_produce_the_same_rows(tmp_path: Path, gz: bool) -> None:
    """A rotated .gz and its uncompressed original are the same data."""
    lines = sample_lines(9)
    name = "same.log.gz" if gz else "same.log"
    log = write_log(tmp_path, lines, name=name, gz=gz)
    with AnalyticsStore(tmp_path / f"t{int(gz)}.sqlite3") as store:
        inserted, _ = ingest(store, log, tmp_path=tmp_path)
    assert inserted == len(lines)
