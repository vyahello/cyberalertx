"""The /admin dashboard: the login wall, the brute-force lockout, what error
responses reveal, the security headers, and the page renderers."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cyberalertx.api.admin import AdminGuard, classify_sources, render_quality, render_sources
from cyberalertx.api.admin.guard import LOCKOUT, MAX_FAILURES
from cyberalertx.api.app import build_app
from tests.test_api import _FakeService, _item

TOKEN = "t" * 48
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _basic(password: str) -> str:
    return "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()


def _h(password: str | None = TOKEN, ip: str = "203.0.113.7", **extra: str) -> dict[str, str]:
    headers = {"X-Real-IP": ip, **extra}
    if password is not None:
        headers["Authorization"] = _basic(password)
    return headers


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> TestClient:
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", TOKEN)
    app = build_app(
        service=_FakeService([_item(url_id="a")]),
        feedback_path=tmp_path / "feedback.jsonl",
        admin_guard=AdminGuard(clock=clock),
    )
    return TestClient(app)


PAGES = ["/admin", "/admin/", "/admin/feedback", "/admin/metrics", "/admin/sources"]
JSON = ["/admin/feedback.json", "/admin/metrics.json", "/admin/sources.json"]


# ---------------------------------------------------------------------------
# The login wall is uniform
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("GET", "/admin"), ("GET", "/admin/"), ("POST", "/admin"), ("DELETE", "/admin/metrics"),
    ("GET", "/admin/does-not-exist"), ("GET", "/admin/.env"), ("PUT", "/admin/feedback"),
    ("GET", "/admin/metrics.json"),
])
def test_every_method_and_path_under_admin_gets_the_same_401(
    client: TestClient, method: str, path: str,
) -> None:
    """Routing used to run first, so `POST /admin` answered 405 and unknown
    paths 404 to anyone — which tells a scanner which admin routes exist."""
    r = client.request(method, path, headers=_h(password=None))
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic")
    assert r.text == "Authentication required."


@pytest.mark.parametrize("path", PAGES)
def test_pages_render_for_the_editor(client: TestClient, path: str) -> None:
    r = client.get(path, headers=_h())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("path", JSON)
def test_json_twins_stay_available_for_scripts(client: TestClient, path: str) -> None:
    r = client.get(path, headers=_h())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")


def test_unknown_admin_path_is_a_404_page_only_after_login(client: TestClient) -> None:
    assert client.get("/admin/nope", headers=_h(password=None)).status_code == 401
    r = client.get("/admin/nope", headers=_h())
    assert r.status_code == 404
    assert "Back to the overview" in r.text


# ---------------------------------------------------------------------------
# Brute force
# ---------------------------------------------------------------------------

def test_an_address_is_locked_out_after_repeated_failures(client: TestClient, clock: _Clock) -> None:
    for _ in range(MAX_FAILURES):
        assert client.get("/admin/", headers=_h("wrong" * 10)).status_code == 401
    locked = client.get("/admin/", headers=_h())  # even the RIGHT password
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0


def test_the_lockout_is_per_address(client: TestClient) -> None:
    for _ in range(MAX_FAILURES):
        client.get("/admin/", headers=_h("wrong" * 10, ip="198.51.100.9"))
    assert client.get("/admin/", headers=_h(ip="198.51.100.9")).status_code == 429
    assert client.get("/admin/", headers=_h(ip="192.0.2.44")).status_code == 200


def test_the_lockout_expires(client: TestClient, clock: _Clock) -> None:
    for _ in range(MAX_FAILURES):
        client.get("/admin/", headers=_h("wrong" * 10))
    clock.t += LOCKOUT + 1
    assert client.get("/admin/", headers=_h()).status_code == 200


def test_the_browsers_first_unauthenticated_request_is_not_a_failure(client: TestClient) -> None:
    """A browser always asks once without credentials — that is how it learns
    to show the login box. Counting it would lock people out on page loads."""
    for _ in range(MAX_FAILURES + 3):
        assert client.get("/admin/", headers=_h(password=None)).status_code == 401
    assert client.get("/admin/", headers=_h()).status_code == 200


def test_a_successful_login_clears_earlier_failures(client: TestClient) -> None:
    for _ in range(MAX_FAILURES - 1):
        client.get("/admin/", headers=_h("wrong" * 10))
    assert client.get("/admin/", headers=_h()).status_code == 200
    for _ in range(MAX_FAILURES - 1):
        client.get("/admin/", headers=_h("wrong" * 10))
    assert client.get("/admin/", headers=_h()).status_code == 200


def test_a_malformed_authorization_header_counts_as_a_failure(client: TestClient) -> None:
    for _ in range(MAX_FAILURES):
        r = client.get("/admin/", headers={"X-Real-IP": "203.0.113.50",
                                           "Authorization": "Basic !!not-base64!!"})
        assert r.status_code == 401
    assert client.get("/admin/", headers=_h(ip="203.0.113.50")).status_code == 429


def test_failed_logins_show_on_the_overview(client: TestClient) -> None:
    for _ in range(3):
        client.get("/admin/", headers=_h("wrong" * 10, ip="198.51.100.77"))
    r = client.get("/admin/", headers=_h())
    assert "Failed admin logins" in r.text
    assert "from 1 address" in r.text


# ---------------------------------------------------------------------------
# What responses reveal
# ---------------------------------------------------------------------------

def test_disabled_admin_names_no_variable_and_no_framework(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first version answered 503 with the exact env var to set. That is
    configuration advice for an attacker."""
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", "")
    c = TestClient(build_app(service=_FakeService([]), feedback_path=tmp_path / "f.jsonl"))
    r = c.get("/admin/")
    assert r.status_code == 503
    assert r.text == "Not available."
    assert "CYBERALERTX" not in r.text
    assert r.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize("path", ["/admin/", "/admin/nope", "/admin/metrics"])
