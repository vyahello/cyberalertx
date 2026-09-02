"""Report assembly and statistical honesty — `server/analytics/aggregate.py`.

IN SCOPE: the one helper that enforces every percentage rule, table ordering
and truncation, the unknown bucket, Wilson intervals at the edges the normal
approximation cannot handle, the quantile heatmap, coverage banners, and — the
point of section C — which sections are SUPPRESSED WITH A REASON rather than
zeroed when the underlying data is legacy-only.

DELIBERATELY NOT IN SCOPE: rendering (`report.py`, `htmlreport.py`) and the
store. A Report is the handoff; both renderers read it and nothing else.

FIXTURES: reports are built through the real pipeline — lines, records, events,
sessions — so a table can never pass by being fed hand-made counters.
"""
from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from pathlib import Path

import pytest

from server.analytics.aggregate import (
    Report,
    Table,
    build_coverage,
    build_report,
    median,
    percentile,
    share_or_none,
    table_from_counter,
    wilson_interval,
)
from server.analytics.logread import ParseStats
from server.analytics.sessionize import (
    AUTOMATION_MIN_PAGEVIEWS,
    Ledger,
    SaltProvider,
    demote_automation,
    iter_events,
    sessionize,
)
from server.analytics.store import DayCapabilities
from tests.test_analytics_logread import (
    CF_EDGE_IP,
    KYIV,
    extended_line,
    legacy_line,
    now_local,
    parse,
)

ARTICLE = "/en/threat/e50e48c737157f8a"


def _capabilities(events: list) -> list[DayCapabilities]:
    """One DayCapabilities per local date, derived from what the day held."""
    by_date: dict[str, list] = {}
    for event in events:
        by_date.setdefault(event.date, []).append(event)
    caps = []
    for local_date, day in sorted(by_date.items()):
        formats = {event.fmt for event in day}
        extended = "extended" in formats
        log_format = ("mixed" if len(formats) > 1
                      else ("extended" if extended else "legacy"))
        stamps = sorted(event.local_ts.isoformat() for event in day)
        caps.append(DayCapabilities(
            local_date=local_date,
            log_format=log_format,
            has_host=extended,
            has_client_ip=extended,
            has_country=extended,
            has_accept_language=extended,
            has_client_hints=extended,
            has_rsc_headers=extended,
            has_timing=extended,
            events=len(day),
            first_seen=stamps[0],
            last_seen=stamps[-1],
        ))
    return caps


def _report(lines: list[str], *, tmp_path: Path, top_n: int = 10,
            demote: dict | None = None, **kw) -> Report:
    stats = ParseStats()
    records = [parse(line, stats=stats) for line in lines]
    ledger = Ledger()
    salts = SaltProvider(tmp_path / "salts.json")
    events = list(iter_events(records, tz=KYIV, salts=salts, ledger=ledger))
    # The reader's share of the ledger: blank and unparseable lines never reach
    # iter_events, so the caller carries them over from ParseStats. Every line
    # in these fixtures parses, so the total is simply the line count.
    ledger.total_lines = len(lines)
    ledger.blank = stats.blank
    ledger.unparseable = stats.unparseable
    # The cross-request behavioural pass, in the same position the CLI puts it:
    # after the events exist, before anything downstream reads them. `demote`
    # is None everywhere except the tests that are about it, so every other
    # fixture keeps exactly the numbers it always had.
    automation = None
    if demote is not None:
        events, automation = demote_automation(events, ledger=ledger, **demote)
    kw.setdefault("automation", automation)
    sessions = sessionize(events)
    caps = _capabilities(events)
    since = min(event.local_ts for event in events) - timedelta(minutes=1)
    until = max(event.local_ts for event in events) + timedelta(minutes=1)
    return build_report(
        events,
        sessions,
        ledger=ledger,
        parse_stats=stats,
        coverage=build_coverage(caps, since=since.date(), until=until.date()),
        since=since,
        until=until,
        tz_name="Europe/Kyiv",
        tz_fallback=False,
        sources=("<fixture>",),
        top_n=top_n,
        **kw,
    )


def _human_lines(count: int, *, legacy: bool = False, hour: int | None = None,
                 path: str = ARTICLE) -> list[str]:
    """`count` distinct readers, one pageview each, all safely in the past."""
    base = now_local() - timedelta(days=2)
    if hour is not None:
        base = base.replace(hour=hour, minute=0, second=0)
    lines = []
    for index in range(count):
        moment = base + timedelta(seconds=index)
        if legacy:
            lines.append(legacy_line(ts=moment, ip=CF_EDGE_IP, path=path))
        else:
            lines.append(extended_line(
                ts=moment, ip=f"192.0.2.{index % 250 + 1}", pip=CF_EDGE_IP,
                u=path, ref="https://t.me/cyberalertx",
            ))
    return lines


