"""Intelligence layer: scoring, dimensions, Top 10, Trending, Breaking.

Fixed, hand-built fixtures only — no data files, no network, no AI.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from cyberalertx.ai.fact_sheet import CvssScore, FactSheet
from cyberalertx.ai.models import ThreatPost
from cyberalertx.intel.config import IntelConfig, config_from_mapping
from cyberalertx.intel.dimensions import confidence, exploitation_status, verification_status
from cyberalertx.intel.engine import run
from cyberalertx.intel.scoring import evaluate
from cyberalertx.intel.selection import (
    apply_alert_state, classify_breaking, daily_top, edition_for, trending,
)
from cyberalertx.intel.sources import SourceTable
from cyberalertx.intel.story import StoryView, _fallback_independent
from cyberalertx.models import NewsItem

NOW = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
TABLE = SourceTable()
CFG = IntelConfig()


def item(title: str, source: str, *, hours_ago: float = 2, body: str = "", url: str = "",
         audiences: list[str] | None = None, score: float = 50.0) -> NewsItem:
    return NewsItem(
        title=title, source=source,
        url=url or f"https://{source.replace(' ', '').lower()}.example/{abs(hash(title + source))}",
        published_at=NOW - timedelta(hours=hours_ago),
        raw_content=body or (title + ". " + "Details of the incident follow in the report. " * 8),
        threat_score=score, audience_targets=audiences or ["enterprise"],
    )


def post(level: str = "High", actions: bool = True) -> ThreatPost:
    return ThreatPost(title="t", short_summary="s", threat_level=level, why_it_matters="w",
                      affected_users=["x"], what_to_do=["Patch now"] if actions else [],
                      language="en", source_fingerprint="f" * 16, generated_by="mock")


def story(*members: NewsItem, key: str = "s:1", sheets: list[FactSheet] | None = None,
          level: str = "High", actions: bool = True, independent: list[str] | None = None) -> StoryView:
    ms = list(members)
    return StoryView(key=key, anchor=ms[0], members=ms,
                     independent_sources=independent or _fallback_independent(ms),
                     sheets=sheets or [], posts={"en": post(level, actions)})


# ---------------------------------------------------------------- sources

def test_syndicated_copies_are_one_independent_source() -> None:
    body = "Widget servers are under attack via CVE-2026-1111 according to the vendor advisory. " * 6
    a = item("Widget servers attacked", "BleepingComputer", body=body)
    b = item("Widget servers attacked", "The Hacker News", body=body)        # verbatim copy
    c = item("Widget hit", "SecurityWeek",
             body="According to BleepingComputer, Widget servers are being hit. " * 6)
    assert _fallback_independent([a, b, c]) == ["BleepingComputer"]


def test_syndication_does_not_inflate_reliability_or_confidence() -> None:
    one = story(item("Widget flaw exploited", "BleepingComputer"))
    body = one.members[0].raw_content
    copies = story(*[replace(one.members[0], source=s, url=f"https://{s}.x/a") for s in
                     ("BleepingComputer", "The Hacker News", "SecurityWeek", "DarkReading")])
    copies.members = [replace(m, raw_content=body) for m in copies.members]
    copies.independent_sources = _fallback_independent(copies.members)
    e1, e2 = evaluate(one, CFG, TABLE, NOW), evaluate(copies, CFG, TABLE, NOW)
    assert e1.components["source_reliability"] == e2.components["source_reliability"]
    assert confidence(one, TABLE).score == confidence(copies, TABLE).score


# ---------------------------------------------------------------- dimensions

def test_dimensions_are_independent_of_importance() -> None:
    claim = story(item("Hackers claim breach of national bank, leak 40 GB", "dev.ua"), level="Critical")
    ev = evaluate(claim, CFG, TABLE, NOW)
    assert ev.raw["potential_impact"] >= 0.7          # high impact ...
    assert ev.dim("verification_status") == "unverified"   # ... unverified ...
    assert ev.dim("confidence") == "low"              # ... low confidence — reported side by side


def test_official_source_confirms_exploitation_and_verifies() -> None:
    s = story(item("CISA adds Widget flaw to Known Exploited Vulnerabilities catalog", "CISA Alerts",
                   body="CISA added CVE-2026-1111 to its Known Exploited Vulnerabilities catalog "
                        "based on evidence of active exploitation. " * 4))
    assert exploitation_status(s, TABLE).value == "confirmed"
    assert verification_status(s, TABLE).value == "verified"


def test_media_report_of_exploitation_is_reported_not_confirmed() -> None:
    s = story(item("Widget servers actively exploited in the wild", "The Hacker News"))
    assert exploitation_status(s, TABLE).value == "reported"


def test_poc_is_its_own_status() -> None:
    s = story(item("Researchers publish proof-of-concept for Widget bug", "BleepingComputer"))
    assert exploitation_status(s, TABLE).value == "poc_available"


def test_contradictions_lower_confidence_not_importance() -> None:
    clean = story(item("Widget flaw exploited", "BleepingComputer"),
                  sheets=[FactSheet(summary="x", exploitation_status="confirmed")])
    contra = story(item("Widget flaw exploited", "BleepingComputer"),
                   sheets=[FactSheet(summary="x", exploitation_status="confirmed"),
                           FactSheet(summary="y", exploitation_status="not_reported")])
    assert confidence(contra, TABLE).score < confidence(clean, TABLE).score
    a, b = evaluate(clean, CFG, TABLE, NOW), evaluate(contra, CFG, TABLE, NOW)
    assert a.raw["potential_impact"] == b.raw["potential_impact"]


def test_many_independent_regional_outlets_partially_verify() -> None:
    s = story(*[item(f"Air-alert app hacked, fake alerts sent ({n})", n, body=f"{n} report " * 60)
                for n in ("dev.ua", "itc.ua", "ain.ua", "dou.ua")])
    assert len(s.independent_sources) == 4
    assert verification_status(s, TABLE).value == "partially_verified"


# ---------------------------------------------------------------- scoring

def test_score_is_bounded_deterministic_and_weighted() -> None:
    s = story(item("Widget flaw exploited", "BleepingComputer"),
              sheets=[FactSheet(summary="x", exploitation_status="confirmed", patch_status="available",
                                cvss_scores=[CvssScore(score=9.8)])], level="Critical")
    a, b = evaluate(s, CFG, TABLE, NOW), evaluate(s, CFG, TABLE, NOW)
    assert a.score == b.score and 0 <= a.score <= 100
    assert abs(sum(a.components.values()) - a.score) < 0.2
    assert set(a.components) == set(CFG.weights.as_dict())
    heavy, _ = config_from_mapping({"weights": {"timeliness": 90}})
    assert evaluate(s, heavy, TABLE, NOW + timedelta(hours=72)).score < a.score


def test_unchanged_story_is_not_recalculated_and_changes_are_diffed() -> None:
    s = story(item("Widget flaw", "BleepingComputer"))
    first = evaluate(s, CFG, TABLE, NOW)
    assert evaluate(s, CFG, TABLE, NOW + timedelta(minutes=20), previous=first) is first
    s.sheets = [FactSheet(summary="x", exploitation_status="confirmed")]
    second = evaluate(s, CFG, TABLE, NOW + timedelta(minutes=20), previous=first)
    assert second is not first
    assert any("exploitation_status" in c for c in second.changes)


# ---------------------------------------------------------------- Top 10

def _evals(stories: list[StoryView]) -> dict[str, Any]:
    return {s.key: evaluate(s, CFG, TABLE, NOW) for s in stories}


def test_top10_threshold_dedup_and_determinism() -> None:
    strong = story(item("CISA warns Widget flaw CVE-2026-1111 exploited", "CISA Alerts",
                        body="Known Exploited Vulnerabilities catalog: CVE-2026-1111 actively exploited. " * 4),
                   key="s:a", level="Critical",
                   sheets=[FactSheet(summary="x", cve_ids=["CVE-2026-1111"], exploitation_status="confirmed")])
    same_cve = story(item("Widget CVE-2026-1111 attacks spread", "The Hacker News"), key="s:b",
                     level="Critical", sheets=[FactSheet(summary="x", cve_ids=["CVE-2026-1111"])])
    weak = story(item("Minor UI bug fixed", "dou.ua", score=5, audiences=["developers"]),
                 key="s:c", level="Low", actions=False)
    stories = [strong, same_cve, weak]
    day, picks, rejected = daily_top(stories, _evals(stories), NOW, CFG)
    assert [p.story_key for p in picks] == ["s:a"]                  # fewer than 10 is fine
    reasons = {r["story_key"]: r["reason"] for r in rejected}
    assert reasons["s:b"].startswith("same event")
    assert "threshold" in reasons["s:c"]
    assert daily_top(stories, _evals(stories), NOW, CFG)[1] == picks   # deterministic


def test_edition_cutoff_respects_timezone() -> None:
    # 06:00 Kyiv cutoff (UTC+2 in November): 03:30 UTC is 05:30 local → today's edition,
    # 04:30 UTC is 06:30 local → tomorrow's.
    d1, _, _ = edition_for(datetime(2026, 11, 3, 3, 30, tzinfo=timezone.utc), CFG)
    d2, _, _ = edition_for(datetime(2026, 11, 3, 4, 30, tzinfo=timezone.utc), CFG)
    assert (d1.isoformat(), d2.isoformat()) == ("2026-11-03", "2026-11-04")


def test_editions_are_preserved_and_revised_on_new_evidence(tmp_path: Path) -> None:
    a = item("Widget exploited", "CISA Alerts", body="Known Exploited Vulnerabilities: CVE-2026-1 exploited. " * 4)
    res1 = run([a], now=NOW, intel_dir=tmp_path)
    edition = tmp_path / "editions" / f"{res1.edition}.json"
    assert edition.exists()
    b = item("Widget exploitation spreads to banks", "BleepingComputer", hours_ago=1,
             body="Banks hit through CVE-2026-1, according to new research by the team. " * 5)
    run([a, b], now=NOW + timedelta(hours=1), intel_dir=tmp_path)
    import json
    data = json.loads(edition.read_text())
    assert data["edition"] == res1.edition
    assert data["revisions"]                              # the earlier version is kept


# ---------------------------------------------------------------- Trending

def test_trending_needs_signals_not_article_count() -> None:
    body = "Widget servers are under attack in the wild. " * 8
    copies = story(*[replace(item("Widget attacked", s, body=body), raw_content=body)
                     for s in ("BleepingComputer", "The Hacker News", "SecurityWeek")], key="s:copies",
                   level="Medium", actions=False)
    copies.independent_sources = _fallback_independent(copies.members)
    assert copies.independent_sources == ["BleepingComputer"]
    res = trending([copies], _evals([copies]), NOW, CFG)
    assert "corroboration" not in res[0].signals


def test_trending_window() -> None:
    old = story(item("Old Widget flaw exploited in the wild", "BleepingComputer", hours_ago=40), key="s:old")
    assert trending([old], _evals([old]), NOW, CFG) == []
    narrow, _ = config_from_mapping({"trending": {"window_hours": 1}})
    recent = story(item("Widget flaw exploited in the wild", "BleepingComputer", hours_ago=2), key="s:r")
    assert trending([recent], _evals([recent]), NOW, narrow) == []


# ---------------------------------------------------------------- Breaking

def _critical_exploited(official: bool) -> StoryView:
    src = "CISA Alerts" if official else "dev.ua"
    return story(item("Widget CVE-2026-1111 exploited, patch now", src,
                      body="Known Exploited Vulnerabilities catalog entry: CVE-2026-1111 is actively exploited. " * 4),
                 key="s:brk", level="Critical",
                 sheets=[FactSheet(summary="x", exploitation_status="confirmed", cvss_scores=[CvssScore(score=9.8)])])


def test_breaking_requires_evidence_and_never_unverified() -> None:
    s = _critical_exploited(official=True)
    d = classify_breaking(s, evaluate(s, CFG, TABLE, NOW), TABLE, CFG, NOW)
    assert d.qualifies and "R1 critical_exploited" in d.rules
    rumour = story(item("Hackers claim to have breached Widget, leak alleged", "dev.ua"), key="s:rum",
                   level="Critical")
    r = classify_breaking(rumour, evaluate(rumour, CFG, TABLE, NOW), TABLE, CFG, NOW)
    assert not r.qualifies


def test_breaking_alerts_once_and_again_only_on_material_change() -> None:
    s = _critical_exploited(official=True)
    state: dict[str, Any] = {}
    first = apply_alert_state(classify_breaking(s, evaluate(s, CFG, TABLE, NOW), TABLE, CFG, NOW), state, NOW)
    assert first.alert == "new"
    again = apply_alert_state(classify_breaking(s, evaluate(s, CFG, TABLE, NOW), TABLE, CFG, NOW), state, NOW)
    assert again.alert == "unchanged"
    s.members.append(item("Widget exploitation confirmed by vendor", "BleepingComputer", hours_ago=1,
                          body="Independent confirmation with new victims and indicators. " * 5))
    s.independent_sources = _fallback_independent(s.members)
    upd = apply_alert_state(classify_breaking(s, evaluate(s, CFG, TABLE, NOW), TABLE, CFG, NOW), state, NOW)
    assert upd.alert == "update"


def test_out_of_scope_never_ranks() -> None:
    s = _critical_exploited(official=True)
    s.relevance = "out_of_scope"
    evs = _evals([s])
    assert daily_top([s], evs, NOW, CFG)[1] == []
    assert trending([s], evs, NOW, CFG) == []
    assert not classify_breaking(s, evs[s.key], TABLE, CFG, NOW).qualifies


@pytest.mark.parametrize("bad", ["", "{not json", "[]"])
def test_bad_config_falls_back_to_defaults(tmp_path: Path, bad: str) -> None:
    from cyberalertx.intel.config import load_config
    p = tmp_path / "config.json"
    p.write_text(bad)
    assert load_config(p) == IntelConfig()


# ---------------------------------------------------------------- admin visibility

def test_admin_intel_is_token_locked_and_shows_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    from fastapi.testclient import TestClient

    from cyberalertx.api.admin import AdminGuard
    from cyberalertx.api.app import build_app
    import cyberalertx.intel.engine as engine

    token = "t" * 48
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", token)
    monkeypatch.setattr(engine, "INTEL_DIR", tmp_path)
    monkeypatch.setattr(engine.load_latest, "__defaults__", (tmp_path,))
    monkeypatch.setattr(engine.load_scores, "__defaults__", (tmp_path,))
    s = _critical_exploited(official=True)
    run(s.members, now=NOW, intel_dir=tmp_path)

    client = TestClient(build_app(feedback_path=tmp_path / "f.jsonl", admin_guard=AdminGuard()))
    for path in ("/admin/intel", "/admin/intel.json"):
        assert client.get(path).status_code == 401                 # never public
    auth = {"Authorization": "Basic " + base64.b64encode(f"ed:{token}".encode()).decode(),
            "X-Real-IP": "203.0.113.9"}
    html = client.get("/admin/intel", headers=auth)
    assert html.status_code == 200 and "Daily Top 10" in html.text
    assert "<script" not in html.text.lower()
    data = client.get("/admin/intel.json", headers=auth).json()
    assert data["latest"]["top"] and data["scores"]
    # Nothing from the intelligence layer leaks into public responses.
    public = client.get("/posts?limit=5").json()
    for post in public["items"]:
        assert not {"selection_score", "importance", "confidence", "verification_status"} & set(post)


def test_build_stories_uses_cluster_evidence_for_contradictions() -> None:
    from types import SimpleNamespace

    from cyberalertx.intel.story import build_stories

    a = item("Widget gateway flaw CVE-2026-2222 exploited in attacks", "BleepingComputer",
             body="Attackers exploit CVE-2026-2222 in Widget gateways, BleepingComputer has learned. " * 5)
    b = item("Widget gateway CVE-2026-2222 patched", "SecurityWeek", hours_ago=1,
             body="Widget released a fix for CVE-2026-2222; the vendor says it has seen no attacks. " * 5)
    sheets = {
        a.fingerprint: FactSheet(summary="x", cve_ids=["CVE-2026-2222"], exploitation_status="confirmed"),
        b.fingerprint: FactSheet(summary="y", cve_ids=["CVE-2026-2222"], exploitation_status="not_reported"),
    }

    class _Sheets:
        def get(self, fp: str) -> Any:
            return SimpleNamespace(sheet=sheets[fp]) if fp in sheets else None

    [s] = [s for s in build_stories([a, b], sheets=_Sheets()) if len(s.members) == 2]
    assert s.evidence is not None and s.evidence.contradictions
    assert any("contradictions" in r for r in confidence(s, TABLE).reasons)
