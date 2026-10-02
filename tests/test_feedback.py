"""Reader feedback: the 👍 / 👎 widget's server side, and the admin surface.

Covers vote validation (v2 and the v1 shape old cached pages still post),
the change-log aggregation, the admin page, and the authentication that now
guards every /admin/* route.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cyberalertx.api.app import build_app
from cyberalertx.feedback import (
    FeedbackError,
    parse_submission,
    read_records,
    summarize,
)
from tests.test_api import _FakeService, _item

TOKEN = "x" * 40
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _auth(password: str = TOKEN) -> dict[str, str]:
    raw = base64.b64encode(f"admin:{password}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


@pytest.fixture
def fb_path(tmp_path: Path) -> Path:
    return tmp_path / "feedback.jsonl"


@pytest.fixture
def client(fb_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", TOKEN)
    items = [_item(url_id="a", title="Chrome zero-day under attack")]
    return TestClient(build_app(service=_FakeService(items), feedback_path=fb_path))


def _vote(post: str, vote: str, previous: str = "none", **kw: object) -> dict[str, object]:
    return {"id": post, "locale": "ua", "kind": "vote", "vote": vote, "previous": previous, **kw}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_v2_vote_is_accepted() -> None:
    rec = parse_submission(_vote("p1", "up"), now=NOW)
    assert rec["kind"] == "vote" and rec["vote"] == "up" and rec["previous"] == "none"


def test_v1_signal_still_counts() -> None:
    """Cached copies of the old five-button page keep posting `signal` for a
    while after a deploy. "helpful" is a 👍; the other four are a 👎 with
    that reason."""
    up = parse_submission({"id": "p", "locale": "en", "signal": "helpful"}, now=NOW)
    assert up["vote"] == "up" and "reason" not in up
    down = parse_submission({"id": "p", "locale": "en", "signal": "too_vague"}, now=NOW)
    assert down["vote"] == "down" and down["reason"] == "too_vague"


@pytest.mark.parametrize("payload", [
    {"id": "", "locale": "ua", "kind": "vote", "vote": "up"},
    {"id": "x" * 65, "locale": "ua", "kind": "vote", "vote": "up"},
    {"id": "p", "locale": "de", "kind": "vote", "vote": "up"},
    {"id": "p", "locale": "ua", "kind": "vote", "vote": "love"},
    {"id": "p", "locale": "ua", "kind": "vote", "vote": "up", "previous": "up"},
    {"id": "p", "locale": "ua", "kind": "reason", "reason": "<script>"},
    {"id": "p", "locale": "ua", "kind": "comment", "text": "hi"},
    {"id": "p", "locale": "ua", "signal": "awesome"},
])
def test_invalid_submissions_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(FeedbackError):
        parse_submission(payload, now=NOW)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def test_switching_and_retracting_give_exact_net_counts() -> None:
    """The browser remembers its own vote and says what each click replaces,
    so net counts need no reader identifier at all."""
    recs = [
        parse_submission(_vote("p1", "up"), now=NOW),               # A 👍
        parse_submission(_vote("p1", "up"), now=NOW),               # B 👍
        parse_submission(_vote("p1", "down", "up"), now=NOW),       # B switches
        parse_submission(_vote("p1", "none", "up"), now=NOW),       # A takes it back
    ]
    s = summarize(recs, now=NOW)
    post = s.posts[0]
    assert (post.up, post.down) == (0, 1)
    assert (s.up, s.down) == (0, 1)


def test_a_forged_previous_cannot_drive_counts_negative() -> None:
    recs = [parse_submission(_vote("p1", "none", "down"), now=NOW)]
    s = summarize(recs, now=NOW)
    assert s.down == 0


def test_a_reason_attaches_to_the_down_vote_it_follows() -> None:
    """The 👎 is sent the moment it is clicked; the reason arrives separately.
    The editor should see one line, "👎 Too vague", not two."""
    vote = parse_submission(_vote("p1", "down"), now=NOW)
    reason = parse_submission(
        {"id": "p1", "locale": "ua", "kind": "reason", "reason": "too_vague"},
        now=NOW + timedelta(seconds=20),
    )
    s = summarize([vote, reason], now=NOW)
    assert len(s.recent_down) == 1
    assert s.recent_down[0]["reason"] == "too_vague"
    assert s.reasons["too_vague"] == 1


def test_worst_post_is_listed_first() -> None:
    recs = [
        parse_submission(_vote("good", "up"), now=NOW),
        parse_submission(_vote("bad", "down"), now=NOW),
        parse_submission(_vote("bad", "down"), now=NOW),
    ]
    assert summarize(recs, now=NOW).posts[0].id == "bad"


def test_a_torn_line_does_not_hide_the_rest(fb_path: Path) -> None:
    fb_path.write_text(
        json.dumps(parse_submission(_vote("p1", "up"), now=NOW)) + "\n"
        + '{"broken json\n'
        + json.dumps({"id": "p2", "locale": "en", "signal": "incorrect",
                      "timestamp": NOW.isoformat()}) + "\n",
        encoding="utf-8",
    )
    s = summarize(read_records(fb_path), now=NOW)
    assert (s.up, s.down) == (1, 1)


# ---------------------------------------------------------------------------
# HTTP: submit
# ---------------------------------------------------------------------------

def test_post_feedback_appends_one_record(client: TestClient, fb_path: Path) -> None:
    r = client.post("/feedback", json=_vote("p1", "down"))
    assert r.status_code == 200 and r.json() == {"ok": True}
    lines = fb_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["vote"] == "down"


def test_post_feedback_rejects_garbage(client: TestClient) -> None:
    assert client.post("/feedback", json={"id": "p", "locale": "ua"}).status_code == 400


def test_feedback_flood_is_capped(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Site-wide, not per client: the origin is reachable directly, so any
    client address the app sees can be forged."""
    monkeypatch.setattr("cyberalertx.api.app._FEEDBACK_MAX_PER_MINUTE", 3)
    codes = [client.post("/feedback", json=_vote(f"p{i}", "up")).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]


