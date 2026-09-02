"""Bucketing, partial periods and period-over-period comparison.

The whole point of `timeseries.py` is that a chart never lies about a period it
only half-covers. A month that is three days old must not be drawn next to
twelve complete ones as though it lost 90% of its traffic, and a gap where no
log was ever ingested must not be drawn as a genuine zero. Both mistakes are
invisible in the output — the chart still renders, it is just wrong — so they
get tests.

Every fixture date hangs off `date.today()` rather than a literal, because the
partial/complete distinction is defined relative to now: a test pinned to
2026-09-02 passes today and starts failing the moment the calendar moves past
the month it hardcoded.

SCOPE: pure functions over (date-string, count) tuples. No I/O, no store, no
network, no /var/log.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from server.analytics.store import DayCapabilities
from server.analytics.timeseries import (
    bucket_bounds,
    bucket_key,
    bucket_label,
    build_series,
    compare_periods,
    is_partial,
    sparkline_values,
)

TODAY: date = date.today()


def caps(day: date, *, log_format: str = "legacy") -> DayCapabilities:
    """A capabilities record for one day, defaulting to the legacy shape.

    A day with a record is a day that was ingested. Its absence is what makes a
    bucket a hole rather than a zero, which is the distinction under test.
    """
    return DayCapabilities(
        local_date=day.isoformat(),
        log_format=log_format,
        has_host=log_format != "legacy",
        has_client_ip=log_format != "legacy",
        has_country=log_format != "legacy",
        has_accept_language=log_format != "legacy",
        has_client_hints=log_format != "legacy",
        has_rsc_headers=log_format != "legacy",
        has_timing=log_format != "legacy",
        events=100,
        first_seen=f"{day.isoformat()}T00:00:00+03:00",
        last_seen=f"{day.isoformat()}T23:59:59+03:00",
    )


def rows(start: date, counts: list[int]) -> list[tuple[str, int, int, int, int]]:
    """`daily_totals`-shaped rows: (date, pageviews, sessions, visitors, bots)."""
    return [
        ((start + timedelta(days=i)).isoformat(), n, 0, 0, n // 4)
        for i, n in enumerate(counts)
    ]


# --------------------------------------------------------------------------
# bucket_key / bucket_label / bucket_bounds
# --------------------------------------------------------------------------
def test_bucket_key_groups_each_granularity() -> None:
    """One day maps into exactly one bucket per granularity."""
    day = date(2026, 9, 2)          # a Wednesday, ISO week 36
    assert bucket_key(day, "day") == "2026-09-02"
    assert bucket_key(day, "month") == "2026-09"
    assert bucket_key(day, "year") == "2026"
    assert bucket_key(day, "week") == "2026-W36"


def test_iso_week_key_follows_the_iso_year_not_the_calendar_year() -> None:
    """The 1 Jan trap: ISO week 1 of 2026 starts in December 2025.

    Keying an ISO week off `d.year` puts 29 Dec 2025 in "2025-W01" — the first
    week of the year it is at the end of — and the December bar lands eleven
    months away from where it belongs.
    """
    assert bucket_key(date(2025, 12, 29), "week") == "2026-W01"
    assert bucket_key(date(2026, 1, 1), "week") == "2026-W01"
    # And the two agree, which is the property that matters for grouping.
    assert bucket_key(date(2025, 12, 29), "week") == bucket_key(date(2026, 1, 1), "week")


def test_bucket_bounds_round_trips_every_key() -> None:
    """A key's bounds must contain the day that produced it, at every bucket."""
    for bucket in ("day", "week", "month", "year"):
        for day in (date(2026, 1, 1), date(2026, 2, 28), date(2026, 12, 31),
                    date(2024, 2, 29)):
            key = bucket_key(day, bucket)
            start, end = bucket_bounds(key, bucket)
            assert start <= day <= end, (bucket, key, day)
            assert bucket_key(start, bucket) == key
            assert bucket_key(end, bucket) == key


