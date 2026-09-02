"""Bucket the daily rollup into days, weeks, months, years and all-time.

The persistent store answers "how many pageviews on 2026-09-02"; this module
answers "how did September compare with August", which is the question the user
actually asked. Two things make that harder than a `GROUP BY`:

PARTIAL PERIODS. A month that is four days old is not a small month. Every
bucket whose calendar span is not fully inside the requested window — or which
runs past today — is flagged `partial`, is labelled as such by both renderers,
and is NEVER extrapolated to a full-period estimate. `compare_periods`
deliberately refuses partial buckets, because comparing a half-finished month
against a whole one is the classic way this section lies.

HOLES. A day the ingester never saw is not a day with no traffic. A bucket with
no capability record anywhere in it is a `hole` and is rendered differently from
a genuine zero, so a week the machine was off does not read as a week nobody
visited.

SCOPE: reads only cyberalertx's own dedicated log plus the shared legacy
archive, filtered to the cyberalertx vhost. The three other vhosts on this
box keep writing to /var/log/nginx/access.log untouched, and nothing here
writes to any log file, ever.

PRIVACY: nothing leaves the box. No network calls at runtime, no third-party
analytics, no dependency outside the stdlib. Raw IPs are never persisted or
printed — only salted hashes, with the salt rotated daily and retained 14 days.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, timedelta

from .aggregate import PeriodComparison, Series, SeriesPoint
from .store import DayCapabilities

logger = logging.getLogger("analytics.timeseries")

BUCKETS: tuple[str, ...] = ("day", "week", "month", "year", "all")

# English month abbreviations, spelled out rather than taken from strftime("%b").
# %b is locale-dependent: under a Ukrainian locale the labels would come back in
# Ukrainian while every date key elsewhere in the tool stays ISO, and the two
# would silently disagree.
_MONTH_ABBR: tuple[str, ...] = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

ALL_KEY: str = "all"


# ---------------------------------------------------------------------------
# Bucket arithmetic
# ---------------------------------------------------------------------------
def bucket_key(d: date, bucket: str) -> str:
    """The stable key a date belongs to, in the requested bucket."""
    if bucket == "day":
        return d.isoformat()
    if bucket == "week":
        iso_year, iso_week, _weekday = d.isocalendar()
        # ISO weeks, not "week of the month": 29 Dec 2025 belongs to 2026-W01,
        # and a naive year+week/7 scheme puts it in the wrong year.
        return f"{iso_year:04d}-W{iso_week:02d}"
    if bucket == "month":
        return f"{d.year:04d}-{d.month:02d}"
    if bucket == "year":
        return f"{d.year:04d}"
    if bucket == "all":
        return ALL_KEY
    raise ValueError(f"unknown bucket: {bucket!r}")


def bucket_bounds(key: str, bucket: str) -> tuple[date, date]:
    """Inclusive (first, last) calendar dates the key covers."""
    if bucket == "day":
        day = date.fromisoformat(key)
        return day, day
    if bucket == "week":
        iso_year, iso_week = key.split("-W")
        start = date.fromisocalendar(int(iso_year), int(iso_week), 1)
        return start, start + timedelta(days=6)
    if bucket == "month":
        year, month = (int(part) for part in key.split("-"))
        start = date(year, month, 1)
        end = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
        return start, end
    if bucket == "year":
        year = int(key)
        return date(year, 1, 1), date(year, 12, 31)
    if bucket == "all":
        return date.min, date.max
    raise ValueError(f"unknown bucket: {bucket!r}")


def bucket_label(key: str, bucket: str) -> str:
    """Human label for a bucket key: '02 Sep', 'W36 (31 Aug - 06 Sep)', 'Sep 2026'."""
    if bucket == "all":
        return "all time"
    start, end = bucket_bounds(key, bucket)
    if bucket == "day":
        return f"{start.day:02d} {_MONTH_ABBR[start.month - 1]}"
    if bucket == "week":
        week = key.split("-W")[1]
        return (
            f"W{week} ({start.day:02d} {_MONTH_ABBR[start.month - 1]} - "
            f"{end.day:02d} {_MONTH_ABBR[end.month - 1]})"
        )
    if bucket == "month":
        return f"{_MONTH_ABBR[start.month - 1]} {start.year}"
    return str(start.year)


def is_partial(key: str, bucket: str, *, since: date, until: date, today: date) -> bool:
    """True when the bucket's calendar span is not fully covered by the window.

    Three ways a bucket is partial, and all three must be caught or the trend
    line invents a cliff at each end:
      * it starts before `since` — the window cuts into it;
      * it ends after `until` — same, at the other end;
      * it reaches today — the period is still accumulating. Today's bucket is
        partial even at 23:59, because the ingest that fills it runs at 03:00
        the next morning; a half-filled bucket rendered as a finished one reads
        as a collapse in traffic every single day.
    """
    if bucket == "all":
        # An all-time total is complete for whatever the store holds; the
        # coverage banner is what states the range it covers.
        return False
    start, end = bucket_bounds(key, bucket)
    return start < since or end > until or end >= today


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------
def build_series(
    rows: Sequence[tuple[str, int, int, int, int]],
    *,
    bucket: str,
    since: date,
    until: date,
    capabilities: Sequence[DayCapabilities],
    title: str,
    today: date,
) -> Series:
    """Aggregate daily rows into the requested bucket.

    `rows` are `(local_date, pageviews, sessions, visitors, bot_events)` exactly
    as `AnalyticsStore.daily_totals` returns them.

    A day that was ingested but saw nothing is a genuine zero and is plotted. A
    day with no capability record was never ingested at all: it contributes
    nothing, and if a whole bucket is made of such days the bucket is a HOLE.
    Both renderers draw those differently, because "we did not look" and "nobody
    came" are different facts and only one of them is about the audience.
    """
    daily = {row[0]: row for row in rows}
    caps = {cap.local_date: cap for cap in capabilities}

    keys: list[str] = []
    members: dict[str, list[date]] = {}
    cursor = since
    while cursor <= until:
        key = bucket_key(cursor, bucket)
        if key not in members:
            members[key] = []
            keys.append(key)
        members[key].append(cursor)
        cursor += timedelta(days=1)

    points: list[SeriesPoint] = []
    visitors_summed = False
    for key in keys:
        days = members[key]
        pageviews = 0
        sessions = 0
        visitors = 0
        bot_events = 0
        ingested_days = 0
        client_ip_days = 0
        dimensions: set[str] = set()
        for day in days:
            iso = day.isoformat()
            capability = caps.get(iso)
            if capability is None:
                continue
            ingested_days += 1
            dimensions |= capability.dimensions()
            if capability.has_client_ip:
                client_ip_days += 1
            row = daily.get(iso)
            if row is None:
                continue
            pageviews += row[1]
            sessions += row[2]
            visitors += row[3]
            bot_events += row[4]

        # Visitors are summed only when EVERY ingested day in the bucket could
        # measure them. A week that is six legacy days plus one extended day
        # would otherwise print a week's visitors that are really one day's, and
        # the number would look like a collapse rather than a measurement gap.
        bucket_visitors: int | None
        if ingested_days and client_ip_days == ingested_days:
            bucket_visitors = visitors
            if len(days) > 1:
                visitors_summed = True
        else:
            bucket_visitors = None

        start_bound, end_bound = (days[0], days[-1]) if bucket == "all" else bucket_bounds(key, bucket)
        points.append(
            SeriesPoint(
                key=key,
                label=bucket_label(key, bucket),
                start=start_bound,
                end=end_bound,
                partial=is_partial(key, bucket, since=since, until=until, today=today),
                hole=ingested_days == 0,
                pageviews=pageviews,
                sessions=sessions if client_ip_days else None,
                visitors=bucket_visitors,
                bot_events=bot_events,
                capabilities=frozenset(dimensions),
            )
        )

    notes: list[str] = []
    if any(point.partial for point in points):
        notes.append(
            "periods marked (partial) are cut by the window or are still running — they are "
            "labelled, never extrapolated to a full-period estimate"
        )
    if any(point.hole for point in points):
        notes.append(
            "periods marked (no data) were never ingested — that is a gap in the record, "
            "not a period with no visitors"
        )
    if visitors_summed:
        notes.append(
            "visitors are summed across days: the salt rotates daily, so a multi-day figure "
            "counts visitor-DAYS, not people, and one reader present all week counts seven "
            "times"
        )

    return Series(
        title=title,
        bucket=bucket,
        points=tuple(points),
        sparkline=tuple(point.pageviews for point in points),
        compare=None,
        notes=tuple(notes),
    )


def compare_periods(series: Series, *, bucket: str) -> PeriodComparison | None:
    """Compare the last COMPLETE bucket against the one before it.

    Returns None when fewer than two complete buckets exist — the honest answer
    to "how does this month compare" after four days of data is "ask again
    later", not a number scaled up by 7.5.
    """
    complete = [point for point in series.points if not point.partial and not point.hole]
    if len(complete) < 2:
        return None
    previous, current = complete[-2], complete[-1]

    metrics: list[tuple[str, int, int, float | None]] = []
    for name, cur, prev in (
        ("pageviews", current.pageviews, previous.pageviews),
        ("sessions", current.sessions, previous.sessions),
        ("visitors", current.visitors, previous.visitors),
        ("bot requests", current.bot_events, previous.bot_events),
    ):
        if cur is None or prev is None:
            # The dimension did not exist in one of the two periods. Skipping it
            # is right: a delta against a period that could not measure the thing
            # would read as a 100% collapse or an infinite rise.
            continue
        # A delta against zero is undefined, not "+100%" and not "+inf".
        delta = ((cur - prev) / prev) if prev else None
        metrics.append((name, int(cur), int(prev), delta))

    return PeriodComparison(
        current_label=current.label,
        previous_label=previous.label,
        metrics=tuple(metrics),
    )


def sparkline_values(series: Series, *, width: int) -> tuple[int, ...]:
    """Fit the series to `width` cells by SUMMING within cells, never dropping.

    Dropping every other point makes a spiky series look calm, which is exactly
    backwards for a trend the reader is scanning for spikes. Summing preserves
    the total, so the sparkline and the table below it tell the same story.

    Fewer points than cells are returned unchanged: padding with zeros would
    draw periods that do not exist.
    """
    values = list(series.sparkline)
    if width <= 0 or not values or len(values) <= width:
        return tuple(values)

    cells: list[int] = []
    total = len(values)
    for index in range(width):
        start = (index * total) // width
        end = ((index + 1) * total) // width
        if end <= start:
            end = start + 1
        cells.append(sum(values[start:end]))
    return tuple(cells)
