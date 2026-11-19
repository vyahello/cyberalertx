"""Editorial visual system V4 (`cax-editorial-4`): brief, scene selection,
facts, the verified photo library, rendering safety/determinism/cost, the
renderer switch and the thumbnail focus box."""
from __future__ import annotations

import json
import re
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cyberalertx.media.assets import MediaStore
from cyberalertx.media.svg_art import UnsafeSvg, sanitize_svg
from cyberalertx.media.v4 import brief as B
from cyberalertx.media.v4 import library
from cyberalertx.media.v4 import type as T
from cyberalertx.media.v4.render import render
from cyberalertx.media.v4.scenes import load_all


def story(title: str, body: str = "", *, key: str = "s:x", category: str = "other", lang: str = "en",
          post: str = "") -> Any:
    from cyberalertx.models import NewsItem
    from datetime import datetime, timezone
    it = NewsItem(title=title, source="Test", url=f"https://t.test/{abs(hash(title))}",
                  published_at=datetime(2026, 11, 17, tzinfo=timezone.utc), raw_content=body, language=lang,
                  category=category)
    posts = {"en": SimpleNamespace(title=post, short_summary="")} if post else {}
    return SimpleNamespace(key=key, anchor=it, members=[it], posts=posts)


# ------------------------------------------------------------------ scene selection (real headlines)

@pytest.mark.parametrize("title,body,scene", [
    ("N-able Patches 17 N-central Flaws as Attackers Exploit Earlier Bugs to Deploy Crypto Miners",
     "N-able released N-central 2026.4 Hotfix 3 for its remote monitoring and management (RMM) platform.",
     "rmm_console"),
    ("Hackers Found a Way Around GitHub SHA Pinning. This Webinar Explains How to Close the Gap",
     "Pinning GitHub Actions to an exact version of their code, known as SHA pinning.", "ci_pinning"),
    ("Inside Modern Phishing Kits Built to Steal Microsoft 365 Sessions",
     "Researchers break down how kits capture and replay M365 tokens.", "session_theft"),
    ("Хакери атакували найпотужніший супер-ПК Японії: викрадено понад 4000 облікових записів",
     "Найпотужніший суперкомп'ютер Японії Fugaku зазнав масштабної хакерської атаки.", "hpc_hall"),
    ("⚡ Weekly Recap: N-able 0-Days, Windows 0-Days, Chrome 0-Days, Fridge 0-Days, and More Bad Days",
     "", "weekly_recap"),
    ("Six Unpatched Danfoss Refrigeration Controller Flaws Could Allow Remote Takeover Without Login", "",
     "refrigeration_controller"),
    ("SANSAR Linux Cryptomining Malware Uses Modified NVIDIA Library to Hide GPU Activity", "",
     "gpu_cryptominer"),
    ("Court clears brothers of $25 million Ethereum crypto heist charges", "", "court_case"),
    ("Uber notifies drivers of data breach affecting nearly 150,000 people", "", "breach_notice"),
])
def test_real_headlines_choose_the_scene_of_their_subject(title: str, body: str, scene: str) -> None:
    b = B.build(story(title, body))
    assert b.scene == scene, (b.scene, b.evidence)
    assert b.confidence in ("high", "medium") and b.evidence


def test_an_incidental_word_never_outvotes_the_subject() -> None:
    b = B.build(story("N-able Patches 17 N-central Flaws as Attackers Exploit Earlier Bugs to Deploy Crypto Miners"))
    assert b.scene == "rmm_console"
    assert all(alt != "gpu_cryptominer" or s < 12 for alt, s in b.alternatives)


def test_unsupported_story_falls_back_honestly() -> None:
    b = B.build(story("Quarterly notes from the editor", "A short note."))
    assert b.scene == "dossier" and b.confidence == "low" and b.reason.startswith("fallback")


def test_brief_is_structured_and_complete() -> None:
    b = B.build(story("Inside Modern Phishing Kits Built to Steal Microsoft 365 Sessions"))
    d = b.to_dict()
    for k in ("subject", "action", "target", "environment", "mechanism", "entities", "impact", "supporting",
              "exclude", "confidence", "evidence", "reason", "facts", "library_id", "alternatives"):
        assert k in d
    assert "brand logos" in b.exclude and "text" not in d


# ------------------------------------------------------------------ facts: only what the sources state

def test_facts_come_from_the_headline() -> None:
    f = B.extract_facts("Хакери атакували супер-ПК Японії: викрадено понад 4000 облікових записів", "", "")
    assert f["accounts"] == "4,000" and f["accounts_plus"] is True
    f = B.extract_facts("Uber notifies drivers of data breach affecting nearly 150,000 people", "", "")
    assert f["people"] == "150,000" and f["people_approx"] is True
    assert B.extract_facts("Court clears brothers of $25 million Ethereum heist", "", "")["money"] == "$25M"
    assert B.extract_facts("Ransomware suspect faces 27 years in prison", "", "")["years"] == "27"
    assert "CVE-2026-1111" in B.extract_facts("Flaw CVE-2026-1111 exploited", "", "")["cves"]


def test_zero_day_wording_is_not_a_day_count() -> None:
    assert "days" not in B.extract_facts("Weekly Recap: N-able 0-Days, Windows 0-Days", "", "")
    assert "flaws" not in B.extract_facts("Gateways hacked via PHP2Shell flaws", "", "")


def test_rewording_the_post_does_not_change_the_inputs_hash() -> None:
    a = B.build(story("Inside Modern Phishing Kits Built to Steal Microsoft 365 Sessions", post="One wording."))
    b = B.build(story("Inside Modern Phishing Kits Built to Steal Microsoft 365 Sessions", post="Other words."))
    assert B.inputs_hash(a) == B.inputs_hash(b)


# ------------------------------------------------------------------ verified photo library (Tier A)

def _manifest() -> list[dict[str, Any]]:
    return json.loads((library.LIB_DIR / "library.json").read_text(encoding="utf-8"))["assets"]


def test_every_library_photo_is_verified() -> None:
    entries = _manifest()
    assert entries, "library is empty"
    for e in entries:
        assert library.validate(e) == [], e["id"]
    assert len(library.load()) == len(entries)


