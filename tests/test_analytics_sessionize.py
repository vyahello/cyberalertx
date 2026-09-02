"""Pageviews, sessions, visitors and the ledger — `server/analytics/sessionize.py`.

IN SCOPE: the pageview allowlist, the RSC / prefetch rules that decide whether
the EN/UA split means anything at all, visitor identity and its suppression on
legacy data, the 30-minute session boundary, bounce and duration arithmetic,
acquisition channel priority, salt rotation, and the ledger that has to account
for every line.

DELIBERATELY NOT IN SCOPE: bot classification (test_analytics_bots.py) and
report assembly (test_analytics_aggregate.py).

FIXTURES: lines are built with the shared builders, timestamps hang off
`now_local()`, and the salt file lives under tmp_path.
"""
from __future__ import annotations

import stat
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

from server.analytics.sessionize import (
    Event,
    Ledger,
    SaltProvider,
    Session,
    classify_channel,
    classify_page,
    enrich,
    ip_key,
    iter_events,
    sessionize,
    visitor_id,
)
from tests.test_analytics_logread import (
    ANDROID_CHROME_UA,
    CF_EDGE_IP,
    KYIV,
    extended_line,
    legacy_line,
    now_local,
    parse,
)

SALT = "0123456789abcdef"
ARTICLE = "/en/threat/e50e48c737157f8a"


def _event(**over: object) -> Event:
    """Enrich one extended line. Defaults are a proxied human hard navigation."""
    hard_only = bool(over.pop("hard_only", False))
    over.setdefault("pip", CF_EDGE_IP)
    return enrich(parse(extended_line(**over)), tz=KYIV, salt=SALT,
                  hard_only=hard_only)


def _legacy_event(**over: object) -> Event:
    return enrich(parse(legacy_line(**over)), tz=KYIV, salt=SALT)


def _events(lines: list[str], *, tmp_path: Path, hard_only: bool = False,
            ledger: Ledger | None = None) -> list[Event]:
    salts = SaltProvider(tmp_path / "salts.json")
    records = [parse(line) for line in lines]
    return list(iter_events(records, tz=KYIV, salts=salts,
                            hard_only=hard_only, ledger=ledger))


# --------------------------------------------------------------------------
# the pageview allowlist
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path, expected",
    [
        ("/en", True),
        ("/ua", True),
        ("/en/", True),                       # the trailing slash is the same page
        (ARTICLE, True),
        ("/ua/threat/e50e48c737157f8a", True),
        # A 16-hex fingerprint is the only shape a real article id can take
        # (frontend/app/[locale]/threat/[id]/page.tsx). Anything else is a probe.
        ("/en/threat/nothex", False),
        ("/en/threat/e50e48c7", False),       # too short to be a fingerprint
        ("/_next/static/chunks/main.js", False),
        ("/brand/logo.svg", False),
        ("/healthz", False),
        ("/posts", False),
        ("/en/feed.xml", False),              # counted, but as RSS polling
        ("/favicon.ico", False),
        ("/", False),                         # the 307 to /en, never a page read
        ("/uk", False),                       # 301'd to /ua; the successor counts
    ],
)
def test_the_pageview_allowlist_admits_only_the_two_real_page_shapes(
    path: str, expected: bool
) -> None:
    assert _event(u=path).is_pageview is expected


def test_classify_page_labels_the_discarded_traffic_rather_than_dropping_it() -> None:
    assert classify_page("/en")[0] == "home"
    assert classify_page(ARTICLE)[0] == "article"
    assert classify_page(ARTICLE)[2] == "e50e48c737157f8a"
    assert classify_page("/en/feed.xml")[0] == "feed"
    assert classify_page("/_next/static/chunks/main.js")[0] == "asset"
    assert classify_page("/brand/logo.svg")[0] == "asset"
    assert classify_page("/en")[1] == "en"
    assert classify_page("/ua")[1] == "ua"


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "POST", "PUT"])
def test_only_get_can_be_a_pageview(method: str) -> None:
    assert _event(m=method, u="/en").is_pageview is False


