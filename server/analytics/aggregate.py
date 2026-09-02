"""Count the events and build the `Report` — the handoff to both renderers.

`report.py` and `htmlreport.py` read `Report` and nothing else, so every
judgement about what may honestly be said lives here, once. The eleven
statistical-honesty rules from the contract are enforced through a single
helper, `share_or_none`, precisely so they cannot be remembered in nine sections
and forgotten in the tenth:

* n < 30 -> counts only, no percentages;
* an individual row with count < 5 -> no percentage for that row, whatever the
  table total is;
* counts always printed beside percentages, denominators in every heading;
* "unknown" is an explicit bucket in its natural rank position, never dropped,
  and carries a bias warning above 15%;
* a truncated tail is `+N more (M, X.X%)`, never a bare ellipsis, and a tail
  over 25% is itself the finding;
* bots are classified, subtracted, and the subtraction is SHOWN (the ledger).

Sections that the data cannot support are SUPPRESSED with a reason string, never
zeroed and never estimated. On legacy-format lines that means country, visitor
identity, sessions, bounce, duration, the language tables, client-hint
dimensions and all latency: the combined format simply does not carry them, and
a zero in those rows would be a claim about the world rather than a fact about
the log.

SCOPE: reads only cyberalertx's own dedicated log plus the shared legacy
archive, filtered to the cyberalertx vhost. The three other vhosts on this
box keep writing to /var/log/nginx/access.log untouched, and nothing here
writes to any log file, ever.

PRIVACY: nothing leaves the box. No network calls at runtime, no third-party
analytics, no dependency outside the stdlib. Raw IPs are never persisted or
printed — only salted hashes, with the salt rotated daily and retained 14 days.
"""
from __future__ import annotations

import hashlib
import logging
import math
import secrets
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING

from . import LOCALES, SITE_HOSTS, __version__
from .logread import EXTENDED, LEGACY, ParseStats
from .sessionize import (
    AgentProfile,
    AutomationFindings,
    Event,
    Ledger,
    Session,
    counts_as_pageview,
    same_day_returns,
)
from .store import DayCapabilities

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .store import AnalyticsStore

logger = logging.getLogger("analytics.aggregate")

# -- the honesty thresholds, in one place ----------------------------------
MIN_N_FOR_SHARE: int = 30       # below this, a percentage is noise dressed as fact
MIN_COUNT_FOR_SHARE: int = 5    # a row this small is a rounding artefact
MIN_N_FOR_HEADLINE: int = 100   # below this, no percentage may be a headline
UNKNOWN_BIAS_THRESHOLD: float = 0.15
TAIL_FINDING_THRESHOLD: float = 0.25
# Above this share of the pre-filter audience, the behavioural demotion stops
# being a footnote and becomes the headline finding of the run.
AUTOMATION_WARN_SHARE: float = 0.10

# -- suppression reasons, verbatim from the contract -----------------------
REASON_NO_COUNTRY = "no CF-IPCountry in the legacy combined format"
REASON_NO_VISITOR = (
    "legacy logs record Cloudflare edge IPs, not visitors — 121 pageviews arrived "
    "via 99 edge IPs"
)
REASON_NO_LANGUAGE = "no Accept-Language in the legacy combined format"
REASON_NO_HINTS = "client hints require the extended log format"
REASON_NO_RSC = "no Next-Router-Prefetch / RSC / Sec-Purpose headers in the legacy format"
REASON_NO_TIMING = "no $request_time in the legacy combined format"
# The behavioural pass is the only filter here that can be off, and an empty
# table has to say which of the two it is: "nothing was demoted" and "nothing
# was looked at" are opposite claims about the audience number above it.
REASON_NO_AUTOMATION_PASS = (
    "the behavioural automation pass did not run for this report"
)

# Unknown-bucket labels. Every dimension gets one; which one says WHY the value
# is missing, which is the difference between "we did not measure it" and "the
# browser refused to tell us".
UNKNOWN_NO_HEADER = "unknown (no header)"
UNKNOWN_UA_REDUCED = "unknown (UA-reduced)"
UNKNOWN_UNPARSED_UA = "unknown (unparsed UA)"
UNKNOWN_NO_CF = "unknown (no CF data)"
UNKNOWN_DIRECT_ORIGIN = "unknown (direct-to-origin)"
TOR_EXIT = "Tor exit node"

_UNKNOWN_LABELS: frozenset[str] = frozenset(
    {
        UNKNOWN_NO_HEADER,
        UNKNOWN_UA_REDUCED,
        UNKNOWN_UNPARSED_UA,
        UNKNOWN_NO_CF,
        UNKNOWN_DIRECT_ORIGIN,
    }
)

# Bounded-cardinality guards. Scanner traffic invents paths without limit, so the
# counters that see hostile input are capped and pruned rather than allowed to
# grow with the attacker's imagination.
_MAX_COUNTER_KEYS = 20_000
_KEEP_ON_PRUNE = 5_000
_MAX_LATENCY_SAMPLES = 250_000
_MAX_ROUTE_SAMPLES = 2_000
_MIN_ROUTE_SAMPLES = 20


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Row:
    label: str
    count: int
    share: float | None      # 0.0-1.0, or None when statistical honesty forbids a %
    note: str | None = None
    secondary: int | None = None
    secondary_label: str | None = None


@dataclass(frozen=True, slots=True)
class Table:
    title: str
    denominator_label: str
    n: int
    rows: tuple[Row, ...]
    tail_count: int
    tail_total: int
    tail_share: float | None
    unknown_share: float | None
    warnings: tuple[str, ...] = ()
    suppressed: bool = False
    suppressed_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Matrix:
    title: str
    n: int
    row_labels: tuple[str, ...]
    col_labels: tuple[str, ...]
    cells: tuple[tuple[int, ...], ...]
    row_totals: tuple[int, ...]
    row_shares: tuple[float | None, ...]
    preference: tuple[str, ...]
    notes: tuple[str, ...] = ()
    suppressed: bool = False
    suppressed_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Heatmap:
    title: str
    values: tuple[tuple[int, ...], ...]    # 7 rows Mon..Sun x 24 hours
    thresholds: tuple[int, ...]            # quantile cut points, 5 of them
    tz_name: str
    publish_marks: tuple[tuple[int, int], ...]
    # What each cell counts. Sessions need visitor identity, which legacy lines
    # do not carry, so the grid falls back to pageviews — and the heading has to
    # say so. Both renderers previously hardcoded "sessions/hour" and then
    # printed this section's own footnote saying it was counted by pageview.
    unit: str = "sessions"
    notes: tuple[str, ...] = ()
    suppressed: bool = False
    suppressed_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    key: str
    label: str
    start: date
    end: date
    partial: bool
    hole: bool               # no data ingested for this bucket at all
    pageviews: int
    sessions: int | None
    visitors: int | None
    bot_events: int
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class PeriodComparison:
    current_label: str
    previous_label: str
    metrics: tuple[tuple[str, int, int, float | None], ...]


@dataclass(frozen=True, slots=True)
class Series:
    title: str
    bucket: str
    points: tuple[SeriesPoint, ...]
    sparkline: tuple[int, ...]
    compare: PeriodComparison | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LatencyStats:
    n: int
    p50: float | None
    p90: float | None
    p99: float | None
    upstream_p50: float | None
    upstream_p90: float | None
    upstream_p99: float | None
    bytes_total: int
    suppressed: bool = False
    suppressed_reason: str | None = None
    # NO MEAN, deliberately. One 30s upstream timeout drags a mean far enough to
    # hide a healthy p99, and the mean of a latency distribution is not a number
    # any user ever experiences.


@dataclass(frozen=True, slots=True)
class SecurityNoise:
    total_hits: int
    # None, not 0, when the source addresses were not observable. A store-backed
    # report never sees an IP — the store deliberately persists none — so a bare
    # 0 here would read as "nobody is probing this box" when the truth is "this
    # report cannot tell you". --from-logs answers it properly.
    distinct_sources: int | None
    top_paths: tuple[Row, ...]
    top_countries: tuple[Row, ...]
    direct_to_origin: int
    forged_crawlers: int
    forged_top_uas: tuple[Row, ...]
    malformed_requests: int
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Headline:
    visitors: int | None
    sessions: int | None
    pageviews: int
    pageviews_hard: int
    pageviews_soft: int
    pages_per_visit_mean: float | None
    pages_per_visit_median: float | None
    bounce_rate: float | None
    bounce_ci_pp: float | None
    span_mean_seconds: float | None
    span_median_seconds: float | None
    engaged_sessions: int | None
    same_day_returns: int | None
    tldr: str


@dataclass(frozen=True, slots=True)
class Coverage:
    first_date: date | None
    last_date: date | None
    days_present: int
    days_missing: tuple[str, ...]
    dimensions_available: frozenset[str]
    dimensions_partial: dict[str, tuple[str, str]]
    dimensions_absent: frozenset[str]
    banner: str


DIMENSION_KEYS: tuple[str, ...] = (
    "country",
    "visitor",
    "language",
    "client_hints",
    "rsc",
    "timing",
    "host",
)