def test_bucket_label_is_human_readable_and_distinct() -> None:
    """Labels are for reading, so they must not collide inside one series."""
    keys = [bucket_key(date(2026, m, 1), "month") for m in range(1, 13)]
    labels = [bucket_label(k, "month") for k in keys]
    assert len(set(labels)) == 12
    assert all(label.strip() for label in labels)


# --------------------------------------------------------------------------
# is_partial
# --------------------------------------------------------------------------
def test_the_current_period_is_partial_and_a_finished_one_is_not() -> None:
    """The month in progress is partial; the one before it is complete."""
    this_month = bucket_key(TODAY, "month")
    last_month = bucket_key(TODAY.replace(day=1) - timedelta(days=1), "month")
    since = TODAY - timedelta(days=400)
    until = TODAY
    assert is_partial(this_month, "month", since=since, until=until, today=TODAY)
    assert not is_partial(last_month, "month", since=since, until=until, today=TODAY)


def test_a_period_clipped_by_the_window_is_partial() -> None:
    """--since landing mid-month makes that month partial even in the past.

    The bucket is finished in calendar terms but the *window* only holds part
    of it, so its bar is not comparable with the ones beside it.
    """
    first_of_month = TODAY.replace(day=1)
    clipped_since = first_of_month - timedelta(days=45)   # mid-way through
    key = bucket_key(clipped_since, "month")
    assert is_partial(key, "month", since=clipped_since,
                      until=TODAY, today=TODAY)


# --------------------------------------------------------------------------
# build_series
# --------------------------------------------------------------------------
def test_build_series_labels_partial_periods_and_never_extrapolates() -> None:
    """A partial bucket keeps its raw count. Scaling it up invents traffic."""
    start = TODAY - timedelta(days=6)
    data = rows(start, [10, 20, 30, 40, 50, 60, 7])
    series = build_series(
        data, bucket="day", since=start, until=TODAY,
        capabilities=[caps(start + timedelta(days=i)) for i in range(7)],
        title="TRAFFIC OVER TIME", today=TODAY,
    )
    assert [p.pageviews for p in series.points] == [10, 20, 30, 40, 50, 60, 7]
    today_point = series.points[-1]
    assert today_point.partial is True
    # The today bar is the smallest despite being "in progress": no correction
    # multiplier has been applied to make it look comparable.
    assert today_point.pageviews == 7
    assert any("partial" in note.lower() for note in series.notes)


def test_a_bucket_with_no_ingest_is_a_hole_not_a_zero() -> None:
    """A gap in ingest is a different fact from a day nobody visited.

    Plotting them the same way turns "the timer did not run" into "the
    audience left", which is the more alarming of the two readings and the
    wrong one.
    """
    start = TODAY - timedelta(days=4)
    missing = start + timedelta(days=3)
    # Day 1 is a real zero: ingested, and nobody read anything. Day 3 is the
    # gap: never ingested at all. They must not render the same way.
    data = rows(start, [10, 0, 20, 40, 50])
    data = [row for row in data if row[0] != missing.isoformat()]
    present = [caps(start + timedelta(days=i)) for i in range(5)
               if start + timedelta(days=i) != missing]
    series = build_series(data, bucket="day", since=start, until=TODAY,
                          capabilities=present, title="T", today=TODAY)
    by_key = {p.key: p for p in series.points}
    assert by_key[missing.isoformat()].hole is True
    assert by_key[missing.isoformat()].pageviews == 0
    # A day that WAS ingested and simply had no pageviews is not a hole.
    genuine_zero = [p for p in series.points
                    if p.pageviews == 0 and not p.hole]
    assert genuine_zero, "a real zero must stay distinguishable from a gap"


def test_series_carries_capability_labels_per_bucket() -> None:
    """A bucket must know which dimensions existed inside it.

    Country exists only after the nginx change lands, so a month spanning the
    switch has to be labelled rather than charted as if country were simply
    zero for the first half.
    """
    start = TODAY - timedelta(days=5)
    mixed = [caps(start + timedelta(days=i),
                  log_format="legacy" if i < 3 else "extended")
             for i in range(6)]
    series = build_series(rows(start, [5] * 6), bucket="day", since=start,
                          until=TODAY, capabilities=mixed, title="T",
                          today=TODAY)
    early = series.points[0]
    late = series.points[-1]
    assert "country" not in early.capabilities
    assert "country" in late.capabilities


