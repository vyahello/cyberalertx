"""Phase 6 control room: navigation, data correctness, security, operations,
health states and reliability.

Fixture stores in tmp_path; probes (frontend, Postgres, systemd) injected;
no network, no AI call, no Telegram/Threads delivery.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cyberalertx.ai.cache import ThreatPostCache
from cyberalertx.ai.generator import ContentGenerator
from cyberalertx.ai.models import ThreatPost
from cyberalertx.api.admin import AdminGuard
from cyberalertx.api.app import _PostService, build_app
from cyberalertx.models import NewsItem
from cyberalertx.ops import health, readmodel as rm, usage
from cyberalertx.ops.audit import AuditLog
from cyberalertx.publish.jobs import JobStore, PublicationJob

TOKEN = "c" * 48
NOW = datetime.now(timezone.utc)


def item(n: str, *, hours: float = 3, story: str = "", lang: str = "en", fetched: datetime | None = None,
         title: str = "") -> NewsItem:
    t = title or f"Widget flaw {n} exploited in attacks"
    it = NewsItem(title=t, source="BleepingComputer", url=f"https://e.test/{n}",
                  published_at=NOW - timedelta(hours=hours),
                  raw_content=f"{t}. Report {n} describes what happened, who is affected and what to do. " * 6,
                  threat_score=70.0, category="vulnerability", actionability_level="urgent_action",
                  source_tier="trusted", language=lang, story_key=story)
    if fetched:
        it.fetched_at = fetched
    return it


def post(it: NewsItem, locale: str, status: str = "auto") -> ThreatPost:
    return ThreatPost(title=("Ваду у Widget атакують" if locale == "ua" else "Attackers hit Widget servers"),
                      short_summary="Widget servers are attacked.", threat_level="Critical", why_it_matters="x",
                      affected_users=["x"], what_to_do=["Patch"], language=locale, source_fingerprint=it.fingerprint,
                      generated_by="mock:test", review_status=status)


class Svc(_PostService):
    def __init__(self, items: list[NewsItem], cache: ThreatPostCache) -> None:
        self._items = items
        self._generator = ContentGenerator(provider=None, cache=cache)

    def list_items(self) -> list[NewsItem]:
        return list(self._items)


def auth(user: str = "editor") -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{TOKEN}".encode()).decode(), "X-Real-IP": "198.51.100.7"}


@pytest.fixture
def room(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import cyberalertx.api.app as app_mod
    import cyberalertx.threads.accounts as acc_mod

    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("CYBERALERTX_TELEGRAM_BOT_TOKEN", "123456:SECRET-BOT-TOKEN-xyz")
    monkeypatch.setenv("CYBERALERTX_TELEGRAM_CHANNEL_EN", "@cax_en")
    monkeypatch.setenv("CYBERALERTX_TELEGRAM_CHANNEL_UA", "-1001234567890")
    monkeypatch.setenv("CYBERALERTX_THREADS_APP_SECRET", "threads-app-secret-SHOULD-NOT-SHOW")
    monkeypatch.setenv("CYBERALERTX_FRONTEND_PROBE_URL", "off")
    monkeypatch.setattr(acc_mod, "ACCOUNTS_PATH", tmp_path / "threads_accounts.json")
    monkeypatch.setattr(acc_mod, "STATES_PATH", tmp_path / "states.json")
    monkeypatch.setattr(app_mod, "_publish_jobs_path", lambda: tmp_path / "publish_jobs.json")
    monkeypatch.setattr(app_mod, "_ops_data_dir", lambda: tmp_path)
    monkeypatch.setattr(app_mod, "_MEDIA_STORE", None)
    monkeypatch.setattr(health, "probe_units", lambda: {})
    health.clear_probe_cache()
    rm.clear_cache()
    # two articles of one story + one standalone story, all fetched now
    a1 = item("a1", story="s:aaaa", title="Attackers exploit CVE-2026-1111 in Widget Gateway")
    a2 = item("a2", story="s:aaaa", hours=2, title="CISA: Widget Gateway CVE-2026-1111 under active attack")
    b = item("b", story="s:bbbb", title="Ransomware gang leaks hospital records in Spain",)
    cache = ThreatPostCache(tmp_path / "threat_posts.json")
    for it in (a1, b):
        cache.set(it.fingerprint, "en", post(it, "en"))
    cache.set(a1.fingerprint, "ua", post(a1, "ua", "pending"))
    svc = Svc([a1, a2, b], cache)
    app = build_app(service=svc, feedback_path=tmp_path / "f.jsonl", admin_guard=AdminGuard())
    return {"client": TestClient(app), "tmp": tmp_path, "items": (a1, a2, b), "cache": cache, "svc": svc}


def csrf_of(client: TestClient, path: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', client.get(path, headers=auth()).text)
    assert m, f"no CSRF token on {path}"
    return m.group(1)


def seed_jobs(tmp: Path, fp: str) -> JobStore:
    store = JobStore(tmp / "publish_jobs.json")
    jobs = []
    for dest, loc, status in (("website", "en", "published"), ("website", "ua", "published"),
                              ("telegram", "en", "failed"), ("telegram", "ua", "outcome_unknown"),
                              ("threads@en", "en", "scheduled"), ("threads@ua", "ua", "retrying")):
        j = PublicationJob(job_id=f"s:aaaa:{loc}:{dest}:initial", story_key="s:aaaa", fingerprint=fp, locale=loc,
                           destination=dest, status=status, completed_at=NOW.isoformat() if status == "published" else "",
                           last_error="boom" if status == "failed" else "", error_category="network" if status == "failed" else "")
        jobs.append(j)
    store.add_missing(jobs, NOW)
    for j in jobs:                                   # add_missing keeps given status
        store.update(j.job_id, lambda x, s=j.status: setattr(x, "status", s), NOW)
    return store


# ---------------------------------------------------------------- navigation & access

ROUTES = ["/admin/", "/admin/stories", "/admin/intel", "/admin/review", "/admin/feedback", "/admin/metrics",
          "/admin/media", "/admin/publishing", "/admin/threads", "/admin/sources", "/admin/usage", "/admin/system",
          "/admin/system.json", "/admin/search?q=widget", "/admin/publishing.json", "/admin/media.json"]


def test_every_admin_route_resolves_and_is_locked(room: dict[str, Any]) -> None:
    c = room["client"]
    for path in ROUTES:
        assert c.get(path).status_code == 401, path
        r = c.get(path, headers=auth())
        assert r.status_code == 200, (path, r.text[:200])
    for path in ("/admin/publishing/action", "/admin/media/regenerate", "/admin/sources/test", "/admin/review/decide"):
        assert c.post(path, data={}).status_code == 401, path


def test_active_navigation_and_breadcrumbs(room: dict[str, Any]) -> None:
    c = room["client"]
    for path, key in (("/admin/stories", "/admin/stories"), ("/admin/usage", "/admin/usage"),
                      ("/admin/system", "/admin/system"), ("/admin/publishing", "/admin/publishing")):
        html = c.get(path, headers=auth()).text
        assert re.search(rf'<a href="{re.escape(key)}" aria-current=page>', html), path
        side = html.split("<aside", 1)[1].split("</aside>", 1)[0]
        assert side.count("aria-current=page>") == 1 and "<script" not in html.lower()
    assert '<div class="crumbs">Operations' in c.get("/admin/usage", headers=auth()).text


def story_key_of(room: dict[str, Any], fp: str) -> str:
    src = rm.OpsSources(items=room["svc"].list_items, posts=lambda: [], post_cache=room["cache"], data_dir=room["tmp"])
    return next(r.key for r in rm.story_rows(rm.intel_view(src, NOW)) if r.anchor == fp or fp in r.key
                or any(m.fingerprint == fp for s in rm.intel_view(src, NOW).stories if s.key == r.key for m in s.members))


def test_story_detail_and_unknown_story(room: dict[str, Any]) -> None:
    c = room["client"]
    key = story_key_of(room, room["items"][0].fingerprint)
    r = c.get(f"/admin/stories/{key}", headers=auth())
    assert r.status_code == 200 and "Source articles (2)" in r.text and "No fact sheet has been extracted" in r.text
    assert c.get("/admin/stories/s:nope", headers=auth()).status_code == 404
    assert c.get("/admin/stories/" + "x" * 200, headers=auth()).status_code == 404


# ---------------------------------------------------------------- data correctness

def test_articles_and_stories_are_counted_separately(room: dict[str, Any]) -> None:
    src = rm.OpsSources(items=room["svc"].list_items, posts=lambda: list(room["cache"].all()),
                        post_cache=room["cache"], data_dir=room["tmp"])
    res = rm.intel_view(src, NOW)
    m = rm.overview_metrics(src, res, [], NOW)
    assert m["articles_today"] == 3 and m["stories_today"] == 2
    assert m["pending_editions"] == 1 and m["pending_stories"] == 1
    a = next(r for r in rm.story_rows(res) if r.articles == 2)
    assert a.editions == {"en": "auto", "ua": "pending"}


def test_kyiv_day_boundary() -> None:
    now = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    start, end, day = rm.kyiv_day(now)
    assert day == date(2026, 11, 4) and start == datetime(2026, 11, 3, 22, 0, tzinfo=timezone.utc)
    summer = rm.kyiv_day(datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
    assert summer[0] == datetime(2026, 6, 30, 21, 0, tzinfo=timezone.utc)


def test_destination_counts_match_jobs(room: dict[str, Any]) -> None:
    from cyberalertx.publish.config import build_telegram_settings
    from cyberalertx.threads.config import ThreadsSettings
    store = seed_jobs(room["tmp"], room["items"][0].fingerprint)
    src = rm.OpsSources(items=room["svc"].list_items, posts=lambda: [], data_dir=room["tmp"])
    d = {(x.key, x.locale): x for x in rm.destinations(src, store.all(), telegram=build_telegram_settings(),
                                                        threads_settings=ThreadsSettings(), threads_accounts={})}
    assert len(d) == 6
    assert d[("website", "en")].counts == {"published": 1} and d[("telegram", "ua")].counts == {"outcome_unknown": 1}
    assert d[("threads@en", "en")].configured == "publishing off" and d[("threads@en", "en")].connected == "not mapped"
    html = room["client"].get("/admin/publishing", headers=auth()).text
    assert html.count("Threads EN") >= 1 and "Website UA" in html


# ---------------------------------------------------------------- security

def test_secrets_are_never_displayed(room: dict[str, Any]) -> None:
    c = room["client"]
    for path in ("/admin/threads", "/admin/threads.json", "/admin/system", "/admin/system.json", "/admin/usage", "/admin/"):
        body = c.get(path, headers=auth()).text
        assert "SECRET-BOT-TOKEN" not in body and "threads-app-secret" not in body and TOKEN not in body, path
        assert "-1001234567890" not in body, path                        # private chat ids stay hidden
    assert "@cax_en" in c.get("/admin/threads", headers=auth()).text      # public handle is fine


@pytest.mark.parametrize("path,data", [
    ("/admin/publishing/action", {"job": "s:aaaa:en:telegram:initial", "action": "retry", "confirm": "yes"}),
    ("/admin/media/regenerate", {"story": "s:aaaa", "confirm": "yes"}),
    ("/admin/sources/test", {"source": "BleepingComputer", "confirm": "yes"}),
])
def test_state_changes_need_csrf_same_origin_and_confirmation(room: dict[str, Any], path: str, data: dict[str, str]) -> None:
    c = room["client"]
    seed_jobs(room["tmp"], room["items"][0].fingerprint)
    assert c.post(path, data=data, headers=auth()).status_code == 403                       # no token
    token = csrf_of(c, "/admin/threads")
    assert c.post(path, data={**data, "csrf": token}, headers={**auth(), "Origin": "https://evil.example"}).status_code == 403
    no_confirm = {k: v for k, v in data.items() if k != "confirm"}
    assert c.post(path, data={**no_confirm, "csrf": token}, headers=auth()).status_code == 400


def test_publication_actions_use_the_engine_and_are_audited(room: dict[str, Any]) -> None:
    c = room["client"]
    store = seed_jobs(room["tmp"], room["items"][0].fingerprint)
    token = csrf_of(c, "/admin/publishing?status=failed")
    r = c.post("/admin/publishing/action", headers=auth("alice"), follow_redirects=False,
               data={"csrf": token, "job": "s:aaaa:en:telegram:initial", "action": "retry", "confirm": "yes",
                     "back": "/admin/publishing?status=failed"})
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/publishing?status=failed&done=")
    assert store.get("s:aaaa:en:telegram:initial").status == "scheduled"            # type: ignore[union-attr]
    # outcome_unknown is never retried blindly — the engine refuses, and that is audited too
    r = c.post("/admin/publishing/action", headers=auth("alice"), follow_redirects=False,
               data={"csrf": token, "job": "s:aaaa:ua:telegram:initial", "action": "retry", "confirm": "yes"})
    assert "failed=" in r.headers["location"] and store.get("s:aaaa:ua:telegram:initial").status == "outcome_unknown"  # type: ignore[union-attr]
    r = c.post("/admin/publishing/action", headers=auth("alice"), follow_redirects=False,
               data={"csrf": token, "job": "s:aaaa:ua:telegram:initial", "action": "reconcile_sent", "confirm": "yes",
                     "external_id": "<script>"})
    assert "failed=" in r.headers["location"]                                          # validated input
    c.post("/admin/publishing/action", headers=auth("alice"),
           data={"csrf": token, "job": "s:aaaa:ua:telegram:initial", "action": "reconcile_not_sent", "confirm": "yes"})
    assert store.get("s:aaaa:ua:telegram:initial").status == "scheduled"            # type: ignore[union-attr]
    c.post("/admin/publishing/action", headers=auth("alice"), data={"csrf": token, "job": "s:aaaa:en:threads@en:initial",
                                                                    "action": "cancel", "confirm": "yes"})
    assert store.get("s:aaaa:en:threads@en:initial").status == "cancelled"          # type: ignore[union-attr]
    log = AuditLog(room["tmp"] / "admin_audit.jsonl").recent()
    assert [(e["action"], e["result"]) for e in reversed(log)] == [
        ("publication.retry", "ok"), ("publication.retry", "refused"), ("publication.reconcile_sent", "refused"),
        ("publication.reconcile_not_sent", "ok"), ("publication.cancel", "ok")]
    assert all(e["actor"] == "alice" and e["address"] == "198.51.100.7" for e in log)
    html = c.get("/admin/publishing?status=outcome_unknown", headers=auth()).text
    assert "No job matches" in html                                                   # filter works


def test_open_redirect_is_impossible(room: dict[str, Any]) -> None:
    c = room["client"]
    seed_jobs(room["tmp"], room["items"][0].fingerprint)
    token = csrf_of(c, "/admin/publishing")
    r = c.post("/admin/publishing/action", headers=auth(), follow_redirects=False,
               data={"csrf": token, "job": "s:aaaa:en:telegram:initial", "action": "retry", "confirm": "yes",
                     "back": "https://evil.example/x"})
    assert r.headers["location"].startswith("/admin/publishing?")


def test_review_decisions_are_audited(room: dict[str, Any]) -> None:
    c = room["client"]
    a1 = room["items"][0]
    token = csrf_of(c, "/admin/review?status=pending")
    c.post("/admin/review/decide", headers=auth("bob"), data={"csrf": token, "decision": "approve",
                                                              "key": f"{a1.fingerprint}:ua", "back": "pending"})
    e = AuditLog(room["tmp"] / "admin_audit.jsonl").recent()[0]
    assert (e["actor"], e["action"], e["target"], e["result"]) == ("bob", "review.approve", f"{a1.fingerprint}:ua", "ok")
    assert e["meta"] == {"previous": "pending"}


def test_audit_meta_never_keeps_credentials(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "a.jsonl")
    log.record(actor="x", action="t", target="https://h/?access_token=SECRET1", result="ok", api_key="SECRET2",
               story_key="s:1", note="Authorization: bot /bot123:ABCdef_ghi/sendMessage")
    raw = (tmp_path / "a.jsonl").read_text()
    assert "SECRET1" not in raw and "SECRET2" not in raw and "ABCdef" not in raw and '"story_key": "s:1"' in raw


# ---------------------------------------------------------------- operations

def test_media_regenerate_only_queues(room: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import cyberalertx.api.app as app_mod
    from cyberalertx.media.assets import MediaAsset, MediaStore
    store = MediaStore(room["tmp"] / "media")
    store.put(MediaAsset(asset_id="illus:s:aaaa", story_key="s:aaaa", asset_type="editorial_illustration",
                         status="failed", attempts=3, last_error="ProviderError", content_hash="h"))
    monkeypatch.setattr(app_mod, "_MEDIA_STORE", store)
    monkeypatch.setenv("CYBERALERTX_IMAGE_PROVIDER", "mock")
    c = room["client"]
    html = c.get("/admin/media?q=s:aaaa", headers=auth()).text
    assert "Regenerate" in html and "1 of 1 records" in html
    token = csrf_of(c, "/admin/threads")
    c.post("/admin/media/regenerate", headers=auth(), data={"csrf": token, "story": "s:aaaa", "confirm": "yes"})
    a = store.get("illus:s:aaaa")
    assert a and a.status == "pending" and a.attempts == 0 and a.content_hash == ""
    monkeypatch.setenv("CYBERALERTX_IMAGE_PROVIDER", "none")
    assert "Regenerate</button>" not in c.get("/admin/media", headers=auth()).text        # nothing to queue for


def test_source_test_fetch_stores_nothing(room: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import cyberalertx.sources.registry as reg

    class Fake:
        def fetch(self) -> list[Any]:
            return [object(), object()]
    monkeypatch.setattr(reg, "build_sources", lambda cfgs: [Fake()])
    c = room["client"]
    token = csrf_of(c, "/admin/threads")
    r = c.post("/admin/sources/test", headers=auth(), follow_redirects=False,
               data={"csrf": token, "source": "BleepingComputer", "confirm": "yes"})
    assert "returned+2+items" in r.headers["location"]
    assert c.post("/admin/sources/test", headers=auth(), data={"csrf": token, "source": "Nope", "confirm": "yes"}).status_code == 400
    page = c.get("/admin/sources", headers=auth()).text
    assert "Reliability profile" in page


def test_usage_aggregation_is_honest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "u.jsonl"
    t = datetime(2026, 11, 3, 22, 30, tzinfo=timezone.utc)            # 00:30 on 4 Nov in Kyiv
    usage.record_call(provider="claude-cli", model="m1", input_tokens=10, output_tokens=5, cost_usd=0.02,
                      cost_source="claude-cli", path=p, now=t)
    with usage.stage("fact_sheet"):
        usage.record_call(provider="anthropic", model="m2", input_tokens=1_000_000, path=p, now=t)
    usage.record_call(provider="anthropic", model="m3", input_tokens=100, path=p, now=t)
    rows = usage.load(p)
    agg = usage.aggregate(rows, period="day", rates={"m2": {"input": 3.0}})
    day = agg["2026-11-04"]
    assert day[("claude-cli", "m1", "unspecified")].estimated_usd == pytest.approx(0.02)
    assert day[("anthropic", "m2", "fact_sheet")].estimated_usd == pytest.approx(3.0)
    m3 = day[("anthropic", "m3", "unspecified")]
    assert m3.estimated_calls == 0 and m3.unavailable_calls == 1        # unpriced = unavailable, not $0
    monkeypatch.setenv("CYBERALERTX_AI_PRICES", "not json")
    assert usage.operator_rates() == {}


def test_usage_page_marks_unavailable_cost(room: dict[str, Any]) -> None:
    usage.record_call(provider="anthropic", model="m", input_tokens=5, path=room["tmp"] / "ai_usage.jsonl")
    html = room["client"].get("/admin/usage", headers=auth()).text
    assert "unavailable" in html and "makes no AI call" in html and "$0.00" not in html


def test_provider_ledger_is_written_by_providers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cyberalertx.ai.providers.anthropic_provider import AnthropicProvider
    monkeypatch.setattr(usage, "USAGE_PATH", tmp_path / "u.jsonl")

    class U:
        input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens = 7, 3, 0, 0
    AnthropicProvider._record_usage(U(), "claude-model-x")
    r = usage.load(tmp_path / "u.jsonl")[0]
    assert (r["provider"], r["model"], r["input_tokens"], r["cost_usd"]) == ("anthropic", "claude-model-x", 7, None)


# ---------------------------------------------------------------- health

def _report(room: dict[str, Any], **probes: Any) -> Any:
    from cyberalertx.publish.config import build_telegram_settings
    from cyberalertx.threads.config import ThreadsSettings
    health.clear_probe_cache()
    src = rm.OpsSources(items=room["svc"].list_items, posts=lambda: [], data_dir=room["tmp"])
    return health.system_report(src, [], now=NOW, health={}, metrics={}, threads_settings=ThreadsSettings(),
                                threads_accounts={}, telegram=build_telegram_settings(), intel_ok=True, **probes)


def test_optional_things_are_not_failures(room: dict[str, Any]) -> None:
    r = _report(room, frontend=lambda: ("healthy", "HTTP 200"), database=lambda: ("not_configured", "json"),
                units=lambda: {})
    statuses = {c.name: c.status for c in r.checks}
    assert statuses["Image provider"] == "not_configured" and statuses["Publication worker"] == "not_configured"
    assert statuses["systemd units"] == "unknown" and statuses["Ingestion"] == "unknown"   # no record ≠ healthy
    assert r.overall in ("unknown", "warning", "critical") and r.overall != "healthy"


def test_outages_are_reported(room: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    r = _report(room, frontend=lambda: ("critical", "no answer (ConnectError)"),
                database=lambda: ("critical", "Postgres mirror unreachable (OperationalError)"),
                units=lambda: {"cyberalertx-run.service": {"Id": "cyberalertx-run.service", "ActiveState": "failed"}})
    s = {c.name: (c.status, c.detail) for c in r.checks}
    assert s["Website (Next.js)"][0] == "critical" and s["Database"][0] == "critical"
    assert s["cyberalertx-run.service"][0] == "critical" and r.overall == "critical"
    assert "postgresql://" not in json.dumps([c.detail for c in r.checks])
    monkeypatch.setattr(health.os, "access", lambda *a: False)
    assert {c.name: c.status for c in _report(room, frontend=lambda: ("healthy", ""), database=lambda: ("healthy", ""),
                                               units=lambda: {}).checks}["Data storage"] == "critical"


def test_database_probe_never_leaks_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CYBERALERTX_STORAGE_BACKEND", "dual")
    monkeypatch.setenv("CYBERALERTX_PG_URL", "postgresql://user:pw-SECRET@127.0.0.1:1/x")
    status, detail = health.probe_database()
    assert status == "critical" and "SECRET" not in detail and "postgresql" not in detail


# ---------------------------------------------------------------- reliability

def test_empty_world_renders_empty_states(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cyberalertx.api.app as app_mod
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("CYBERALERTX_FRONTEND_PROBE_URL", "off")
    monkeypatch.setattr(app_mod, "_publish_jobs_path", lambda: tmp_path / "none.json")
    monkeypatch.setattr(health, "probe_units", lambda: {})
    rm.clear_cache()
    health.clear_probe_cache()
    c = TestClient(build_app(service=Svc([], ThreatPostCache(tmp_path / "p.json")),
                             feedback_path=tmp_path / "f.jsonl", admin_guard=AdminGuard()))
    for path in ROUTES:
        assert c.get(path, headers=auth()).status_code == 200, path
    assert "No publication jobs yet" in c.get("/admin/publishing", headers=auth()).text
    assert "No recorded events yet" in c.get("/admin/", headers=auth()).text


def test_intel_failure_degrades_gracefully(room: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("core down")
    import cyberalertx.intel.engine as eng
    monkeypatch.setattr(eng, "run", boom)
    rm.clear_cache()
    c = room["client"]
    assert "could not be computed" in c.get("/admin/stories", headers=auth()).text
    assert c.get("/admin/", headers=auth()).status_code == 200
    sysj = {x["name"]: x["status"] for x in c.get("/admin/system.json", headers=auth()).json()["checks"]}
    assert sysj["Intelligence Core"] == "critical"


def test_large_datasets_paginate_server_side() -> None:
    rows = [rm.StoryRow(key=f"s:{i:04d}", title=f"Story {i}", anchor=f"{i:016x}", articles=1, sources=[], relevance="in_scope",
                        score=float(i % 100), confidence="low" if i % 3 == 0 else "high", verification="verified",
                        exploitation="unknown", category="vulnerability", top_rank=None, trending=False, breaking=False,
                        fact_sheet=False, editions={"en": "auto", "ua": "missing"}, first_seen=NOW, latest=NOW)
            for i in range(1, 131)]
    page3, total = rm.filter_stories(rows, rm.StoryQuery(page=3))
    assert total == 130 and len(page3) == 30
    low, n = rm.filter_stories(rows, rm.StoryQuery.from_params({"confidence": "low", "min_score": "50", "page": "zz"}))
    assert n == sum(1 for r in rows if r.confidence == "low" and (r.score or 0) >= 50) and all(r.confidence == "low" for r in low)
    q = rm.StoryQuery.from_params({"confidence": "<script>", "since": "not-a-date", "sort": "drop table"})
    assert q.confidence == "" and q.since is None and q.sort == "score"

    from cyberalertx.api.admin.publishing_page import JobQuery, filter_jobs
    jobs = [PublicationJob(job_id=f"s:{i}:en:website:initial", story_key=f"s:{i}", fingerprint="f", locale="en",
                           destination="website", updated_at=NOW.isoformat()) for i in range(120)]
    page, total = filter_jobs(jobs, JobQuery.from_params({"page": "3", "destination": "nope"}))
    assert total == 120 and len(page) == 20
