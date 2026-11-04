"""Story clustering confidence, source independence, manual corrections,
relevance scope and the cluster-wide evidence layer. Hand-built fixtures only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cyberalertx.ai.fact_sheet import (
    AffectedProduct,
    Claim,
    Evidence,
    FactSheet,
    FactSheetEntry,
    Ioc,
    AttackTechnique,
    cluster_evidence,
    sanitize_fact_sheet,
)
from cyberalertx.models import NewsItem
from cyberalertx.pipeline.dedup import (
    StoryFeatures,
    StoryOverrides,
    apply_story_overrides,
    assign_incremental,
    attributed_outlets,
    cluster_items,
    independent_sources,
    load_story_overrides,
    match_story,
    normalize_url,
    same_story,
)
from cyberalertx.pipeline.relevance import (
    RelevanceDecision,
    classify_scope,
    effective_relevance,
    filter_relevant_hybrid,
    is_renderable,
    load_relevance_overrides,
    save_relevance_override,
)
from cyberalertx.storage.pg.serializers import row_to_news_item
from cyberalertx.tools import stories as stories_cli

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
FILLER = (" The report describes the activity in detail and lists the steps "
          "defenders should take. ") * 3


def item(title: str, source: str, *, hours: float = 0, body: str = "",
         url: str = "", category: str = "other", language: str = "en") -> NewsItem:
    return NewsItem(
        title=title, source=source,
        url=url or f"https://{source.lower().replace(' ', '')}.example/{abs(hash(title)) % 10**8}",
        published_at=T0 + timedelta(hours=hours),
        raw_content=body or (title + "." + FILLER),
        category=category, language=language,
    )


def groups(items: list[NewsItem], **kw: object) -> list[set[str]]:
    clusters = cluster_items(items, **kw)  # type: ignore[arg-type]
    return sorted(({m.title for m in c.members} for c in clusters), key=lambda g: sorted(g))


def together(items: list[NewsItem], a: NewsItem, b: NewsItem, **kw: object) -> bool:
    return any({a.title, b.title} <= g for g in groups(items, **kw))


# ---------------------------------------------------------------------------
# 1–2. Acceptance scenarios
# ---------------------------------------------------------------------------

def test_same_incident_from_multiple_sources_merges_with_a_decision() -> None:
    a = item("Drupal warns of critical Commerce Core flaw exploited in attacks",
             "BleepingComputer", body="Drupal says CVE-2026-5555 in Commerce Core is exploited." + FILLER)
    b = item("Hackers Actively Exploit Highly Critical Drupal Commerce Core Flaw",
             "The Hacker News", hours=3,
             body="CVE-2026-5555 affects Drupal Commerce Core and is under attack." + FILLER)
    clusters = cluster_items([a, b])
    assert len(clusters) == 1
    (decision,) = clusters[0].decisions
    assert decision.rule == "rule_a_identical_cves"
    assert decision.confidence == "high"
    assert decision.merges and "CVE-2026-5555" in decision.reason
    assert independent_sources(clusters[0]) == ["BleepingComputer", "The Hacker News"]


def test_same_cve_with_different_affected_versions_is_one_story() -> None:
    # Decision: ONE story. The CVE identifies one flaw; a second outlet
    # listing a wider version range is a difference in the facts, which
    # `cluster_evidence` records as a contradiction, not a second story.
    a = item("Apache Tomcat flaw CVE-2026-7001 lets attackers bypass auth",
             "BleepingComputer", body="CVE-2026-7001 affects Tomcat 9.0.0 to 9.0.90." + FILLER)
    b = item("Apache Tomcat CVE-2026-7001 Also Hits Tomcat 10 and 11 Branches",
             "The Hacker News", hours=5,
             body="CVE-2026-7001 affects Tomcat 10.1.0 to 10.1.30 and 11.0.0." + FILLER)
    assert together([a, b], a, b)
    sheets = {
        a.fingerprint: FactSheet(cve_ids=["CVE-2026-7001"], affected_products=[
            AffectedProduct(vendor="Apache", product="Tomcat", versions=["9.0.0-9.0.90"])]),
        b.fingerprint: FactSheet(cve_ids=["CVE-2026-7001"], affected_products=[
            AffectedProduct(vendor="Apache", product="Tomcat", versions=["10.1.0-10.1.30", "11.0.0"])]),
    }
    ev = cluster_evidence([a, b], sheets)
    assert any("affected versions" in c.statement for c in ev.contradictions)
    cve = next(f for f in ev.facts if f.kind == "cve")
    assert cve.status == "confirmed" and len(cve.origins) == 2


def test_same_cve_in_unrelated_exploitation_incidents_stays_separate() -> None:
    a = item("Acme Corp hit by hackers exploiting Fortinet CVE-2026-1111",
             "BleepingComputer", body="Acme Corp was breached via CVE-2026-1111." + FILLER)
    b = item("Globex Industries suffers breach through Fortinet CVE-2026-1111",
             "The Hacker News", hours=20, body="Globex Industries says CVE-2026-1111 was used." + FILLER)
    assert not together([a, b], a, b)
    d = match_story(StoryFeatures.from_item(a), StoryFeatures.from_item(b))
    assert d is not None and d.confidence == "low" and not d.merges
    assert d.rule == "same_cve_different_incident"
    clusters = cluster_items([a, b])
    assert sum(len(c.links) for c in clusters) == 1   # kept as a link


def test_different_incidents_at_the_same_company_stay_separate() -> None:
    a = item("Contoso discloses data breach affecting 2 million customers",
             "BleepingComputer", category="breach")
    b = item("Contoso Azure tenant misconfiguration exposes internal build logs",
             "The Hacker News", hours=30, category="breach")
    assert not together([a, b], a, b)


def test_different_ransomware_victims_of_one_family_stay_separate() -> None:
    a = item("Akira ransomware hits Northwind Traders, steals 40GB",
             "BleepingComputer", category="ransomware")
    b = item("Akira ransomware gang claims attack on Fabrikam Hospital",
             "The Record", hours=10, category="ransomware")
    assert not together([a, b], a, b)


def test_rare_shared_threat_name_with_different_victims_is_a_low_link() -> None:
    fa = StoryFeatures(fingerprint="a", source="X", title="Qilin ransomware hits Northwind",
                       published_at=T0, cves=frozenset(), distinctive=frozenset({"qilin", "northwind"}),
                       entities=frozenset(), body_digest="",
                       names=frozenset({"qilin", "northwind"}), category="ransomware")
    fb = StoryFeatures(fingerprint="b", source="Y", title="Qilin ransomware breaches Fabrikam",
                       published_at=T0 + timedelta(hours=5), cves=frozenset(),
                       distinctive=frozenset({"qilin", "fabrikam"}), entities=frozenset(),
                       body_digest="", names=frozenset({"qilin", "fabrikam"}), category="ransomware")
    from cyberalertx.pipeline.dedup import name_statistics
    stats = name_statistics([fa, fb])
    d = match_story(fa, fb, name_stats=stats)
    assert d is not None and d.rule == "same_threat_different_victim" and not d.merges
    assert same_story(fa, fb, name_stats=stats) is False
    assert same_story(fb, fa, name_stats=stats) is False


def test_follow_up_with_new_development_is_separate_and_linked() -> None:
    a = item("Ivanti patches Connect Secure flaw CVE-2026-2222",
             "BleepingComputer", body="Ivanti fixed CVE-2026-2222 in Connect Secure." + FILLER)
    b = item("Ivanti Connect Secure CVE-2026-2222 now actively exploited in attacks",
             "The Hacker News", hours=72,
             body="CVE-2026-2222 in Ivanti Connect Secure is now exploited." + FILLER)
    clusters = cluster_items([a, b])
    assert len(clusters) == 2
    links = [d for c in clusters for d in c.links]
    assert [d.rule for d in links] == ["follow_up"]
    # Same-day coverage of the same development is NOT a follow-up.
    c = item("Ivanti Connect Secure CVE-2026-2222 now exploited, CISA warns",
             "SecurityWeek", hours=74,
             body="CVE-2026-2222 in Ivanti Connect Secure is exploited." + FILLER)
    assert together([b, c], b, c)


def test_syndicated_copies_merge_but_count_as_one_independent_source() -> None:
    body = ("BleepingComputer reports that the Example botnet hijacked 40,000 routers "
            "across Europe using default credentials, according to a new analysis." + FILLER)
    original = item("Example botnet hijacks 40,000 routers across Europe", "BleepingComputer",
                    body=body, url="https://www.bleepingcomputer.com/news/security/example-botnet/")
    copy1 = item("Example botnet hijacks 40,000 routers across Europe", "Aggregator One",
                 hours=2, body=body)
    copy2 = item("Botnet takes over 40,000 European routers", "Aggregator Two", hours=4,
                 body=("According to BleepingComputer, a botnet took over 40,000 routers. "
                       "Source: https://bleepingcomputer.com/news/security/example-botnet?utm_source=x"
                       + FILLER))
    clusters = cluster_items([original, copy1, copy2])
    big = max(clusters, key=lambda c: len(c.members))
    assert {m.source for m in big.members} >= {"BleepingComputer", "Aggregator One"}
    assert any(d.rule == "rule0_identical_body" for d in big.decisions)
    assert independent_sources(big) == ["BleepingComputer"]


def test_similar_headlines_for_unrelated_events_stay_separate() -> None:
    a = item("Critical flaw in Zyxel firewalls lets attackers run code", "BleepingComputer",
             category="vulnerability")
    b = item("Critical flaw in SonicWall firewalls lets attackers run code", "The Hacker News",
             hours=6, category="vulnerability")
    assert not together([a, b], a, b)


def test_same_story_stays_symmetric_with_decisions() -> None:
    a = item("Acme Corp hit by hackers exploiting Fortinet CVE-2026-1111", "A",
             body="CVE-2026-1111" + FILLER)
    b = item("Globex Industries suffers breach through Fortinet CVE-2026-1111", "B", hours=2,
             body="CVE-2026-1111" + FILLER)
    fa, fb = StoryFeatures.from_item(a), StoryFeatures.from_item(b)
    da, db = match_story(fa, fb), match_story(fb, fa)
    assert da is not None and db is not None
    assert (da.rule, da.confidence) == (db.rule, db.confidence)


# ---------------------------------------------------------------------------
# 3. Source independence helpers
# ---------------------------------------------------------------------------

def test_attribution_and_url_normalisation() -> None:
    assert attributed_outlets("as first reported by The Record, the gang ...") == {"The Record"}
    assert attributed_outlets("Про це повідомляє dev.ua.") == {"dev.ua"}
    assert attributed_outlets("according to Microsoft, the flaw ...") == frozenset()
    assert normalize_url("https://www.Example.com/a/?utm_source=x#top") == "example.com/a"


def test_one_outlet_reporting_twice_is_one_origin() -> None:
    a = item("Example botnet hijacks 40,000 routers across Europe", "BleepingComputer")
    b = item("Example botnet hijacks 40,000 routers across Europe, update", "BleepingComputer",
             hours=1, body="Different text about the Example botnet routers." + FILLER)
    cluster = cluster_items([a, b])[0]
    if len(cluster.members) == 2:
        assert independent_sources(cluster) == ["BleepingComputer"]


# ---------------------------------------------------------------------------
# 4. Overrides
# ---------------------------------------------------------------------------

def _pair() -> tuple[NewsItem, NewsItem, NewsItem]:
    a = item("Drupal warns of critical Commerce Core flaw exploited in attacks", "BleepingComputer",
             body="CVE-2026-5555 Drupal." + FILLER)
    b = item("Hackers Actively Exploit Highly Critical Drupal Commerce Core Flaw", "The Hacker News",
             hours=3, body="CVE-2026-5555 Drupal." + FILLER)
    c = item("Unrelated Zyxel NAS firmware update ships new UI", "Vendor Blog", hours=1)
    return a, b, c


def test_split_override_separates_without_touching_items() -> None:
    a, b, c = _pair()
    before = [i.to_storage_dict() for i in (a, b, c)]
    ov = StoryOverrides(split=frozenset({a.fingerprint}))
    assert not together([a, b, c], a, b, overrides=ov)
    assert together([a, b, c], a, b)
    assert [i.to_storage_dict() for i in (a, b, c)] == before


def test_merge_override_joins_and_is_recorded() -> None:
    a, b, c = _pair()
    ov = StoryOverrides(merge=((a.fingerprint, c.fingerprint),), reasons={c.fingerprint: "editor"})
    clusters = cluster_items([a, b, c], overrides=ov)
    home = next(cl for cl in clusters if c.fingerprint in {m.fingerprint for m in cl.members})
    assert a.fingerprint in {m.fingerprint for m in home.members}
    assert any(d.rule == "override_merge" and d.reason == "editor" for d in home.decisions)


def test_overrides_in_incremental_assignment() -> None:
    a, b, c = _pair()
    known = [a]
    assign_incremental([a], [])
    ov = StoryOverrides(split=frozenset({b.fingerprint}))
    dups = assign_incremental([b], known, overrides=ov)
    assert dups == [] and b.story_key != a.story_key
    ov2 = StoryOverrides(merge=((a.fingerprint, c.fingerprint),))
    dups = assign_incremental([c], known, overrides=ov2)
    assert dups == [c] and c.story_key == a.story_key and c.duplicate_of == a.fingerprint


def test_apply_story_overrides_rewrites_grouping_in_memory() -> None:
    a, b, c = _pair()
    from cyberalertx.pipeline.dedup import assign_story_keys
    assign_story_keys([a, b, c])
    assert a.story_key == b.story_key
    canonical = a if not a.duplicate_of else b
    other = b if canonical is a else a
    changes = apply_story_overrides([a, b, c], StoryOverrides(split=frozenset({canonical.fingerprint})))
    assert [ch.rule for ch in changes] == ["override_split"]
    assert canonical.story_key != other.story_key
    assert canonical.duplicate_of == "" and other.duplicate_of == ""
    changes = apply_story_overrides([a, b, c], StoryOverrides(merge=((a.fingerprint, c.fingerprint),)))
    assert c.story_key == a.story_key and c.duplicate_of == (a.duplicate_of or a.fingerprint)


def test_load_story_overrides_file(tmp_path: Path) -> None:
    p = tmp_path / "overrides.json"
    assert not load_story_overrides(p)
    p.write_text(json.dumps({"split": [{"fingerprint": "x", "reason": "r"}],
                             "merge": [{"fingerprints": ["a", "b"]}, {"fingerprints": ["c"]}]}))
    ov = load_story_overrides(p)
    assert ov.split == {"x"} and ov.merge == (("a", "b"),)
    assert ov.partners("b") == ["a"] and ov.reason_for("x") == "r"


# ---------------------------------------------------------------------------
# 5. Dry-run CLI
# ---------------------------------------------------------------------------

def _store(tmp_path: Path, items: list[NewsItem]) -> None:
    (tmp_path / "items.json").write_text(json.dumps(
        {"items": [{**i.to_storage_dict(), "fingerprint": i.fingerprint} for i in items]}))


def test_cluster_report_is_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a, b, c = _pair()
    _store(tmp_path, [a, b, c])            # no story keys stored: every merge is "changed"
    before = (tmp_path / "items.json").read_bytes()
    assert stories_cli.main(["--data-dir", str(tmp_path), "cluster-report"]) == 0
    assert (tmp_path / "items.json").read_bytes() == before
    report = json.loads((tmp_path / "stories" / "cluster_report.json").read_text())
    assert report["dry_run"] and len(report["changed_merges"]) == 1
    joined = report["changed_merges"][0]["joined"][0]
    assert joined["confidence"] in ("high", "medium") and joined["reason"]


def test_split_merge_and_relevance_override_commands(tmp_path: Path) -> None:
    a, b, c = _pair()
    _store(tmp_path, [a, b, c])
    d = str(tmp_path)
    assert stories_cli.main(["--data-dir", d, "split", a.fingerprint, "--reason", "r1"]) == 0
    assert stories_cli.main(["--data-dir", d, "merge", a.fingerprint, c.fingerprint,
                             "--reason", "r2"]) == 0
    ov = load_story_overrides(tmp_path / "stories" / "overrides.json")
    assert a.fingerprint in ov.split and ov.merge == ((a.fingerprint, c.fingerprint),)
    assert stories_cli.main(["--data-dir", d, "relevance-override", c.fingerprint,
                             "out_of_scope", "--reason", "vendor UI news"]) == 0
    rel = load_relevance_overrides(tmp_path / "stories" / "relevance_overrides.json")
    assert rel[c.fingerprint]["status"] == "out_of_scope"
    report = stories_cli.build_relevance_report(
        [NewsItem.from_storage_dict(x) for x in json.loads((tmp_path / "items.json").read_text())["items"]],
        tmp_path)
    assert report["by_effective_status"].get("out_of_scope", 0) >= 1


# ---------------------------------------------------------------------------
# 7. Relevance scope
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "No Law: трейлер кіберпанкового RPG-шутера від Neon Giant",
    "Cronos: Lazarus отримав новий трейлер із ґеймплеєм",
    "Огляд монітора Acer Nitro XF273 UF3",
    "У США пустили 272-тонні потяги по плавучому мосту",
    "Chateau Chizay і NADRA випустили лімітовану колекцію винних пляшок",
    "NAVI вибила Spirit із турніру PGL Masters з Counter-Strike 2",
    "Витік довіри до інтернету | Російський супутник | Кінець BioWare — DOU News #273",
    "Міноборони України допустило до експлуатації 413 моделей БпАК",
])
def test_clearly_off_topic_items_are_out_of_scope(title: str) -> None:
    status, reason = classify_scope(item(title, "dev.ua", language="ua"))
    assert status == "out_of_scope", reason


@pytest.mark.parametrize("title", [
    "Apple backports CoreGraphics zero-day patches to older iPhones",
    "Tailscale Patches SSH Flaws That Could Let Hacked Devices Gain Root",
    "LiteLLM release pipeline hacked to distribute info-stealer malware",
    "Ruby Fixes Three Regex Engine Bugs Responsible for GitLab RCE Flaws",
    "Researchers Demonstrate Node2Shell RCE Exploit on Node.js",
    "Хакери зламали застосунок «Повітряна тривога»",
    "Розробники Kingdom Come: Deliverance зазнали серйозної кібератаки",
    "Fix for CVE-2026-1234 in OpenSSL ships",
])
def test_security_developments_are_in_scope(title: str) -> None:
    status, reason = classify_scope(item(title, "x"))
    assert status == "in_scope", reason


def test_security_word_alone_does_not_rescue_an_off_topic_subject() -> None:
    status, _ = classify_scope(item("Безоплатні курси з кібербезпеки для держсектору", "dou.ua"))
    assert status == "needs_review"
    status, _ = classify_scope(item("ThreatsDay: Critical Firewall Flaws + 26 More Stories", "THN"))
    assert status == "needs_review"


def test_body_carries_scope_when_headline_does_not() -> None:
    it = item("Google changes how Android installs apps", "THN",
              body="The change blocks malware sideloading and phishing installers." + FILLER)
    assert classify_scope(it)[0] == "in_scope"
    plain = item("Spotify changes family plan rules", "dev.ua", body="Family plans." + FILLER)
    assert classify_scope(plain)[0] == "out_of_scope"
    ai = RelevanceDecision(is_relevant=True, score=2, source="ai-accept")
    assert classify_scope(plain, ai) == ("in_scope", "gray zone: AI classifier accepted")


def test_effective_relevance_prefers_override_and_classifies_legacy_items() -> None:
    it = item("Огляд монітора Acer Nitro", "itc.ua")
    assert it.relevance_status == ""
    assert effective_relevance(it) == "out_of_scope" and not is_renderable(it)
    it.relevance_override = "in_scope"
    assert effective_relevance(it) == "in_scope" and is_renderable(it)


def test_hybrid_filter_stamps_kept_items() -> None:
    kept, _ = filter_relevant_hybrid([item("Hackers breach Acme via phishing and ransomware", "x")])
    assert kept[0].relevance_status == "in_scope" and kept[0].relevance_reason


def test_relevance_fields_round_trip_and_old_json_loads() -> None:
    it = item("x", "y")
    it.relevance_status, it.relevance_reason, it.relevance_override = "needs_review", "r", "in_scope"
    back = NewsItem.from_storage_dict(it.to_storage_dict())
    assert (back.relevance_status, back.relevance_reason, back.relevance_override) == \
        ("needs_review", "r", "in_scope")
    legacy = it.to_storage_dict()
    for k in ("relevance_status", "relevance_reason", "relevance_override"):
        legacy.pop(k)
    assert NewsItem.from_storage_dict(legacy).relevance_status == ""
    row = {"title": "t", "source": "s", "url": "u", "published_at": T0}
    assert row_to_news_item(row).relevance_override == ""
    assert it.to_public_dict()["relevance_status"] == "needs_review"


def test_save_relevance_override_validates(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_relevance_override(tmp_path / "r.json", "fp", "maybe", "x")


# ---------------------------------------------------------------------------
# 6. Fact sheet extension
# ---------------------------------------------------------------------------

def test_version_1_sheet_loads_and_legacy_statuses_map() -> None:
    v1 = {"status": "ok", "schema_version": 1, "sheet": {
        "summary": "s", "claims": [
            {"statement": "a", "status": "claimed"},
            {"statement": "b", "status": "alleged"},
            {"statement": "c", "status": "confirmed"}]}}
    sheet = FactSheetEntry.from_dict(v1).sheet
    assert sheet is not None
    assert [c.status for c in sheet.claims] == ["reported", "unverified", "confirmed"]
    assert sheet.event_type == "other" and sheet.evidence == [] and sheet.iocs == []
    assert "event_type" not in sheet.compact_dict()


def test_new_fields_validate_and_coerce() -> None:
    sheet = FactSheet.model_validate({
        "event_type": "Active Exploitation",
        "claims": [{"statement": "x", "status": "editorial"}],
        "evidence": [{"claim": "c", "excerpt": " ".join(["w"] * 40), "status": "disputed"}],
    })
    assert sheet.event_type == "active_exploitation"
    assert sheet.claims[0].status == "interpretation"
    assert len(sheet.evidence[0].excerpt.split()) == 25
    assert sheet.evidence[0].status == "contradictory"
    assert FactSheet.model_validate({"event_type": "weird"}).event_type == "other"


def test_sanitize_keeps_only_verbatim_iocs_mitre_and_excerpts() -> None:
    body = "The loader beacons to 203.0.113[.]7 and uses spearphishing (T1566.001)." + FILLER
    sheet = FactSheet(
        iocs=[Ioc(type="ip", value="203.0.113[.]7"), Ioc(type="ip", value="198.51.100.9")],
        attack_techniques=[AttackTechnique(description="spearphishing", mitre_id="T1566.001"),
                           AttackTechnique(description="persistence", mitre_id="T1547")],
        evidence=[Evidence(claim="C2", excerpt="beacons to 203.0.113[.]7"),
                  Evidence(claim="made up", excerpt="the attackers are Russian")],
    )
    clean, dropped = sanitize_fact_sheet(sheet, "t", body, source_name="Src", source_url="https://s")
    assert [i.value for i in clean.iocs] == ["203.0.113[.]7"]
    assert [t.mitre_id for t in clean.attack_techniques] == ["T1566.001", ""]
    assert clean.evidence[0].excerpt and clean.evidence[1].excerpt == ""
    assert clean.evidence[0].source == "Src" and clean.evidence[0].url == "https://s"
    assert {"ioc:198.51.100.9", "mitre:T1547"} <= set(dropped)


def test_cluster_evidence_does_not_let_syndicated_copies_confirm() -> None:
    body = "Example botnet hijacked 40,000 routers, researchers at Acme Labs said." + FILLER
    a = item("Example botnet hijacks 40,000 routers", "BleepingComputer", body=body)
    b = item("Example botnet hijacks 40,000 routers", "Aggregator", hours=1, body=body)
    sheet = FactSheet(malware_families=["Example"],
                      claims=[Claim(statement="40,000 routers hijacked", attribution="Acme Labs")],
                      exploitation_status="confirmed")
    ev = cluster_evidence([a, b], {a.fingerprint: sheet, b.fingerprint: sheet})
    assert ev.independent_sources == ["BleepingComputer"]
    fam = next(f for f in ev.facts if f.kind == "malware")
    assert fam.status == "reported" and fam.sources == ["BleepingComputer", "Aggregator"]
    # An independent outlet does confirm; a disagreeing one is recorded.
    c = item("Router botnet Example grows", "The Record", hours=3,
             body="The Example botnet now controls routers." + FILLER)
    other = FactSheet(malware_families=["Example"], exploitation_status="not_reported")
    ev = cluster_evidence([a, b, c], {a.fingerprint: sheet, b.fingerprint: sheet,
                                      c.fingerprint: other})
    assert next(f for f in ev.facts if f.kind == "malware").status == "confirmed"
    assert any("exploitation" in x.statement for x in ev.contradictions)
    assert ev.exploitation_status == "confirmed"


def test_primary_confirmed_evidence_confirms_a_claim() -> None:
    a = item("Vendor confirms flaw", "Vendor PSIRT")
    sheet = FactSheet(evidence=[Evidence(claim="patch released", primary=True, status="confirmed")])
    ev = cluster_evidence([a], {a.fingerprint: sheet})
    assert ev.confirmed()[0].value == "patch released"