def _tables(report: Report) -> list[Table]:
    return [
        value for field in dataclasses.fields(report)
        if isinstance(value := getattr(report, field.name), Table)
    ]


# --------------------------------------------------------------------------
# the one honesty helper
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "count, n, expected",
    [
        (10, 20, None),      # n < 30: the whole table prints counts only
        (29, 29, None),      # the boundary itself is still too small
        (4, 1000, None),     # a row under 5 is a rounding artefact, however big
                             # the table is
        (5, 1000, 0.005),    # ...and 5 is where a row starts to mean something
        (15, 30, 0.5),       # the smallest table that may carry percentages
        (0, 100, None),      # a zero row: count < 5
        (100, 100, 1.0),
    ],
)
def test_share_or_none_refuses_a_percentage_it_cannot_justify(
    count: int, n: int, expected: float | None
) -> None:
    result = share_or_none(count, n)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_share_or_none_never_divides_by_zero() -> None:
    assert share_or_none(0, 0) is None


def test_a_small_report_carries_no_percentages_anywhere(tmp_path: Path) -> None:
    """The rule lives in one helper precisely so it cannot be remembered in
    eleven sections and forgotten in the twelfth."""
    report = _report(_human_lines(20), tmp_path=tmp_path)
    tables = _tables(report)
    assert tables                                    # the report has tables at all
    for table in tables:
        if table.suppressed:
            continue
        for row in table.rows:
            assert row.share is None, f"{table.title}: {row.label}"


# --------------------------------------------------------------------------
# table construction
# --------------------------------------------------------------------------

def test_tables_order_by_count_and_break_ties_alphabetically() -> None:
    """Determinism: two runs over the same data must print the same table."""
    table = table_from_counter(
        {"beta": 5, "alpha": 5, "gamma": 40, "delta": 5},
        title="X", denominator_label="by session", n=55, top_n=10,
    )
    assert [row.label for row in table.rows] == ["gamma", "alpha", "beta", "delta"]


def test_the_unknown_bucket_keeps_its_natural_rank_and_is_never_hidden() -> None:
    """Exiling "unknown" to the bottom is how a report quietly stops mentioning
    that a third of its data has no value for this dimension."""
    table = table_from_counter(
        {"uk": 50, "unknown (no header)": 30, "en": 20},
        title="Languages", denominator_label="by session", n=100, top_n=10,
        unknown_labels=("unknown (no header)",),
    )
    assert [row.label for row in table.rows] == ["uk", "unknown (no header)", "en"]
    assert table.unknown_share == pytest.approx(0.30)


def test_more_than_fifteen_percent_unknown_earns_a_bias_warning() -> None:
    """Unknowns are not missing at random — privacy-conscious readers strip
    headers — so the known part is only trustworthy if that is acknowledged."""
    noisy = table_from_counter(
        {"uk": 70, "unknown (no header)": 30},
        title="Languages", denominator_label="by session", n=100, top_n=10,
        unknown_labels=("unknown (no header)",),
    )
    quiet = table_from_counter(
        {"uk": 95, "unknown (no header)": 5},
        title="Languages", denominator_label="by session", n=100, top_n=10,
        unknown_labels=("unknown (no header)",),
    )
    assert noisy.warnings
    assert not quiet.warnings


def test_truncation_reconciles_with_the_full_counter() -> None:
    """"+N more (M, X.X%)" — never a bare "...". The tail's size is itself
    information, and a tail over a quarter of the data is the finding."""
    counter = {"a": 40, "b": 30, "c": 20, "d": 6, "e": 5, "f": 5}
    table = table_from_counter(
        counter, title="X", denominator_label="by session", n=106, top_n=3,
    )
    assert len(table.rows) == 3
    assert table.tail_count == 3
    assert table.tail_total == 16
    assert sum(row.count for row in table.rows) + table.tail_total == sum(counter.values())
    assert table.tail_share == pytest.approx(16 / 106)


def test_a_counter_smaller_than_top_n_has_no_tail() -> None:
    table = table_from_counter(
        {"a": 3, "b": 1}, title="X", denominator_label="by session", n=4, top_n=10,
    )
    assert table.tail_count == 0
    assert table.tail_total == 0
    assert table.tail_share is None


