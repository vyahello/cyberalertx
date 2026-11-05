"""RSS fetch errors, backoff and source health (CISA Alerts, 5 Nov 2026).

CISA's edge answers HTTP 403 to data-centre networks (this host, the
Cloudflare-Worker proxy). The fix is not a workaround: the source reports the
failure, backs off instead of retrying every 30-minute cycle, and shows as
failing on the admin page. Every case runs against httpx.MockTransport; no
network.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from cyberalertx.observability.source_health import SourceHealth
from cyberalertx.sources.rss import RssSource
from cyberalertx.storage.json_store import JsonNewsStore

FEED_URL = "https://www.cisa.gov/cybersecurity-advisories/all.xml"
RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>CISA</title>
<item><title>CISA Adds One Known Exploited Vulnerability to Catalog</title>
<link>https://www.cisa.gov/news-events/alerts/2026/11/05/cisa-adds-one-kev</link>
<pubDate>Thu, 05 Nov 2026 12:00:00 GMT</pubDate><description>Evidence of active exploitation.</description></item>
</channel></rss>"""


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


def _source(handler, clock: Clock | None = None, url: str = FEED_URL) -> tuple[RssSource, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    src = RssSource("CISA Alerts", url, timeout=5, clock=clock or Clock(),
                    transport=httpx.MockTransport(wrapped))
    return src, seen


def test_success_parses_items_and_sends_an_identifiable_user_agent() -> None:
    src, seen = _source(lambda r: httpx.Response(200, content=RSS))
    items = src.fetch()
    assert [i.title for i in items] == ["CISA Adds One Known Exploited Vulnerability to Catalog"]
    assert src.last_outcome.status == "ok"
    ua = seen[0].headers["User-Agent"]
    assert ua.startswith("CyberAlertX/") and "Mozilla" not in ua


def test_403_is_reported_and_backed_off_without_new_requests() -> None:
    clock = Clock()
    src, seen = _source(lambda r: httpx.Response(403, text="Access Denied"), clock)
    assert src.fetch() == []
    out = src.last_outcome
    assert (out.status, out.error, out.consecutive_failures) == ("error", "http_403", 1)
    assert out.next_attempt_utc == clock.now + timedelta(minutes=30)
    for _ in range(2):                     # reads inside the 30-min window: no request
        clock.advance(minutes=10)
        assert src.fetch() == [] and src.last_outcome.status == "skipped"
    assert len(seen) == 1
    clock.advance(minutes=11)              # window over: one retry, delay doubles
    src.fetch()
    assert len(seen) == 2 and src.last_outcome.consecutive_failures == 2
    assert src.last_outcome.next_attempt_utc == clock.now + timedelta(hours=1)


def test_refused_backoff_is_capped_at_24_hours() -> None:
    clock = Clock()
    src, _ = _source(lambda r: httpx.Response(403), clock)
    for _ in range(12):
        src.fetch()
        clock.now = src.last_outcome.next_attempt_utc  # type: ignore[assignment]
    assert src.last_outcome.next_attempt_utc - clock.now <= timedelta(hours=24)  # type: ignore[operator]


def test_429_honours_retry_after() -> None:
    clock = Clock()
    src, _ = _source(lambda r: httpx.Response(429, headers={"Retry-After": "7200"}), clock)
    src.fetch()
    assert src.last_outcome.error == "http_429"
    assert src.last_outcome.next_attempt_utc == clock.now + timedelta(hours=2)


def test_5xx_is_transient_and_capped_at_6_hours() -> None:
    clock = Clock()
    src, _ = _source(lambda r: httpx.Response(503), clock)
    for _ in range(10):
        src.fetch()
        clock.now = src.last_outcome.next_attempt_utc  # type: ignore[assignment]
    assert src.last_outcome.error == "http_503"
    src.fetch()
    assert src.last_outcome.next_attempt_utc - clock.now == timedelta(hours=6)  # type: ignore[operator]


def test_timeout_is_classified() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)
    src, _ = _source(boom)
    assert src.fetch() == [] and src.last_outcome.error == "timeout"


