"""Threads event-level deduplication (threads/events.py + planning/claim guards):
one initial post per cybersecurity event and account, across story keys,
outlets and headlines; substantive developments still get a post."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from cyberalertx.models import NewsItem
from cyberalertx.publish.jobs import JobStore
from cyberalertx.publish.orchestrator import PublishPolicy, plan, run
from cyberalertx.threads import events as EV
from tests.test_publication import FakeSource, settings, view
from tests.test_threads import NOW, ASSET, FakeThreads, both, tdest

FIX = json.loads((Path(__file__).parent / "fixtures" / "threads_events_2026_11.json").read_text())


def news(title: str, lead: str = "", *, at: datetime = NOW - timedelta(hours=2), source: str = "BleepingComputer",
         key: str = "", lang: str = "en") -> NewsItem:
    it = NewsItem(title=title, source=source, url=f"https://e.test/{abs(hash((title, source)))}", published_at=at,
                  raw_content=lead, language=lang, source_tier="trusted")
    it.story_key = key or f"s:{abs(hash((title, source))) % 10**12:012d}"
    return it


def real(name: str, *, shift: timedelta = timedelta(0)) -> NewsItem:
    f = FIX[name]
    at = datetime.fromisoformat(f["published_at"])
    return news(f["title"], f["lead"], at=at + shift, source=f["source"], key=f"s:{name}")


def sig(it: NewsItem) -> dict[str, Any]:
    return EV.signature({"translations": {"en": {"title": it.title}}}, it)


def same(a: NewsItem, b: NewsItem) -> bool:
    return EV.same_event(sig(a), sig(b))


# ---------------------------------------------------------------- real pairs from the replay (Nov 2026)

@pytest.mark.parametrize("first,second", [
    ("roller_bc", "roller_thn"),                   # same event, different headlines and publishers
    ("optimizely_bc", "optimizely_krebs"),
    ("pt_bc", "pt_krebs"), ("pt_bc", "pt_thn"),   # Patch Tuesday, three outlets
    ("broadworks_thn", "broadworks_bc"),
    ("http2_thn", "http2_bc"),                     # the first article already reports the fix
    ("kev_two", "unrealircd_thn"),                 # the KEV post already named the exploited CVE
])
def test_the_same_event_from_another_outlet_is_one_event(first: str, second: str) -> None:
    a, b = real(first), real(second)
    assert same(a, b)
    assert EV.update_reason(sig(a), sig(b)) == "", "a new headline or outlet is not an update"


@pytest.mark.parametrize("first,second", [
    ("http2_thn", "nginx_thn"),                    # HTTP/2 in two different servers
    ("checkpoint_php2shell", "checkpoint_zeroday"),  # same vendor, not clearly one event: kept apart
    ("broadworks_thn", "kev_two"),                 # two KEV additions, different CVEs
    ("roller_bc", "kev_four"),                     # the KEV list adds CVEs the Roller post did not cover
    ("pt_bc", "broadworks_thn"),
])
def test_distinct_events_are_never_merged(first: str, second: str) -> None:
    assert not same(real(first), real(second))


def test_the_same_event_outside_the_window_is_not_suppressed() -> None:
    assert not same(real("roller_bc"), real("roller_thn", shift=EV.EVENT_WINDOW + timedelta(hours=1)))


# ---------------------------------------------------------------- vendors and CVEs

def test_same_vendor_different_incidents_stay_distinct() -> None:
    a = news("Microsoft November 2026 Patch Tuesday fixes 1,235 flaws, Outlook zero-day")
    b = news("Attackers compromise Microsoft's Agent Framework PyPI package to steal cloud credentials")
    c = news("Microsoft confirms breach of employee email accounts by state hackers")
    assert not same(a, b) and not same(a, c) and not same(b, c)


def test_same_vendor_different_cves_stay_distinct() -> None:
    a = news("Apache Roller RCE flaw CVE-2026-129448 exploited in attacks")
    b = news("Apache Tomcat flaw CVE-2026-130001 exploited in attacks")
    assert not same(a, b)


def test_a_catalog_adding_new_cves_is_not_covered_by_one_of_them() -> None:
    one = news("Apache Roller flaw CVE-2026-129448 exploited in attacks")
    kev = news("CISA adds four known exploited vulnerabilities to catalog",
               "CVE-2026-129448 Apache Roller; CVE-2026-90436 LiteLLM; CVE-2026-90817 REDCap; CVE-2024-10441 Synology")
    assert not EV.same_event(sig(one), sig(kev))         # new CVEs: a new post
    assert EV.same_event(sig(kev), sig(one))             # the reverse: the catalog covered Roller


# ---------------------------------------------------------------- substantive updates

@pytest.mark.parametrize("first,later,reason", [
    (("Critical Apache Roller RCE flaw CVE-2026-129448 disclosed", "A flaw was disclosed."),
     ("Apache Roller flaw CVE-2026-129448 now exploited in attacks", "Attackers are exploiting it."),
     "exploitation"),
    (("Ransomware gang claims breach of Acme Bank", "The gang claims it stole data."),
     ("Acme Bank confirms data breach after ransomware attack", "Acme Bank confirmed the breach."),
     "breach confirmed"),
    (("Critical Zoom Workplace flaw CVE-2026-140001 has no fix yet", "No patch is available."),
     ("Zoom patches Workplace flaw CVE-2026-140001", "Zoom released a fix."), "patch"),
    (("Acme Health ransomware breach exposes 10,000 patients", ""),
     ("Acme Health ransomware breach now affects 250,000 patients", ""), "more affected"),
])
def test_substantive_developments_are_updates(first: tuple[str, str], later: tuple[str, str], reason: str) -> None:
    a = news(*first, at=NOW - timedelta(hours=20))
    b = news(*later, at=NOW - timedelta(hours=2))
    assert same(a, b), (sig(a), sig(b))
    assert reason in EV.update_reason(sig(a), sig(b))


def test_an_arrest_is_a_development_of_a_ransomware_story() -> None:
    a = news("Akira ransomware hits Contoso hospitals", at=NOW - timedelta(hours=30))
    b = news("Police arrest Akira ransomware suspects over Contoso hospitals attack")
    s_a, s_b = sig(a), sig(b)
    # Different event kinds: the arrest is never suppressed as a repeat of the attack.
    assert not EV.same_event(s_a, s_b) or "law-enforcement" in EV.update_reason(s_a, s_b)


# ---------------------------------------------------------------- planning and sending

def _world(tmp_path: Path, items: list[NewsItem], api: FakeThreads, *, level: str = "Critical",
           ua: dict[str, str] | None = None) -> tuple[JobStore, FakeSource, dict[str, Any]]:
    pays: dict[tuple[str, str], dict[str, Any]] = {}
    for it in items:
        for loc in ("en", "ua"):
            pays[(it.fingerprint, loc)] = {
                "id": it.fingerprint, "source": it.source, "source_url": it.url, "threat_level": level,
                "actionability_level": "", "category": "vulnerability", "published_at": it.published_at.isoformat(),
                "available_locales": ["en", "ua"],
                "translations": {loc: {"title": (ua or {}).get(it.fingerprint, it.title) if loc == "ua" else it.title,
                                       "short_summary": "s", "plain_summary": "p"}},
                "media": {"illustration": {"asset_id": ASSET, "alt": {"en": "Illustration.", "ua": "Ілюстрація."}}}}
    src = FakeSource(items, pays)
    accounts = both(tmp_path, api)
    d = {"threads@en": tdest("en", accounts, api), "threads@ua": tdest("ua", accounts, api)}
    return JobStore(tmp_path / "jobs.json"), src, d


def _plan(store: JobStore, src: FakeSource, d: dict[str, Any], items: list[NewsItem], now: datetime = NOW) -> Any:
    return plan(src, store, now=now, settings=settings(channels={}), destinations=d, view=view(*items),
                policy=PublishPolicy(threads_per_run=5))


def _go(store: JobStore, src: FakeSource, d: dict[str, Any], now: datetime = NOW) -> Any:
    return run(src, store, d, now=now, clock=lambda: now, rng=lambda: 0.5, policy=PublishPolicy(threads_per_run=5))


def _threads(store: JobStore) -> dict[str, str]:
    return {j.job_id: j.status for j in store.all() if j.destination.startswith("threads@")}


def test_planning_keeps_the_first_report_and_skips_the_same_event_per_account(tmp_path: Path) -> None:
    api = FakeThreads()
    a = news(FIX["roller_bc"]["title"], FIX["roller_bc"]["lead"], at=NOW - timedelta(hours=6), key="s:a")
    b = news(FIX["roller_thn"]["title"], FIX["roller_thn"]["lead"], at=NOW - timedelta(hours=2),
             source="The Hacker News", key="s:b")
    store, src, d = _world(tmp_path, [a, b], api)
    res = _plan(store, src, d, [a, b])
    assert set(_threads(store)) == {"s:a:en:threads@en:initial", "s:a:ua:threads@ua:initial"}  # both accounts
    assert sum("same event as s:a" in s["reason"] for s in res.skipped) == 2
    _go(store, src, d)
    assert len(api.posts) == 2 and {p["user"] for p in api.posts} == {"111", "222"}   # one per account
    _plan(store, src, d, [a, b], now=NOW + timedelta(hours=2))                       # later runs: still skipped
    _go(store, src, d, now=NOW + timedelta(hours=2))
    assert len(api.posts) == 2


def test_ua_edition_of_a_ukrainian_outlet_about_the_same_event_is_one_event(tmp_path: Path) -> None:
    api = FakeThreads()
    a = news("Apache warns of Roller RCE vulnerability CVE-2026-129448 exploited in attacks",
             at=NOW - timedelta(hours=6), key="s:a")
    b = news("Хакери атакують Apache Roller через вразливість CVE-2026-129448", at=NOW - timedelta(hours=2),
             source="ITC.ua", key="s:b", lang="ua")
    store, src, d = _world(tmp_path, [a, b], api)
    _plan(store, src, d, [a, b])
    assert set(_threads(store)) == {"s:a:en:threads@en:initial", "s:a:ua:threads@ua:initial"}


def test_pending_and_published_jobs_block_cancelled_and_failed_do_not(tmp_path: Path) -> None:
    api = FakeThreads()
    a = news("Apache Roller flaw CVE-2026-129448 exploited in attacks", at=NOW - timedelta(hours=6), key="s:a")
    b = news("Hackers exploit Apache Roller flaw CVE-2026-129448 in attacks", at=NOW - timedelta(hours=2),
             source="The Hacker News", key="s:b")
    store, src, d = _world(tmp_path, [a], api)
    _plan(store, src, d, [a])                                          # a pending
    src2 = FakeSource([a, b], {**src.payloads, **_world(tmp_path / "x", [b], FakeThreads())[1].payloads})
    _plan(store, src2, d, [a, b])
    assert not any(k.startswith("s:b") for k in _threads(store))       # pending a blocks b
    for jid in list(_threads(store)):                                   # a never posted (failed gate)
        store.update(jid, lambda j: setattr(j, "status", "failed"), NOW)
    _plan(store, src2, d, [a, b])
    assert any(k.startswith("s:b") for k in _threads(store))           # now b may go


def _race(store: JobStore, src: FakeSource, d: dict[str, Any], a: NewsItem, b: NewsItem, tmp: Path) -> None:
    """Two planners that both read the store before either wrote: one plans a, one plans b."""
    _plan(store, FakeSource([a], src.payloads), d, [a])
    other = JobStore(tmp / "other_planner.json")
    _plan(other, FakeSource([b], src.payloads), d, [b])
    store.add_missing(other.all(), NOW)


def test_concurrent_planners_cannot_both_send_one_event(tmp_path: Path) -> None:
    """Two planners each saw only one article: both jobs exist; the claim guard
    (inside the job-store lock) lets one through and cancels the other."""
    api = FakeThreads()
    a = news("Apache Roller flaw CVE-2026-129448 exploited in attacks", at=NOW - timedelta(hours=6), key="s:a")
    b = news("Hackers exploit Apache Roller flaw CVE-2026-129448 in attacks", at=NOW - timedelta(hours=2),
             source="The Hacker News", key="s:b")
    store, src, d = _world(tmp_path, [a, b], api)
    _race(store, src, d, a, b, tmp_path)
    assert len(_threads(store)) == 4                                    # the race produced both
    _go(store, src, d)
    _go(store, src, d, now=NOW + timedelta(hours=2))
    assert len(api.posts) == 2 and len({p["user"] for p in api.posts}) == 2
    cancelled = [j for j in store.all() if j.status == "cancelled" and j.destination.startswith("threads@")]
    assert len(cancelled) == 2 and all("same event as" in j.last_error for j in cancelled)


def test_an_uncertain_send_blocks_the_same_event(tmp_path: Path) -> None:
    api = FakeThreads()
    a = news("Apache Roller flaw CVE-2026-129448 exploited in attacks", at=NOW - timedelta(hours=6), key="s:a")
    b = news("Hackers exploit Apache Roller flaw CVE-2026-129448 in attacks", at=NOW - timedelta(hours=2),
             source="The Hacker News", key="s:b")
    store, src, d = _world(tmp_path, [a, b], api)
    _race(store, src, d, a, b, tmp_path)
    for j in store.all():
        if j.story_key == "s:a":
            store.update(j.job_id, lambda x: setattr(x, "status", "outcome_unknown"), NOW)
    _go(store, src, d)
    assert api.posts == []                                              # maybe-sent a: b is never sent
    b_threads = [j for j in store.all() if j.story_key == "s:b" and j.destination.startswith("threads@")]
    assert b_threads and all(j.status == "cancelled" and "already sent" in j.last_error for j in b_threads)
    assert all(j.status == "scheduled" for j in store.all() if j.story_key == "s:b" and j.destination == "website")


def test_a_substantive_update_is_planned_with_its_reason(tmp_path: Path) -> None:
    api = FakeThreads()
    a = news("Critical Apache Roller RCE flaw CVE-2026-129448 disclosed", "A flaw was disclosed.",
             at=NOW - timedelta(hours=20), key="s:a")
    b = news("Apache Roller flaw CVE-2026-129448 now exploited in attacks", "Attackers are exploiting it.",
             at=NOW - timedelta(hours=2), source="The Hacker News", key="s:b")
    store, src, d = _world(tmp_path, [a, b], api)
    _plan(store, src, d, [a, b])
    jobs = {j.job_id: j for j in store.all() if j.destination == "threads@en"}
    assert set(jobs) == {"s:a:en:threads@en:initial", "s:b:en:threads@en:initial"}
    assert any("event update: exploitation" in r for r in jobs["s:b:en:threads@en:initial"].reasons)


def test_distinct_events_both_get_their_post(tmp_path: Path) -> None:
    api = FakeThreads()
    a = real("http2_thn", shift=NOW - datetime.fromisoformat(FIX["http2_thn"]["published_at"]) - timedelta(hours=6))
    b = real("nginx_thn", shift=NOW - datetime.fromisoformat(FIX["nginx_thn"]["published_at"]) - timedelta(hours=2))
    store, src, d = _world(tmp_path, [a, b], api)
    _plan(store, src, d, [a, b])
    assert len(_threads(store)) == 4


# ---------------------------------------------------------------- not editorial news

@pytest.mark.parametrize("title,lead", [
    ("Hackers Found a Way Around GitHub SHA Pinning. This Webinar Explains How to Close the Gap", ""),
    ("⚡ Weekly Recap: N-able 0-Days, Windows 0-Days, Chrome 0-Days, and More", ""),
    ("ThreatsDay: 59 Linux Kernel Bugs, Falcon Spyware, GSocket Backdoors + 17 More Stories", ""),
    ("Your Endpoint Management Platform Could Be Your Biggest Security Risk", "Sponsored by Action1."),
    ("Inside Modern Phishing Kits Built to Steal Microsoft 365 Sessions", "Written by Huntress. Sponsored by Huntress Labs."),
])
def test_sponsored_webinars_and_roundups_are_not_threads_news(title: str, lead: str) -> None:
    assert EV.not_news({}, news(title, lead))


@pytest.mark.parametrize("name", list(FIX))
def test_real_news_is_never_classified_as_promotion(name: str) -> None:
    assert EV.not_news({}, real(name)) == ""


def test_promotional_pieces_are_skipped_for_threads_only(tmp_path: Path) -> None:
    api = FakeThreads()
    it = news("Hackers Found a Way Around GitHub SHA Pinning. This Webinar Explains How to Close the Gap", key="s:w")
    store, src, d = _world(tmp_path, [it], api)
    res = _plan(store, src, d, [it])
    assert _threads(store) == {} and any("not editorial news" in s["reason"] for s in res.skipped)


def test_jobs_without_a_signature_are_never_blocked() -> None:
    from cyberalertx.publish.jobs import PublicationJob
    from cyberalertx.publish.orchestrator import _event_conflict
    old = PublicationJob(job_id="x", story_key="s:x", fingerprint="f", locale="en", destination="threads@en",
                         status="published")
    new = PublicationJob(job_id="y", story_key="s:y", fingerprint="g", locale="en", destination="threads@en",
                         event=sig(news("Apache Roller flaw CVE-2026-129448 exploited")))
    assert _event_conflict(new, [old]) == ""
    assert _event_conflict(PublicationJob(job_id="t", story_key="s", fingerprint="f", locale="en",
                                          destination="telegram"), [old]) == ""
    _ = timezone


def test_claim_time_cancellations_are_in_the_run_report_and_the_job_history(tmp_path: Path) -> None:
    api = FakeThreads()
    a = news("Apache Roller flaw CVE-2026-129448 exploited in attacks", at=NOW - timedelta(hours=6), key="s:a")
    b = news("Hackers exploit Apache Roller flaw CVE-2026-129448 in attacks", at=NOW - timedelta(hours=2),
             source="The Hacker News", key="s:b")
    store, src, d = _world(tmp_path, [a, b], api)
    _race(store, src, d, a, b, tmp_path)
    _go(store, src, d)
    rep = _go(store, src, d, now=NOW + timedelta(hours=2))
    assert len(api.posts) == 2 and any("same event as" in c["reason"] for c in rep.cancelled)
    loser = next(c["job_id"] for c in rep.cancelled if c["job_id"].endswith(":en:threads@en:initial"))
    j = store.get(loser)
    assert j and j.history[-1]["event"] == "cancelled" and "same event" in j.history[-1]["reason"]