@pytest.mark.parametrize(
    "status, expected",
    [
        ("200", True),
        ("304", True),      # a conditional GET is a real page read
        ("301", False),     # /uk -> /ua; the successor line is the pageview
        ("307", False),     # / -> /en, from middleware.ts
        ("404", False),
        ("500", False),
    ],
)
def test_only_a_rendered_response_can_be_a_pageview(
    status: str, expected: bool
) -> None:
    assert _event(u="/en", st=status).is_pageview is expected


def test_a_bot_pageview_is_not_a_pageview() -> None:
    assert _event(u="/en", ua="Mozilla/5.0 (compatible; Googlebot/2.1; "
                              "+http://www.google.com/bot.html)").is_pageview is False


# --------------------------------------------------------------------------
# the RSC rule — the single most important behaviour in the suite
# --------------------------------------------------------------------------

def test_the_language_switcher_prefetch_does_not_manufacture_a_mirror_pageview(
    tmp_path: Path,
) -> None:
    """LanguageSwitcher.tsx:61 passes prefetch={active ? false : undefined},
    which is Next's viewport default, and the switcher sits in the header of
    every page. So every EN pageview fires a mirror /ua prefetch. Counting it
    drives the EN/UA split toward 50/50 BY CONSTRUCTION and destroys the single
    most valuable number in the report.

    One real EN read plus its mirror UA prefetch must be 1-0, never 1-1.
    """
    moment = now_local() - timedelta(minutes=10)
    events = _events(
        [
            extended_line(ts=moment, u="/en", rsc="", pf="", sfm="navigate",
                          sfd="document"),
            extended_line(ts=moment + timedelta(milliseconds=80), u="/ua?_rsc=1a2b3",
                          rsc="1", pf="1", sfm="cors", sfd="empty"),
        ],
        tmp_path=tmp_path,
    )
    locales = Counter(e.locale for e in events if e.is_pageview)

    assert locales["en"] == 1
    assert locales["ua"] == 0
    assert [e.nav for e in events] == ["hard", "prefetch"]


def test_sec_purpose_prefetch_alone_also_excludes() -> None:
    """Chrome sends Sec-Purpose: prefetch even when the router header is absent."""
    event = _event(u="/ua?_rsc=1a2b3", rsc="1", pf="", sp="prefetch")
    assert event.nav == "prefetch"
    assert event.is_pageview is False


def test_a_soft_navigation_is_a_real_page_read() -> None:
    """App Router client-side navigation only fires from a real JS-executing
    browser, so an unprefetched RSC request is a strong positive human signal.
    Dropping all RSC turns a four-page visit into one pageview."""
    event = _event(u="/ua?_rsc=1a2b3", rsc="1", pf="", sp="")
    assert event.nav == "soft"
    assert event.is_pageview is True


def test_hard_only_reproduces_the_naive_document_only_count(tmp_path: Path) -> None:
    lines = [
        extended_line(u="/en", rsc="", pf=""),
        extended_line(u="/ua?_rsc=1a2b3", rsc="1", pf=""),
    ]
    both = [e for e in _events(lines, tmp_path=tmp_path) if e.is_pageview]
    hard = [e for e in _events(lines, tmp_path=tmp_path, hard_only=True)
            if e.is_pageview]

    assert len(both) == 2
    assert len(hard) == 1
    assert hard[0].nav == "hard"


def test_legacy_rsc_lines_are_excluded_entirely_and_nav_is_unknown() -> None:
    """C.7: legacy lines carry no prefetch header, so a prefetch cannot be told
    from a real soft navigation. Counting them would reintroduce the switcher
    symmetry trap, so legacy pageviews are hard navigations only — a labelled
    lower bound, never a guess."""
    soft_looking = _legacy_event(path="/ua?_rsc=1a2b3")
    hard = _legacy_event(path="/ua")

    assert soft_looking.is_pageview is False
    assert soft_looking.nav == "unknown"
    assert hard.is_pageview is True
    assert hard.nav == "unknown"


# --------------------------------------------------------------------------
# visitor identity
# --------------------------------------------------------------------------