def test_redirect_is_followed_and_a_loop_is_an_error() -> None:
    def moved(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("all.xml"):
            return httpx.Response(301, headers={"Location": "https://www.cisa.gov/new/advisories.xml"})
        return httpx.Response(200, content=RSS)
    src, seen = _source(moved)
    assert len(src.fetch()) == 1 and len(seen) == 2

    loop, _ = _source(lambda r: httpx.Response(302, headers={"Location": str(r.url)}))
    assert loop.fetch() == [] and loop.last_outcome.error == "redirect_loop"


def test_invalid_xml_is_an_error_not_an_empty_feed() -> None:
    src, _ = _source(lambda r: httpx.Response(200, text="<html><h1>Access Denied</h1>"))
    assert src.fetch() == [] and src.last_outcome.error == "invalid_feed"


def test_a_valid_empty_feed_is_ok() -> None:
    src, _ = _source(lambda r: httpx.Response(200, content=b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'))
    assert src.fetch() == [] and src.last_outcome.status == "ok"


def test_recovery_clears_the_failure(caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    state = {"code": 403}
    src, _ = _source(lambda r: httpx.Response(state["code"], content=RSS), clock)
    src.fetch()
    state["code"] = 200
    clock.advance(minutes=31)
    with caplog.at_level(logging.INFO, logger="cyberalertx.sources.rss"):
        assert len(src.fetch()) == 1
    assert src.last_outcome.status == "ok" and "recovered" in caplog.text


def test_repeated_failures_warn_once(caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    src, _ = _source(lambda r: httpx.Response(403), clock)
    with caplog.at_level(logging.INFO, logger="cyberalertx.sources.rss"):
        for _ in range(4):
            src.fetch()
            clock.now = src.last_outcome.next_attempt_utc  # type: ignore[assignment]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_source_health_separates_failures_from_empty_feeds(tmp_path: Path) -> None:
    health = SourceHealth(_path=tmp_path / "source_health.json")
    src, _ = _source(lambda r: httpx.Response(403))
    src.fetch()
    health.record_cycle({"CISA Alerts": []}, [], outcomes={"CISA Alerts": src.last_outcome})
    s = health.as_dict()["sources"]["CISA Alerts"]
    assert (s["cycles_failed"], s["cycles_empty"], s["last_error"], s["consecutive_failures"]) == (1, 0, "http_403", 1)
    assert s["last_successful_ingest_utc"] is None and s["next_attempt_utc"]
    reloaded = SourceHealth.load(tmp_path / "source_health.json").as_dict()["sources"]["CISA Alerts"]
    assert reloaded["last_error"] == "http_403"


def test_admin_shows_a_failing_source_with_its_error() -> None:
    from cyberalertx.api.admin.pages import classify_sources
    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    health = {"last_cycle_utc": now.isoformat(), "sources": {"CISA Alerts": {
        "cycles_seen": 40, "consecutive_failures": 3, "last_error": "http_403",
        "last_successful_ingest_utc": (now - timedelta(minutes=20)).isoformat(),
        "next_attempt_utc": (now + timedelta(hours=2)).isoformat()}}}
    rows, _ = classify_sources(health, now)
    assert rows[0].status == "failing" and "http_403" in rows[0].reason


def test_endpoint_change_does_not_duplicate_articles(tmp_path: Path) -> None:
    store = JsonNewsStore(tmp_path / "items.json")
    old, _ = _source(lambda r: httpx.Response(200, content=RSS), url=FEED_URL)
    new, _ = _source(lambda r: httpx.Response(200, content=RSS),
                     url="https://www.cisa.gov/cybersecurity-advisories/alerts.xml")
    assert len(store.upsert_many(old.fetch())) == 1
    assert store.upsert_many(new.fetch()) == []      # same article link -> same fingerprint
    assert len(store.all()) == 1 and store.all()[0].source == "CISA Alerts"
