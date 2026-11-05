"""End-to-end validation over the SYNTHETIC 12-scenario dataset
(tests/fixtures/e2e_dataset.py): ingestion → normalization → clustering →
relevance → fact sheets → intelligence → EN/UA editorial → review → media →
publication jobs → website / Telegram / Threads, plus failure injection.

Every external system is mocked: the AI provider returns fixed synthetic
answers, Telegram is httpx.MockTransport, Threads is the stateful fake from
tests/test_threads.py, the image provider is the Media Engine mock. All
stores live in tmp directories. No network, no paid call, no real channel.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from cyberalertx.ai.cache import ThreatPostCache
from cyberalertx.ai.fact_sheet import FactSheetCache, get_or_create_fact_sheet
from cyberalertx.ai.generator import ContentGenerator
from cyberalertx.ai.models import ThreatPostResponse
from cyberalertx.ai.review import apply_decision
from cyberalertx.api.app import _PostService
from cyberalertx.models import NewsItem
from cyberalertx.pipeline.orchestrator import Pipeline
from cyberalertx.pipeline.relevance import effective_relevance
from cyberalertx.sources.base import Source
from cyberalertx.storage.json_store import JsonNewsStore
from tests.fixtures.e2e_dataset import NOW, SPECS, SYNTHETIC, items

URL = "https://synthetic.test/"


def key_of(item: NewsItem) -> str:
    return item.url.removeprefix(URL)


class Static(Source):
    def __init__(self, name: str, batch: list[NewsItem], *, fail: bool = False) -> None:
        super().__init__(name)
        self.batch, self.fail = batch, fail

    def fetch(self) -> list[NewsItem]:
        if self.fail:
            raise ConnectionError("synthetic source outage")
        return [NewsItem.from_storage_dict(i.to_storage_dict()) for i in self.batch]       # fresh objects each fetch


def sources(*, fail: str = "") -> list[Source]:
    by: dict[str, list[NewsItem]] = {}
    for it in items():
        by.setdefault(it.source, []).append(it)
    return [Static(n, v, fail=(n == fail)) for n, v in by.items()]


# ---------------------------------------------------------------- mock AI (synthetic answers)

SHEETS: dict[str, dict[str, Any]] = {
    "kev_cisa": {"summary": f"{SYNTHETIC} CISA lists CVE-2026-50001 as exploited.", "event_type": "active_exploitation",
                 "cve_ids": ["CVE-2026-50001"], "cvss_scores": [{"score": 9.8, "cve_id": "CVE-2026-50001"}],
                 "affected_products": [{"vendor": "Widget", "product": "Widget Gateway", "versions": ["9.1"]}],
                 "exploitation_status": "confirmed", "patch_status": "available",
                 "claims": [{"statement": "Actively exploited", "attribution": "CISA", "status": "confirmed"}],
                 "evidence": [{"claim": "CVE-2026-50001 is exploited", "source": "CISA Alerts", "primary": True,
                               "status": "confirmed", "excerpt": "after confirming active exploitation"}]},
    "kev_bc": {"summary": f"{SYNTHETIC} Attackers exploit CVE-2026-50001.", "event_type": "active_exploitation",
               "cve_ids": ["CVE-2026-50001", "CVE-2026-59999"],                # second id is NOT in the source
               "cvss_scores": [{"score": 9.8}],                                 # not in this source either
               "affected_products": [{"vendor": "Widget", "product": "Widget Gateway", "versions": ["9.1"]}],
               "exploitation_status": "confirmed", "patch_status": "available"},
    "umbrella_a": {"summary": f"{SYNTHETIC} Hackers claim an Umbrella Corp breach.", "event_type": "breach",
                   "organizations": ["Umbrella Corp"],
                   "claims": [{"statement": "5 million records stolen", "attribution": "hacking group",
                               "status": "unverified"}],
                   "open_questions": ["Whether the records are new"]},
    "umbrella_b": {"summary": f"{SYNTHETIC} Umbrella Corp denies the breach.", "event_type": "breach",
                   "organizations": ["Umbrella Corp"],
                   "claims": [{"statement": "Systems were not breached", "attribution": "Umbrella Corp",
                               "status": "contradictory"}],
                   "contradictions": [{"statement": "Hackers claim a breach; Umbrella Corp denies it",
                                       "sources": ["SecurityWeek"]}]},
    "grid_claim": {"summary": f"{SYNTHETIC} Unconfirmed claim of a grid breach.", "event_type": "breach",
                   "claims": [{"statement": "Grid control systems breached", "attribution": "hacker group",
                               "status": "unverified"}],
                   "open_questions": ["Which operator", "Whether any access was real"]},
}


def _resp(locale: str, story: str, **over: Any) -> ThreatPostResponse:
    en = {
        "kev": dict(title="Hackers hijack Widget Gateway devices through CVE-2026-50001",
                    short_summary="Attackers exploit CVE-2026-50001 in Widget Gateway; version 9.2 fixes it.",
                    plain_summary="If you run Widget Gateway, update it now: attackers already break in.",
                    why_it_matters="An exposed gateway lets attackers into the network behind it.",
                    affected_users=["Widget Gateway administrators"], what_to_do=["Upgrade Widget Gateway to 9.2."],
                    quick_facts=["CVE-2026-50001", "Fixed in 9.2"]),
        "ransom": dict(title="Ransomware forces Northwind Hospital to divert ambulances",
                       short_summary="A LockFox ransomware attack encrypted Northwind Hospital scheduling systems.",
                       plain_summary="A hospital had to send ambulances elsewhere after hackers locked its systems.",
                       why_it_matters="Ransomware at hospitals delays care for patients.",
                       affected_users=["Northwind Hospital patients"], what_to_do=["Keep offline backups."],
                       quick_facts=["LockFox ransomware"]),
    }[story]
    ua = {
        "kev": dict(title="Хакери захоплюють пристрої Widget Gateway через CVE-2026-50001",
                    short_summary="Зловмисники використовують CVE-2026-50001 у Widget Gateway; версія 9.2 її виправляє.",
                    plain_summary="Якщо у вас Widget Gateway, оновіть його зараз: зловмисники вже проникають усередину.",
                    why_it_matters="Відкритий шлюз пускає зловмисників у мережу за ним.",
                    affected_users=["Адміністратори Widget Gateway"], what_to_do=["Оновіть Widget Gateway до 9.2."],
                    quick_facts=["CVE-2026-50001", "Виправлено у 9.2"]),
        "ransom": dict(title="Через програму-вимагача лікарня Northwind перенаправляє швидкі",
                       short_summary="Атака LockFox зашифрувала системи запису пацієнтів у лікарні Northwind.",
                       plain_summary="Лікарні довелося відправляти швидкі деінде, бо хакери заблокували її системи.",
                       why_it_matters="Атаки на лікарні затримують допомогу пацієнтам.",
                       affected_users=["Пацієнти лікарні Northwind"], what_to_do=["Зберігайте резервні копії офлайн."],
                       quick_facts=["Програма-вимагач LockFox"]),
    }[story]
    base: dict[str, Any] = dict(threat_level="Critical" if story == "kev" else "High", what_not_to_do=[],
                                emotional_weight=0.6, reading_time_seconds=20, **(ua if locale == "ua" else en))
    base.update(over)
    return ThreatPostResponse(**base)


@dataclass
class MockAI:
    """Synthetic provider. Fact sheets by article; briefs by story and locale."""
    name: str = "mock:e2e"
    timeout_posts: bool = False
    bad_identifier: bool = False
    post_calls: list[tuple[str, str]] = field(default_factory=list)
    json_calls: list[str] = field(default_factory=list)

    def generate_json(self, system: str, user: str, *, schema: dict[str, Any]) -> dict[str, Any]:
        key = next((s.key for s in SPECS if s.title in user), "")
        self.json_calls.append(key)
        if key not in SHEETS:
            raise RuntimeError("synthetic: no sheet for this article")
        return dict(SHEETS[key])

    def generate_post(self, system: str, user: str) -> ThreatPostResponse:
        locale = "ua" if "OUTPUT_LANGUAGE: ua" in system else "en"
        self.post_calls.append((locale, user))
        if self.timeout_posts:
            raise TimeoutError("synthetic provider timeout")
        story = "kev" if "Widget Gateway" in user else "ransom"
        if self.bad_identifier:
            return _resp(locale, story, short_summary="Attackers exploit CVE-2026-50001 and CVE-2026-58888 "
                                                      "in Widget Gateway; 9.2 fixes it.")
        return _resp(locale, story)


class Svc(_PostService):
    def __init__(self, store: JsonNewsStore, cache: ThreatPostCache) -> None:
        self._store = store
        self._generator = ContentGenerator(provider=None, cache=cache)

    def list_items(self) -> list[NewsItem]:
        return self._store.all()


# ---------------------------------------------------------------- the world

@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from cyberalertx.observability import metrics, source_health
    tmp = tmp_path_factory.mktemp("e2e")
    metrics._reset_singleton_for_tests(tmp / "qm.json")
    source_health._reset_singleton_for_tests(tmp / "sh.json")
    repo = JsonNewsStore(tmp / "items.json")
    result = Pipeline(sources(), repo, stories_dir=tmp / "stories").run_once()
    stored = {key_of(i): i for i in repo.all()}
    sheets = FactSheetCache(tmp / "fact_sheets.json")
    ai = MockAI()
    for it in stored.values():
        get_or_create_fact_sheet(ai, it, sheets)
    posts = ThreatPostCache(tmp / "threat_posts.json")
    gen = ContentGenerator(provider=ai, cache=posts, fact_sheets=sheets)
    kev_anchor = next(i for k, i in stored.items() if k.startswith("kev") and not i.duplicate_of)
    for loc in ("en", "ua"):
        gen.generate(kev_anchor, language=loc)
        gen.generate(stored["ransom"], language=loc)
    return {"tmp": tmp, "repo": repo, "result": result, "stored": stored, "sheets": sheets, "posts": posts,
            "ai": ai, "kev": kev_anchor, "svc": Svc(repo, posts)}


def intel(world: dict[str, Any], *, write: bool = False, its: list[NewsItem] | None = None, now: Any = NOW) -> Any:
    from cyberalertx.intel.engine import run
    return run(its or world["repo"].all(), now=now, sheets=world["sheets"], posts=world["posts"],
               write=write, intel_dir=world["tmp"] / "intel")


def story_of(res: Any, key: str) -> Any:
    return next(s for s in res.stories if any(key_of(m) == key for m in s.members))


# ---------------------------------------------------------------- 5.1 ingestion

def test_ingestion_records_dates_urls_and_drops_non_security(world: dict[str, Any]) -> None:
    stored = world["stored"]
    assert set(stored) == {s.key for s in SPECS} - {"bakery"}           # irrelevant item never stored
    assert world["result"].fetched == 15 and world["result"].new == 14
    for s in SPECS:
        if s.key in stored:
            it = stored[s.key]
            assert it.url == URL + s.key and it.published_at == NOW - timedelta(hours=s.hours_ago)
            assert it.published_at.tzinfo is not None and it.source == s.source and it.language == "en"


def test_reingestion_creates_no_duplicates(world: dict[str, Any], tmp_path: Path) -> None:
    repo = JsonNewsStore(tmp_path / "items.json")
    Pipeline(sources(), repo, stories_dir=tmp_path / "s").run_once()
    again = Pipeline(sources(), repo, stories_dir=tmp_path / "s").run_once()
    assert again.new == 0 and len(repo.all()) == 14


def test_failed_source_neither_blocks_nor_corrupts(tmp_path: Path) -> None:
    repo = JsonNewsStore(tmp_path / "items.json")
    r = Pipeline(sources(fail="BleepingComputer"), repo, stories_dir=tmp_path / "s").run_once()
    assert r.new == 14 - sum(1 for s in SPECS if s.source == "BleepingComputer")
    before = (tmp_path / "items.json").read_text()
    r2 = Pipeline(sources(), repo, stories_dir=tmp_path / "s").run_once()   # outage over: recovers
    assert r2.new == sum(1 for s in SPECS if s.source == "BleepingComputer") and len(repo.all()) == 14
    assert json.loads(before)                                               # file was valid throughout


def test_crash_during_store_write_leaves_previous_data_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = JsonNewsStore(tmp_path / "items.json")
    Pipeline(sources(fail="The Hacker News"), repo, stories_dir=tmp_path / "s").run_once()
    good = (tmp_path / "items.json").read_bytes()

    def crash(*a: Any, **k: Any) -> None:
        raise OSError("synthetic: disk vanished mid-write")
    monkeypatch.setattr("cyberalertx.storage.json_store.os.replace", crash)
    with pytest.raises(OSError):
        Pipeline(sources(), repo, stories_dir=tmp_path / "s").run_once()
    assert (tmp_path / "items.json").read_bytes() == good                  # atomic: old file untouched
    monkeypatch.undo()
    r = Pipeline(sources(), JsonNewsStore(tmp_path / "items.json"), stories_dir=tmp_path / "s").run_once()
    assert r.new == sum(1 for s in SPECS if s.source == "The Hacker News") - 1   # bakery is THN, never stored


# ---------------------------------------------------------------- 5.2 clustering / 5.3 relevance

def test_same_event_clusters_and_unrelated_events_stay_apart(world: dict[str, Any]) -> None:
    s = world["stored"]
    assert s["kev_cisa"].story_key == s["kev_bc"].story_key                   # 7: same event
    assert sum(1 for k in ("kev_cisa", "kev_bc") if s[k].duplicate_of) == 1   # one canonical
    assert s["umbrella_a"].story_key == s["umbrella_b"].story_key             # 11: conflicting reports, one story
    assert s["ransom_city"].story_key != s["ransom_school"].story_key         # 8: similar, unrelated
    assert len({i.story_key for i in s.values()}) == 12


def test_outdated_story_beyond_window_is_a_new_story(world: dict[str, Any]) -> None:
    """KNOWN LIMIT (OPEN_ISSUES): matching is bounded by _WINDOW_DAYS = 5, so a
    development 6 days later becomes its own story rather than updating the old one."""
    s = world["stored"]
    assert s["old_vpn"].story_key != s["new_vpn"].story_key


def test_cluster_decisions_carry_confidence_and_overrides_correct_them(world: dict[str, Any], tmp_path: Path) -> None:
    res = intel(world)
    kev = story_of(res, "kev_bc")
    assert len(kev.members) == 2 and kev.decisions and all(d.get("confidence") for d in kev.decisions)
    assert len(kev.independent_sources) == 2
    # Correction with the existing override file (split): re-ingest keeps them apart.
    from cyberalertx.pipeline.dedup import cluster_items, load_story_overrides
    (tmp_path / "overrides.json").write_text(json.dumps(
        {"split": [{"fingerprint": world["stored"]["kev_cisa"].fingerprint, "reason": "e2e: wrong merge"}]}))
    ov = load_story_overrides(tmp_path / "overrides.json")
    clusters = cluster_items([world["stored"]["kev_cisa"], world["stored"]["kev_bc"]], overrides=ov)
    assert len(clusters) == 2


def test_relevance_is_stamped_and_out_of_scope_skips_generation(world: dict[str, Any], tmp_path: Path) -> None:
    assert all(effective_relevance(i) == "in_scope" for i in world["stored"].values())
    from cyberalertx.pipeline.relevance import is_renderable
    it = NewsItem.from_storage_dict(world["stored"]["phish"].to_storage_dict())
    it.relevance_override = "out_of_scope"
    assert not is_renderable(it) and effective_relevance(it) == "out_of_scope"
    it.relevance_override = "needs_review"
    assert effective_relevance(it) == "needs_review" and is_renderable(it)     # uncertain → review, still kept


# ---------------------------------------------------------------- 5.4 fact sheets

def test_fact_sheets_keep_identifiers_evidence_and_doubt(world: dict[str, Any]) -> None:
    sheets = world["sheets"]
    bc = sheets.get(world["stored"]["kev_bc"].fingerprint).sheet
    assert bc.cve_ids == ["CVE-2026-50001"]                         # invented CVE-2026-59999 dropped
    assert bc.cvss_scores == []                                      # 9.8 is not in this article
    cisa = sheets.get(world["stored"]["kev_cisa"].fingerprint).sheet
    assert [c.score for c in cisa.cvss_scores] == [9.8] and cisa.evidence[0].source == "CISA Alerts"
    res = intel(world)
    kev = story_of(res, "kev_bc")
    confirmed = {f.value for f in kev.evidence.confirmed()}
    assert "CVE-2026-50001" in confirmed                            # two independent origins
    um = story_of(res, "umbrella_a")
    assert um.evidence.contradictions                                # contradiction kept
    grid = story_of(res, "grid_claim")
    statuses = {c.status for s in grid.sheets for c in s.claims}
    assert statuses == {"unverified"} and "Which operator" in grid.sheets[0].open_questions
    assert not grid.evidence.confirmed()                             # unverified never becomes a fact
    assert sheets.get(world["stored"]["phish"].fingerprint).status == "failed"   # failure recorded, not faked


# ---------------------------------------------------------------- 5.5 intelligence

def test_intelligence_dimensions_and_selection(world: dict[str, Any]) -> None:
    res = intel(world)
    kev, grid = story_of(res, "kev_bc"), story_of(res, "grid_claim")
    ek, eg = res.evals[kev.key], res.evals[grid.key]
    assert ek.dim("exploitation_status") == "confirmed" and ek.dim("verification_status") == "verified"
    assert ek.score > eg.score and all(ek.reasons.get(k) for k in ek.components if ek.components[k] > 0)
    assert eg.dim("verification_status") == "unverified" and eg.dim("confidence") == "low"
    assert kev.key in {b["story_key"] for b in res.breaking}
    assert grid.key not in {b["story_key"] for b in res.breaking}   # low confidence never breaking
    assert grid.key not in {p["story_key"] for p in res.picks}
    nv = res.evals[story_of(res, "newvuln").key]
    assert nv.dim("exploitation_status") != "confirmed"


def test_ranking_is_deterministic_and_recalculates_on_new_evidence(world: dict[str, Any]) -> None:
    a, b = intel(world), intel(world)
    assert [p["story_key"] for p in a.picks] == [p["story_key"] for p in b.picks]
    assert {k: v.score for k, v in a.evals.items()} == {k: v.score for k, v in b.evals.items()}
    intel(world, write=True)
    extra = NewsItem(title="Acme Router CVE-2026-50002 now exploited, CISA warns", source="CISA Alerts",
                     url=URL + "newvuln_kev", published_at=NOW - timedelta(hours=1),
                     raw_content=f"CISA confirmed exploitation of CVE-2026-50002 in Acme Router 5.2. {SYNTHETIC}")
    its = world["repo"].all() + [extra]
    c = intel(world, write=True, its=its, now=NOW + timedelta(minutes=5))
    nv = story_of(c, "newvuln")
    assert len(nv.members) == 2
    scores = json.loads((world["tmp"] / "intel" / "scores.json").read_text())
    rec = scores[nv.key]
    assert rec["history"] and rec["current"]["changes"] != ["first evaluation"]


# ---------------------------------------------------------------- 5.6 editorial

def test_editions_are_independent_and_share_the_fact_sheet(world: dict[str, Any]) -> None:
    ai, posts, kev = world["ai"], world["posts"], world["kev"]
    en, ua = posts.get(kev.fingerprint, "en"), posts.get(kev.fingerprint, "ua")
    assert en.generated_by == ua.generated_by == "mock:e2e"
    assert en.language == "en" and ua.language == "ua" and en.title != ua.title
    assert "CVE-2026-50001" in en.short_summary and "CVE-2026-50001" in ua.short_summary
    calls = [(loc, u) for loc, u in ai.post_calls if "Widget Gateway" in u]
    assert {loc for loc, _ in calls} == {"en", "ua"}                # two separate generations, not a translation
    assert all("CVE-2026-50001" in u for _, u in calls)             # both prompts carry the shared facts
    assert world["ai"].json_calls.count("kev_bc") == 1             # one sheet per article, reused


def test_unsupported_identifier_is_rejected_and_fallback_is_not_cached(world: dict[str, Any], tmp_path: Path) -> None:
    posts = ThreatPostCache(tmp_path / "p.json")
    bad = ContentGenerator(provider=MockAI(bad_identifier=True), cache=posts, fact_sheets=world["sheets"])
    p = bad.generate(world["kev"], language="en")
    assert p.generated_by == "rule_based" and posts.get(world["kev"].fingerprint, "en") is None
    timeout = ContentGenerator(provider=MockAI(timeout_posts=True), cache=posts, fact_sheets=world["sheets"])
    assert timeout.generate(world["kev"], language="ua").generated_by == "rule_based"
    good = ContentGenerator(provider=MockAI(), cache=posts, fact_sheets=world["sheets"])
    assert good.generate(world["kev"], language="ua").generated_by == "mock:e2e"   # recovers next run


def test_review_decision_hides_only_that_edition(world: dict[str, Any], tmp_path: Path) -> None:
    import shutil
    cache = ThreatPostCache(tmp_path / "posts.json")
    shutil.copy(world["tmp"] / "threat_posts.json", tmp_path / "posts.json")
    cache = ThreatPostCache(tmp_path / "posts.json")
    apply_decision(cache, world["kev"].fingerprint, "ua", "reject", "admin:e2e")
    svc = Svc(world["repo"], cache)
    assert svc.render_if_cached(world["kev"], required_locale="ua") is None
    en = svc.render_if_cached(world["kev"], required_locale="en")
    assert en is not None and "ua" not in en["translations"] and en["source"] == world["kev"].source


# ---------------------------------------------------------------- 5.7 media

def test_cards_per_edition_and_every_public_story_gets_a_free_svg(world: dict[str, Any], tmp_path: Path) -> None:
    from cyberalertx.media import cards
    from cyberalertx.media.assets import MediaStore
    from cyberalertx.media.engine import illustration_payload, run as media_run
    from cyberalertx.media.illustrations import NoProvider
    payload = world["svc"].render(world["kev"])
    en, ua = cards.card_asset(payload, "en", "s"), cards.card_asset(payload, "ua", "s")
    assert en and ua and en.variants["og"] != ua.variants["og"]
    assert "/en/threat/" in en.public_url and "/ua/threat/" in ua.public_url
    assert en.variants == cards.card_asset(world["svc"].render(world["kev"]), "en", "s").variants   # stable
    assert ua.alt_text["ua"].endswith(f"«{payload['translations']['ua']['title']}»")
    store = MediaStore(tmp_path / "media")
    res = media_run(world["repo"].all(), store=store, sheets=world["sheets"], posts=world["posts"], now=NOW,
                    provider=NoProvider(), intel_dir=world["tmp"] / "intel")
    # No image service at all: the server-side SVG renderer still gives every
    # public story its one canonical illustration, at no cost.
    assert res.cards >= 4 and not res.failed and res.provider == "svg" and res.cost_usd == 0
    assert res.generated and set(res.generated) == set(res.eligible)
    block = illustration_payload(store, world["kev"].fingerprint)
    assert block and block["generated"] is True
    asset = next(a for a in store.all() if a.asset_type == "editorial_illustration")
    assert asset.generation_method == "svg" and asset.mime_type == "image/svg+xml"


def test_mock_illustration_for_the_breaking_story(world: dict[str, Any], tmp_path: Path) -> None:
    from cyberalertx.media.assets import MediaStore
    from cyberalertx.media.engine import illustration_payload, run as media_run
    from tests.test_media import MockProvider
    store = MediaStore(tmp_path / "media")
    res = media_run(world["repo"].all(), store=store, sheets=world["sheets"], posts=world["posts"], now=NOW,
                    provider=MockProvider(), intel_dir=world["tmp"] / "intel")
    assert res.generated and res.calls <= 3
    assert illustration_payload(store, world["kev"].fingerprint) is not None


# ---------------------------------------------------------------- 5.8 publication (six destinations)

def test_six_destinations_with_failure_isolation_and_idempotency(world: dict[str, Any], tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    from cyberalertx.publish.destinations import TelegramDestination, WebsiteDestination
    from cyberalertx.publish.jobs import JobStore
    from cyberalertx.publish.orchestrator import EditionSource, PublishPolicy, intel_view, plan, run, IntelView
    from tests.test_publication import BASE, Bot, settings
    from tests.test_threads import FakeThreads, both, tdest

    api = FakeThreads()
    accounts = both(tmp_path, api)
    bot = Bot({"sendMessage": [httpx.Response(502, json={"ok": False, "description": "Bad Gateway"})]})
    s = settings(channels={"en": "@fake_en", "ua": "@fake_ua"})
    d = {"website": WebsiteDestination(BASE),
         "telegram": TelegramDestination(s, ledger_path=tmp_path / "ledger.jsonl", publisher_factory=bot.factory()),
         "threads@en": tdest("en", accounts, api), "threads@ua": tdest("ua", accounts, api)}
    store = JobStore(tmp_path / "jobs.json")
    source = EditionSource(world["svc"])
    view = IntelView.from_run(intel(world))
    pol = PublishPolicy(telegram_per_run=10, threads_per_run=10)
    created = plan(source, store, now=NOW, settings=s, destinations=d, view=view, policy=pol).created
    kev_jobs = {j.job_id: j for j in created if j.fingerprint == world["kev"].fingerprint}
    dests = {(j.destination, j.locale) for j in kev_jobs.values()}
    assert dests == {("website", "en"), ("website", "ua"), ("telegram", "en"), ("telegram", "ua"),
                     ("threads@en", "en"), ("threads@ua", "ua")}
    assert all(j.priority == 100 for j in kev_jobs.values())                # breaking first
    run(source, store, d, now=NOW, clock=lambda: NOW, policy=pol, rng=lambda: 0.5)
    st = {(j.destination, j.locale): j.status for j in store.all() if j.fingerprint == world["kev"].fingerprint}
    assert list(st.values()).count("retrying") == 1 and list(st.values()).count("published") == 5   # one 502 isolated
    # locale routing: every message/post went to its own language's channel/profile
    for b in bot.sent("sendMessage"):
        assert ("/ua/threat/" in b["reply_markup"]["inline_keyboard"][0][0]["url"]) == (b["chat_id"] == "@fake_ua")
    for p in api.posts:
        assert ("/ua/threat/" in p["text"]) == (p["user"] == "222")
    # idempotency: planning and running again sends nothing new; the retry finishes once
    plan(source, store, now=NOW, settings=s, destinations=d, view=view, policy=pol)
    sent_before = len(bot.sent()), len(api.posts)
    run(source, store, d, now=NOW + timedelta(minutes=10), clock=lambda: NOW + timedelta(minutes=10), policy=pol,
        rng=lambda: 0.5)
    assert len(api.posts) == sent_before[1]
    assert len(bot.sent()) == sent_before[0] + 1                           # only the retried EN message
    assert all(j.status == "published" for j in store.all() if j.fingerprint == world["kev"].fingerprint)
    _ = intel_view                                                          # (production builder exists)


def test_admin_and_dashboard_make_no_external_calls(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Opening every admin page must not call an AI provider or publish."""
    import cyberalertx.api.app as app_mod
    from fastapi.testclient import TestClient
    from cyberalertx.api.admin import AdminGuard
    from cyberalertx.ops import health
    import base64

    def forbidden(*a: Any, **k: Any) -> Any:
        raise AssertionError("external call from an admin page")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)   # real network only
    monkeypatch.setattr(health, "probe_frontend", lambda: ("not_configured", "off"))
    monkeypatch.setattr(health, "probe_units", lambda: {})
    monkeypatch.setattr(app_mod, "_ops_data_dir", lambda: world["tmp"])
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", "e" * 48)
    from cyberalertx.ops import readmodel
    readmodel.clear_cache()
    health.clear_probe_cache()
    c = TestClient(app_mod.build_app(service=world["svc"], feedback_path=world["tmp"] / "f.jsonl",
                                     admin_guard=AdminGuard()))
    auth = {"Authorization": "Basic " + base64.b64encode(b"ops:" + b"e" * 48).decode()}
    before = len(world["ai"].post_calls), len(world["ai"].json_calls)
    for path in ("/admin/", "/admin/stories", "/admin/intel", "/admin/review", "/admin/media", "/admin/publishing",
                 "/admin/threads", "/admin/sources", "/admin/usage", "/admin/system"):
        assert c.get(path, headers=auth).status_code == 200, path
    assert (len(world["ai"].post_calls), len(world["ai"].json_calls)) == before