def test_admin_errors_are_plain_text_not_framework_json(client: TestClient, path: str) -> None:
    r = client.get(path, headers=_h(password=None))
    assert '{"detail"' not in r.text


def test_public_api_errors_keep_their_json_shape(client: TestClient) -> None:
    r = client.post("/feedback", json={"id": "x", "locale": "ua"})
    assert r.status_code == 400
    assert r.json() == {"detail": "invalid kind"}


@pytest.mark.parametrize("path", PAGES)
def test_admin_pages_carry_security_headers(client: TestClient, path: str) -> None:
    r = client.get(path, headers=_h())
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp
    assert "script-src" not in csp  # nothing whitelists script, so none can run
    assert r.headers["cache-control"] == "no-store"
    assert "noindex" in r.headers["x-robots-tag"]
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "<script" not in r.text.lower()


def test_headers_apply_to_refusals_too(client: TestClient) -> None:
    r = client.get("/admin/", headers=_h(password=None))
    assert r.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _health(**sources: dict[str, object]) -> dict[str, object]:
    return {"last_cycle_utc": (NOW - timedelta(minutes=10)).isoformat(), "sources": sources}


def test_sources_are_classified_against_the_last_cycle() -> None:
    fresh = (NOW - timedelta(minutes=20)).isoformat()
    health = _health(
        Healthy={"cycles_seen": 40, "last_successful_ingest_utc": fresh,
                 "last_published_at_utc": (NOW - timedelta(hours=3)).isoformat()},
        Quiet={"cycles_seen": 40, "last_successful_ingest_utc": fresh,
               "last_published_at_utc": (NOW - timedelta(days=5)).isoformat()},
        Broken={"cycles_seen": 40, "last_successful_ingest_utc": (NOW - timedelta(hours=9)).isoformat(),
                "last_published_at_utc": (NOW - timedelta(hours=9)).isoformat()},
        Dead={"cycles_seen": 12, "last_successful_ingest_utc": None},
        Newcomer={"cycles_seen": 1, "last_successful_ingest_utc": None},
    )
    rows, stopped = classify_sources(health, NOW)
    status = {r.name: r.status for r in rows}
    assert status == {"Healthy": "healthy", "Quiet": "quiet", "Broken": "failing",
                      "Dead": "failing", "Newcomer": "new"}
    assert stopped is False
    assert [r.name for r in rows][:2] == ["Broken", "Dead"]  # worst first


def test_a_stopped_ingest_is_one_banner_not_every_feed_failing() -> None:
    """Sources are judged against the last cycle. When the loop itself stops,
    the page says so once instead of turning every feed red together."""
    stale_cycle = NOW - timedelta(hours=30)
    health = {"last_cycle_utc": stale_cycle.isoformat(), "sources": {
        "A": {"cycles_seen": 9, "last_successful_ingest_utc": stale_cycle.isoformat(),
              "last_published_at_utc": stale_cycle.isoformat()}}}
    rows, stopped = classify_sources(health, NOW)
    assert stopped is True
    assert rows[0].status != "failing"
    assert "Ingest has stopped" in render_sources(health, now=NOW)


def test_quality_page_speaks_in_plain_language() -> None:
    html = render_quality({
        "counters": {"ai_renders_attempted": 100, "ai_renders_success": 80,
                     "ai_validation_rejects": 12, "ai_provider_errors": 8,
                     "cliche_rejects": 5, "empty_field_rejects": 7},
        "top_failure_messages": {"<b>empty why_it_matters</b>": 7},
        "first_seen_utc": "2026-05-12T00:00:00+00:00",
    }, now=NOW)
    assert "Used a banned AI cliché" in html
    assert "A required field came back empty" in html
    assert "80%" in html
    assert "&lt;b&gt;empty why_it_matters" in html  # validator text is escaped
    assert "cliche_rejects" not in html               # no raw counter names