def test_visitor_identity_is_suppressed_on_legacy_lines_never_estimated() -> None:
    """121 pageviews arrived via 99 Cloudflare EDGE IPs. An edge address
    identifies Cloudflare, not a person."""
    record = parse(legacy_line(ip=CF_EDGE_IP))
    assert record.ip_is_visitor is False
    assert visitor_id(record, salt=SALT) is None
    assert _legacy_event().visitor is None


def test_a_visitor_id_is_stable_within_a_salt_and_unrecoverable_across_salts() -> None:
    record = parse(extended_line(ip="192.0.2.10"))
    first = visitor_id(record, salt=SALT)
    assert first is not None
    assert visitor_id(record, salt=SALT) == first
    assert visitor_id(record, salt="a-different-day") != first
    # Different reader, same salt.
    other = parse(extended_line(ip="192.0.2.11"))
    assert visitor_id(other, salt=SALT) != first
    # The raw address never appears in what we persist.
    assert "192.0.2.10" not in first


def test_ipv6_is_truncated_to_the_subscriber_network() -> None:
    """RFC 4941 privacy addresses rotate the low 64 bits, often daily, so
    hashing the full /128 splits one human into several."""
    assert ip_key("2001:db8:abcd:1234::1") == ip_key("2001:db8:abcd:1234:ffff:ffff:ffff:99")
    assert ip_key("2001:db8:abcd:1234::1") != ip_key("2001:db8:abcd:9999::1")


def test_ipv4_keeps_its_whole_address_and_garbage_keys_to_nothing() -> None:
    assert ip_key("192.0.2.10") == ip_key("192.0.2.10")
    assert ip_key("192.0.2.10") != ip_key("192.0.2.11")
    assert ip_key(None) == ""
    assert ip_key("not-an-ip") == ""
    assert ip_key("") == ""


# --------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------

def _visit(tmp_path: Path, offsets: list[timedelta], *,
           path: str = ARTICLE) -> list[Session]:
    base = now_local() - timedelta(hours=3)
    lines = [extended_line(ts=base + delta, u=path, ip="192.0.2.10")
             for delta in offsets]
    return sessionize(_events(lines, tmp_path=tmp_path))


@pytest.mark.parametrize(
    "gap_minutes, expected_sessions",
    [
        (29, 1),    # inside the window
        (30, 1),    # exactly at the boundary: the split is on a gap GREATER than 30
        (31, 2),    # past it
        (120, 2),
    ],
)
def test_sessions_split_only_on_a_gap_wider_than_thirty_minutes(
    tmp_path: Path, gap_minutes: int, expected_sessions: int
) -> None:
    sessions = _visit(tmp_path, [timedelta(0), timedelta(minutes=gap_minutes)])
    assert len(sessions) == expected_sessions


def test_sessions_do_not_split_at_midnight(tmp_path: Path) -> None:
    """Midnight splitting is a daily-batch artefact that manufactures a 00:00
    session spike and a batch of fake bounces."""
    base = (now_local() - timedelta(days=1)).replace(hour=23, minute=50, second=0)
    lines = [
        extended_line(ts=base, u="/en", ip="192.0.2.10"),
        extended_line(ts=base + timedelta(minutes=15), u=ARTICLE, ip="192.0.2.10"),
    ]
    sessions = sessionize(_events(lines, tmp_path=tmp_path))
    assert len(sessions) == 1
    assert sessions[0].pageviews == 2


def test_a_single_pageview_session_is_a_bounce_with_zero_duration(
    tmp_path: Path,
) -> None:
    sessions = _visit(tmp_path, [timedelta(0)])
    assert len(sessions) == 1
    assert sessions[0].pageviews == 1
    assert sessions[0].is_bounce is True
    assert sessions[0].duration_seconds == 0.0