# ---------------------------------------------------------------- regression: story re-keying (found in Phase 7)

def test_newer_coverage_does_not_rekey_a_story(world: dict[str, Any], tmp_path: Path) -> None:
    """cluster_items anchors on the NEWEST article; before the Phase 7 fix the
    Core's story key moved when newer coverage arrived, resetting score history
    and Breaking state and letting the planner create new Threads jobs."""
    repo = JsonNewsStore(tmp_path / "items.json")
    Pipeline(sources(), repo, stories_dir=tmp_path / "s").run_once()
    before = intel(world, its=repo.all())
    key_before = story_of(before, "kev_bc").key
    newer = NewsItem(title="CVE-2026-50001: Widget Gateway attacks spread to more networks", source="The Record",
                     url=URL + "kev_record", published_at=NOW - timedelta(minutes=30),
                     raw_content=f"Attacks exploiting CVE-2026-50001 in Widget Gateway 9.1 spread. {SYNTHETIC}")

    class One(Source):
        def fetch(self) -> list[NewsItem]:
            return [newer]
    Pipeline([One("The Record")], repo, stories_dir=tmp_path / "s").run_once()
    after = intel(world, its=repo.all())
    kev = story_of(after, "kev_bc")
    assert len(kev.members) == 3 and kev.key == key_before
    assert {s.key for s in after.stories} >= {s.key for s in before.stories}   # nobody else re-keyed
    assert len({s.key for s in after.stories}) == len(after.stories)          # keys stay unique


