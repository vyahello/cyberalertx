"""Canonical story identity across publishers and languages (RULE F), the
publication-level guarantee (one initial post per story, destination and
language), and the read-only duplicate audit. Fixtures are sanitized from the
16-17 Nov 2026 Google AI-attacks coverage that produced duplicate posts."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.dedup import StoryFeatures, cluster_items, match_story

T0 = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def item(url: str, source: str, title: str, body: str, *, hours: float = 0, lang: str = "en",
         category: str = "other", story_key: str = "") -> NewsItem:
    it = NewsItem(title=title, source=source, url=url, published_at=T0 + timedelta(hours=hours),
                  raw_content=body, language=lang, category=category)
    if story_key:
        it.story_key = story_key
    return it


BC = item("https://bleepingcomputer.test/google-ai", "BleepingComputer",
          "Google warns that fully-automated AI attacks are coming soon",
          "Threat actors are now relying on agentic workflows powered by AI-based offensive frameworks to "
          "automate vulnerability discovery and exploitation, accelerating attacks to machine speed.")
THN = item("https://thehackernews.test/google-agents", "The Hacker News",
           "Google Finds Hackers Using AI Agents to Build and Run Exploits From Software Patches",
           "Google on Monday revealed that adversarial use of artificial intelligence (AI) by threat actors has "
           "gone beyond manual prompting to deploying autonomous multi-agent offensive frameworks.")
ITC = item("https://itc.test/google-shi", "itc.ua",
           "Google попереджає про близькі повністю автоматизовані хакерські атаки на базі ШІ",
           "Google Threat Intelligence Group (GTIG) попереджає, що кіберзловмисники переходять до агентних робочих "
           "процесів на основі ШІ-фреймворків, які автоматизують пошук і експлуатацію вразливостей.",
           hours=2.5, lang="ua")
P0 = item("https://bleepingcomputer.test/project-zero", "BleepingComputer",
          "Google Project Zero cuts bug disclosure deadline amid AI threats",
          "Google Project Zero is shortening the time vendors get to fix reported vulnerabilities, citing faster "
          "exploitation driven by AI.", hours=7.5)


def F(it: NewsItem) -> StoryFeatures:
    return StoryFeatures.from_item(it)


# ------------------------------------------------------------------ story identity

def test_same_event_across_publishers_and_languages_is_one_story() -> None:
    clusters = cluster_items([BC, THN, ITC])
    assert len(clusters) == 1 and {m.fingerprint for m in clusters[0].members} == {
        BC.fingerprint, THN.fingerprint, ITC.fingerprint}
    d = match_story(F(BC), F(ITC))
    assert d is not None and d.rule == "rule_f_event" and d.confidence == "medium"


def test_rewritten_headlines_still_match() -> None:
    d = match_story(F(BC), F(THN))
    assert d is not None and d.confidence in ("high", "medium")


def test_same_vendor_different_event_is_only_a_review_link() -> None:
    d = match_story(F(ITC), F(P0))
    assert d is None or d.confidence == "low"                       # never merged
    assert all(len(c.members) == 1 or P0.fingerprint not in {m.fingerprint for m in c.members} or
               len(c.members) == 1 for c in cluster_items([ITC, P0]))
    assert len(cluster_items([ITC, P0])) == 2


def test_generic_trade_words_are_not_shared_names() -> None:
    a = item("https://a.test/1", "The Hacker News", "AntiFox AI Agents Linked to Cybersecurity Attacks on AWS",
             "Attackers used AI agents to steal credentials from AWS accounts.", category="malware")
    b = item("https://b.test/2", "dou.ua", "Шеймінг замість культури: Cybersecurity в епоху ШІ",
             "Колонка про культуру кібербезпеки та атаки з використанням ШІ-агентів і крадіжку облікових даних.",
             hours=3, lang="ua", category="other")
    d = match_story(F(a), F(b))
    assert d is None or d.confidence == "low"


def test_events_far_apart_in_time_stay_separate() -> None:
    later = item("https://itc.test/later", "itc.ua", ITC.title, ITC.raw_content, hours=24 * 6, lang="ua")
    assert len(cluster_items([BC, later])) == 2


def test_exact_url_duplicates_are_one_story() -> None:
    a = item("https://bleepingcomputer.test/x?utm_source=rss", "BleepingComputer", "Widget flaw exploited",
             "Attackers exploit Widget servers.")
    b = item("https://bleepingcomputer.test/x", "BleepingComputer", "Widget flaw exploited",
             "Attackers exploit Widget servers.", hours=0.1)
    assert len(cluster_items([a, b])) == 1


def test_same_cve_different_events_are_kept_apart() -> None:
    a = item("https://a.test/c1", "BleepingComputer", "Hackers exploit CVE-2026-1111 to breach Acme",
             "Acme confirmed attackers used CVE-2026-1111 against its VPN.", category="breach")
    b = item("https://b.test/c2", "The Hacker News", "CVE-2026-2222 exploited to breach Globex",
             "Globex says attackers used CVE-2026-2222.", hours=5, category="breach")
    assert len(cluster_items([a, b])) == 2


# ------------------------------------------------------------------ one post per story, destination, language

def _jobs(tmp_path: Path, jobs: list[dict[str, Any]]) -> Any:
    from cyberalertx.publish.jobs import JobStore, PublicationJob
    store = JobStore(tmp_path / "publish_jobs.json")
    store.add_missing([PublicationJob(**j) for j in jobs], T0)
    return store


def _job(story: str, fp: str, locale: str, dest: str, status: str) -> dict[str, Any]:
    return dict(job_id=f"{story}:{locale}:{dest}:initial", story_key=story, fingerprint=fp, locale=locale,
                destination=dest, publication_type="initial", status=status, members=[fp])


def test_pending_duplicate_of_a_published_story_is_cancelled_per_destination_and_language(tmp_path: Path) -> None:
    from cyberalertx.publish.orchestrator import IntelView, _supersede_story_duplicates
    store = _jobs(tmp_path, [
        _job("s:bc", BC.fingerprint, "ua", "telegram", "published"),
        _job("s:thn", THN.fingerprint, "ua", "telegram", "scheduled"),     # same story, same channel: cancel
        _job("s:thn", THN.fingerprint, "en", "telegram", "scheduled"),     # EN never posted: keep
        _job("s:thn", THN.fingerprint, "ua", "threads@ua", "scheduled"),   # other destination: keep
    ])
    view = IntelView(members={"s:bc": [BC.fingerprint, THN.fingerprint]})
    preview = _supersede_story_duplicates(store, view, T0, dry_run=True)
    assert [x["job_id"] for x in preview] == ["s:thn:ua:telegram:initial"]
    assert {j.job_id: j.status for j in store.all()}["s:thn:ua:telegram:initial"] == "scheduled"   # dry run
    _supersede_story_duplicates(store, view, T0, dry_run=False)
    st = {j.job_id: j.status for j in store.all()}
    assert st["s:thn:ua:telegram:initial"] == "cancelled"
    assert st["s:thn:en:telegram:initial"] == "scheduled" and st["s:thn:ua:threads@ua:initial"] == "scheduled"
    assert st["s:bc:ua:telegram:initial"] == "published"


def test_an_unknown_outcome_also_blocks_a_second_post(tmp_path: Path) -> None:
    from cyberalertx.publish.orchestrator import IntelView, _supersede_story_duplicates
    store = _jobs(tmp_path, [_job("s:bc", BC.fingerprint, "en", "telegram", "outcome_unknown"),
                             _job("s:thn", THN.fingerprint, "en", "telegram", "retrying")])
    _supersede_story_duplicates(store, IntelView(members={"s:x": [BC.fingerprint, THN.fingerprint]}), T0,
                                dry_run=False)
    assert {j.job_id: j.status for j in store.all()}["s:thn:en:telegram:initial"] == "cancelled"


# ------------------------------------------------------------------ historical audit

def test_duplicate_audit_reports_posts_and_changes_nothing(tmp_path: Path) -> None:
    from cyberalertx.storage.json_store import JsonNewsStore
    from cyberalertx.tools.stories import build_duplicate_audit
    for it, key in ((BC, "s:bc"), (THN, "s:thn"), (ITC, "s:itc")):
        it.story_key = key
    JsonNewsStore(tmp_path / "items.json").upsert_many([BC, THN, ITC])
    _jobs(tmp_path, [_job("s:bc", BC.fingerprint, "ua", "telegram", "published"),
                     _job("s:itc", ITC.fingerprint, "ua", "telegram", "published"),
                     _job("s:thn", THN.fingerprint, "ua", "telegram", "scheduled")])
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    audit = build_duplicate_audit(JsonNewsStore(tmp_path / "items.json").all(), tmp_path)
    assert len(audit["events_split_across_story_keys"]) == 1 and audit["with_duplicate_posts"] == 1
    ev = audit["events_split_across_story_keys"][0]
    assert len(ev["duplicate_posts"]["telegram:ua"]) == 2 and ev["pending_jobs"] == ["s:thn:ua:telegram:initial"]
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before     # read-only
    json.dumps(audit)                                                                   # serialisable