@dataclass(frozen=True, slots=True)
class Report:
    # -- provenance
    generated_at: datetime
    tool_version: str
    tz_name: str
    tz_fallback: bool
    since: datetime
    until: datetime
    sources: tuple[str, ...]
    formats_seen: frozenset[str]
    host_filter: tuple[str, ...]
    include_bots: bool
    hard_only: bool
    top_n: int
    # -- always present
    coverage: Coverage
    ledger: Ledger
    headline: Headline
    parse_stats: ParseStats
    # -- sections, in report order (see F)
    timeseries: Series
    all_time: Series | None
    countries: Table
    language_locale: Matrix
    languages: Table
    channels: Table
    campaigns: Table
    referrers: Table
    device_types: Table
    vendors: Table
    models: Table
    os_families: Table
    os_versions: Table
    browsers: Table
    in_app: Table
    locales: Table
    top_articles: Table
    entry_pages: Table
    broken_links: Table
    not_found: Table
    heatmap: Heatmap
    status_codes: Table
    latency: LatencyStats
    slowest_routes: Table
    bot_labels: Table
    bot_categories: Table
    agent_reach: Table
    feed_subscribers: Table
    suspected_automation: Table
    security: SecurityNoise
    # -- prose
    notes: tuple[str, ...]
    warnings: tuple[str, ...]


# ---------------------------------------------------------------------------
# Statistics — the honesty helpers
# ---------------------------------------------------------------------------
def share_or_none(count: int, n: int) -> float | None:
    """THE statistical-honesty helper, used by every table in the report.

    Returns None — meaning "print the count, print no percentage" — when the
    sample is too small for a percentage to carry information:

      n < 30       -> None. "33% of visitors use Firefox" over nine sessions is
                      three people, and a reader cannot tell that from the digit.
      count < 5    -> None, even when the table total is large. One extra request
                      moves a 4-count row by 25%.
      otherwise    -> count / n.
    """
    if n <= 0 or count < 0:
        return None
    if n < MIN_N_FOR_SHARE:
        return None
    if count < MIN_COUNT_FOR_SHARE:
        return None
    return count / n