def test_duration_is_measured_between_pageviews_and_assets_never_extend_it(
    tmp_path: Path,
) -> None:
    """Sessionizing over asset requests inflates every duration and erases
    bounces, because a page's twenty asset fetches trail its pageview."""
    base = now_local() - timedelta(hours=2)
    lines = [
        extended_line(ts=base, u="/en", ip="192.0.2.10"),
        extended_line(ts=base + timedelta(minutes=2), ip="192.0.2.10",
                      u="/_next/static/chunks/main.js"),
        extended_line(ts=base + timedelta(minutes=5), u=ARTICLE, ip="192.0.2.10"),
        extended_line(ts=base + timedelta(minutes=9), ip="192.0.2.10",
                      u="/_next/static/chunks/late.js"),
    ]
    sessions = sessionize(_events(lines, tmp_path=tmp_path))

    assert len(sessions) == 1
    assert sessions[0].pageviews == 2
    assert sessions[0].duration_seconds == pytest.approx(300.0)
    assert sessions[0].is_bounce is False


def test_two_visitors_never_share_a_session(tmp_path: Path) -> None:
    base = now_local() - timedelta(hours=1)
    lines = [
        extended_line(ts=base, u="/en", ip="192.0.2.10"),
        extended_line(ts=base + timedelta(minutes=1), u="/en", ip="192.0.2.11"),
    ]
    sessions = sessionize(_events(lines, tmp_path=tmp_path))
    assert len(sessions) == 2
    assert len({s.visitor for s in sessions}) == 2


def test_legacy_events_produce_no_sessions_at_all(tmp_path: Path) -> None:
    events = _events([legacy_line(path=ARTICLE)], tmp_path=tmp_path)
    assert events[0].is_pageview is True
    assert sessionize(events) == []


# --------------------------------------------------------------------------
# salts
# --------------------------------------------------------------------------

def test_the_salt_survives_a_restart_so_a_rerun_reproduces_the_numbers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "salts.json"
    moment = now_local()
    first = SaltProvider(path)
    salt = first.salt_for(moment)
    first.save()

    second = SaltProvider(path)
    assert second.salt_for(moment) == salt


def test_the_salt_day_turns_over_at_four_in_the_morning_not_at_midnight(
    tmp_path: Path,
) -> None:
    """A salt change forces a session split, so the cut belongs in the traffic
    trough — and never at midnight, which would manufacture a 00:00 spike."""
    provider = SaltProvider(tmp_path / "salts.json")
    day = (now_local() - timedelta(days=1)).replace(minute=0, second=0)

    assert provider.salt_for(day.replace(hour=0, minute=30)) == \
        provider.salt_for(day.replace(hour=3, minute=59))
    assert provider.salt_for(day.replace(hour=3, minute=59)) != \
        provider.salt_for(day.replace(hour=4, minute=1))
    assert provider.salt_for(day.replace(hour=4, minute=1)) == \
        provider.salt_for(day.replace(hour=23, minute=59))


def test_salts_are_pruned_so_the_key_cannot_outlive_the_logs_it_rekeys(
    tmp_path: Path,
) -> None:
    path = tmp_path / "salts.json"
    provider = SaltProvider(path)
    stale = now_local() - timedelta(days=40)
    provider.salt_for(stale)
    provider.salt_for(now_local())
    provider.save()

    assert provider.prune() >= 1
    provider.save()
    assert stale.strftime("%Y-%m-%d") not in path.read_text(encoding="utf-8")


def test_the_salt_file_is_written_private(tmp_path: Path) -> None:
    path = tmp_path / "salts.json"
    provider = SaltProvider(path)
    provider.salt_for(now_local())
    provider.save()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


# --------------------------------------------------------------------------
# acquisition channel
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "referer, query, expected_channel, expected_campaign",
    [
        # 1: a UTM tag beats everything, including a matching referer.
        ("https://t.me/cyberalertx",
         "utm_source=telegram&utm_medium=channel&utm_campaign=en", "campaign", "en"),
        # 2: the site's primary distribution channel.
        ("https://t.me/cyberalertx", "", "telegram", None),
        ("https://web.telegram.org/", "", "telegram", None),
        # 3-5: search, social, feed readers.
        ("https://www.google.com/", "", "search", None),
        ("https://duckduckgo.com/", "", "search", None),
        ("https://x.com/someone/status/1", "", "social", None),
        ("https://feedly.com/i/latest", "", "rss", None),
        # 6: our own pages. A naive script reports the site as its own top
        # referrer; internal is excluded from attribution entirely.
        ("https://cyberalertx.com/en", "", "internal", None),
        # 7: absent. Printed as "direct / unattributed", because it is mostly
        # in-app browsers and referrer stripping, not people typing the URL.
        ("-", "", "direct", None),
        ("", "", "direct", None),
        (None, "", "direct", None),
        # 8: everything else.
        ("https://news.example.test/link", "", "referral", None),
    ],
)
def test_channel_priority_is_strict_and_utm_wins(
    referer: str | None, query: str, expected_channel: str,
    expected_campaign: str | None,
) -> None:
    assert classify_channel(referer, query) == (expected_channel, expected_campaign)