# --------------------------------------------------------------------------
# the statistics themselves
# --------------------------------------------------------------------------

@pytest.mark.parametrize("successes, n", [(0, 100), (100, 100), (1, 5), (50, 100)])
def test_wilson_stays_inside_zero_and_one_where_the_normal_interval_does_not(
    successes: int, n: int
) -> None:
    """At 0/100 and 100/100 the normal approximation runs out of bounds and
    prints a bounce rate of -3% or 104%."""
    low, high = wilson_interval(successes, n)
    assert 0.0 <= low <= high <= 1.0


def test_median_and_percentile_handle_the_empty_and_single_cases() -> None:
    assert median([]) is None
    assert percentile([], 0.9) is None
    assert median([4.0]) == 4.0
    assert median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == pytest.approx(3.0)


# --------------------------------------------------------------------------
# suppression on legacy-only data (C.5) — never a misleading zero
# --------------------------------------------------------------------------

def test_geography_is_suppressed_with_its_reason_on_legacy_only_data(
    tmp_path: Path,
) -> None:
    """The combined format carries no CF-IPCountry at all. A zero-filled
    country table would read as "nobody is in Ukraine"."""
    report = _report(_human_lines(40, legacy=True), tmp_path=tmp_path)

    assert report.countries.suppressed is True
    assert report.countries.suppressed_reason is not None
    assert "cf-ipcountry" in report.countries.suppressed_reason.lower()
    assert report.countries.rows == ()
    assert report.formats_seen == frozenset({"legacy"})


def test_language_latency_and_identity_are_suppressed_on_legacy_only_data(
    tmp_path: Path,
) -> None:
    report = _report(_human_lines(40, legacy=True), tmp_path=tmp_path)

    assert report.language_locale.suppressed is True
    assert "accept-language" in (report.language_locale.suppressed_reason or "").lower()
    assert report.languages.suppressed is True
    assert report.latency.suppressed is True
    assert "request_time" in (report.latency.suppressed_reason or "").lower()

    # Every visitor-derived headline number, suppressed rather than estimated:
    # 121 pageviews arrived through 99 Cloudflare edge addresses.
    assert report.headline.visitors is None
    assert report.headline.sessions is None
    assert report.headline.bounce_rate is None
    assert report.headline.pages_per_visit_mean is None
    assert report.headline.span_mean_seconds is None
    # Pageviews survive: path and status are both in the combined format.
    assert report.headline.pageviews == 40


def test_the_same_sections_are_available_on_extended_data(tmp_path: Path) -> None:
    report = _report(_human_lines(40), tmp_path=tmp_path)

    assert report.countries.suppressed is False
    assert report.language_locale.suppressed is False
    assert report.latency.suppressed is False
    assert report.headline.visitors is not None
    assert report.headline.sessions is not None
    assert report.formats_seen == frozenset({"extended"})


def test_a_mixed_range_warns_that_the_dimensions_arrive_partway_through(
    tmp_path: Path,
) -> None:
    """The day the nginx change lands, the series steps up for methodological
    reasons. The report has to say so rather than let it read as growth."""
    report = _report(
        _human_lines(20, legacy=True) + _human_lines(20), tmp_path=tmp_path,
    )
    assert report.formats_seen == frozenset({"legacy", "extended"})
    assert report.warnings


# --------------------------------------------------------------------------
# coverage
# --------------------------------------------------------------------------

def _cap(day: date, *, extended: bool) -> DayCapabilities:
    return DayCapabilities(
        local_date=day.isoformat(),
        log_format="extended" if extended else "legacy",
        has_host=extended,
        has_client_ip=extended,
        has_country=extended,
        has_accept_language=extended,
        has_client_hints=extended,
        has_rsc_headers=extended,
        has_timing=extended,
        events=10,
        first_seen=f"{day.isoformat()}T00:00:00+03:00",
        last_seen=f"{day.isoformat()}T23:59:59+03:00",
    )