# ---------------------------------------------------------------------------
# HTTP: admin authentication — every /admin/* route
# ---------------------------------------------------------------------------

ADMIN_ROUTES = ["/admin/metrics", "/admin/sources", "/admin/feedback", "/admin/feedback.json"]


@pytest.mark.parametrize("route", ADMIN_ROUTES)
def test_admin_routes_refuse_anonymous_requests(client: TestClient, route: str) -> None:
    """These used to be public. /admin/metrics carried the AI provider's error
    counts, /admin/sources the ingest health of every feed."""
    r = client.get(route)
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic")


@pytest.mark.parametrize("route", ADMIN_ROUTES)
def test_admin_routes_refuse_a_wrong_password(client: TestClient, route: str) -> None:
    assert client.get(route, headers=_auth("wrong" * 10)).status_code == 401


@pytest.mark.parametrize("route", ADMIN_ROUTES)
def test_admin_routes_serve_with_the_right_password(client: TestClient, route: str) -> None:
    assert client.get(route, headers=_auth()).status_code == 200


@pytest.mark.parametrize("token", ["", "short-token"])
def test_admin_fails_closed_without_a_strong_token(
    fb_path: Path, monkeypatch: pytest.MonkeyPatch, token: str,
) -> None:
    """No token, or one too short to resist guessing, and the routes do not
    serve at all — a deploy can never expose them by default."""
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", token)
    c = TestClient(build_app(service=_FakeService([]), feedback_path=fb_path))
    for route in ADMIN_ROUTES:
        assert c.get(route, headers=_auth(token or "anything")).status_code == 503


def test_the_token_is_never_accepted_in_the_url(client: TestClient) -> None:
    """nginx logs the full request URI into the analytics store, so a token
    in a query string would be written to disk on every visit."""
    assert client.get(f"/admin/feedback?token={TOKEN}").status_code == 401


# ---------------------------------------------------------------------------
# HTTP: admin page content
# ---------------------------------------------------------------------------

def test_admin_page_shows_the_post_and_the_reason(client: TestClient) -> None:
    fp = _item(url_id="a").fingerprint
    client.post("/feedback", json={"id": fp, "locale": "en", "kind": "vote", "vote": "down"})
    client.post("/feedback", json={"id": fp, "locale": "en", "kind": "reason",
                                   "reason": "too_technical"})
    r = client.get("/admin/feedback", headers=_auth())
    assert r.status_code == 200
    assert "Chrome zero-day under attack" in r.text
    assert f'href="/en/threat/{fp}"' in r.text
    assert "Too technical" in r.text
    assert r.headers["cache-control"] == "no-store"
    assert "noindex" in r.headers["x-robots-tag"]


def test_admin_page_escapes_what_it_prints(client: TestClient, fb_path: Path) -> None:
    """Post ids come from the public POST, so they are untrusted."""
    client.post("/feedback", json={"id": "<img src=x onerror=alert(1)>", "locale": "en",
                                   "kind": "vote", "vote": "down"})
    r = client.get("/admin/feedback", headers=_auth())
    assert "<img src=x" not in r.text
    assert "&lt;img src=x" in r.text


def test_admin_page_has_an_empty_state(client: TestClient) -> None:
    r = client.get("/admin/feedback", headers=_auth())
    assert "No feedback yet" in r.text