# --------------------------------------------------------------------------
# compare_periods
# --------------------------------------------------------------------------
def test_compare_periods_ignores_partial_buckets() -> None:
    """Comparing a half-finished period against a whole one is how this lies.

    The in-progress bucket here holds 1 pageview against the previous
    complete bucket's 100. If it were used, the report would print a 99% drop
    on the strength of the clock not having reached midnight yet.
    """
    start = TODAY - timedelta(days=3)
    series = build_series(
        rows(start, [100, 100, 100, 1]), bucket="day", since=start,
        until=TODAY, capabilities=[caps(start + timedelta(days=i))
                                   for i in range(4)],
        title="T", today=TODAY,
    )
    comparison = compare_periods(series, bucket="day")
    assert comparison is not None
    assert TODAY.isoformat() not in comparison.current_label
    # metrics are (name, current, previous, delta) tuples.
    by_name = {row[0]: row for row in comparison.metrics}
    name, current, previous, delta = by_name["pageviews"]
    # Two complete, equal periods: the delta is flat, not catastrophic.
    assert (current, previous) == (100, 100)
    assert delta == 0


def test_compare_periods_returns_none_without_two_complete_periods() -> None:
    """One complete bucket has nothing to compare against. Say nothing."""
    series = build_series(
        rows(TODAY, [5]), bucket="day", since=TODAY, until=TODAY,
        capabilities=[caps(TODAY)], title="T", today=TODAY,
    )
    assert compare_periods(series, bucket="day") is None


# --------------------------------------------------------------------------
# sparkline_values
# --------------------------------------------------------------------------
def test_sparkline_values_fit_the_width_and_stay_in_range() -> None:
    """The sparkline is a fixed-width glyph index, so it must be bounded."""
    start = TODAY - timedelta(days=59)
    series = build_series(
        rows(start, [i * 3 for i in range(60)]), bucket="day", since=start,
        until=TODAY, capabilities=[caps(start + timedelta(days=i))
                                   for i in range(60)],
        title="T", today=TODAY,
    )
    values = sparkline_values(series, width=20)
    assert len(values) <= 20
    assert all(v >= 0 for v in values), values
    # Downsampling SUMS within a cell rather than dropping points, so the total
    # survives and the sparkline cannot disagree with the table beneath it.
    assert sum(values) == sum(p.pageviews for p in series.points)
    # A rising series must still read as rising after downsampling.
    assert values[-1] >= values[0]


def test_sparkline_shorter_than_the_width_is_returned_unpadded() -> None:
    """Padding to the full width would draw periods that do not exist."""
    start = TODAY - timedelta(days=2)
    series = build_series(
        rows(start, [1, 2, 3]), bucket="day", since=start, until=TODAY,
        capabilities=[caps(start + timedelta(days=i)) for i in range(3)],
        title="T", today=TODAY,
    )
    assert len(sparkline_values(series, width=40)) == 3


@pytest.mark.parametrize("bucket", ["day", "week", "month", "year"])
def test_every_bucket_builds_a_series_without_raising(bucket: str) -> None:
    """A year of data must bucket at all four granularities.

    Guards the calendar edges — leap day, ISO week 53, December rollover —
    which is where date arithmetic written for one granularity breaks in
    another.
    """
    start = TODAY - timedelta(days=365)
    series = build_series(
        rows(start, [7] * 366), bucket=bucket, since=start, until=TODAY,
        capabilities=[caps(start + timedelta(days=i)) for i in range(366)],
        title="T", today=TODAY,
    )
    assert series.points
    assert sum(p.pageviews for p in series.points) == 7 * 366
    keys = [p.key for p in series.points]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