@pytest.mark.parametrize("change,problem", [
    ({"license": "CC-BY-SA-4.0"}, "not allowed"),
    ({"license": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/"}, "not allowed"),
    ({"commercial_use": None}, "missing"),
    ({"modification_allowed": False}, "modification_allowed"),
    ({"sha256": "0" * 64}, "hash"),
    ({"source_url": "http://commons.wikimedia.org/x"}, "https"),
    ({"license_url": "https://creativecommons.org/licenses/by/4.0/"}, "does not match"),
])
def test_unverified_photos_are_refused(change: dict[str, Any], problem: str) -> None:
    e = {**_manifest()[0], **change}
    assert any(problem in p for p in library.validate(e))


def test_library_photo_has_no_metadata_and_correct_size() -> None:
    data = (library.LIB_DIR / "fugaku-riken-r-ccs.jpg").read_bytes()
    assert data[:2] == b"\xff\xd8" and b"Exif" not in data[:200] and b"GPS" not in data
    a = library.find("Найпотужніший суперкомп'ютер Японії Fugaku")
    assert a is not None and a.license == "CC0-1.0" and a.credit


def test_fugaku_story_uses_the_photo_with_credit_and_annotation() -> None:
    b = B.build(story("Хакери атакували найпотужніший супер-ПК Японії: викрадено понад 4000 облікових записів",
                      "За інформацією Japan Times, суперкомп'ютер Fugaku зазнав атаки.", lang="ua"))
    assert b.library_id == "fugaku-riken-r-ccs"
    svg = render(b)
    sanitize_svg(svg.encode())
    assert svg.count("<image") == 1 and 'href="data:image/jpeg;base64,' in svg
    alt = B.alt_text(b)
    assert "CC0" in alt["en"] and "Fugaku" in alt["en"] and "Fugaku" in alt["ua"]


def test_photo_is_never_used_for_a_story_that_does_not_name_it() -> None:
    b = B.build(story("Attackers breach a university supercomputer cluster", "HPC accounts were stolen."))
    assert b.scene == "hpc_hall" and b.library_id == ""
    svg = render(b)
    assert "<image" not in svg


# ------------------------------------------------------------------ rendering: every scene, safe and cheap

def _brief_for(scene: str, **kw: Any) -> B.EditorialBrief:
    base = B.build(story("Widget flaw", key=f"s:{scene}"))
    spec = B.SPECS.get(scene, B.FALLBACK)
    return replace(base, scene=scene, palette=spec.palette, **kw)


def test_every_catalogue_scene_is_implemented() -> None:
    scenes = load_all()
    missing = [s.id for s in B.CATALOGUE if s.id not in scenes] + [x for x in ("dossier", "hpc_drawn")
                                                                    if x not in scenes]
    assert missing == []


@pytest.mark.parametrize("scene", [s.id for s in B.CATALOGUE] + ["dossier", "hpc_drawn"])
def test_every_scene_renders_safe_deterministic_and_cheap(scene: str) -> None:
    b = _brief_for(scene, facts={"cves": ["CVE-2026-1111"], "money": "$25M", "people": "150,000",
                                 "accounts": "4,000", "years": "27", "videos": "90", "flaws": "17"},
                   entities=("Widget", "Acme"))
    t = time.perf_counter()
    svg = render(b)
    took = time.perf_counter() - t
    w, h = sanitize_svg(svg.encode())
    assert (w, h) == (1600, 900)
    assert render(b) == svg                                   # deterministic
    assert len(svg) < 400 * 1024
    assert took < 0.5                                         # generous on a loaded CI runner
    assert "<text" not in svg and "http://" not in svg.replace("http://www.w3.org/2000/svg", "")


def test_different_stories_of_one_scene_differ() -> None:
    a = render(replace(_brief_for("vuln_advisory"), seed="s:a:cax-editorial-4", story_key="s:a"))
    b = render(replace(_brief_for("vuln_advisory"), seed="s:b:cax-editorial-4", story_key="s:b"))
    assert a != b


def test_image_text_is_paths_and_ascii_only() -> None:
    svg, w = T.text_path("Fugaku — 4,000+", 0, 50, 20, font="display")
    assert svg.startswith("<path") and w > 0
    assert T.supported("Хакери Fugaku", "ui") == " Fugaku"
    assert T.text_path("Хакери", 0, 0, 20)[0] == ""
    assert T.fit("a very long identifier string", 16, 80, "mono").endswith("…")


def test_focus_box_is_a_valid_16_9_region() -> None:
    svg = render(_brief_for("ci_pinning"))
    m = re.search(r'<rect id="cax-focus" x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)"', svg)
    if m:
        x, y, w, h = map(int, m.groups())
        assert w >= 480 and abs(w * 9 / 16 - h) <= 1 and x + w <= 1600 and y + h <= 900
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" id="cax-editorial-4"')


# ------------------------------------------------------------------ sanitizer additions

def test_sanitizer_accepts_only_inline_rasters() -> None:
    ok = ('<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900">'
          '<image width="10" height="10" href="data:image/jpeg;base64,AAAA"/></svg>')
    assert sanitize_svg(ok.encode()) == (1600, 900)
    for bad in ('<image href="https://x.test/a.jpg"/>', '<image href="data:image/svg+xml;base64,AAAA"/>',
                '<rect href="data:image/png;base64,AAAA"/>',
                '<image xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="data:image/png;base64,AA"/>'):
        with pytest.raises(UnsafeSvg):
            sanitize_svg(f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900">{bad}</svg>'.encode())


# ------------------------------------------------------------------ the renderer switch (V3 stays default)

def test_v3_is_the_default_and_v4_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from cyberalertx.media import renderer
    monkeypatch.delenv("CYBERALERTX_ILLUSTRATION_RENDERER", raising=False)
    assert renderer.active() == "cax-svg-3"
    monkeypatch.setenv("CYBERALERTX_ILLUSTRATION_RENDERER", "editorial-4")
    assert renderer.active() == "cax-editorial-4"


def test_switching_renderers_never_replaces_images_by_itself(monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Path) -> None:
    from cyberalertx.media import engine
    from tests.test_media import NOW, critical_story, fake_intel
    stories = [critical_story("s:one"), critical_story("s:two", products=("Gadget Hub",))]
    fake_intel(monkeypatch, stories)
    store = MediaStore(tmp_path / "media")
    anchors = [s.anchor for s in stories]
    monkeypatch.delenv("CYBERALERTX_ILLUSTRATION_RENDERER", raising=False)
    assert len(engine.run(anchors, store=store, now=NOW).generated) == 2
    v3 = {a.asset_id: a.storage_key for a in store.all() if a.asset_type == "editorial_illustration"}

    monkeypatch.setenv("CYBERALERTX_ILLUSTRATION_RENDERER", "editorial-4")
    assert engine.run(anchors, store=store, now=NOW).generated == []          # the hourly pass keeps V3
    plan = engine.backfill_plan(anchors, store=store)
    assert plan["to_generate"] == 2 and plan["renderer"] == "cax-editorial-4"
    assert len(engine.run(anchors, store=store, now=NOW, upgrade_renderer=True).generated) == 2
    v4 = {a.asset_id: a for a in store.all() if a.asset_type == "editorial_illustration"}
    assert all(a.generation_model == "cax-editorial-4" and a.storage_key != v3[k] for k, a in v4.items())
    assert all(v3[k] in a.previous_storage_keys for k, a in v4.items())       # old URLs keep working

    # Rollback: the V3 re-render is byte-identical, so the old file comes back.
    monkeypatch.setenv("CYBERALERTX_ILLUSTRATION_RENDERER", "svg-3")
    assert engine.run(anchors, store=store, now=NOW).generated == []
    engine.run(anchors, store=store, now=NOW, upgrade_renderer=True)
    assert {a.asset_id: a.storage_key for a in store.all() if a.asset_type == "editorial_illustration"} == v3


def test_library_credit_reaches_the_public_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from cyberalertx.ai.models import ThreatPost
    from cyberalertx.intel.story import StoryView
    from cyberalertx.media import engine
    from tests.test_media import NOW, fake_intel, item
    m = item("Хакери атакували найпотужніший супер-ПК Японії: викрадено понад 4000 облікових записів", "itc.ua",
             body="Суперкомп'ютер Fugaku зазнав масштабної хакерської атаки. " * 8)
    from tests.test_media import tpost
    st = StoryView(key="s:fugaku", anchor=m, members=[m], independent_sources=["itc.ua"], posts={"en": tpost()})
    assert isinstance(st.posts["en"], ThreatPost)
    fake_intel(monkeypatch, [st])
    monkeypatch.setenv("CYBERALERTX_ILLUSTRATION_RENDERER", "editorial-4")
    store = MediaStore(tmp_path / "media")
    assert engine.run([m], store=store, now=NOW).generated == ["s:fugaku"]
    a = store.get("illus:s:fugaku")
    assert a is not None and a.source.startswith("library:fugaku-riken-r-ccs") and "CC0" in a.license
    payload = engine.illustration_payload(store, m.fingerprint)
    assert payload is not None and "CC0" in payload["credit"]["en"] and "CC0" in payload["credit"]["ua"]


def test_a_researchers_claim_is_drawn_as_proof_of_concept_not_exploitation() -> None:
    from cyberalertx.media.v4.kit import PALETTES
    from cyberalertx.media.v4.scenes.vuln_advisory import _facts, _status
    pal = PALETTES["midnight"]
    claim = replace(_brief_for("vuln_advisory"), status="attacks_observed",
                    text="researchers claim two rce exploits that bypass telegram's new android defenses")
    assert _status(_facts(claim), pal)[0] == "PROOF OF CONCEPT"
    wild = replace(claim, text="researchers found the flaw exploited in the wild against telegram users")
    assert _status(_facts(wild), pal)[0] == "EXPLOITED"


def test_photo_annotation_follows_what_the_story_states() -> None:
    off = B.build(story("Japan takes Fugaku supercomputer offline after cyberattack",
                        "RIKEN has taken the Fugaku supercomputer offline following a security breach."))
    assert off.library_id and "taken offline" in B.alt_text(off)["en"] and "accounts" not in B.alt_text(off)["en"]
    acc = B.build(story("Hackers breach Fugaku, steal more than 4,000 accounts", "Fugaku accounts were stolen."))
    assert "compromised accounts" in B.alt_text(acc)["en"]


def test_canary_rollback_rerenders_only_the_v4_images(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The documented rollback: flag back to V3, `regenerate` each V4 story, next run.
    Images of older renderers (cax-svg-2 archive) are never touched; V4 old URLs keep working."""
    from cyberalertx.media import engine
    from cyberalertx.tools import media as media_cli
    from tests.test_media import NOW, critical_story, fake_intel
    old, new = critical_story("s:old"), critical_story("s:new", products=("Gadget Hub",))
    store = MediaStore(tmp_path / "media")
    monkeypatch.setattr("cyberalertx.media.assets.MEDIA_DIR", tmp_path / "media")
    monkeypatch.delenv("CYBERALERTX_ILLUSTRATION_RENDERER", raising=False)
    fake_intel(monkeypatch, [old])
    engine.run([old.anchor], store=store, now=NOW)
    a = store.get("illus:s:old")
    assert a is not None
    a.generation_model = "cax-svg-2"                      # the archive's older renderer
    store.put(a)
    archive = (a.storage_key, a.generation_model)

    fake_intel(monkeypatch, [old, new])
    monkeypatch.setenv("CYBERALERTX_ILLUSTRATION_RENDERER", "editorial-4")    # canary
    assert engine.run([old.anchor, new.anchor], store=store, now=NOW).generated == ["s:new"]
    v4 = store.get("illus:s:new")
    assert v4 is not None and v4.generation_model == "cax-editorial-4"

    monkeypatch.setenv("CYBERALERTX_ILLUSTRATION_RENDERER", "svg-3")          # soft rollback
    assert engine.run([old.anchor, new.anchor], store=store, now=NOW).generated == []
    assert media_cli.main(["regenerate", "s:new"]) == 0                       # full rollback, one story
    assert engine.run([old.anchor, new.anchor], store=store, now=NOW).generated == ["s:new"]
    back = store.get("illus:s:new")
    assert back is not None and back.generation_model == "cax-svg-3" and v4.storage_key in back.previous_storage_keys
    keep = store.get("illus:s:old")
    assert keep is not None and (keep.storage_key, keep.generation_model) == archive


@pytest.mark.parametrize("title,scene", [
    ("Operation Endgame Takes Down Gootloader, CastleRAT and StealC Servers, Seizes 600 Domains", "police_takedown"),
    ("Police dismantle Gootloader, CastleRAT, StealC malware infrastructure", "police_takedown"),
    ("FBI agent stole $2.5 million in crypto from hackers under investigation", "crypto_theft"),
    ("Fandango says hackers stole payment card details from checkout pages", "payment_skimmer"),
    # the means (deepfake calls) is the depictable subject, not the theft
    ("FBI Says North Korean Hackers Stole Over $400 Million in Crypto Using Deepfake Video Calls", "deepfake_call"),
    # a takedown mentioned as history does not make a worm story a police action
    ("Retadup Worm Resurfaces 7 Years After Takedown to Spread CoffeeLoader Malware", "usb_worm"),
    ("Court clears brothers of $25 million Ethereum crypto heist charges", "court_case"),
])
def test_v41_routing(title: str, scene: str) -> None:
    assert B.build(story(title)).scene == scene


def test_a_cvss_score_is_not_a_flaw_count() -> None:
    assert "flaws" not in B.extract_facts("SAP fixes CVSS 10.0 flaws in NetWeaver", "", "")
    assert "flaws" not in B.extract_facts("Patch for a flaw with a CVSS score of 9.8 vulnerabilities", "", "")
    assert B.extract_facts("SAP fixes 35 flaws in NetWeaver", "", "")["flaws"] == "35"


def test_alt_text_describes_the_variant_the_scene_draws() -> None:
    leak = B.build(story("Lapsus$ hacker who leaked 90 GTA VI videos pleads guilty"))
    assert leak.scene == "court_case" and "90 leaked videos" in B.alt_text(leak)["en"]
    denied = B.build(story("Binance denies data breach after alleged ShinyHunters claims", category="breach"))
    if denied.scene == "breach_notice":
        assert "breach denied" in B.alt_text(denied)["en"]
    years = B.build(story("Ransomware affiliate suspect extradited to US, faces 27 years in prison"))
    assert "27 tally strokes" in B.alt_text(years)["en"]


def test_a_year_in_a_film_title_is_not_a_governance_story() -> None:
    assert B.build(story("Прем'єра «Того, хто біжить по лезу 2099»: як виглядали головні зірки")).scene != "governance"
    assert B.build(story("Кібербезпека — це не лише питання IT: що потрібно знати у 2027 році")).scene == "governance"


def test_a_phishing_story_about_passwords_is_not_password_policy() -> None:
    b = B.build(story("Шахраї полюють на паролі: як зловмисники використовують збій Microsoft 365 для фішингу"))
    assert b.scene in ("credential_phish", "session_theft")


# ------------------------------------------------------------------ law enforcement and headline-first subjects

UA_FRAUD = ("Нацполіція та ФБР викрили хакерів, які під виглядом фахівців ІТ-підтримки виманили понад $40,5 млн",
            "Кіберполіція спільно з ФБР викрили угруповання, яке за допомогою ШІ-платформи для дзвінків і "
            "програм-вимагачів викрадало дані.")


@pytest.mark.parametrize("title,body", [
    UA_FRAUD,
    ("Кіберполіція затримала хакерів, які атакували банки", ""),
    ("Правоохоронці заарештували адміністратора ботнету", ""),
    ("Police arrest suspected admin of ransomware gang", ""),
    ("FBI busts crypto fraud ring that stole $10 million", ""),
    ("Europol and FBI dismantle phishing-as-a-service platform", ""),
])
def test_law_enforcement_headlines_route_to_the_police_scene(title: str, body: str) -> None:
    assert B.build(story(title, body)).scene == "police_takedown"


@pytest.mark.parametrize("title,body", [
    ("Critical flaw exposed 10,000 servers to remote takeover", "The vulnerability exposed admin panels."),
    ("Researchers uncover new Android banking trojan", ""),
    ("Operation ShadowCloud: cloud service-based backdoors targeting government networks", ""),
    # the body mentions police, the headline is about a vulnerability: the headline decides
    ("Apache patches critical RCE flaw", "Police in several countries urged admins to update after arrests."),
])
def test_exposed_and_operation_names_alone_are_not_police_actions(title: str, body: str) -> None:
    assert B.build(story(title, body)).scene != "police_takedown"


def test_exposure_story_keeps_the_ai_fact_as_secondary_context() -> None:
    from cyberalertx.media.v4.scenes.police_takedown import _action, _actors, _ai_calls, _seizure
    b = B.build(story(*UA_FRAUD))
    assert _action(b) == "EXPOSED" and _actors(b) == ["National Police", "FBI"] and not _seizure(b)
    assert _ai_calls(b)                                   # sourced: "ШІ-платформи для дзвінків"
    alt = B.alt_text(b)["en"]
    assert "exposed" in alt and "FBI" in alt
    svg = render(b)
    sanitize_svg(svg.encode())


def test_a_body_word_never_becomes_the_fallback_subject() -> None:
    from cyberalertx.media.v4.scenes.dossier import _subject
    b = replace(B.build(story("Хакери атакували мережу міської лікарні",
                              "Зловмисники використали ШІ для генерації листів.")), scene="dossier")
    lead, _ = _subject(b)
    assert lead != "AI"                                    # AI is only in the body
    b2 = replace(B.build(story("Штучний інтелект змінює кібербезпеку", "")), scene="dossier")
    assert _subject(b2)[0] == "AI"                         # in the headline: it is the subject


def test_names_from_our_headline_count_only_when_the_source_contains_them() -> None:
    body = ("At least 178 top web destinations served malware exploits against visitors, injected into sites "
            "like the BBC, CNN, Equifax, Ledger and Zoom via Optimizely.")
    b = B.build(story("Attackers Used Optimizely to A/B Test Malware on Top Websites", body,
                      post="BBC, CNN and Zoom among 178 sites that served malware via Optimizely"))
    assert b.scene == "third_party_script"
    assert {"BBC", "CNN", "Zoom"} <= set(b.entities) and b.facts.get("sites") == "178"
    # a name only in our headline, not in the source, is never drawn
    b2 = B.build(story("Attackers Used Optimizely to A/B Test Malware on Top Websites", body,
                       post="Acme and BBC among sites that served malware via Optimizely"))
    assert "Acme" not in b2.entities


def test_script_scene_alt_text_names_what_is_drawn() -> None:
    body = ("At least 178 top web destinations served malware exploits against visitors, injected into sites "
            "like the BBC, CNN, Equifax, Ledger and Zoom via Optimizely.")
    b = B.build(story("Attackers Used Optimizely to A/B Test Malware on Top Websites", body, category="malware",
                      post="BBC, CNN and Zoom among 178 sites that served malware via Optimizely"))
    b = replace(b, status="compromise")
    en = B.alt_text(b)["en"]
    assert "178 websites" in en and "BBC" in en and "visitors" in en and "Optimizely" in en


# ------------------------------------------------------------------ O54: entity labels and alt-text integrity

CREDIT_UNIONS = ("Data breach impacts 40 Irish credit unions in reported IT provider hack",
                 "A cyberattack on IT provider Wellington IT exposed sensitive data belonging to members of 50 "
                 "credit unions, most of them in Ireland.")
CREDIT_UNIONS_POST = "Irish credit union members' data exposed after attack on supplier Wellington IT"


@pytest.mark.parametrize("title,context,never", [
    ("Data breach impacts 40 Irish credit unions in reported IT provider hack", "", {"IT", "Irish"}),
    ("Scammers used an AI platform for calls to pose as bank staff", "", {"AI"}),
    ("Fraudsters Used AI Platform for Calls to Drain Accounts", "fraudsters used an ai platform for calls", {"AI"}),
    ("Apache warns of Roller RCE vulnerability exploited in attacks", "", {"RCE", "Roller RCE"}),
    ("Google patches AMD Turin CPU flaw in cloud VMs", "", {"CPU", "Turin CPU"}),
    ("Chinese hackers breach Japanese retailer's security software vendor", "", {"Chinese", "Japanese"}),
])
def test_generic_tokens_never_become_entities(title: str, context: str, never: set[str]) -> None:
    got = set(B.extract_entities(title, context))
    assert not (got & never), got


@pytest.mark.parametrize("title,context,name", [
    ("Irish credit union members' data exposed after attack on supplier Wellington IT",
     "a cyberattack on IT provider Wellington IT exposed data", "Wellington IT"),
    ("Scale AI exposes contractor data", "Scale AI said the files were public", "Scale AI"),
    ("Cursor extension key issued to Fireworks AI was stolen", "the key we had issued to Fireworks AI", "Fireworks AI"),
    ("IT-Harvest report tracks 3,000 security vendors", "", "IT-Harvest"),
])
def test_genuine_names_that_contain_generic_words_stay_whole(title: str, context: str, name: str) -> None:
    assert name in B.extract_entities(title, context)


def test_a_generic_suffix_joins_a_name_only_when_the_source_writes_the_compound() -> None:
    # "Acme AI" never appears in the source: "AI" stays a common noun
    assert B.extract_entities("Acme AI assistant leaks chats", "acme's assistant leaked chats") == ["Acme"]


def test_names_only_in_the_article_body_are_never_entities() -> None:
    b = B.build(story("Data breach at third-party provider hits clinic patients",
                      "Microsoft and Wellington IT were not involved, the clinic said."))
    assert "Microsoft" not in b.entities and "Wellington IT" not in b.entities


def test_mentions_is_a_whole_word_test() -> None:
    assert B.mentions("IT", "it provider hack") and not B.mentions("IT", "with credit unions")
    assert not B.mentions("Roller", "high rollers lose") and B.mentions("Baker Tilly", "baker tilly notifies")


def _credit_union_brief() -> B.EditorialBrief:
    return replace(B.build(story(*CREDIT_UNIONS, post=CREDIT_UNIONS_POST)), status="compromise")


def test_credit_union_breach_shows_the_count_and_the_supplier_never_an_it_sender() -> None:
    from cyberalertx.media.v4.render import render_doc
    from cyberalertx.media.v4.scenes.breach_notice import _plan
    b = _credit_union_brief()
    assert b.scene == "breach_notice"
    assert b.facts["orgs"] == "40" and b.facts["orgs_noun"] == "Irish credit unions"
    assert b.entities == ("Wellington IT",)
    pl = _plan(b)
    assert (pl.figure, pl.noun, pl.sender) == ("40", "Irish credit unions", "")
    assert pl.stamp == ("IT PROVIDER HACK", "Wellington IT")
    labels = render_doc(b).labels
    assert "IT" not in labels and "40" in labels and "Irish credit unions" in labels
    alt = B.alt_text(b)
    assert "40 Irish credit unions" in alt["en"] and "Wellington IT" in alt["en"] and "Wellington IT" in alt["ua"]
    assert "number of people" not in alt["en"]


def test_an_unnamed_supplier_is_stamped_without_a_name() -> None:
    from cyberalertx.media.v4.render import render_doc
    from cyberalertx.media.v4.scenes.breach_notice import _plan
    b = replace(B.build(story("Baker Tilly notifies clients of data breach at third-party provider",
                              "Baker Tilly Advisory Group is notifying clients that a breach at a third-party "
                              "provider compromised personal information.")), status="compromise")
    pl = _plan(b)
    assert pl.sender == "Baker Tilly"                    # the notifier, joined, never "Tilly" or "Baker"
    assert pl.stamp == ("SUPPLIER BREACH", "")           # the source's own word; no invented supplier name
    labels = render_doc(b).labels
    assert "Baker" not in labels and "Tilly" not in labels and "Baker Tilly" in labels
    assert "supplier's name" not in B.alt_text(b)["en"]


def test_a_breach_with_no_supplier_and_no_name_draws_no_orphan_caption() -> None:
    from cyberalertx.media.v4.render import render_doc
    b = replace(B.build(story("Data breach exposes customer information", "")), scene="breach_notice",
                palette=B.SPECS["breach_notice"].palette, status="compromise", entities=())
    doc = render_doc(b)
    assert doc.labels == []
    assert "number" not in B.alt_text(b)["en"]


def test_money_keeps_the_sources_qualifier_and_decimal_point() -> None:
    f = B.extract_facts("Нацполіція та ФБР викрили хакерів, які виманили понад $40,5 млн", "", "")
    assert f["money"] == "$40.5M" and f["money_plus"]
    assert B.extract_facts("Firm lost $1,500 in the scam", "", "")["money"] == "$1,500"


def test_police_tag_reads_over_and_alt_names_only_drawn_tags() -> None:
    from cyberalertx.media.v4.consistency import check_brief
    from cyberalertx.media.v4.render import render_doc
    b = B.build(story(*UA_FRAUD))
    doc = render_doc(b)
    assert any(x.startswith("OVER $") for x in doc.labels)
    alt = B.alt_text(b)
    assert "OVER $" in alt["en"] and "reported figures" not in alt["en"]
    assert check_brief(b, doc.labels) == []


@pytest.mark.parametrize("alt,labels,problem", [
    ({"en": "Illustration: an envelope and the number of people affected."}, ["customer data"],
     "claims a figure"),
    ({"en": "Illustration: an envelope marked '150,000 drivers'."}, ["drivers"], "number '150,000'"),
    ({"en": "Illustration: an envelope addressed from IT."}, ["IT"], ""),            # generic: not a name
    ({"en": "Illustration: an envelope addressed from Acme."}, ["customer data"], "name 'Acme'"),
    ({"ua": "Ілюстрація: конверт з написом «Wellington IT»."}, ["40"], "quoted label 'Wellington IT'"),
    ({"en": "Illustration: an envelope marked '40 Irish credit unions'."}, ["40", "Irish credit unions"], ""),
    ({"en": "Photograph: the machine hall. Photo: Barsaka2, Wikimedia Commons (CC0)."}, [], ""),
])
def test_alt_consistency_check(alt: dict[str, str], labels: list[str], problem: str) -> None:
    from cyberalertx.media.v4.consistency import check
    got = check(alt, labels)
    assert (any(problem in p for p in got) if problem else got == []), got


@pytest.mark.parametrize("scene", [s.id for s in B.CATALOGUE] + ["dossier", "hpc_drawn"])
def test_every_scene_alt_text_matches_what_it_draws(scene: str) -> None:
    from cyberalertx.media.v4.consistency import check_brief
    from cyberalertx.media.v4.render import render_doc
    for facts in ({}, {"cves": ["CVE-2026-1111"], "money": "$25M", "people": "150,000", "orgs": "12",
                       "orgs_noun": "hospitals", "accounts": "4,000", "years": "27", "videos": "90", "flaws": "17"}):
        for entities in ((), ("Widget", "Acme")):
            for status in ("not_reported", "compromise", "exploited", "attacks_observed"):
                b = _brief_for(scene, facts=facts, entities=entities, status=status)
                assert check_brief(b, render_doc(b).labels) == [], (facts, entities, status)


def test_alt_text_is_refreshed_only_for_an_image_drawn_byte_for_byte(monkeypatch: pytest.MonkeyPatch,
                                                                      tmp_path: Path) -> None:
    from cyberalertx.media import engine
    from cyberalertx.media.renderer import Plan
    plan = Plan("cax-editorial-4", _brief_for("vuln_advisory"), {"en": "new", "ua": "нове"}, "h")
    import hashlib
    data = engine.render_plan(plan)
    same = SimpleNamespace(generation_method="svg", generation_model="cax-editorial-4",
                           storage_key=hashlib.sha256(data).hexdigest() + ".svg")
    other = SimpleNamespace(generation_method="svg", generation_model="cax-editorial-4",
                            storage_key="0" * 64 + ".svg")
    assert engine._draws_stored_image(plan, same)          # type: ignore[arg-type]
    assert not engine._draws_stored_image(plan, other)     # type: ignore[arg-type]


def test_advisory_alt_names_the_drawn_status_not_patch_status() -> None:
    b = B.build(story("Apache warns of Roller RCE vulnerability exploited in attacks",
                      "Apache has released security updates to address a critical Roller flaw that threat actors "
                      "are exploiting."))
    assert b.scene == "vuln_advisory"
    en = B.alt_text(b)["en"]
    assert "'EXPLOITED'" in en and "'CRITICAL'" in en and "patch status" not in en


def test_sites_alt_mentions_the_phone_only_when_it_is_drawn() -> None:
    title = "IKEA, Salesforce and Zoom websites hacked to push malware"
    plain = replace(B.build(story(title, "Visitors were redirected.")), scene="compromised_sites",
                    status="compromise", entities=("IKEA", "Salesforce", "Zoom"))
    assert "phone" not in B.alt_text(plain)["en"]
    ios = replace(plain, text=plain.text + " iphone users were targeted")
    assert "phone" in B.alt_text(ios)["en"]


def test_ics_alt_names_an_identifier_only_when_one_is_drawn() -> None:
    b = _brief_for("ics_controller", facts={})
    assert "'ADVISORY'" in B.alt_text(b)["en"] and "identifier" not in B.alt_text(b)["en"]
    b2 = _brief_for("ics_controller", facts={"cves": ["CVE-2026-1111"]})
    assert "CVE-2026-1111" in B.alt_text(b2)["en"]


# ------------------------------------------------------------------ hybrid policy: confidence routing (V4.1.2)

def _plan(monkeypatch: pytest.MonkeyPatch, title: str, body: str = "", **kw: Any) -> Any:
    from cyberalertx.media import renderer
    monkeypatch.setenv("CYBERALERTX_ILLUSTRATION_RENDERER", "editorial-4")
    return renderer.plan_for(story(title, body, **kw))


@pytest.mark.parametrize("title,body,scene", [
    ("Apache warns of Roller RCE vulnerability exploited in attacks", "critical flaw exploited", "vuln_advisory"),
    (*CREDIT_UNIONS, "breach_notice"),
    ("Uber notifies drivers of data breach affecting nearly 150,000 people", "", "breach_notice"),
    (*UA_FRAUD, "police_takedown"),
    ("Кіберполіція затримала хакерів, які атакували банки", "", "police_takedown"),
    ("Police arrest suspected admin of ransomware gang", "", "police_takedown"),
    ("Europol and FBI dismantle phishing-as-a-service platform", "", "police_takedown"),
])
def test_confident_scenes_are_drawn_by_v4(monkeypatch: pytest.MonkeyPatch, title: str, body: str,
                                          scene: str) -> None:
    from cyberalertx.media.v4.consistency import check_brief
    from cyberalertx.media.v4.render import render_doc
    plan = _plan(monkeypatch, title, body)
    assert plan.renderer == "cax-editorial-4" and plan.routed == ""
    assert plan.brief.scene == scene and plan.brief.confidence in ("high", "medium")
    labels = render_doc(plan.brief).labels
    assert check_brief(plan.brief, labels) == []                    # alt text matches the drawn labels
    assert not {"IT", "AI", "RCE"} & set(labels) and not {"IT", "AI", "RCE"} & set(plan.brief.entities)


@pytest.mark.parametrize("title,body", [
    ("What security teams should plan for next year", ""),
    ("Why AI matters for security leaders", ""),                    # "AI" alone: no scene, no name
    # headline/body conflict: the body's scene words cannot pull a vague headline into a scene
    ("Hospital chain says a fire alarm fault disrupted services",
     "Attackers used ransomware to encrypt files at another firm, researchers said."),
])
def test_low_confidence_stories_stay_on_v3(monkeypatch: pytest.MonkeyPatch, title: str, body: str) -> None:
    from cyberalertx.media import renderer
    plan = _plan(monkeypatch, title, body)
    assert plan.renderer == "cax-svg-3" and "low-confidence" in plan.routed
    v3 = renderer.plan_for(story(title, body), renderer.V3)
    # exactly the V3 plan: same alt text and inputs hash, so a V3 image is reused, never redrawn
    assert (plan.alt, plan.inputs_hash) == (v3.alt, v3.inputs_hash)
    assert "AI" not in B.build(story(title, body)).entities


def test_headline_decides_over_the_body_in_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    # police headline, AI only in the body: V4 police scene, AI as secondary context only
    plan = _plan(monkeypatch, *UA_FRAUD)
    assert plan.renderer == "cax-editorial-4" and plan.brief.scene == "police_takedown"
    # vulnerability headline, police only in the body: V4 advisory, never the police scene
    plan2 = _plan(monkeypatch, "Apache patches critical RCE flaw",
                  "Police in several countries urged admins to update after arrests.")
    assert plan2.brief.scene != "police_takedown"


def test_canary_draws_confident_stories_with_v4_and_keeps_weak_ones_on_v3(monkeypatch: pytest.MonkeyPatch,
                                                                          tmp_path: Path) -> None:
    from cyberalertx.media import engine
    from tests.test_media import NOW, critical_story, fake_intel
    strong = critical_story("s:strong")
    weak = critical_story("s:weak")
    weak.anchor.title, weak.anchor.raw_content = "What security teams should plan for next year", ""
    store = MediaStore(tmp_path / "media")
    anchors = [strong.anchor, weak.anchor]
    monkeypatch.delenv("CYBERALERTX_ILLUSTRATION_RENDERER", raising=False)
    fake_intel(monkeypatch, [weak])
    engine.run([weak.anchor], store=store, now=NOW)                        # the weak story already has V3
    fake_intel(monkeypatch, [strong, weak])
    before = store.get("illus:s:weak")
    assert before is not None and before.generation_model == "cax-svg-3"

    monkeypatch.setenv("CYBERALERTX_ILLUSTRATION_RENDERER", "editorial-4")
    res = engine.run(anchors, store=store, now=NOW)
    assert res.generated == ["s:strong"]                                   # the weak V3 image is reused
    assert store.get("illus:s:strong").generation_model == "cax-editorial-4"  # type: ignore[union-attr]
    after = store.get("illus:s:weak")
    assert after is not None and (after.storage_key, after.generation_model) == (before.storage_key, "cax-svg-3")
    # a brand-new weak story under the canary is drawn by V3
    new = critical_story("s:new-weak")
    new.anchor.title, new.anchor.raw_content = "Why AI matters for security leaders", ""
    fake_intel(monkeypatch, [strong, weak, new])
    assert engine.run(anchors + [new.anchor], store=store, now=NOW).generated == ["s:new-weak"]
    assert store.get("illus:s:new-weak").generation_model == "cax-svg-3"   # type: ignore[union-attr]


# ------------------------------------------------------------------ O55: advisories are never drawn as incidents

F5 = ("F5 Warns 6 Critical BIG-IP Flaws Can Crash Traffic in Specific Setups, May Allow RCE",
      "F5 has disclosed six critical BIG-IP flaws that let unauthenticated attackers crash TMM on certain iRule or "
      "APM setups, possibly allowing RCE.")


@pytest.mark.parametrize("title,body", [
    F5,
    ("Critical Pre-Auth MongoDB Flaw (CVE-2026-118383) Can Crash Lagging Servers on Failover",
     "A MongoDB fix stops a crash that hits replica set servers after failover."),
    ("Citrix Patches 12 NetScaler and Secure Access Client Flaws, Including Authentication Bypass", ""),
    ("New NoisyTCP vulnerability lets attackers crash Linux servers", ""),
    ("Researchers publish exploit for critical RCE flaw in Fortinet FortiGate", ""),       # a PoC is not an attack
    ("Critical Ivanti EPMM flaw could let attackers crash devices, patch now", ""),
    ("Microsoft попереджає про критичну вразливість, яка може призвести до збою серверів", ""),
])
def test_an_advisory_is_drawn_as_exposure_not_as_an_incident(title: str, body: str) -> None:
    b = B.build(story(title, body))
    assert b.status not in B.ATTACK_STATUSES
    assert B.advisory_without_incident(title, b.status)
    assert b.scene not in B.INCIDENT_SCENES, (b.scene, b.evidence)
    assert b.scene == "vuln_advisory"


@pytest.mark.parametrize("title,scene", [
    ("Hackers exploit Citrix flaw to deploy wiper on ESXi hosts", "edge_wiper"),
    ("Attackers exploit F5 BIG-IP flaw to crash servers in ongoing DDoS campaign", "kernel_dos"),
    ("Uber notifies drivers of data breach affecting nearly 150,000 people", "breach_notice"),
])
def test_incidents_with_evidence_keep_their_incident_scene(title: str, scene: str) -> None:
    assert B.build(story(title)).scene == scene


@pytest.mark.parametrize("status,allowed", [("not_reported", False), ("exploited", True), ("confirmed", True),
                                            ("attacks_observed", True), ("compromise", True)])
def test_exploitation_evidence_reopens_incident_scenes_for_an_advisory(status: str, allowed: bool) -> None:
    assert B.advisory_without_incident(F5[0], status) is not allowed


def test_f5_advisory_image_and_alt_show_the_disclosed_flaws() -> None:
    from cyberalertx.media.v4.consistency import check_brief
    from cyberalertx.media.v4.render import render_doc
    b = B.build(story(*F5))
    labels = render_doc(b).labels
    assert any("F5" in x for x in labels) and any("BIG-IP" in x for x in labels)
    assert "DISCLOSED" in labels and "EXPLOITED" not in labels
    assert check_brief(b, labels) == [] and "'DISCLOSED'" in B.alt_text(b)["en"]


def test_attack_preconditions_and_cve_ids_are_not_product_names() -> None:
    from cyberalertx.media.v4.render import render_doc
    b = B.build(story("Critical Pre-Auth MongoDB Flaw (CVE-2026-118383) Can Crash Lagging Servers on Failover",
                      "A MongoDB fix stops a crash that hits replica set servers after failover."))
    labels = render_doc(b).labels
    assert "MongoDB" in labels and not any("Pre-Auth" in x for x in labels)
    assert sum(x == "CVE-2026-118383" for x in labels) == 1


# ------------------------------------------------------------------ O56: police roles (actor, group, object, action)

def _police(title: str, body: str = "") -> tuple[B.EditorialBrief, list[str], str]:
    from cyberalertx.media.v4.consistency import check_brief
    from cyberalertx.media.v4.render import render_doc
    b = B.build(story(title, body))
    labels = render_doc(b).labels
    assert b.scene == "police_takedown", (b.scene, b.evidence)
    assert check_brief(b, labels) == []
    return b, labels, B.alt_text(b)["en"]


def test_o56_arrest_is_never_drawn_as_a_seizure_and_a_country_is_never_seized() -> None:
    b, labels, alt = _police("Ukraine, FBI arrest ransomware gang members tied to $40M in ransoms",
                             "Ukrainian authorities and the FBI detained four suspected members of an international "
                             "ransomware operation tied to over $40.5M in ransoms from at least 28 firms.")
    assert "SEIZED" not in labels and "Ukraine" not in labels           # no seizure; Ukraine is no object
    assert "ARRESTED" in labels and "Ukrainian authorities + FBI" in labels and "RANSOMWARE GANG" in labels
    assert "OVER $40.5M" in labels and "in ransoms" in labels           # the source's precise figure
    assert "case file labelled 'RANSOMWARE GANG'" in alt and "'arrested'" in alt
    assert "Ukrainian authorities and FBI" in alt


@pytest.mark.parametrize("title,authority,group", [
    ("Кіберполіція затримала хакерів, які атакували банки", "Cyber Police", "HACKERS"),
    ("Police arrest suspected admin of ransomware gang", "Police", "RANSOMWARE GANG"),
    ("Правоохоронці заарештували адміністратора ботнету", "Police", "BOTNET OPERATORS"),
])
def test_arrests_without_a_seizure_show_the_group_and_the_authority(title: str, authority: str, group: str) -> None:
    _, labels, alt = _police(title)
    assert "SEIZED" not in labels and "ARRESTED" in labels
    assert authority in labels and group in labels and "phone" not in alt


def test_the_phone_appears_only_when_calls_are_the_stated_channel() -> None:
    _, labels, alt = _police(*UA_FRAUD)
    assert "incoming call" in labels and "IT SUPPORT" in labels and "phone" in alt


@pytest.mark.parametrize("title,word,seized", [
    ("Operation Endgame Takes Down Gootloader, CastleRAT and StealC Servers, Seizes 6.4M Stolen Logins",
     "SEIZED", ["Gootloader", "CastleRAT", "StealC"]),
    ("Police dismantle Gootloader, CastleRAT, StealC malware infrastructure", "TAKEN DOWN",
     ["Gootloader", "CastleRAT", "StealC"]),
    ("Europol and Ukraine take down DanaBot infrastructure", "TAKEN DOWN", ["DanaBot"]),
    ("FBI and Dutch police seize Rhysida leak site, arrest two admins in Germany", "SEIZED", ["Rhysida"]),
])
def test_stated_seizures_and_takedowns_keep_the_rack_with_their_own_action(title: str, word: str,
                                                                             seized: list[str]) -> None:
    from cyberalertx.media.v4.scenes.police_takedown import _authorities, _seized_names
    b, labels, alt = _police(title, "Law enforcement took Gootloader, CastleRAT, StealC, DanaBot and Rhysida "
                                    "infrastructure offline.")
    assert word in labels and (word == "SEIZED" or "SEIZED" not in labels)
    assert _seized_names(b) == seized
    for place_or_agency in ("Ukraine", "Europol", "Dutch", "Germany", "FBI", "Police"):
        assert place_or_agency not in _seized_names(b)
    assert "server rack" in alt and f"'{word.lower()}'" in alt
    if "Europol and Ukraine" in title:
        assert _authorities(b) == ["Ukraine", "Europol"]


# ------------------------------------------------------------------ QA sweep (19 Nov): scene and label integrity

@pytest.mark.parametrize("title,body,never", [
    ("Railway breach leads to $740,000 in fraudulent AI charges", "", "court_case"),          # billing charges
    ("Blind Eagle Uses Fake Court Notices to Deliver Remote Access Trojan Across Latin America", "", "court_case"),
    ("Забудьте про крадіжки відеокарт: у Бразилії бізнесмен намагався підірвати конкурента бомбою в Xbox 360",
     "", "gpu_cryptominer"),                                                                     # a hook, not mining
    ("Check Point warns of zero-day flaw exploited for root access", "", "edge_wiper"),        # no wiper stated
    ("Russian Turla Hackers Use New Cereal Malware to Steal Emails From Government Exchange Servers", "",
     "espionage_backdoor"),                                                                      # no cloud service
    ("Отруєне оновлення: хакери атакували Quantum Systems, яка постачає дрони Україні", "", "dev_supply_chain"),
    ("Who Runs the Ransomware Group Qilin?", "", "ransomware_impact"),                          # a profile
    ("Ransomware recovery is now a client retention metric", "Kaseya examines recovery tools.", "ransomware_impact"),
])
def test_a_scene_needs_its_subject_in_the_headline_and_damage_needs_an_incident(title: str, body: str,
                                                                               never: str) -> None:
    assert B.build(story(title, body)).scene != never


@pytest.mark.parametrize("title,scene", [
    ("British Scattered Spider hacker sentenced to 6 years in prison", "court_case"),
    ("SANSAR Linux Cryptomining Malware Uses Modified NVIDIA Library to Hide GPU Activity", "gpu_cryptominer"),
    ("Check Point gateways hacked via PHP2Shell to deploy VMware ESXi wiper", "edge_wiper"),
    ("Operation ShadowCloud: cloud service-based backdoors targeting government networks in Asia", "espionage_backdoor"),
    ("Stolen Fireworks AI Key Led to Cursor Data Breach and Trojanized Claude Code Extension", "dev_supply_chain"),
])
def test_scenes_whose_subject_is_stated_still_apply(title: str, scene: str) -> None:
    assert B.build(story(title)).scene == scene


def test_an_imposed_sentence_is_not_a_maximum_the_defendant_faces() -> None:
    from cyberalertx.media.v4.render import render_doc
    b = B.build(story("British Scattered Spider hacker sentenced to 6 years in prison",
                      "A court sentenced him to six years."))
    labels = render_doc(b).labels
    assert "FACES UP TO" not in labels and "PRISON SENTENCE" in labels
    assert "sentence handed down" in B.alt_text(b)["en"] and "faces" not in B.alt_text(b)["en"]
    b2 = B.build(story("Ransomware affiliate suspect extradited to US, faces 27 years in prison"))
    assert "FACES UP TO" in render_doc(b2).labels


def _adv(title: str, body: str = "", status: str | None = None) -> list[str]:
    from cyberalertx.media.v4.render import render_doc
    b = B.build(story(title, body))
    if status:
        b = replace(b, status=status)
    assert b.scene == "vuln_advisory", (b.scene, b.evidence)
    return render_doc(b).labels


def test_fixes_announced_as_coming_are_not_a_patch() -> None:
    labels = _adv("PHP Warns of Critical Security Flaws Affecting All Supported Versions, Fixes Coming November 19",
                  "PHP maintainers say fixes are coming on November 19.")
    assert "PATCH AVAILABLE" not in labels and "DISCLOSED" in labels and "PHP" in labels
    # an appeal to patch is not a statement that a fix exists (owner review, 19 Nov)
    urged = _adv("CISA Urges Immediate Patching of Java4Shell Flaw That Could Allow RCE")
    assert "PATCHING URGED" in urged and "PATCH AVAILABLE" not in urged
    assert "PATCH AVAILABLE" in _adv("10-Year-Old NGINX HTTP/2 Flaw Lets Unauthenticated Attackers Execute Code",
                                     "Fixed versions 1.31.9 and 1.30.7 came out today.")


def test_a_kev_list_of_several_vendors_is_the_catalogue_not_one_vendor() -> None:
    labels = _adv("CISA Adds Four Known Exploited Vulnerabilities to Catalog",
                  "CISA has added four new vulnerabilities to its Known Exploited Vulnerabilities (KEV) Catalog. "
                  "CVE-2024-10441 Synology DiskStation Manager CVE-2026-40217 BerriAI LiteLLM "
                  "CVE-2026-90436 Apache Axis CVE-2026-90817 REDCap", status="confirmed")
    assert "CISA KEV" in labels and "Synology" not in labels


def test_a_cve_is_never_drawn_under_a_product_it_is_not_tied_to() -> None:
    labels = _adv("CISA Warns of Active Exploitation of OpenSSH, GPUStack, FreeSWITCH, and IBM Flaws",
                  "CISA added four flaws impacting GPUStack, SignalWire FreeSwitch, OpenBSD OpenSSH and IBM Aspera "
                  "Faspex to its catalog, citing active exploitation. The vulnerabilities are listed below - "
                  "CVE-2026-123218 (CVSS score: 9.8) - An incorrect authorization vulnerability in GPUStack",
                  status="confirmed")
    assert "CVE-2026-123218" not in labels or "CISA KEV" in labels       # never under OpenSSH


def test_a_kev_story_naming_several_vendors_only_in_the_body_is_the_catalogue() -> None:
    labels = _adv("CISA Warns of Active Exploitation of OpenSSH, GPUStack, FreeSWITCH, and IBM Flaws",
                  "CISA on Monday added four security flaws impacting GPUStack, SignalWire FreeSwitch, OpenBSD "
                  "OpenSSH, and IBM Aspera Faspex to its Known Exploited Vulnerabilities (KEV) catalog. "
                  "CVE-2026-123218 (CVSS score: 9.8)", status="confirmed")
    assert "CISA KEV" in labels and "OpenSSH" not in labels


@pytest.mark.parametrize("title,never", [
    ("Binance warns of iOS flaw that could leak crypto wallet secrets", "Binance"),        # the warner
    ("Google patches eighth Chrome zero-day exploited in attacks this year", "+ Google"),   # the vendor-reporter
])
def test_a_warner_or_reporter_is_not_the_affected_product(title: str, never: str) -> None:
    from cyberalertx.media.v4.render import render_doc
    b = B.build(story(title))
    assert never not in render_doc(b).labels


def test_hackers_targeting_a_product_is_exploitation() -> None:
    labels = _adv("Hackers Target Qlik Sense Servers With Reverse Shells, Stage ActiveMQ and Veeam Exploits",
                  status="suspected")
    assert "EXPLOITED" in labels and "DISCLOSED" not in labels


def test_disclosed_flaws_are_not_drawn_as_patched() -> None:
    from cyberalertx.media.v4.render import render_doc
    b = replace(B.build(story("N-able Takes N-central Cloud Offline After Researcher Discloses 33 Zero-Days",
                              "the public disclosure of over 30 vulnerabilities")), scene="rmm_console")
    labels = render_doc(b).labels
    assert "30+ flaws disclosed" in labels and not any("patched" in x for x in labels)


def test_a_picture_that_names_nothing_of_the_story_stays_on_v3(monkeypatch: pytest.MonkeyPatch) -> None:
    from cyberalertx.media import renderer
    plan = _plan(monkeypatch, "Російські хакери здійснили першу повністю автоматизовану ШІ-атаку",
                 "Штучний інтелект провів кібератаку без участі людини.")
    assert plan.renderer == "cax-svg-3"                                   # unlabelled gears: not recognisable
    fugaku = renderer.plan_for(story("Japan takes Fugaku supercomputer offline after cyberattack",
                                     "RIKEN took Fugaku offline after a security breach."))
    assert fugaku.renderer == "cax-editorial-4"                           # a verified photo of the subject


# ------------------------------------------------------------------ canary 5 review fixes

def test_a_protocol_version_stays_in_the_product_name_and_never_stands_alone() -> None:
    from cyberalertx.media.v4.render import render_doc
    labels = render_doc(B.build(story("10-Year-Old NGINX HTTP/2 Flaw Lets Unauthenticated Attackers Execute Code",
                                      "A flaw in NGINX's HTTP/2 support. Fixed versions 1.31.9 and 1.30.7 came out "
                                      "today."))).labels
    assert "NGINX HTTP/2" in labels and "NGINX HTTP" not in labels
    labels2 = render_doc(B.build(story("Apache HTTP Server patches critical HTTP/2 remote code execution flaw"))).labels
    assert not any(x.startswith("+") and "HTTP/2" in x for x in labels2)


def test_kev_alt_text_lists_every_cve_the_catalogue_draws() -> None:
    from cyberalertx.media.v4.consistency import check_brief
    from cyberalertx.media.v4.render import render_doc
    body = ("CISA has added new vulnerabilities to its Known Exploited Vulnerabilities (KEV) Catalog. "
            "CVE-2026-1001 Acme CVE-2026-1002 Beta CVE-2026-1003 Gamma CVE-2026-1004 Delta")
    b = replace(B.build(story("CISA Adds Four Known Exploited Vulnerabilities to Catalog", body)), status="confirmed")
    alt = B.alt_text(b)["en"]
    assert all(f"CVE-2026-100{i}" in alt for i in range(1, 5))
    assert check_brief(b, render_doc(b).labels) == []
    b6 = replace(B.build(story("CISA Adds Six Known Exploited Vulnerabilities to Catalog", body)), status="confirmed")
    labels6 = render_doc(b6).labels
    assert "+2 more" in labels6 and "'+2 more'" in B.alt_text(b6)["en"]
    assert check_brief(b6, labels6) == []


def test_a_figure_from_our_summary_is_never_drawn_even_if_another_subject_shares_it() -> None:
    # Oracle's 11 Java SE fixes are a different subject from CVE-2026-114938 (owner review, 19 Nov)
    from types import SimpleNamespace as NS
    s = story("CISA Urges Immediate Patching of Java4Shell Flaw That Could Allow Remote Code Execution",
              "CISA has urged organizations to immediately patch a newly disclosed critical security flaw impacting "
              "Oracle Java. The flaw, tracked as CVE-2026-114938 (CVSS score: 8.1).",
              post="Oracle's Java update targets 11 flaws reachable without any login")
    s.members = [s.anchor, NS(title="Oracle to Patch 11 Java Flaws Today", raw_content="The 11 vulnerabilities")]
    from cyberalertx.media.v4.render import render_doc
    b = B.build(s)
    labels = render_doc(b).labels
    assert "flaws" not in b.facts and "11" not in labels
    assert "PATCHING URGED" in labels and "PATCH AVAILABLE" not in labels      # urged; availability not stated
    assert "CVE-2026-114938" in labels and not any("Oracle" in x for x in labels)
    assert "'PATCHING URGED'" in B.alt_text(b)["en"]


def test_a_cve_from_our_summary_stays_only_when_a_source_contains_it() -> None:
    from types import SimpleNamespace as NS
    s = story("Google patches eighth Chrome zero-day exploited in attacks this year", "Google fixed a zero-day.",
              post="Chrome zero-day CVE-2026-125350 exploited")
    assert "cves" not in B.build(s).facts
    s.members = [s.anchor, NS(title="Chrome update", raw_content="tracked as CVE-2026-125350")]
    assert B.build(s).facts.get("cves") == ["CVE-2026-125350"]


def test_the_ukraine_arrest_names_the_authorities_and_the_precise_amount() -> None:
    b, labels, alt = _police("Ukraine, FBI arrest ransomware gang members tied to $40M in ransoms",
                             "Ukrainian authorities, working with the FBI, have arrested four suspected members of an "
                             "international ransomware organization linked to more than $40.5 million in ransom "
                             "payments from at least 28 companies worldwide.")
    assert "Ukrainian authorities + FBI" in labels and "OVER $40.5M" in labels and "$40M" not in labels
    assert "Ukrainian authorities and FBI" in alt and "'OVER $40.5M in ransoms'" in alt


def test_a_precise_headline_amount_keeps_its_own_qualifier() -> None:
    f = B.extract_facts("Нацполіція та ФБР викрили хакерів, які виманили понад $40,5 млн",
                        "Угруповання виманило $40,5 млн у жертв.", "")
    assert f["money"] == "$40.5M" and f["money_plus"]


def test_counts_step_over_hyphenated_product_names() -> None:
    assert B.extract_facts("N-able Patches 17 N-central Flaws", "", "")["flaws"] == "17"


# ------------------------------------------------------------------ supply chain: registries vs extensions vs signing keys

PYPI = ("Microsoft’s Agent Framework PyPI package compromised to steal credentials",
        "Hackers compromised Microsoft's official Agent Framework Python package on PyPI, publishing two malicious "
        "versions designed to steal cloud credentials and other sensitive information from developers' systems.")


@pytest.mark.parametrize("title,body", [
    PYPI,
    ("Malicious npm packages steal developer tokens", "Attackers published typosquatted npm packages."),
    ("Шкідливі пакети в PyPI викрадають ключі розробників", ""),
])
def test_a_package_registry_compromise_is_never_drawn_as_an_extension(monkeypatch: pytest.MonkeyPatch, title: str,
                                                                    body: str) -> None:
    plan = _plan(monkeypatch, title, body)
    assert plan.renderer == "cax-svg-3"                                    # no faithful V4.1 scene: V3
    assert B.build(story(title, body)).scene != "dev_supply_chain"


def test_the_pypi_story_draws_no_marketplace_no_key_and_no_extension() -> None:
    from cyberalertx.media.v4.render import render_doc
    b = replace(B.build(story(*PYPI)), scene="dev_supply_chain", palette="midnight", status="compromise")
    labels = render_doc(b).labels                                         # even if forced into the scene
    assert not any("MARKETPLACE" in x for x in labels) and "ISSUED TO" not in labels
    assert "stolen key" not in B.alt_text(b)["en"]


def test_a_browser_extension_names_only_what_the_sources_state() -> None:
    from cyberalertx.media.v4.consistency import check_brief
    from cyberalertx.media.v4.render import render_doc
    b = B.build(story("Malicious Chrome extension steals passwords from 10,000 users",
                      "A browser Chrome extension in the Chrome Web Store stole saved passwords."))
    labels = render_doc(b).labels
    assert b.scene == "dev_supply_chain" and "Chrome" in labels and "Malicious" not in labels
    assert "ISSUED TO" not in labels and not any("MARKETPLACE" in x for x in labels)   # no key, no marketplace stated
    assert check_brief(b, labels) == []


def test_a_stated_stolen_key_and_named_marketplace_are_drawn() -> None:
    from cyberalertx.media.v4.consistency import check_brief
    from cyberalertx.media.v4.render import render_doc
    b = B.build(story("Stolen Fireworks AI Key Led to Cursor Data Breach and Trojanized Claude Code Extension",
                      "An access key Cursor had issued to Fireworks AI was stolen; attackers pushed a trojanized "
                      "Claude Code extension through the Cursor marketplace."))
    labels = render_doc(b).labels
    assert {"CURSOR MARKETPLACE", "Claude Code", "TROJANIZED", "ISSUED TO", "Fireworks AI"} <= set(labels)
    assert "stolen key tagged Fireworks AI" in B.alt_text(b)["en"] and check_brief(b, labels) == []


def test_signing_key_theft_is_the_code_signing_scene_not_a_marketplace() -> None:
    b = B.build(story("Hackers stole Acme code-signing key to sign malware",
                      "Attackers stole the company code-signing key and signed malware with it."))
    assert b.scene == "code_signing"