def test_planner_never_reposts_an_article_under_a_new_story_key(world: dict[str, Any], tmp_path: Path) -> None:
    from cyberalertx.publish.destinations import TelegramDestination, WebsiteDestination
    from cyberalertx.publish.jobs import JobStore
    from cyberalertx.publish.orchestrator import EditionSource, IntelView, plan
    from tests.test_publication import BASE, Bot, settings
    s = settings(channels={"en": "@fake_en"})
    d = {"website": WebsiteDestination(BASE),
         "telegram": TelegramDestination(s, ledger_path=tmp_path / "l.jsonl", publisher_factory=Bot().factory())}
    store, source = JobStore(tmp_path / "jobs.json"), EditionSource(world["svc"])
    view = IntelView.from_run(intel(world))
    first = plan(source, store, now=NOW, settings=s, destinations=d, view=view).created
    assert first
    rekeyed = IntelView(story_of={fp: "s:REKEYED" + key for fp, key in view.story_of.items()},
                        members={"s:REKEYED" + k: v for k, v in view.members.items()},
                        top_rank={}, breaking={}, relevance={"s:REKEYED" + k: v for k, v in view.relevance.items()})
    again = plan(source, store, now=NOW, settings=s, destinations=d, view=rekeyed).created
    assert again == []                                                       # same articles → no new jobs