def wilson_interval(successes: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — NOT the normal approximation.

    Bounce rates on a small news site sit near 0.9, and the normal interval
    around a proportion that close to 1 runs off the end of the scale and prints
    an upper bound above 100%. Wilson stays inside [0, 1] at every proportion,
    including the degenerate 0/n and n/n cases.
    """
    if n <= 0:
        return (0.0, 0.0)
    phat = successes / n
    denominator = 1.0 + (z * z) / n
    centre = phat + (z * z) / (2 * n)
    spread = z * math.sqrt((phat * (1.0 - phat) + (z * z) / (4 * n)) / n)
    low = (centre - spread) / denominator
    high = (centre + spread) / denominator
    return (max(0.0, low), min(1.0, high))


def median(values: Sequence[float]) -> float | None:
    """Median, or None for an empty sample. Never returns 0.0 for 'no data'."""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return (float(ordered[mid - 1]) + float(ordered[mid])) / 2.0


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile, q in [0, 1]. None for an empty sample."""
    if not values:
        return None
    if q <= 0:
        return float(min(values))
    if q >= 1:
        return float(max(values))
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(ordered[int(position)])
    lower = ordered[low] * (high - position)
    upper = ordered[high] * (position - low)
    return float(lower + upper)


def table_from_counter(
    counter: Mapping[str, int],
    *,
    title: str,
    denominator_label: str,
    n: int,
    top_n: int,
    notes: Mapping[str, str] | None = None,
    unknown_labels: Collection[str] = (),
    warnings: Sequence[str] = (),
) -> Table:
    """Order by count descending, alphabetical on ties, apply the honesty rules.

    Ties break alphabetically so two runs over the same data produce byte-
    identical output — a report that reshuffles its own rows between runs cannot
    be diffed, and diffing week over week is how anyone actually uses this.

    "unknown (...)" rows keep their NATURAL RANK POSITION. Exiling them to the
    bottom is the standard way an analytics tool hides how much it does not
    know; if unknown is the largest bucket, that is the headline.
    """
    unknown_keys = set(unknown_labels) | _UNKNOWN_LABELS
    note_map = dict(notes or {})
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    head = ordered[:top_n]
    tail = ordered[top_n:]

    rows = tuple(
        Row(label=label, count=count, share=share_or_none(count, n), note=note_map.get(label))
        for label, count in head
    )
    tail_total = sum(count for _label, count in tail)
    tail_share = share_or_none(tail_total, n)

    unknown_total = sum(count for label, count in ordered if label in unknown_keys)
    unknown_share = (unknown_total / n) if n > 0 else None

    collected = list(warnings)
    if unknown_share is not None and unknown_share > UNKNOWN_BIAS_THRESHOLD:
        collected.append(
            f"unknown is {unknown_share:.1%} of this dimension — the known part is "
            "trustworthy only if the unknowns are missing at random, and they are not: "
            "privacy-conscious users strip headers, so 'unknown' is a biased subset"
        )
    if tail_share is not None and tail_share > TAIL_FINDING_THRESHOLD:
        collected.append(
            f"the tail below the top {top_n} is {tail_share:.1%} of the total — a long-tail "
            "distribution is itself the finding here, not a truncation artefact"
        )
    if 0 < n < MIN_N_FOR_SHARE:
        collected.append(f"n = {n}: counts only, percentages are not meaningful below {MIN_N_FOR_SHARE}")

    return Table(
        title=title,
        denominator_label=denominator_label,
        n=n,
        rows=rows,
        tail_count=len(tail),
        tail_total=tail_total,
        tail_share=tail_share,
        unknown_share=unknown_share,
        warnings=tuple(collected),
    )


def suppressed_table(title: str, *, denominator_label: str, reason: str) -> Table:
    """An empty table that says WHY it is empty. Never a zero, never an estimate."""
    return Table(
        title=title,
        denominator_label=denominator_label,
        n=0,
        rows=(),
        tail_count=0,
        tail_total=0,
        tail_share=None,
        unknown_share=None,
        warnings=(),
        suppressed=True,
        suppressed_reason=reason,
    )


def build_ledger_rows(ledger: Ledger) -> list[tuple[str, int, float | None]]:
    """Thin façade over `Ledger.steps()` so renderers import only this module."""
    return ledger.steps()


# ---------------------------------------------------------------------------
# The behavioural automation pass, as the report sees it
# ---------------------------------------------------------------------------
def _correct_series_rows(
    rows: Sequence[tuple[str, int, int, int, int]],
    automation: AutomationFindings | None,
    *,
    include_bots: bool,
) -> list[tuple[str, int, int, int, int]]:
    """Subtract the demoted pageviews from the stored per-day rollup.

    Arithmetic, not estimation: the pass recorded exactly how many pageviews it
    removed on each local date, so each day is corrected by its own count and
    the same count is added to that day's bot column. A day the pass did not
    judge — everything outside the reporting window in the all-time series —
    is returned untouched, which is honest and is footnoted where it happens.

    `visitors` is deliberately NOT adjusted. It is a distinct-hash count, not a
    sum, so subtracting requests from it would be arithmetic on the wrong kind
    of number; on this site it is suppressed anyway, because legacy lines carry
    Cloudflare edge addresses rather than visitors.
    """
    if include_bots or automation is None or not automation.ran:
        return list(rows)
    removed = automation.demoted_by_date
    if not removed:
        return list(rows)
    corrected: list[tuple[str, int, int, int, int]] = []
    for day, pageviews, sessions, visitors, bot_events in rows:
        delta = removed.get(day, 0)
        corrected.append((day, max(0, pageviews - delta), sessions, visitors,
                          bot_events + delta))
    return corrected


def _automation_evidence(profile: AgentProfile, *, window_days: int) -> str:
    """The full case against one user-agent, as a footnote line.

    It goes in the table's footnotes rather than in the row's trailing note
    because the row note is dropped whenever the terminal is too narrow for it,
    and this is the part of the appendix a reader needs in order to disagree.
    The counts are absolute, never shares: two demoted agents are not a
    distribution.
    """
    sources = (f"{profile.distinct_sources} distinct source addresses"
               if profile.distinct_sources is not None
               else "source addresses unavailable (the store persists none)")
    return (
        f"evidence — {profile.label}: {profile.requests} requests, of which "
        f"{profile.human_requests} were classified human and "
        f"{profile.human_pageviews} counted as audience; "
        f"{profile.asset_requests} static-asset fetches; "
        f"{profile.distinct_paths} distinct paths; {sources}; active on "
        f"{profile.active_days} of {window_days} days, "
        f"{profile.active_hours} of 24 hours."
    )


def build_automation_table(
    automation: AutomationFindings | None, *, top_n: int
) -> Table:
    """Name every user-agent the behavioural pass removed, with its evidence.

    SUPPRESSED WITH A REASON whenever the pass did not run, never rendered as
    an empty table: "nothing was demoted" and "nothing was examined" are
    opposite claims about the audience figure printed above it, and a bare zero
    cannot tell them apart.
    """
    title = "SUSPECTED AUTOMATION (DEMOTED)"
    denominator = "by human pageview removed"
    if automation is None:
        return suppressed_table(title, denominator_label=denominator,
                                reason=REASON_NO_AUTOMATION_PASS)
    if not automation.ran:
        return suppressed_table(
            title, denominator_label=denominator,
            reason=automation.reason or REASON_NO_AUTOMATION_PASS,
        )

    n = automation.pageviews_before
    head = automation.demoted_agents[:top_n]
    tail = automation.demoted_agents[top_n:]
    rows = tuple(
        Row(
            label=profile.label,
            count=profile.human_pageviews,
            share=share_or_none(profile.human_pageviews, n),
            # The decisive fact, short enough to survive an 80-column
            # terminal. The rest of the evidence is a footnote below.
            note=f"{profile.asset_requests} assets",
            secondary=profile.requests,
            secondary_label="requests",
        )
        for profile in head
    )
    tail_total = sum(profile.human_pageviews for profile in tail)

    warnings = [
        _automation_evidence(profile, window_days=automation.window_days)
        for profile in head
    ]
    warnings += [
        f"the rule, in full: of the {automation.identities} user-agent identities that "
        f"produced a pageview in this {automation.window_days}-day window, one is demoted "
        f"only when it produced {automation.min_pageviews} or more human pageviews, "
        f"fetched exactly ZERO static assets across the whole window, and was active on at "
        f"least {automation.min_active_days} days. All three, or nothing happens.",
        "zero asset fetches is normal for a returning reader — Next.js chunks are "
        "immutable and cached for a year, so most real readers here fetch none. It is "
        "evidence only above the pageview floor, and the floor is deliberately high: "
        "at a floor of 20 this rule would have deleted 931 genuine pageviews across "
        "32 real reader populations.",
        "a scraper that fetches one asset per window defeats this test completely. "
        "One fetch exempts an identity, because fetching an asset proves a browser.",
    ]
    if automation.demoted_agents:
        warnings.append(
            "the judgement is per USER-AGENT STRING over the whole window, not per "
            "person: a demoted string takes any genuine reader sending that exact "
            "string with it."
        )
    return Table(
        title=title,
        denominator_label=denominator,
        n=n,
        rows=rows,
        tail_count=len(tail),
        tail_total=tail_total,
        tail_share=share_or_none(tail_total, n),
        unknown_share=None,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------
def build_coverage(
    capabilities: Sequence[DayCapabilities], *, since: date, until: date
) -> Coverage:
    """Summarise which dimensions existed, when, into the mandatory banner line.

    A dimension is `available` when every ingested day in the window carried it,
    `partial` when some days did and some did not (with the first and last dates
    it existed), and `absent` when no day carried it. The report prints this in
    every run, always: the day the nginx change lands, half the dimensions
    change from absent to partial, and a reader who cannot see that will read a
    methodological step-change as a change in the audience.
    """
    in_range = [cap for cap in capabilities if since.isoformat() <= cap.local_date <= until.isoformat()]
    present_dates = sorted(cap.local_date for cap in in_range)
    first = date.fromisoformat(present_dates[0]) if present_dates else None
    last = date.fromisoformat(present_dates[-1]) if present_dates else None

    missing: list[str] = []
    if first is not None and last is not None:
        known = set(present_dates)
        cursor = first
        while cursor <= last:
            if cursor.isoformat() not in known:
                missing.append(cursor.isoformat())
            cursor += timedelta(days=1)

    available: set[str] = set()
    partial: dict[str, tuple[str, str]] = {}
    absent: set[str] = set()
    for dimension in DIMENSION_KEYS:
        days = [cap.local_date for cap in in_range if dimension in cap.dimensions()]
        if not days:
            absent.add(dimension)
        elif len(days) == len(in_range):
            available.add(dimension)
        else:
            partial[dimension] = (min(days), max(days))

    formats = sorted({cap.log_format for cap in in_range})
    parts: list[str] = []
    if first is not None and last is not None:
        parts.append(f"{first.isoformat()} .. {last.isoformat()}")
        parts.append(f"{len(in_range)} days, {len(missing)} missing")
    else:
        parts.append("no data in range")
    if formats:
        parts.append("format: " + "/".join(formats))

    banner = "DATA COVERAGE  " + " · ".join(parts)
    unavailable = sorted(absent | set(partial))
    if unavailable:
        banner += "\n               unavailable for part of the range: " + ", ".join(unavailable)

    return Coverage(
        first_date=first,
        last_date=last,
        days_present=len(in_range),
        days_missing=tuple(missing),
        dimensions_available=frozenset(available),
        dimensions_partial=partial,
        dimensions_absent=frozenset(absent),
        banner=banner,
    )


# ---------------------------------------------------------------------------
# TL;DR
# ---------------------------------------------------------------------------
def build_tldr(report_parts: Mapping[str, object] | None = None) -> str:
    """One sentence naming the dominant country, device, channel and peak hour.

    Surfaced at the top of the report precisely because the section order is by
    reading dependency: the country mix is needed to read the language table, so
    the actual finding would otherwise sit at section six where nobody reads it.

    Recognised keys: country, device, channel, hour, mismatch (a
    (language, locale, share) triple), pageviews, locale_top.
    """
    parts = dict(report_parts or {})
    clauses: list[str] = []

    country = parts.get("country")
    device = parts.get("device")
    channel = parts.get("channel")
    hour = parts.get("hour")

    if country:
        clauses.append(f"mostly {country}")
    if device:
        clauses.append(str(device))
    if channel:
        label = "direct / unattributed" if channel == "direct" else str(channel)
        clauses.append(f"arriving via {label}")
    if isinstance(hour, int):
        clauses.append(f"peaking around {hour:02d}:00")

    sentence = ", ".join(clauses) if clauses else "not enough traffic yet to characterise the audience"
    mismatch = parts.get("mismatch")
    if isinstance(mismatch, tuple) and len(mismatch) == 3:
        language, locale, share = mismatch
        if isinstance(share, float):
            sentence += (
                f" — and {share:.0%} of {language}-language browsers read the "
                f"{str(locale).upper()} edition"
            )
    return sentence[:1].upper() + sentence[1:] if sentence else sentence


# ---------------------------------------------------------------------------
# Small internal helpers
# ---------------------------------------------------------------------------
def _prune(counter: Counter[str]) -> None:
    """Bound a counter fed by hostile input, keeping the meaningful head.

    Scanner traffic invents an unbounded number of distinct paths, so the
    counters that see it are capped. Only the long tail of one-hit entries is
    dropped, and the security section prints the total hit count from a separate
    scalar, so nothing that is reported becomes wrong — only the tail of the
    top-paths list is approximate.
    """
    if len(counter) <= _MAX_COUNTER_KEYS:
        return
    for label, _count in counter.most_common()[_KEEP_ON_PRUNE:]:
        del counter[label]


def _resolve_tz(tz_name: str) -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 - zoneinfo raises several distinct types
        # The caller already knows about the fallback (`tz_fallback`); a report
        # must never die at rendering time after all the parsing work is done.
        return timezone.utc


def _country_label(code: str | None) -> str:
    if code is None or code == "":
        # Absent CF-IPCountry means the request never came through Cloudflare.
        # That bucket is nearly all bots, which is itself the useful signal.
        return UNKNOWN_DIRECT_ORIGIN
    if code == "XX":
        return UNKNOWN_NO_CF
    if code == "T1":
        return TOR_EXIT
    return code


def _language_label(language: str | None) -> str:
    return language if language else UNKNOWN_NO_HEADER


def _vendor_label(vendor: str | None) -> str:
    return vendor if vendor else UNKNOWN_UA_REDUCED


def _model_label(model: str | None) -> str:
    # The `K` placeholder never reaches here as a model — useragent.py maps it to
    # None — so it lands in "unknown (UA-reduced)" rather than becoming a phantom
    # #1 handset called K. That bug is guaranteed to fire on a mobile-heavy
    # Chrome audience, and it is the single most common defect in this class of
    # tool.
    return model if model else UNKNOWN_UA_REDUCED


def _browser_label(browser: str | None) -> str:
    if not browser or browser == "Other":
        return UNKNOWN_UNPARSED_UA
    return browser


def _os_version_label(os_family: str, version: str | None, reliable: bool) -> str:
    if not version:
        return f"{os_family} (version not reported)"
    if not reliable:
        return f"{os_family} {version} (frozen by the UA)"
    return f"{os_family} {version}"


def _hashed(value: str, salt: str) -> str:
    return hashlib.blake2b(
        salt.encode("ascii") + b"\x00" + value.encode("utf-8", "replace"), digest_size=8
    ).hexdigest()


@dataclass
class _DayTally:
    """One local day's capability flags, accumulated while streaming events."""

    formats: set[str] = field(default_factory=set)
    events: int = 0
    host: bool = False
    client_ip: bool = False
    country: bool = False
    language: bool = False
    hints: bool = False
    rsc: bool = False
    timing: bool = False
    first: str = ""
    last: str = ""


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------
def build_report(
    events: Sequence[Event] | Iterable[Event],
    sessions: Sequence[Session],
    *,
    ledger: Ledger,
    parse_stats: ParseStats,
    coverage: Coverage,
    since: datetime,
    until: datetime,
    tz_name: str,
    tz_fallback: bool,
    sources: Sequence[str],
    top_n: int = 10,
    include_bots: bool = False,
    hard_only: bool = False,
    bucket: str = "day",
    all_time: bool = False,
    compare: bool = False,
    store: AnalyticsStore | None = None,
    publish_times: Sequence[datetime] = (),
    titles: Mapping[str, str] | None = None,
    host_filter: Sequence[str] | None = None,
    automation: AutomationFindings | None = None,
) -> Report:
    """Build the whole Report: one streaming pass over events, one over sessions.

    Nothing here holds the events themselves. The per-event pass accumulates
    counters, a bounded latency sample and per-article visitor sets, all of which
    are proportional to the CARDINALITY of the data rather than to its volume.

    `automation` is the outcome of `sessionize.demote_automation`, which the
    caller has ALREADY applied to `events` before handing them over. Nothing
    here re-decides anything: every audience counter below is corrected for
    free, because the demotion rewrote `Event.is_pageview` upstream. What this
    function still needs the findings for is the two things the events cannot
    carry — the evidence table naming what was subtracted, and the arithmetic
    correction to the stored daily rollup, which was computed at ingest time
    from the per-request verdict and knows nothing about the window. None means
    the pass did not run, and then this builds exactly what it always did.
    """
    from .timeseries import build_series, compare_periods  # local: avoids an import cycle

    tz = _resolve_tz(tz_name)
    titles = dict(titles or {})
    # An ephemeral per-run salt, so the distinct-source count in the security
    # section never holds a raw address in memory and cannot be replayed later.
    run_salt = secrets.token_hex(8)

    formats_seen: set[str] = set()
    saw_country = saw_language = saw_visitor = saw_hints = saw_timing = saw_rsc = False

    # -- per-event accumulators --------------------------------------------
    pageviews = 0
    pageviews_hard = 0
    pageviews_soft = 0
    pv_locale: Counter[str] = Counter()
    pv_channel: Counter[str] = Counter()
    pv_referrer: Counter[str] = Counter()
    pv_campaign: Counter[str] = Counter()
    pv_device: Counter[str] = Counter()
    pv_vendor: Counter[str] = Counter()
    pv_model: Counter[str] = Counter()
    pv_os: Counter[str] = Counter()
    pv_os_version: Counter[str] = Counter()
    pv_browser: Counter[str] = Counter()
    pv_in_app: Counter[str] = Counter()
    pv_entry: Counter[str] = Counter()

    article_visitors: dict[str, set[str]] = {}
    article_pageviews: Counter[str] = Counter()

    status_counter: Counter[str] = Counter()
    request_times: list[float] = []
    upstream_times: list[float] = []
    route_times: dict[str, list[float]] = {}
    bytes_total = 0
    latency_seen = 0

    bot_label_counter: Counter[str] = Counter()
    bot_category_counter: Counter[str] = Counter()
    reach_counter: Counter[str] = Counter()
    feed_polls: Counter[str] = Counter()
    feed_subscribers: dict[str, int] = {}

    broken_links: Counter[str] = Counter()
    broken_link_referers: dict[str, str] = {}
    scanner_404 = 0
    redirect_uk = 0

    security_hits = 0
    security_paths: Counter[str] = Counter()
    security_countries: Counter[str] = Counter()
    security_sources: set[str] = set()
    forged_uas: Counter[str] = Counter()
    direct_origin = 0
    forged_total = 0
    malformed_total = 0

    daily_pageviews: Counter[str] = Counter()
    daily_events: Counter[str] = Counter()
    daily_bots: Counter[str] = Counter()
    daily_visitors: dict[str, set[str]] = {}
    day_tally: dict[str, _DayTally] = {}

    # weekday x hour of human pageviews, used when sessions are unavailable
    heat_pv = [[0] * 24 for _ in range(7)]
    assigned_locale_sessions = 0

    for event in events:
        record = event.record
        formats_seen.add(record.fmt)
        verdict = event.verdict
        agent = event.agent

        saw_country |= record.cf_country is not None
        saw_language |= bool(record.accept_language)
        saw_visitor |= bool(record.ip_is_visitor)
        saw_hints |= bool(record.ch_available)
        saw_timing |= record.request_time is not None
        saw_rsc |= record.fmt == EXTENDED

        # per-day series scaffolding, used when no store is available
        daily_events[event.date] += 1
        tally = day_tally.setdefault(event.date, _DayTally())
        tally.events += 1
        tally.formats.add(record.fmt)
        tally.client_ip |= bool(record.ip_is_visitor)
        tally.country |= record.cf_country is not None
        tally.language |= bool(record.accept_language)
        tally.hints |= bool(record.ch_available)
        # RSC/prefetch is a property of the FORMAT: an extended line without the
        # header means "not a prefetch", a legacy line means "unknowable".
        tally.rsc |= record.fmt == EXTENDED
        tally.timing |= record.request_time is not None
        tally.host |= record.host is not None
        stamp = event.local_ts.isoformat()
        if not tally.first or stamp < tally.first:
            tally.first = stamp
        if stamp > tally.last:
            tally.last = stamp

        if verdict.klass != "human":
            daily_bots[event.date] += 1

        # -- security noise, counted then dropped before any audience rollup --
        if verdict.rule in ("cf-provenance", "forged-crawler", "scanner-path", "malformed"):
            security_hits += 1
            if record.path:
                security_paths[record.path] += 1
                _prune(security_paths)
            security_countries[_country_label(record.cf_country)] += 1
            source = record.peer_ip or record.client_ip
            if source:
                security_sources.add(_hashed(source, run_salt))
            if verdict.rule == "cf-provenance":
                direct_origin += 1
            if verdict.forged:
                forged_total += 1
                # Prefer the raw UA; fall back to the label the classifier
                # assigned, which the store DOES keep. Otherwise every forged
                # crawler on a store-backed report collapses into one row called
                # "(empty)" and the section stops naming what was impersonated.
                claimed = (record.user_agent or "")[:120]
                if not claimed:
                    claimed = verdict.label or "(unknown)"
                forged_uas[claimed] += 1
            if verdict.rule == "malformed":
                malformed_total += 1
            continue

        # -- automated traffic appendix ---------------------------------------
        if verdict.klass != "human":
            bot_label_counter[verdict.label] += 1
            bot_category_counter[verdict.category] += 1
            if verdict.subclass == "reach":
                reach_counter[verdict.label] += 1
            elif verdict.subclass == "feed":
                feed_polls[verdict.label] += 1
                if verdict.subscribers:
                    # Max-seen per reader: the number in the UA is what the
                    # reader reports right now, and the maximum across the range
                    # is the closest thing to a subscriber count that exists.
                    previous = feed_subscribers.get(verdict.label, 0)
                    feed_subscribers[verdict.label] = max(previous, int(verdict.subscribers))

        # -- technical health --------------------------------------------------
        # Computed over requests that actually reached the application: the
        # direct-to-origin probes and scanner noise were dropped above, and
        # including them would fill the status distribution with 400s that no
        # visitor ever saw.
        if record.status is not None:
            status_counter[str(record.status)] += 1
        if record.body_bytes:
            bytes_total += int(record.body_bytes)
        if record.request_time is not None:
            latency_seen += 1
            if len(request_times) < _MAX_LATENCY_SAMPLES:
                request_times.append(float(record.request_time))
                samples = route_times.setdefault(record.path, [])
                if len(samples) < _MAX_ROUTE_SAMPLES:
                    samples.append(float(record.request_time))
        if record.upstream_time is not None and len(upstream_times) < _MAX_LATENCY_SAMPLES:
            upstream_times.append(float(record.upstream_time))

        if record.path.startswith("/uk"):
            redirect_uk += 1

        # -- 404s: two populations that must never be merged -------------------
        if record.status == 404:
            if verdict.klass == "human" and event.referer_host:
                # A real browser followed a real link and it broke. Listed
                # individually, because each one is fixable.
                broken_links[record.path] += 1
                broken_link_referers.setdefault(record.path, event.referer_host)
            else:
                scanner_404 += 1

        # -- audience ----------------------------------------------------------
        if not counts_as_pageview(event, include_bots=include_bots):
            continue
        pageviews += 1
        daily_pageviews[event.date] += 1
        if event.nav == "soft":
            pageviews_soft += 1
        else:
            pageviews_hard += 1
        if event.visitor:
            daily_visitors.setdefault(event.date, set()).add(event.visitor)
        heat_pv[event.weekday][event.hour] += 1
        if event.locale_assigned:
            # Arrived via the / -> /en 307. The locale was ASSIGNED, not chosen,
            # and the language matrix footnotes the count so nobody reads these
            # as a preference for English.
            assigned_locale_sessions += 1

        pv_locale[event.locale or UNKNOWN_NO_HEADER] += 1
        pv_channel[event.channel] += 1
        if event.channel not in ("internal", "direct") and event.referer_host:
            pv_referrer[event.referer_host] += 1
        if event.campaign:
            pv_campaign[event.campaign] += 1
        pv_device[agent.device_type] += 1
        pv_vendor[_vendor_label(agent.device_vendor)] += 1
        pv_model[_model_label(agent.device_model)] += 1
        pv_os[agent.os_family] += 1
        pv_os_version[
            _os_version_label(agent.os_family, agent.os_version, agent.os_version_reliable)
        ] += 1
        pv_browser[_browser_label(agent.browser_family)] += 1
        pv_in_app[agent.in_app or "none (regular browser)"] += 1
        pv_entry[record.path] += 1

        if event.article_id:
            article_pageviews[event.article_id] += 1
            if event.visitor:
                article_visitors.setdefault(event.article_id, set()).add(event.visitor)

    # -- per-session pass ---------------------------------------------------
    se_country: Counter[str] = Counter()
    se_language: Counter[str] = Counter()
    se_channel: Counter[str] = Counter()
    se_campaign: Counter[str] = Counter()
    se_device: Counter[str] = Counter()
    se_vendor: Counter[str] = Counter()
    se_model: Counter[str] = Counter()
    se_os: Counter[str] = Counter()
    se_os_version: Counter[str] = Counter()
    se_browser: Counter[str] = Counter()
    se_in_app: Counter[str] = Counter()
    se_entry: Counter[str] = Counter()
    matrix_cells: Counter[tuple[str, str]] = Counter()
    heat = [[0] * 24 for _ in range(7)]

    bounces = 0
    engaged_spans: list[float] = []
    pages_per_visit: list[float] = []
    for session in sessions:
        se_country[_country_label(session.country)] += 1
        se_language[_language_label(session.language)] += 1
        se_channel[session.channel] += 1
        if session.campaign:
            se_campaign[session.campaign] += 1
        se_device[session.agent.device_type] += 1
        se_vendor[_vendor_label(session.agent.device_vendor)] += 1
        se_model[_model_label(session.agent.device_model)] += 1
        se_os[session.agent.os_family] += 1
        se_os_version[
            _os_version_label(
                session.agent.os_family,
                session.agent.os_version,
                session.agent.os_version_reliable,
            )
        ] += 1
        se_browser[_browser_label(session.agent.browser_family)] += 1
        se_in_app[session.agent.in_app or "none (regular browser)"] += 1
        se_entry[session.entry_path] += 1
        heat[session.started.weekday()][session.started.hour] += 1
        pages_per_visit.append(float(session.pageviews))
        if session.is_bounce:
            bounces += 1
        else:
            engaged_spans.append(session.duration_seconds)
        language = _language_label(session.language)
        for locale in sorted(session.locales):
            matrix_cells[(language, locale)] += 1

    legacy_only = EXTENDED not in formats_seen and LEGACY in formats_seen
    mixed = len(formats_seen) > 1
    has_sessions = bool(sessions)
    session_n = len(sessions)

    # -- choose the denominator for the per-dimension tables ----------------
    # Sessions are the honest unit for "who visited": one reader working through
    # ten articles is one Ukrainian mobile Telegram visitor, not ten. When
    # identity is unavailable the unit falls back to pageviews and every table
    # says so, rather than quietly changing meaning.
    if has_sessions:
        unit_label = "by session"
        unit_n = session_n
        dim_warnings: tuple[str, ...] = ()
        c_channel, c_campaign = se_channel, se_campaign
        c_device, c_vendor, c_model = se_device, se_vendor, se_model
        c_os, c_os_version, c_browser, c_in_app = se_os, se_os_version, se_browser, se_in_app
        c_entry = se_entry
    else:
        unit_label = "by pageview"
        unit_n = pageviews
        dim_warnings = (
            "counted by pageview, not by session: visitor identity is unavailable on "
            "legacy-format lines, so one reader of ten articles counts ten times",
        )
        c_channel, c_campaign = pv_channel, pv_campaign
        c_device, c_vendor, c_model = pv_device, pv_vendor, pv_model
        c_os, c_os_version, c_browser, c_in_app = pv_os, pv_os_version, pv_browser, pv_in_app
        c_entry = pv_entry
    legacy_marker = ("(legacy: client hints and visitor identity unavailable)",) if legacy_only else ()

    # -- time series ---------------------------------------------------------
    since_date = since.astimezone(tz).date()
    until_date = until.astimezone(tz).date()
    today = datetime.now(tz).date()
    if store is not None:
        rows = store.daily_totals(since=since_date, until=until_date, include_bots=include_bots)
        # THE TRAP. `daily_totals` answers from the `rollup` table, whose
        # pageview column was computed at ingest time from the PER-REQUEST
        # `events.is_pageview` — it has never heard of the whole-window
        # behavioural pass. Left alone it keeps summing to the pre-demotion
        # total, so TRAFFIC OVER TIME says 4 181 while AUDIENCE AT A GLANCE says
        # 2 324 and the report quietly contradicts itself. Corrected by
        # arithmetic on the exact per-day counts the pass recorded, never by an
        # estimate, and mirrored into the bot column so the day still balances.
        # Not applied under --include-bots: that mode deliberately re-admits
        # every non-human page request, so the uncorrected rollup is the right
        # answer there.
        rows = _correct_series_rows(rows, automation, include_bots=include_bots)
        capabilities = store.capabilities(since=since_date, until=until_date)
    else:
        rows = [
            (
                day,
                daily_pageviews.get(day, 0),
                0,
                len(daily_visitors.get(day, ())),
                daily_bots.get(day, 0),
            )
            for day in sorted(daily_events)
        ]
        capabilities = [
            _capability_from_tally(day, tally) for day, tally in sorted(day_tally.items())
        ]
        if has_sessions:
            per_day: Counter[str] = Counter(s.started.date().isoformat() for s in sessions)
            rows = [(day, pv, per_day.get(day, 0), vis, bots) for day, pv, _s, vis, bots in rows]

    series = build_series(
        rows,
        bucket=bucket,
        since=since_date,
        until=until_date,
        capabilities=capabilities,
        title="TRAFFIC OVER TIME",
        today=today,
    )
    if legacy_only or mixed:
        series = replace(
            series,
            notes=series.notes
            + (
                "legacy periods count hard navigations only — soft navigations are not "
                "distinguishable in the legacy format, so the series steps up on the day "
                "the extended log starts for methodological reasons, not growth",
            ),
        )
    if compare:
        series = replace(series, compare=compare_periods(series, bucket=bucket))

    all_time_series: Series | None = None
    if all_time and store is not None:
        span = store.date_range()
        if span is not None:
            all_rows = store.daily_totals(since=span[0], until=span[1], include_bots=include_bots)
            # The all-time span is wider than the reporting window, so the
            # correction can only reach the days the pass actually judged. Days
            # outside the window keep their per-request totals; the section's
            # note says so rather than leaving the reader to discover it.
            all_rows = _correct_series_rows(all_rows, automation, include_bots=include_bots)
            all_time_series = build_series(
                all_rows,
                bucket="month",
                since=span[0],
                until=span[1],
                capabilities=store.capabilities(),
                title="ALL-TIME SUMMARY",
                today=today,
            )
            if automation is not None and automation.ran and span[0] < since_date:
                all_time_series = replace(
                    all_time_series,
                    notes=all_time_series.notes
                    + (
                        "the behavioural automation filter was applied only to the "
                        f"reporting window ({since_date} .. {until_date}); earlier "
                        "months here are the raw per-request counts and are inflated "
                        "by whatever automation wore a browser user-agent then",
                    ),
                )

    # -- tables ---------------------------------------------------------------
    countries = (
        table_from_counter(
            se_country if has_sessions else Counter(),
            title="COUNTRY",
            denominator_label=unit_label,
            n=session_n,
            top_n=top_n,
            warnings=(
                "VPN exit nodes systematically overcount NL/DE/PL and undercount UA — a "
                "Ukrainian reader on a VPN shows as the exit country, and this is not "
                "silently corrected",
                "computed AFTER bot removal: datacenter traffic is heavily US-concentrated "
                "and this section is meaningless before the ledger's subtractions",
            )
            + legacy_marker,
        )
        if saw_country and has_sessions
        else suppressed_table("COUNTRY", denominator_label=unit_label, reason=REASON_NO_COUNTRY)
    )

    language_locale = (
        _build_matrix(matrix_cells, assigned=assigned_locale_sessions)
        if saw_language and has_sessions
        else Matrix(
            title="BROWSER LANGUAGE × EDITION READ",
            n=0,
            row_labels=(),
            col_labels=(),
            cells=(),
            row_totals=(),
            row_shares=(),
            preference=(),
            notes=(),
            suppressed=True,
            suppressed_reason=REASON_NO_LANGUAGE,
        )
    )

    languages = (
        table_from_counter(
            se_language,
            title="LANGUAGES",
            denominator_label=unit_label,
            n=session_n,
            top_n=top_n,
            warnings=(
                "'ru' is its own row and is never folded into 'other' — many readers run a "
                "Russian-language device UI while deliberately reading Ukrainian, and that "
                "gap is a product-decision input",
            ),
        )
        if saw_language and has_sessions
        else suppressed_table("LANGUAGES", denominator_label=unit_label, reason=REASON_NO_LANGUAGE)
    )

    channels = table_from_counter(
        Counter({_channel_label(k): v for k, v in c_channel.items() if k != "internal"}),
        title="ACQUISITION",
        denominator_label=unit_label,
        n=max(0, unit_n - c_channel.get("internal", 0)),
        top_n=top_n,
        warnings=dim_warnings
        + (
            "'direct / unattributed' is not 'people typed the URL': it holds in-app "
            "browsers, referrer stripping and this site's own strict-origin policy",
            "internal referers are excluded from attribution entirely — counting them "
            "makes the site its own top referrer",
        ),
    )
    campaigns = table_from_counter(
        c_campaign,
        title="CAMPAIGNS",
        denominator_label=unit_label,
        n=sum(c_campaign.values()),
        top_n=top_n,
        warnings=()
        if c_campaign
        else (
            "no UTM-tagged links seen — see the note about tagging the Telegram publish path",
        ),
    )
    # Referrers are counted by PAGEVIEW even when sessions exist: a Session
    # records the acquisition channel but not the referring host, and inventing a
    # session-level referrer by picking one of several would be a guess.
    referrers = table_from_counter(
        pv_referrer,
        title="TOP EXTERNAL REFERRERS",
        denominator_label="by pageview",
        n=sum(pv_referrer.values()),
        top_n=top_n,
        warnings=(
            "internal referers are excluded; 'direct / unattributed' carries no host and "
            "cannot appear here at all",
        ),
    )

    device_types = table_from_counter(
        c_device,
        title="DEVICE CLASS",
        denominator_label=unit_label,
        n=unit_n,
        top_n=top_n,
        warnings=dim_warnings
        + (
            "Android in 'request desktop site' mode reports as Linux desktop, and iPadOS "
            "Safari defaults to a Macintosh UA — iPads hide inside macOS with no "
            "server-side fix",
        ),
    )
    vendors = table_from_counter(
        c_vendor,
        title="DEVICE VENDOR",
        denominator_label=unit_label,
        n=unit_n,
        top_n=top_n,
        warnings=dim_warnings + legacy_marker,
    )
    models = table_from_counter(
        c_model,
        title="DEVICE MODEL",
        denominator_label=unit_label,
        n=unit_n,
        top_n=top_n,
        warnings=dim_warnings
        + (
            "model is enrichment, not a core metric: Chrome's UA reduction removed it for "
            "most Android sessions and iOS has never carried one",
        )
        + legacy_marker,
    )
    os_families = table_from_counter(
        c_os,
        title="OPERATING SYSTEM",
        denominator_label=unit_label,
        n=unit_n,
        top_n=top_n,
        warnings=dim_warnings,
    )
    os_versions = table_from_counter(
        c_os_version,
        title="OS VERSION",
        denominator_label=unit_label,
        n=unit_n,
        top_n=top_n,
        warnings=dim_warnings
        + (
            "'Windows 10/11' is one bucket because the UA freezes at NT 10.0; splitting it "
            "needs Sec-CH-UA-Platform-Version, and that threshold is itself unverified",
            "macOS reports no version at all — Safari freezes it at 10_15_7",
        ),
    )
    browsers = table_from_counter(
        c_browser,
        title="BROWSER",
        denominator_label=unit_label,
        n=unit_n,
        top_n=top_n,
        warnings=dim_warnings
        + (
            "Brave is invisible: it strips its token and counts as Chrome, so no Brave "
            "figure is claimed here",
        ),
    )
    in_app_table = table_from_counter(
        c_in_app,
        title="IN-APP BROWSER",
        denominator_label=unit_label,
        n=unit_n,
        top_n=top_n,
        warnings=dim_warnings
        + (
            "this is where the Telegram answer lives — in-app taps often send no Referer, "
            "so the acquisition table under-reports what this table shows",
        ),
    )

    locales_table = table_from_counter(
        pv_locale,
        title="EDITIONS READ",
        denominator_label="by pageview",
        n=pageviews,
        top_n=top_n,
        warnings=(
            "prefetch is excluded; a locale switch served from the Router Cache emits no "
            "request at all, so switching is systematically under-measured and no "
            "correction multiplier is applied",
        ),
    )

    if article_visitors:
        ranked = sorted(article_visitors.items(), key=lambda item: (-len(item[1]), item[0]))
        article_rows = ranked[:top_n]
        art_n = len({v for values in article_visitors.values() for v in values})
        top_articles = Table(
            title="TOP ARTICLES",
            denominator_label="by distinct visitor",
            n=art_n,
            rows=tuple(
                Row(
                    label=titles.get(article, article),
                    count=len(visitors),
                    share=share_or_none(len(visitors), art_n),
                    secondary=article_pageviews.get(article, 0),
                    secondary_label="pageviews",
                )
                for article, visitors in article_rows
            ),
            tail_count=len(ranked) - len(article_rows),
            tail_total=sum(len(visitors) for _article, visitors in ranked[top_n:]),
            tail_share=None,
            unknown_share=None,
            warnings=(
                "ranked by distinct visitors, not pageviews: ranking by pageviews lets one "
                "refresh-happy reader or one scraper create a #1 story",
            ),
        )
    else:
        top_articles = table_from_counter(
            Counter({titles.get(k, k): v for k, v in article_pageviews.items()}),
            title="TOP ARTICLES",
            denominator_label="by pageview",
            n=sum(article_pageviews.values()),
            top_n=top_n,
            warnings=(
                "ranked by pageviews because visitor identity is unavailable — one heavy "
                "reader can create a #1 story here",
            ),
        )

    entry_pages = table_from_counter(
        c_entry,
        title="ENTRY PAGES",
        denominator_label=unit_label,
        n=unit_n,
        top_n=top_n,
        warnings=dim_warnings
        if has_sessions
        else dim_warnings
        + ("approximated: without sessions every pageview counts as an entry",),
    )

    broken_rows = tuple(
        Row(
            label=path,
            count=count,
            share=None,
            note=f"from {broken_link_referers.get(path, 'unknown referer')}",
        )
        for path, count in sorted(broken_links.items(), key=lambda item: (-item[1], item[0]))[:top_n]
    )
    broken_table = Table(
        title="BROKEN LINKS",
        denominator_label="by request (browser UA with a referer)",
        n=sum(broken_links.values()),
        rows=broken_rows,
        tail_count=max(0, len(broken_links) - len(broken_rows)),
        tail_total=max(0, sum(broken_links.values()) - sum(r.count for r in broken_rows)),
        tail_share=None,
        unknown_share=None,
        warnings=("each of these is a real link somewhere that points at a page that is gone",),
    )
    not_found = Table(
        title="NOT FOUND (PROBES)",
        denominator_label="by request",
        n=scanner_404,
        rows=(
            Row(label="scanner and probe 404s (collapsed)", count=scanner_404, share=None),
            Row(label="/uk requests 301-redirected to /ua", count=redirect_uk, share=None,
                note="surviving old bookmarks and inbound links"),
        ),
        tail_count=0,
        tail_total=0,
        tail_share=None,
        unknown_share=None,
        warnings=("never enumerated: listing scanner paths turns the report into the "
                  "attacker's wordlist",),
    )

    heatmap = _build_heatmap(
        heat if has_sessions else heat_pv,
        tz_name=tz_name,
        publish_times=publish_times,
        tz=tz,
        by_session=has_sessions,
        since=since,
        until=until,
    )

    status_codes = table_from_counter(
        status_counter,
        title="STATUS CODES",
        denominator_label="by request (direct-to-origin probes and scanners excluded)",
        n=sum(status_counter.values()),
        top_n=top_n,
    )

    if saw_timing and request_times:
        latency = LatencyStats(
            n=latency_seen,
            p50=percentile(request_times, 0.50),
            p90=percentile(request_times, 0.90),
            p99=percentile(request_times, 0.99),
            upstream_p50=percentile(upstream_times, 0.50),
            upstream_p90=percentile(upstream_times, 0.90),
            upstream_p99=percentile(upstream_times, 0.99),
            bytes_total=bytes_total,
        )
        route_rows = []
        for path, samples in route_times.items():
            if len(samples) < _MIN_ROUTE_SAMPLES:
                continue
            p90 = percentile(samples, 0.90) or 0.0
            route_rows.append(
                Row(
                    label=path,
                    count=int(round(p90 * 1000)),
                    share=None,
                    secondary=len(samples),
                    secondary_label="requests",
                    note="p90 ms",
                )
            )
        route_rows.sort(key=lambda row: (-row.count, row.label))
        slowest_routes = Table(
            title="SLOWEST ROUTES",
            denominator_label="p90 request time, ms",
            n=len(route_rows),
            rows=tuple(route_rows[:top_n]),
            tail_count=max(0, len(route_rows) - top_n),
            tail_total=0,
            tail_share=None,
            unknown_share=None,
            warnings=(
                f"routes with fewer than {_MIN_ROUTE_SAMPLES} samples are excluded — a p90 "
                "over three requests is not a percentile",
            ),
        )
    else:
        latency = LatencyStats(
            n=0,
            p50=None,
            p90=None,
            p99=None,
            upstream_p50=None,
            upstream_p90=None,
            upstream_p99=None,
            bytes_total=bytes_total,
            suppressed=True,
            suppressed_reason=REASON_NO_TIMING,
        )
        slowest_routes = suppressed_table(
            "SLOWEST ROUTES", denominator_label="p90 request time, ms", reason=REASON_NO_TIMING
        )

    bot_total = sum(bot_label_counter.values())
    bot_labels = table_from_counter(
        bot_label_counter,
        title="TOP BOTS",
        denominator_label="by request",
        n=bot_total,
        top_n=top_n,
        warnings=(
            "these are a share of requests REACHING THE ORIGIN, not of all traffic — "
            "Cloudflare's managed rules drop the worst before it ever gets here",
        ),
    )
    bot_categories = table_from_counter(
        bot_category_counter,
        title="BOT CATEGORIES",
        denominator_label="by request",
        n=bot_total,
        top_n=top_n,
    )
    agent_reach = table_from_counter(
        reach_counter,
        title="LINK SHARES (REACH)",
        denominator_label="by unfurl request",
        n=sum(reach_counter.values()),
        top_n=top_n,
        warnings=(
            "each hit is one person pasting a link somewhere — a share event, not a visit",
        ),
    )
    feed_rows = tuple(
        Row(
            label=label,
            count=count,
            share=None,
            secondary=feed_polls.get(label, 0),
            secondary_label="polls",
        )
        for label, count in sorted(feed_subscribers.items(), key=lambda item: (-item[1], item[0]))[
            :top_n
        ]
    )
    feed_table = Table(
        title="FEED SUBSCRIBERS",
        denominator_label="max subscribers reported per reader",
        n=sum(feed_subscribers.values()),
        rows=feed_rows,
        tail_count=0,
        tail_total=0,
        tail_share=None,
        unknown_share=None,
        warnings=(
            "reported as SUBSCRIBERS, never as visits: one Feedly subscriber generates "
            "50-100 polls a day and would otherwise be the site's top reader",
        ),
    )

    suspected_automation = build_automation_table(automation, top_n=top_n)

    security = SecurityNoise(
        total_hits=security_hits,
        # Zero observed sources means the addresses were never available
        # (store-backed run), not that nobody probed the origin.
        distinct_sources=len(security_sources) or None,
        top_paths=tuple(
            Row(label=path, count=count, share=None)
            for path, count in security_paths.most_common(10)
        ),
        top_countries=tuple(
            Row(label=label, count=count, share=None)
            for label, count in security_countries.most_common(5)
        ),
        direct_to_origin=direct_origin,
        forged_crawlers=forged_total,
        forged_top_uas=tuple(
            Row(label=ua, count=count, share=None) for ua, count in forged_uas.most_common(5)
        ),
        malformed_requests=malformed_total,
        notes=(
            "direct-to-origin means someone has the origin IP and is bypassing Cloudflare — "
            "an infrastructure signal, not just noise",
            "this section exists to keep the filter auditable: a silently discarded bucket "
            "is one nobody notices has grown to swallow real traffic",
        ),
    )

    # -- headline -------------------------------------------------------------
    visitors = len({s.visitor for s in sessions}) if (has_sessions and saw_visitor) else None
    bounce_rate = (bounces / session_n) if session_n else None
    bounce_ci_pp: float | None = None
    if session_n >= MIN_N_FOR_HEADLINE:
        # Below MIN_N_FOR_HEADLINE the rate is still computed but carries no
        # interval: the renderer then prints the raw counts beside it, and a
        # bounce rate over twelve sessions is a description of twelve sessions.
        low, high = wilson_interval(bounces, session_n)
        bounce_ci_pp = (high - low) / 2 * 100

    tldr = build_tldr(
        {
            "country": _top_key(se_country, skip=_UNKNOWN_LABELS),
            "device": _top_key(c_device, skip={"unknown"}),
            "channel": _top_key(c_channel, skip={"internal"}),
            "hour": _peak_hour(heat if has_sessions else heat_pv),
            "mismatch": _biggest_off_diagonal(matrix_cells),
        }
    )

    headline = Headline(
        visitors=visitors,
        sessions=session_n if has_sessions else None,
        pageviews=pageviews,
        pageviews_hard=pageviews_hard,
        pageviews_soft=pageviews_soft,
        pages_per_visit_mean=(sum(pages_per_visit) / len(pages_per_visit)) if pages_per_visit else None,
        pages_per_visit_median=median(pages_per_visit),
        bounce_rate=bounce_rate,
        bounce_ci_pp=bounce_ci_pp,
        span_mean_seconds=(sum(engaged_spans) / len(engaged_spans)) if engaged_spans else None,
        span_median_seconds=median(engaged_spans),
        engaged_sessions=len(engaged_spans) if has_sessions else None,
        same_day_returns=same_day_returns(sessions) if has_sessions else None,
        tldr=tldr,
    )

    # -- prose ----------------------------------------------------------------
    notes = _build_notes(hard_only=hard_only, legacy_only=legacy_only,
                         automation=automation)
    warnings = _build_warnings(
        formats_seen=formats_seen,
        capabilities=capabilities,
        parse_stats=parse_stats,
        tz_fallback=tz_fallback,
        tz_name=tz_name,
        include_bots=include_bots,
        automation=automation,
    )

    return Report(
        generated_at=datetime.now(tz),
        tool_version=__version__,
        tz_name=tz_name,
        tz_fallback=tz_fallback,
        since=since,
        until=until,
        sources=tuple(sources),
        formats_seen=frozenset(formats_seen),
        host_filter=tuple(host_filter) if host_filter else tuple(sorted(SITE_HOSTS)),
        include_bots=include_bots,
        hard_only=hard_only,
        top_n=top_n,
        coverage=coverage,
        ledger=ledger,
        headline=headline,
        parse_stats=parse_stats,
        timeseries=series,
        all_time=all_time_series,
        countries=countries,
        language_locale=language_locale,
        languages=languages,
        channels=channels,
        campaigns=campaigns,
        referrers=referrers,
        device_types=device_types,
        vendors=vendors,
        models=models,
        os_families=os_families,
        os_versions=os_versions,
        browsers=browsers,
        in_app=in_app_table,
        locales=locales_table,
        top_articles=top_articles,
        entry_pages=entry_pages,
        broken_links=broken_table,
        not_found=not_found,
        heatmap=heatmap,
        status_codes=status_codes,
        latency=latency,
        slowest_routes=slowest_routes,
        bot_labels=bot_labels,
        bot_categories=bot_categories,
        agent_reach=agent_reach,
        feed_subscribers=feed_table,
        suspected_automation=suspected_automation,
        security=security,
        notes=notes,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------
def _channel_label(channel: str) -> str:
    # Rendered this way EVERYWHERE. "direct" alone reads as "people typed the
    # URL", which is the one thing it does not mean.
    return "direct / unattributed" if channel == "direct" else channel


def _build_matrix(cells: Mapping[tuple[str, str], int], *, assigned: int) -> Matrix:
    """Browser language x edition read. The signal is in the OFF-DIAGONALS.

    A session that read both editions contributes to both columns, so the cells
    count (session, locale) pairs and the row total is the row's pair count. The
    ratio must be read WITHIN a row: the aggregate column share just restates the
    site's overall EN/UA split.
    """
    if not cells:
        return Matrix(
            title="BROWSER LANGUAGE × EDITION READ",
            n=0,
            row_labels=(),
            col_labels=(),
            cells=(),
            row_totals=(),
            row_shares=(),
            preference=(),
        )
    languages = sorted({language for language, _locale in cells}, key=lambda lang: (
        -sum(count for (row_lang, _), count in cells.items() if row_lang == lang),
        lang,
    ))
    seen_locales = {locale for _language, locale in cells}
    columns = tuple(locale for locale in LOCALES if locale in seen_locales) + tuple(
        sorted(seen_locales - set(LOCALES))
    )
    grid: list[tuple[int, ...]] = []
    totals: list[int] = []
    preference: list[str] = []
    for language in languages:
        row = tuple(cells.get((language, locale), 0) for locale in columns)
        grid.append(row)
        totals.append(sum(row))
        best = max(range(len(columns)), key=lambda i: row[i]) if columns else 0
        if columns and row.count(row[best]) > 1:
            preference.append("mixed")
        else:
            preference.append(columns[best] if columns else "")
    n = sum(totals)
    return Matrix(
        title="BROWSER LANGUAGE × EDITION READ",
        n=n,
        row_labels=tuple(languages),
        col_labels=columns,
        cells=tuple(grid),
        row_totals=tuple(totals),
        row_shares=tuple(share_or_none(total, n) for total in totals),
        preference=tuple(preference),
        notes=(
            f"! {assigned} EN sessions were ASSIGNED via the / → /en redirect, not chosen.",
            "! prefetch excluded; cached locale switches are invisible (see notes)",
            "read the ratio WITHIN each language row, never the aggregate column share",
            "a session that read both editions counts once in each column",
        ),
    )


def _build_heatmap(
    grid: Sequence[Sequence[int]],
    *,
    tz_name: str,
    publish_times: Sequence[datetime],
    tz: tzinfo,
    by_session: bool,
    since: datetime,
    until: datetime,
) -> Heatmap:
    """7x24 weekday x hour, on a QUANTILE scale.

    A linear scale leaves twenty of the twenty-four columns blank on a site with
    one strong evening peak, which hides the shape the section exists to show.

    Publish times are overlaid as marks, because publishing here is automated:
    without the overlay this section shows the user their own cron schedule
    reflected back at them and calls it audience behaviour.
    """
    values = [value for row in grid for value in row]
    non_zero = sorted(v for v in values if v > 0)
    if non_zero:
        cuts = [percentile(non_zero, q) or 0.0 for q in (0.2, 0.4, 0.6, 0.8, 0.95)]
        thresholds = tuple(int(math.ceil(cut)) for cut in cuts)
    else:
        thresholds = (0, 0, 0, 0, 0)

    marks = sorted(
        {
            (moment.astimezone(tz).weekday(), moment.astimezone(tz).hour)
            for moment in publish_times
        }
    )

    notes = [
        f"times are {tz_name} — a UTC heatmap for a UTC+3 audience shifts the peak three "
        "hours and every recommendation derived from it is wrong",
        "worthless without bot filtering: bots poll uniformly around the clock and flatten "
        "the human diurnal peak into noise",
    ]
    if marks:
        notes.append(
            "▲ marks automated publish times, so 'the audience is awake at 09:00' stays "
            "distinguishable from 'I posted at 09:00'"
        )
    else:
        notes.append("no publish times supplied — the audience peak cannot be separated "
                     "from the publishing schedule in this run")
    if not by_session:
        notes.append(
            "counted by pageview: sessions need visitor identity, which legacy-format "
            "lines do not carry"
        )
    if since.utcoffset() != until.utcoffset():
        notes.append(
            "the range contains a DST transition — one hour column is empty and another "
            "holds two hours of traffic; this is left visible rather than 'fixed'"
        )

    return Heatmap(
        title="WHEN THEY READ",
        values=tuple(tuple(int(v) for v in row) for row in grid),
        thresholds=thresholds,
        tz_name=tz_name,
        publish_marks=tuple(marks),
        unit="sessions" if by_session else "pageviews",
        notes=tuple(notes),
    )


def _capability_from_tally(day: str, tally: _DayTally) -> DayCapabilities:
    """The per-day capability record for a run with no store behind it.

    `--from-logs` reads the logs directly and still owes the reader the coverage
    banner, so the same record the store would have written is derived on the fly.
    """
    if tally.formats == {EXTENDED}:
        log_format = EXTENDED
    elif tally.formats == {LEGACY}:
        log_format = LEGACY
    else:
        log_format = "mixed"
    return DayCapabilities(
        local_date=day,
        log_format=log_format,
        has_host=tally.host,
        has_client_ip=tally.client_ip,
        has_country=tally.country,
        has_accept_language=tally.language,
        has_client_hints=tally.hints,
        has_rsc_headers=tally.rsc,
        has_timing=tally.timing,
        events=tally.events,
        first_seen=tally.first,
        last_seen=tally.last,
    )


def _top_key(counter: Mapping[str, int], *, skip: Collection[str] = ()) -> str | None:
    candidates = [(count, label) for label, count in counter.items() if label not in skip]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[1]


def _peak_hour(grid: Sequence[Sequence[int]]) -> int | None:
    hours = [sum(row[hour] for row in grid) for hour in range(24)]
    if not any(hours):
        return None
    return max(range(24), key=lambda hour: hours[hour])


def _biggest_off_diagonal(cells: Mapping[tuple[str, str], int]) -> tuple[str, str, float] | None:
    """The largest share of one language reading a DIFFERENT edition.

    This is the finding the user cannot guess: a Ukrainian-language browser
    choosing the English edition is a product signal, and it is invisible in
    both the language table and the locale table taken separately.
    """
    totals: Counter[str] = Counter()
    for (language, _locale), count in cells.items():
        totals[language] += count
    best: tuple[str, str, float] | None = None
    for (language, locale), count in cells.items():
        if language == UNKNOWN_NO_HEADER:
            continue
        # "uk" is the ISO code for the Ukrainian language; "ua" is this site's
        # locale segment. They are the diagonal, not an off-diagonal.
        diagonal = (language == "uk" and locale == "ua") or language == locale
        if diagonal:
            continue
        total = totals[language]
        if total < MIN_N_FOR_SHARE or count < MIN_COUNT_FOR_SHARE:
            continue
        share = count / total
        if best is None or share > best[2]:
            best = (language, locale, share)
    return best


def _automation_notes(automation: AutomationFindings | None) -> list[str]:
    """The behavioural filter's footnotes: the rule, and how it fails BOTH ways.

    Printed whether or not it removed anything, and printed when it did not run
    at all. A subtraction the reader cannot see is a subtraction the reader
    cannot argue with, and a filter that silently switched itself off is worse
    than one that found nothing — the audience number means something different
    in each case.
    """
    if automation is None:
        return []
    if not automation.ran:
        return [
            "the behavioural automation filter did NOT run for this report "
            f"({automation.reason}). The pageview total above is therefore the "
            "per-request one: a scraper wearing a plausible browser user-agent and "
            "arriving through Cloudflare is counted in it as a reader."
        ]
    removed = automation.demoted_pageviews
    share = automation.demoted_share
    share_text = f" ({share:.1%} of the pre-filter total)" if share is not None else ""
    notes = [
        "behavioural automation filter: a user-agent is removed from the audience only "
        f"when it produced at least {automation.min_pageviews} human pageviews, fetched "
        f"ZERO static assets across the whole window, and was active on at least "
        f"{automation.min_active_days} days. This run removed "
        f"{len(automation.demoted_agents)} user-agent(s), {removed} pageviews"
        f"{share_text}, over a {automation.window_days}-day window.",
        "that filter's failure modes, both directions: (a) the verdict is per USER-AGENT "
        "STRING over the whole window, so a demoted string takes any real reader sending "
        "that exact string with it; (b) the inverse is never applied — a LOW-VOLUME "
        "user-agent that fetches no assets is a returning reader with a warm cache and is "
        "never demoted, because Next.js static chunks are immutable and cached for a "
        "year; (c) fetching assets proves a browser but never whitelists a declared "
        "crawler — Baiduspider-render fetches /_next/static/chunks/*.js and the signature "
        "catalogue still outranks behaviour; (d) a scraper that fetches one asset per "
        "window defeats the test entirely.",
        "the filter is a REPORT-TIME judgement over the whole window, never written back "
        "into the store: stored rows keep the per-request verdict, so `ingest --reingest` "
        "stays reproducible and the rule can be re-run or revised as evidence accrues. "
        "It is scoped to this report's window, so a different --since can reach a "
        "different verdict about the same user-agent; below "
        f"{automation.min_window_days} days it suppresses itself entirely rather than "
        "apply a rule that measurably inverts at short windows.",
    ]
    return notes


def _build_notes(*, hard_only: bool, legacy_only: bool,
                 automation: AutomationFindings | None = None) -> tuple[str, ...]:
    notes = [
        "visitors = distinct daily IP+UA+language hashes, salted, rotated at 04:00. "
        "Carrier NAT (Kyivstar, Vodafone, lifecell) merges several people into one, so the "
        "true figure is HIGHER than reported. IPv6 rotation may split one person into "
        "several; mitigated by hashing the /64 prefix.",
        "cross-day identity is not computable by design — the salt rotates daily. "
        "'Returning visitors' and retention curves are therefore never printed.",
        "bounce rate is an UPPER BOUND: App Router back/forward emits no request.",
        "measured span excludes time on the final page — nothing marks its end.",
        "device model is unavailable for most sessions (Chrome UA reduction); iPhone models "
        "are never available server-side; Brave counts as Chrome; iPads count as macOS.",
        "bot shares are of requests reaching the origin, not of all traffic.",
        "Telegram's in-app WebViews frequently send no Referer, so a large share of Telegram "
        "traffic lands in 'direct / unattributed'. Appending "
        "?utm_source=telegram&utm_medium=channel&utm_campaign=<en|ua> to the auto-published "
        "links is a one-line change in the publish path and converts the biggest blind spot "
        "into a measured channel, with per-channel EN/UA performance.",
    ]
    notes.extend(_automation_notes(automation))
    if hard_only:
        notes.append(
            "--hard-only is on: soft (client-side) navigations are excluded, which reproduces "
            "the naive document-only count and understates real reading."
        )
    if legacy_only:
        notes.append(
            "legacy pageviews are hard navigations only and are a LOWER BOUND on real page "
            "reads; extended pageviews are hard + soft. The two must never be compared "
            "without this label."
        )
    return tuple(notes)


def _build_warnings(
    *,
    formats_seen: Collection[str],
    capabilities: Sequence[DayCapabilities],
    parse_stats: ParseStats,
    tz_fallback: bool,
    tz_name: str,
    include_bots: bool,
    automation: AutomationFindings | None = None,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if automation is not None and automation.ran:
        share = automation.demoted_share
        if share is not None and share >= AUTOMATION_WARN_SHARE:
            # At this size the filter is not a footnote, it is the finding. On
            # the 15 days this was written against it removed 44.4% of the
            # reported audience, and every locale, channel and article number
            # below moved with it.
            warnings.append(
                f"{automation.demoted_pageviews} pageviews ({share:.1%} of the "
                f"pre-filter total) were removed as suspected automation, from "
                f"{len(automation.demoted_agents)} user-agent(s). A share this large "
                "changes the conclusions, not just the totals — read SUSPECTED "
                "AUTOMATION (DEMOTED) in the automated appendix and check the evidence "
                "before quoting anything here."
            )
    if automation is not None and not automation.ran:
        warnings.append(
            f"the behavioural automation filter did not run: {automation.reason}."
        )
    if include_bots:
        warnings.append(
            "INCLUDING BOTS AND AGENTS — these are not audience numbers."
        )
    if len(set(formats_seen)) > 1:
        extended_days = sorted(
            cap.local_date for cap in capabilities if cap.log_format in (EXTENDED, "mixed")
        )
        first_extended = extended_days[0] if extended_days else "the format change"
        warnings.append(
            "Range spans the log-format change — visitor, country and language numbers "
            f"exist only from {first_extended}."
        )
    if tz_fallback:
        warnings.append(
            f"tzdata is missing — {tz_name} was unavailable and all times are UTC."
        )
    if parse_stats.stale_cf_ranges:
        warnings.append(
            f"{parse_stats.stale_cf_ranges} requests carried a CF-Ray but came from an IP "
            "outside the compiled Cloudflare ranges — the range list is stale and real "
            "visitors are being classified as direct-to-origin. Refresh it."
        )
    if parse_stats.files_unreadable:
        for path, reason in parse_stats.files_unreadable:
            warnings.append(f"could not read {path}: {reason}")
    return tuple(warnings)
