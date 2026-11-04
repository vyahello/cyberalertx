"""Review state: backward-compatible model, modes, public filtering, Telegram
selection, the /admin/review queue (auth, CSRF, persistence) and the CLI."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cyberalertx.ai.cache import ThreatPostCache
from cyberalertx.ai.generator import ContentGenerator
from cyberalertx.ai.models import ThreatPost
from cyberalertx.ai.review import (
    apply_decision, initial_status, is_publicly_visible, parse_key, review_mode,
)
from cyberalertx.api.admin import AdminGuard
from cyberalertx.api.app import _PostService, build_app
from cyberalertx.models import NewsItem

TOKEN = "t" * 48


def _item(url_id: str = "a") -> NewsItem:
    return NewsItem(
        title=f"Widget flaw {url_id}", source="BleepingComputer", url=f"https://e.test/{url_id}",
        published_at=datetime.now(timezone.utc) - timedelta(hours=3),
        raw_content="A widget flaw is exploited.", threat_score=70.0, category="vulnerability",
        actionability_level="urgent_action", actionability_score=0.9,
        source_tier="trusted", source_credibility_score=0.9, language="en",
    )


def _post(item: NewsItem, locale: str, status: str = "auto") -> ThreatPost:
    ua = locale == "ua"
    return ThreatPost(
        title="Зловмисники атакують сервери Widget" if ua else "Attackers hit Widget servers",
        short_summary=("BleepingComputer повідомляє про атаки на Widget." if ua
                       else "BleepingComputer reports attacks on Widget servers."),
        threat_level="Critical", why_it_matters="x", affected_users=["x"], what_to_do=["x"],
        language=locale, source_fingerprint=item.fingerprint, generated_by="mock:test",
        review_status=status, quality={"score": 40, "review_reasons": ["score 40 is below 85"]},
    )


class _Svc(_PostService):
    def __init__(self, items: list[NewsItem], cache: ThreatPostCache) -> None:
        self._items = items
        self._generator = ContentGenerator(provider=None, cache=cache)

    def list_items(self) -> list[NewsItem]:
        return list(self._items)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", TOKEN)
    ok, held = _item("ok"), _item("held")
    cache = ThreatPostCache(tmp_path / "posts.json")
    for loc in ("en", "ua"):
        cache.set(ok.fingerprint, loc, _post(ok, loc))
        cache.set(held.fingerprint, loc, _post(held, loc, "pending"))
    svc = _Svc([ok, held], cache)
    app = build_app(service=svc, feedback_path=tmp_path / "f.jsonl", admin_guard=AdminGuard())
    return {"ok": ok, "held": held, "cache": cache, "svc": svc, "client": TestClient(app)}


def _ids(resp: Any) -> set[str]:
    return {p["id"] for p in resp.json()["items"]}


# ---------------------------------------------------------------------------
# Model + modes
# ---------------------------------------------------------------------------

def test_old_cache_entries_load_as_auto() -> None:
    legacy = {"title": "t", "short_summary": "s", "threat_level": "Low", "why_it_matters": "w",
              "affected_users": [], "what_to_do": []}
    post = ThreatPost.from_dict(legacy)
    assert (post.review_status, post.quality, post.reviewed_by, post.reviewed_at) == ("auto", {}, "", "")
    assert ThreatPost.from_dict({**legacy, "review_status": "bogus"}).review_status == "auto"
    assert ThreatPost.from_dict(post.to_dict()) == post


def test_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CYBERALERTX_REVIEW_MODE", raising=False)
    assert review_mode() == "flag"
    assert initial_status(True, "flag") == "pending" == initial_status(True, "hold")
    assert initial_status(True, "off") == "auto" == initial_status(False, "flag")
    pending, rejected = _post(_item(), "en", "pending"), _post(_item(), "en", "rejected")
    assert is_publicly_visible(pending, "flag") and not is_publicly_visible(pending, "hold")
    assert not is_publicly_visible(rejected, "flag") and is_publicly_visible(rejected, "off")


def test_parse_key() -> None:
    assert parse_key("abc123:uk") == ("abc123", "ua")
    for bad in ("abc", "abc:fr", ":en", "a/b:en"):
        with pytest.raises(ValueError):
            parse_key(bad)


def test_apply_decision_persists(tmp_path: Path) -> None:
    item, cache = _item(), ThreatPostCache(tmp_path / "p.json")
    cache.set(item.fingerprint, "en", _post(item, "en", "pending"))
    apply_decision(cache, item.fingerprint, "en", "approve", "ed",
                   now=datetime(2026, 11, 3, tzinfo=timezone.utc))
    again = ThreatPostCache(tmp_path / "p.json").get(item.fingerprint, "en")
    assert again is not None and again.review_status == "approved"
    assert (again.reviewed_by, again.reviewed_at) == ("ed", "2026-11-03T00:00:00+00:00")
    with pytest.raises(KeyError):
        apply_decision(cache, "nope", "en", "approve", "ed")
    with pytest.raises(ValueError):
        apply_decision(cache, item.fingerprint, "en", "delete", "ed")


# ---------------------------------------------------------------------------
# Public filtering
# ---------------------------------------------------------------------------

def test_flag_mode_keeps_pending_posts_public(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CYBERALERTX_REVIEW_MODE", "flag")
    c, held = world["client"], world["held"]
    assert held.fingerprint in _ids(c.get("/posts?language=en"))
    assert c.get(f"/posts/{held.fingerprint}").status_code == 200


def test_hold_mode_hides_pending_everywhere(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CYBERALERTX_REVIEW_MODE", "hold")
    c, ok, held = world["client"], world["ok"], world["held"]
    for url in ("/posts", "/posts?language=en", "/posts?language=ua",
                "/posts/trending?language=en", "/posts/latest"):
        ids = _ids(c.get(url))
        assert held.fingerprint not in ids, url
        assert ok.fingerprint in ids, url
    assert c.get(f"/posts/{held.fingerprint}").status_code == 404
    assert c.get(f"/posts/{ok.fingerprint}").status_code == 200


def test_rejected_is_hidden_in_flag_mode_and_off_hides_nothing(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    held, cache, c = world["held"], world["cache"], world["client"]
    for loc in ("en", "ua"):
        apply_decision(cache, held.fingerprint, loc, "reject", "ed")
    monkeypatch.setenv("CYBERALERTX_REVIEW_MODE", "flag")
    assert held.fingerprint not in _ids(c.get("/posts"))
    monkeypatch.setenv("CYBERALERTX_REVIEW_MODE", "off")
    assert held.fingerprint in _ids(c.get("/posts"))


def test_hold_mode_one_locale_held(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CYBERALERTX_REVIEW_MODE", "hold")
    ok, cache, c = world["ok"], world["cache"], world["client"]
    cache.set(ok.fingerprint, "ua", _post(ok, "ua", "pending"))
    assert ok.fingerprint in _ids(c.get("/posts?language=en"))
    assert ok.fingerprint not in _ids(c.get("/posts?language=ua"))


def test_telegram_selection_skips_held_posts(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from cyberalertx.publish.config import TelegramSettings
    from cyberalertx.publish.ledger import PublishLedger
    from cyberalertx.publish.service import publish_once

    settings = TelegramSettings(bot_token="x", channels={"en": "@en"}, min_level="High", limit=5,
                                send_delay_seconds=0.0, public_base_url="https://c.test")
    for mode, expected in (("flag", 2), ("hold", 1)):
        monkeypatch.setenv("CYBERALERTX_REVIEW_MODE", mode)
        result = publish_once(settings=settings, service=world["svc"], dry_run=True,
                              ledger=PublishLedger(tmp_path / f"{mode}.jsonl"))
        assert result.sent == expected, mode


# ---------------------------------------------------------------------------
# Admin queue
# ---------------------------------------------------------------------------

def _auth(**extra: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"ed:{TOKEN}".encode()).decode(),
            "X-Real-IP": "203.0.113.9", **extra}


def _csrf(html: str) -> str:
    return html.split('name="csrf" value="', 1)[1].split('"', 1)[0]


def test_review_page_needs_login_and_lists_pending(world: dict[str, Any]) -> None:
    c, held = world["client"], world["held"]
    assert c.get("/admin/review").status_code == 401
    r = c.get("/admin/review", headers=_auth())
    assert r.status_code == 200
    assert f"{held.fingerprint}:en" in r.text and "score 40 is below 85" in r.text
    assert world["ok"].fingerprint not in r.text
    assert "form-action 'self'" in r.headers["content-security-policy"]
    # Phase 6: every admin page has GET search/filter forms, so form-action is
    # 'self' everywhere (never another origin); scripts stay forbidden.
    other = c.get("/admin/", headers=_auth()).headers["content-security-policy"]
    assert "form-action 'self'" in other and "script-src" not in other and "default-src 'none'" in other
    assert "<script" not in r.text.lower()
    assert c.get("/admin/review.json", headers=_auth()).json()["counts"]["pending"] == 2


def test_approve_persists_through_the_cache(world: dict[str, Any]) -> None:
    c, held = world["client"], world["held"]
    token = _csrf(c.get("/admin/review", headers=_auth()).text)
    r = c.post("/admin/review/decide", headers=_auth(**{"Sec-Fetch-Site": "same-origin", "Origin": "null"}),
               data={"key": f"{held.fingerprint}:en", "decision": "approve", "csrf": token},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/review?status=pending")
    post = ThreatPostCache(world["cache"]._path).get(held.fingerprint, "en")  # noqa: SLF001
    assert post is not None and post.review_status == "approved"
    assert post.reviewed_by == "admin:ed" and post.reviewed_at


@pytest.mark.parametrize("headers,csrf,status", [
    ({}, "", 403),                                              # no token
    ({}, "123.deadbeef", 403),                                  # forged token
    ({"Sec-Fetch-Site": "cross-site"}, "VALID", 403),           # cross-site browser request
    ({"Origin": "https://evil.test"}, "VALID", 403),            # foreign origin
])
def test_decide_rejects_csrf(world: dict[str, Any], headers: dict[str, str], csrf: str, status: int) -> None:
    c, held = world["client"], world["held"]
    token = _csrf(c.get("/admin/review", headers=_auth()).text) if csrf == "VALID" else csrf
    r = c.post("/admin/review/decide", headers=_auth(**headers),
               data={"key": f"{held.fingerprint}:en", "decision": "reject", "csrf": token})
    assert r.status_code == status
    post = world["cache"].get(held.fingerprint, "en")
    assert post is not None and post.review_status == "pending"


def test_decide_without_login_is_401(world: dict[str, Any]) -> None:
    r = world["client"].post("/admin/review/decide", data={"key": "x:en", "decision": "approve"})
    assert r.status_code == 401


def test_csrf_tokens_expire() -> None:
    clock = {"t": 1_000_000.0}
    guard = AdminGuard(wall=lambda: clock["t"])
    import os
    os.environ["CYBERALERTX_ADMIN_TOKEN"] = TOKEN
    try:
        token = guard.csrf_token()
        assert guard.csrf_ok(token)
        clock["t"] += 13 * 3600
        assert not guard.csrf_ok(token)
    finally:
        del os.environ["CYBERALERTX_ADMIN_TOKEN"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_review_approve_reject_and_score_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from cyberalertx import main as cli
    from cyberalertx.ai import config as ai_config
    from cyberalertx.storage.json_store import JsonNewsStore

    item = _item("cli")
    posts_path, items_path = tmp_path / "threat_posts.json", tmp_path / "items.json"
    cache = ThreatPostCache(posts_path)
    cache.set(item.fingerprint, "en", _post(item, "en", "pending"))
    cache.set(item.fingerprint, "ua", _post(item, "ua", "pending"))
    JsonNewsStore(items_path).upsert_many([item])
    monkeypatch.setattr(ai_config, "AI_SETTINGS", ai_config.AISettings(
        cache_path=posts_path, fact_sheet_path=tmp_path / "fact_sheets.json"))
    monkeypatch.setattr(cli, "SETTINGS", type(cli.SETTINGS)(storage_path=items_path))
    monkeypatch.setenv("CYBERALERTX_STORAGE_BACKEND", "json")

    assert cli.main(["review", "list"]) == 0
    assert f"{item.fingerprint}:en" in capsys.readouterr().out
    assert cli.main(["review", "approve", f"{item.fingerprint}:en", "--by", "ed"]) == 0
    assert cli.main(["review", "reject", f"{item.fingerprint}:ua"]) == 0
    fresh = ThreatPostCache(posts_path)
    assert fresh.get(item.fingerprint, "en").review_status == "approved"  # type: ignore[union-attr]
    assert fresh.get(item.fingerprint, "ua").review_status == "rejected"  # type: ignore[union-attr]
    assert cli.main(["review", "approve", "nope:en"]) == 1

    before = hashlib.md5(posts_path.read_bytes()).hexdigest()
    out = tmp_path / "editorial" / "archive_scores.json"
    assert cli.main(["review", "score-archive", "--out", str(out)]) == 0
    assert hashlib.md5(posts_path.read_bytes()).hexdigest() == before   # cache untouched
    assert not (tmp_path / "fact_sheets.json").exists()
    report = json.loads(out.read_text())
    assert {r["key"] for r in report["posts"]} == {f"{item.fingerprint}:en", f"{item.fingerprint}:ua"}
    assert set(report["summary"]["locales"]) == {"en", "ua"}
    assert "Archive scorecard" in capsys.readouterr().out