def test_coverage_marks_a_dimension_partial_and_names_when_it_arrived() -> None:
    """Reports must LABEL periods where a dimension did not exist, never plot
    a misleading zero across them."""
    first = (now_local() - timedelta(days=4)).date()
    days = [first + timedelta(days=offset) for offset in range(4)]
    caps = [
        _cap(days[0], extended=False),
        _cap(days[1], extended=False),
        _cap(days[3], extended=True),      # days[2] never ingested at all
    ]
    coverage = build_coverage(caps, since=days[0], until=days[3])

    assert coverage.first_date == days[0]
    assert coverage.last_date == days[3]
    assert coverage.days_present == 3
    assert days[2].isoformat() in coverage.days_missing
    assert "country" in coverage.dimensions_partial
    assert coverage.dimensions_partial["country"][0] == days[3].isoformat()
    assert "country" not in coverage.dimensions_available
    assert coverage.banner
    assert "country" in coverage.banner


def test_coverage_reports_a_dimension_absent_when_no_day_ever_had_it() -> None:
    day = (now_local() - timedelta(days=1)).date()
    coverage = build_coverage([_cap(day, extended=False)], since=day, until=day)
    assert "country" in coverage.dimensions_absent
    assert "country" not in coverage.dimensions_partial


def test_every_report_carries_the_coverage_banner(tmp_path: Path) -> None:
    report = _report(_human_lines(20), tmp_path=tmp_path)
    assert report.coverage.banner.strip()


# --------------------------------------------------------------------------
# the heatmap
# --------------------------------------------------------------------------

def test_the_heatmap_is_seven_by_twenty_four_on_quantile_thresholds(
    tmp_path: Path,
) -> None:
    """A linear scale on this shape leaves 20 of the 24 columns blank: one
    evening peak swamps everything, which is the normal shape of a news site."""
    lines = _human_lines(60, hour=20) + _human_lines(3, hour=4, path="/en")
    report = _report(lines, tmp_path=tmp_path)
    heatmap = report.heatmap

    assert len(heatmap.values) == 7
    assert all(len(row) == 24 for row in heatmap.values)
    assert len(heatmap.thresholds) == 5
    assert list(heatmap.thresholds) == sorted(heatmap.thresholds)
    peak = max(max(row) for row in heatmap.values)
    assert peak > 0
    # Quantile cut points sit among the observed values, well below the peak;
    # linear ones would be peak/5, 2*peak/5, ...
    assert heatmap.thresholds[-1] < peak
    assert heatmap.tz_name == "Europe/Kyiv"


# --------------------------------------------------------------------------
# the surfaced finding
# --------------------------------------------------------------------------

def test_the_tldr_names_a_country_a_device_a_channel_and_an_hour(
    tmp_path: Path,
) -> None:
    """Section order is by reading dependency, so the actual finding would
    otherwise be buried at section six."""
    report = _report(_human_lines(120, hour=20), tmp_path=tmp_path)
    tldr = report.headline.tldr

    assert tldr
    assert "Ukraine" in tldr or "UA" in tldr
    assert "mobile" in tldr.lower()
    assert "telegram" in tldr.lower()
    assert any(character.isdigit() for character in tldr)


def test_the_ledger_is_present_and_ends_at_human_pageviews(tmp_path: Path) -> None:
    report = _report(_human_lines(30), tmp_path=tmp_path)
    steps = report.ledger.steps()
    assert steps[-1][0].lower().startswith("human pageviews")
    assert sum(count for _, count, _ in steps) == report.ledger.total_lines


# --------------------------------------------------------------------------
# the behavioural automation filter
# --------------------------------------------------------------------------
# The defect this closes: classification was purely per-request, so a scraper
# with a plausible browser UA arriving through Cloudflare was counted as a
# reader. On 15 days of this site's own traffic two such identities held 1 857
# of 4 181 reported pageviews — 44.4% of the audience.
#
# THE ASYMMETRY THESE TESTS EXIST TO PROTECT: fetching an asset PROVES a
# browser; never fetching one is evidence ONLY AT VOLUME, because a returning
# reader with a warm cache legitimately requests pages and no assets.

#: The forged user-agent measured doing exactly this. Committed verbatim: it is
#: a UA string, carries no address, and naming the real one is what makes the
#: fixture recognisable to whoever reads this next.
SCRAPER_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 "
    "Mobile/15E148 Safari/604.1"
)

#: A second, ordinary browser string, so the fixtures hold two distinct
#: identities and a test can prove the filter separates them.
READER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
)

#: Long enough to clear AUTOMATION_MIN_WINDOW_DAYS, short enough to stay cheap.
_SPREAD_DAYS = 12