# --------------------------------------------------------------------------
# assigned versus chosen locale
# --------------------------------------------------------------------------

def test_a_locale_reached_through_the_redirect_is_assigned_not_chosen(
    tmp_path: Path,
) -> None:
    """middleware.ts redirects the bare domain to /en, so those EN reads are
    ASSIGNED. Counting them as "chose English" inflates EN in the one table
    the user most wants to trust."""
    base = now_local() - timedelta(minutes=30)
    lines = [
        extended_line(ts=base, u="/", st="307", ip="192.0.2.10", ref="-"),
        extended_line(ts=base + timedelta(seconds=1), u="/en", st="200",
                      ip="192.0.2.10", ref="-"),
        # A different reader typing /en directly chose it.
        extended_line(ts=base + timedelta(seconds=2), u="/en", st="200",
                      ip="192.0.2.11", ref="-"),
    ]
    events = _events(lines, tmp_path=tmp_path)
    pageviews = [e for e in events if e.is_pageview]

    assert len(pageviews) == 2
    assert pageviews[0].locale_assigned is True
    assert pageviews[1].locale_assigned is False


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------

def test_every_line_is_accounted_for_in_the_ledger(tmp_path: Path) -> None:
    """If the reader cannot see how much was discarded and why, nothing below
    the ledger in the report is trustworthy."""
    base = now_local() - timedelta(hours=1)
    lines = [
        extended_line(ts=base, u="/en", ip="192.0.2.10"),                 # human
        extended_line(ts=base, u=ARTICLE, ip="192.0.2.11"),               # human
        extended_line(ts=base, u="/ua?_rsc=1", rsc="1", pf="1"),          # prefetch
        extended_line(ts=base, u="/_next/static/chunks/main.js"),         # asset
        extended_line(ts=base, u="/healthz", ua="Mozilla/5.0 Chrome/151"),  # health
        extended_line(ts=base, u="/wp-config.php", st="404"),             # scanner
        extended_line(ts=base, pip="203.0.113.7", u="/en"),               # direct
        extended_line(ts=base, pip="203.0.113.7", u="/.env",
                      ua="Mozilla/5.0 (compatible; Googlebot/2.1; "
                         "+http://www.google.com/bot.html)"),             # forged
        extended_line(ts=base, u="/en/feed.xml",
                      ua="Feedly/1.0 (+http://www.feedly.com/fetcher.html; "
                         "12 subscribers)"),                              # feed agent
        legacy_line(ts=base, ip="198.51.100.6", request=r"\x16\x03\x01",
                    status=400, bytes=166, ua="-"),                       # malformed
        extended_line(ts=base, u="/", st="307"),                          # redirect
    ]
    ledger = Ledger()
    _events(lines, tmp_path=tmp_path, ledger=ledger)
    # The reader owns the three counters no record can carry: a blank line and
    # an unparseable one never become records at all, so iter_events cannot see
    # them. The CLI fills these from ParseStats; the invariant is that the two
    # halves balance.
    ledger.blank = 1
    ledger.unparseable = 1
    ledger.total_lines = len(lines) + 2

    steps = ledger.steps()
    assert sum(count for _, count, _ in steps) == ledger.total_lines
    assert steps[-1][0].lower().startswith("human pageviews")
    assert ledger.human_pageviews == 2
    assert ledger.prefetch >= 1
    assert ledger.direct_origin >= 1
    assert ledger.forged_crawlers >= 1
    assert ledger.health_probes >= 1
    assert ledger.scanners >= 1
    assert ledger.malformed >= 1
