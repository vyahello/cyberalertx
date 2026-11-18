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