def _agent_lines(count: int, *, ua: str, days: int = _SPREAD_DAYS,
                 assets: int = 0, path: str = ARTICLE) -> list[str]:
    """`count` pageviews from ONE user-agent, spread evenly over `days` days.

    Proxied through a real Cloudflare edge address, because CF provenance is
    what makes these count as human in the first place — that is the whole
    point of the defect. Client addresses come from 192.0.2.0/24.
    """
    base = now_local() - timedelta(days=days + 1)
    lines = []
    for index in range(count):
        moment = base + timedelta(days=index % days, seconds=index)
        lines.append(extended_line(
            ts=moment, ip=f"192.0.2.{index % 250 + 1}", pip=CF_EDGE_IP,
            u=path, ua=ua, ref="https://t.me/cyberalertx",
        ))
    for index in range(assets):
        moment = base + timedelta(days=index % days, seconds=900 + index)
        lines.append(extended_line(
            ts=moment, ip=f"192.0.2.{index % 250 + 1}", pip=CF_EDGE_IP,
            u="/_next/static/chunks/main-4f2a1c.js", ua=ua,
        ))
    return lines


def _pageviews(report: Report) -> int:
    return report.headline.pageviews


def test_a_high_volume_zero_asset_user_agent_is_demoted_out_of_the_audience(
    tmp_path: Path,
) -> None:
    """The fix, end to end and at the shipped threshold."""
    lines = _agent_lines(AUTOMATION_MIN_PAGEVIEWS + 20, ua=SCRAPER_UA)
    lines += _agent_lines(30, ua=READER_UA)

    before = _report(lines, tmp_path=tmp_path)
    after = _report(lines, tmp_path=tmp_path, demote={})

    assert _pageviews(before) == AUTOMATION_MIN_PAGEVIEWS + 50
    assert _pageviews(after) == 30                      # only the real reader survives
    assert after.ledger.suspected_automation == AUTOMATION_MIN_PAGEVIEWS + 20
    assert not after.suspected_automation.suppressed
    assert [row.count for row in after.suspected_automation.rows] == [
        AUTOMATION_MIN_PAGEVIEWS + 20
    ]


def test_a_low_volume_warm_cache_reader_is_never_demoted(tmp_path: Path) -> None:
    """THE expensive direction, and the reason the floor is 100 rather than 20.

    42 pageviews with categorically zero assets over twelve days is the exact
    shape of the largest INNOCENT zero-asset user-agent measured in production:
    Next.js chunks are immutable and cached for a year, so a returning reader's
    assets never reach the origin. A rule that demotes this deletes readers.
    """
    lines = _agent_lines(42, ua=READER_UA)
    report = _report(lines, tmp_path=tmp_path, demote={})

    assert _pageviews(report) == 42
    assert report.ledger.suspected_automation == 0
    assert report.suspected_automation.rows == ()


def test_one_asset_fetch_exempts_an_agent_however_much_it_read(
    tmp_path: Path,
) -> None:
    """Fetching an asset proves a browser, so the test is categorical: a single
    /_next/ chunk anywhere in the window ends the matter."""
    lines = _agent_lines(AUTOMATION_MIN_PAGEVIEWS + 20, ua=SCRAPER_UA, assets=1)
    report = _report(lines, tmp_path=tmp_path, demote={})

    assert _pageviews(report) == AUTOMATION_MIN_PAGEVIEWS + 20
    assert report.ledger.suspected_automation == 0


def test_the_ledger_still_reconciles_after_a_demotion(tmp_path: Path) -> None:
    """The funnel is what licenses every number under it. A new deduction that
    does not come OUT of human pageviews breaks the arithmetic silently."""
    lines = _agent_lines(AUTOMATION_MIN_PAGEVIEWS + 20, ua=SCRAPER_UA, assets=0)
    lines += _agent_lines(30, ua=READER_UA)
    report = _report(lines, tmp_path=tmp_path, demote={})

    steps = report.ledger.steps()
    labels = [label for label, _count, _share in steps]
    assert sum(count for _, count, _ in steps) == report.ledger.total_lines
    assert labels[-1].lower().startswith("human pageviews")
    # A deduction, inserted before the final row — never a row added beside it.
    assert "suspected automation" in labels[-2]
    assert report.ledger.hard + report.ledger.soft == report.ledger.human_pageviews
    assert report.ledger.human_pageviews == _pageviews(report)


def test_the_behavioural_filter_can_be_switched_off(tmp_path: Path) -> None:
    """--no-automation-filter. The report then says so rather than looking the
    same as a filter that found nothing."""
    lines = _agent_lines(AUTOMATION_MIN_PAGEVIEWS + 20, ua=SCRAPER_UA)
    report = _report(lines, tmp_path=tmp_path, demote={"enabled": False})

    assert _pageviews(report) == AUTOMATION_MIN_PAGEVIEWS + 20
    assert report.ledger.suspected_automation == 0
    assert report.suspected_automation.suppressed
    assert "--no-automation-filter" in (report.suspected_automation.suppressed_reason or "")
    assert any("did not run" in warning for warning in report.warnings)


def test_a_short_window_suppresses_the_filter_rather_than_inverting_it(
    tmp_path: Path,
) -> None:
    """Below ten days the separation does not weaken, it INVERTS: over three-day
    windows the largest innocent zero-asset agent held 84 pageviews and the
    smallest real scraper 48. Suppressed with a reason, never applied weakly."""
    lines = _agent_lines(AUTOMATION_MIN_PAGEVIEWS + 20, ua=SCRAPER_UA, days=3)
    report = _report(lines, tmp_path=tmp_path, demote={})

    assert _pageviews(report) == AUTOMATION_MIN_PAGEVIEWS + 20
    assert report.suspected_automation.suppressed
    assert "insufficient history" in (report.suspected_automation.suppressed_reason or "")
    assert any("did not run" in warning for warning in report.warnings)


def test_the_threshold_is_tunable_and_a_zero_threshold_is_refused(
    tmp_path: Path,
) -> None:
    """--automation-threshold. Lowering it is allowed and dangerous; taking it
    to zero would demote every warm-cache reader, so the pass refuses."""
    lines = _agent_lines(42, ua=READER_UA)

    tuned = _report(lines, tmp_path=tmp_path, demote={"min_pageviews": 40})
    assert _pageviews(tuned) == 0
    assert tuned.ledger.suspected_automation == 42

    refused = _report(lines, tmp_path=tmp_path, demote={"min_pageviews": 0})
    assert _pageviews(refused) == 42
    assert refused.suspected_automation.suppressed


def test_the_demoted_agent_is_named_with_the_evidence_against_it(
    tmp_path: Path,
) -> None:
    """A subtraction the reader cannot audit is a subtraction the reader cannot
    argue with. The appendix names the agent, its volume, and the asset count
    that convicted it — with the failure modes in both directions beside it."""
    lines = _agent_lines(AUTOMATION_MIN_PAGEVIEWS + 20, ua=SCRAPER_UA)
    report = _report(lines, tmp_path=tmp_path, demote={})
    table = report.suspected_automation

    assert table.rows and "iPhone OS 13_2_3" in table.rows[0].label
    assert table.rows[0].note == "0 assets"
    assert table.rows[0].secondary == AUTOMATION_MIN_PAGEVIEWS + 20
    blob = " ".join(table.warnings)
    assert "0 static-asset fetches" in blob
    assert str(AUTOMATION_MIN_PAGEVIEWS) in blob
    assert "returning reader" in blob            # the false-positive direction
    assert "one asset per window defeats" in blob  # the false-negative direction
    footnotes = " ".join(report.notes)
    assert "behavioural automation filter" in footnotes
    assert "never whitelists a declared crawler" in footnotes


def test_a_large_demotion_is_a_warning_not_a_footnote(tmp_path: Path) -> None:
    """At 44% of the reported audience the filter IS the finding of the run, and
    a finding that only appears in the notes is one nobody reads."""
    lines = _agent_lines(AUTOMATION_MIN_PAGEVIEWS + 20, ua=SCRAPER_UA)
    lines += _agent_lines(30, ua=READER_UA)
    report = _report(lines, tmp_path=tmp_path, demote={})

    assert any("suspected automation" in warning for warning in report.warnings)


def test_demoted_traffic_lands_in_the_automated_appendix_not_security_noise(
    tmp_path: Path,
) -> None:
    """A scraper wearing a browser UA is automated traffic, not an attack. Its
    rule must differ from the four that `build_report` drops into SECURITY
    NOISE, or the events vanish before the appendix that should name them."""
    lines = _agent_lines(AUTOMATION_MIN_PAGEVIEWS + 20, ua=SCRAPER_UA)
    report = _report(lines, tmp_path=tmp_path, demote={})

    assert report.security.total_hits == 0
    assert report.security.forged_crawlers == 0
    labels = {row.label: row.count for row in report.bot_labels.rows}
    assert labels.get("Suspected automation") == AUTOMATION_MIN_PAGEVIEWS + 20
