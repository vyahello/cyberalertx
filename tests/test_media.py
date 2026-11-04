"""Media Engine: branded cards, illustration eligibility/prompt, provider
lifecycle, storage validation, API exposure, Telegram preparation.

Hand-built fixtures, a mock image provider and a mock Telegram transport —
no network, no AI, no live channel.
"""
from __future__ import annotations

import base64
import json
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from cyberalertx.ai.fact_sheet import AffectedProduct, CvssScore, FactSheet
from cyberalertx.ai.models import ThreatPost
from cyberalertx.intel.config import IntelConfig
from cyberalertx.intel.scoring import evaluate
from cyberalertx.intel.sources import SourceTable
from cyberalertx.intel.story import StoryView, _fallback_independent
from cyberalertx.media import cards
from cyberalertx.media import engine as media_engine
from cyberalertx.media.assets import MediaAsset, MediaStore, MediaValidationError, sniff, validate_image
from cyberalertx.media.illustrations import (
    EligibilityConfig, GeneratedImage, NoProvider, ProviderError, build_prompt, eligibility,
)
from cyberalertx.models import NewsItem
from cyberalertx.publish.config import TelegramSettings
from cyberalertx.publish.format import CAPTION_LIMIT, render_caption, visible_length
from cyberalertx.publish.ledger import PublishLedger
from cyberalertx.publish.service import photo_for, publish_once
from cyberalertx.publish.telegram import TelegramError, TelegramPublisher

NOW = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
CFG, TABLE = IntelConfig(), SourceTable()


def png(w: int, h: int, colour: tuple[int, int, int] = (14, 17, 22)) -> bytes:
    """A real, decodable RGB PNG of the given size."""
    row = b"\x00" + bytes(colour) * w
    raw = zlib.compress(row * h, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def item(title: str, source: str, body: str = "", hours_ago: float = 2) -> NewsItem:
    return NewsItem(title=title, source=source, url=f"https://{source.replace(' ', '').lower()}.example/{abs(hash(title))}",
                    published_at=NOW - timedelta(hours=hours_ago),
                    raw_content=body or (title + ". Details of the incident follow in the report. " * 8),
                    threat_score=60.0, audience_targets=["enterprise"], category="vulnerability")


def tpost(level: str = "Critical") -> ThreatPost:
    return ThreatPost(title="t", short_summary="s", threat_level=level, why_it_matters="w",
                      affected_users=["x"], what_to_do=["Patch now"], language="en",
                      source_fingerprint="f" * 16, generated_by="mock")


def critical_story(key: str = "s:crit", *, exploited: bool = True, products: tuple[str, ...] = ("Widget Server",)) -> StoryView:
    m = item("Widget CVE-2026-1111 exploited, patch now", "CISA Alerts",
             body="Known Exploited Vulnerabilities catalog entry: CVE-2026-1111 is actively exploited. " * 5)
    sheet = FactSheet(summary="x", exploitation_status="confirmed" if exploited else "none",
                      cvss_scores=[CvssScore(score=9.8)],
                      affected_products=[AffectedProduct(vendor="Acme", product=p) for p in products])
    return StoryView(key=key, anchor=m, members=[m], independent_sources=_fallback_independent([m]),
                     sheets=[sheet], posts={"en": tpost()})


def thin_story(key: str = "s:thin") -> StoryView:
    m = item("Rumour of a Widget leak", "dev.ua", body="Short claim.")
    return StoryView(key=key, anchor=m, members=[m], independent_sources=["dev.ua"], sheets=[],
                     posts={"en": tpost("Low")})


def fake_intel(monkeypatch: pytest.MonkeyPatch, stories: list[StoryView], breaking: tuple[str, ...] = ()) -> None:
    import cyberalertx.intel.engine as intel_engine

    evals = {s.key: evaluate(s, CFG, TABLE, NOW) for s in stories}
    result = SimpleNamespace(stories=stories, evals=evals, picks=[],
                             breaking=[{"story_key": k} for k in breaking])
    monkeypatch.setattr(intel_engine, "run", lambda *a, **k: result)


class MockProvider:
    name = "mock"

    def __init__(self, outcomes: list[Any] | None = None) -> None:
        self.outcomes = outcomes or []
        self.calls: list[dict[str, Any]] = []

    def generate(self, prompt: str, *, width: int, height: int, timeout_s: float) -> GeneratedImage:
        self.calls.append({"prompt": prompt, "width": width, "height": height, "timeout_s": timeout_s})
        out = self.outcomes.pop(0) if self.outcomes else GeneratedImage(png(1536, 1024), "image/png", "mock-1", 0.04)
        if isinstance(out, BaseException):
            raise out
        return out


# ---------------------------------------------------------------- branded cards

def payload(title_en: str = "Widget flaw exploited", title_ua: str = "Ваду у Widget уже використовують",
            **extra: Any) -> dict[str, Any]:
    p: dict[str, Any] = {"id": "0123456789abcdef", "category": "vulnerability", "threat_level": "Critical",
                         "published_at": NOW.isoformat(), "signals": {"active_exploitation": True},
                         "translations": {}}
    if title_en:
        p["translations"]["en"] = {"title": title_en}
    if title_ua:
        p["translations"]["ua"] = {"title": title_ua}
    p.update(extra)
    return p


def test_card_is_built_from_each_editions_own_text() -> None:
    en, ua = cards.card_asset(payload(), "en", "s:1"), cards.card_asset(payload(), "ua", "s:1")
    assert en and ua
    assert "Widget flaw exploited" in en.alt_text["en"] and "critical severity" in en.alt_text["en"]
    assert ua.alt_text["ua"].startswith("Картка CyberAlertX, рівень загрози критичний, уже використовують")
    assert "«Ваду у Widget уже використовують»" in ua.alt_text["ua"]
    assert set(en.variants) == {"og", "telegram", "threads-portrait", "threads-square", "preview"}
    assert en.variants["og"].startswith("https://cyberalertx.com/en/threat/0123456789abcdef/card/og.png?v=")
    assert ua.variants["telegram"].startswith("https://cyberalertx.com/ua/threat/0123456789abcdef/card/telegram.png?v=")
    assert en.content_hash != ua.content_hash and en.status == "generated"


def test_no_card_from_another_languages_headline() -> None:
    assert cards.card_asset(payload(title_ua=""), "ua", "s:1") is None
    assert cards.card_asset(payload(title_en="  "), "en", "s:1") is None


def test_card_hash_changes_only_with_visible_inputs() -> None:
    a = cards.content_hash(cards.card_inputs(payload(), "en") or {})
    assert a == cards.content_hash(cards.card_inputs(payload(), "en") or {})            # deterministic
    assert a == cards.content_hash(cards.card_inputs(payload(source="X"), "en") or {})  # invisible field
    assert a != cards.content_hash(cards.card_inputs(payload(title_en="Other"), "en") or {})
    with_art = payload(media={"illustration": {"asset_id": "ab" * 8}})
    assert a != cards.content_hash(cards.card_inputs(with_art, "en") or {})


def test_card_with_missing_optional_fields() -> None:
    p = {"id": "0123456789abcdef", "translations": {"en": {"title": "Bare"}}}
    c = cards.card_asset(p, "en", "s:1")
    assert c and c.alt_text["en"] == "CyberAlertX card: “Bare”"


def test_card_url_rejects_unknown_variant(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        cards.card_url("en", "0123456789abcdef", "banner")
    monkeypatch.setenv("CYBERALERTX_PUBLIC_BASE_URL", "https://staging.example/")
    assert cards.card_url("en", "x", "og") == "https://staging.example/en/threat/x/card/og.png"


# ---------------------------------------------------------------- eligibility & prompt

def test_high_priority_verified_story_is_eligible() -> None:
    s = critical_story()
    e = eligibility(s, evaluate(s, CFG, TABLE, NOW), breaking=True)
    assert e.eligible and "breaking" in e.reasons


def test_thin_unverified_or_out_of_scope_story_is_not() -> None:
    s = thin_story()
    e = eligibility(s, evaluate(s, CFG, TABLE, NOW), top_rank=1)
    assert not e.eligible and any("context" in r or "verification" in r for r in e.reasons)
    oos = critical_story()
    oos.relevance = "out_of_scope"
    assert not eligibility(oos, evaluate(oos, CFG, TABLE, NOW), breaking=True).eligible
    assert not eligibility(critical_story(), None).eligible


def test_importance_threshold_is_configurable() -> None:
    s = critical_story(exploited=False)
    s.members = [item("Widget CVE-2026-1111 patched", "CISA Alerts",
                      body="CISA released an advisory: the vendor patched CVE-2026-1111 in Widget Server. " * 5)]
    s.anchor = s.members[0]
    ev = evaluate(s, CFG, TABLE, NOW)
    assert ev.dim("exploitation_status") != "confirmed"
    assert eligibility(s, ev, cfg=EligibilityConfig(min_importance=0)).eligible
    assert not eligibility(s, ev, cfg=EligibilityConfig(min_importance=101)).eligible


def test_prompt_uses_fact_sheet_and_never_depicts_brands_or_text() -> None:
    s = critical_story(products=("Widget Server", "Widget Gateway"))
    p = build_prompt(s, evaluate(s, CFG, TABLE, NOW))
    assert "Widget Gateway" in p.prompt and "never its brand" in p.prompt
    assert "No text" in p.prompt and "No people's faces" in p.prompt
    assert p.inputs["products"] == ["Widget Gateway", "Widget Server"]
    assert p.alt["ua"].startswith("Абстрактна ілюстрація: ")


def test_prompt_shows_exploitation_only_when_confirmed() -> None:
    s = critical_story(exploited=False)
    s.members = [item("Widget CVE-2026-1111 patched", "Vendor blog",
                      body="The vendor patched CVE-2026-1111. No exploitation is known. " * 6)]
    s.anchor = s.members[0]
    s.anchor.category = "exploit"
    ev = evaluate(s, CFG, TABLE, NOW)
    assert ev.dim("exploitation_status") != "confirmed"
    p = build_prompt(s, ev)
    assert p.inputs["event"] == "vulnerability_disclosure" and "intrusion path" not in p.prompt


def test_prompt_without_fact_sheet_falls_back_to_category() -> None:
    s = critical_story()
    s.sheets = []
    p = build_prompt(s, evaluate(s, CFG, TABLE, NOW))
    assert p.inputs["products"] == [] and "affected technology" not in p.prompt


def test_headline_edit_does_not_change_prompt_inputs() -> None:
    s = critical_story()
    h1 = build_prompt(s, evaluate(s, CFG, TABLE, NOW)).inputs_hash
    s.anchor.title = "A completely different headline"
    assert build_prompt(s, evaluate(s, CFG, TABLE, NOW)).inputs_hash == h1


# ---------------------------------------------------------------- storage validation

def test_sniff_and_validate() -> None:
    assert sniff(png(1600, 900)) == ("image/png", 1600, 900)
    with pytest.raises(MediaValidationError, match="dimensions"):
        validate_image(png(300, 200))
    with pytest.raises(MediaValidationError, match="declared"):
        validate_image(png(1024, 1024), declared_mime="image/jpeg")
    with pytest.raises(MediaValidationError):
        validate_image(b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    with pytest.raises(MediaValidationError, match="empty"):
        validate_image(b"")
    with pytest.raises(MediaValidationError, match="too large"):
        validate_image(b"\x89PNG" + b"0" * (8 * 1024 * 1024 + 1))


def test_store_dedupes_by_content_and_refuses_unvalidated(tmp_path: Path) -> None:
    store = MediaStore(tmp_path)
    data = png(1536, 1024)
    sha1, *_ = store.save_bytes(data, declared_mime="image/png")
    sha2, *_ = store.save_bytes(data)
    assert sha1 == sha2 and len(list(store.files.iterdir())) == 1
    a = MediaAsset(asset_id="illus:s:1", story_key="s:1", asset_type="editorial_illustration",
                   storage_key=f"{sha1}.png", status="failed", members=["f1"])
    store.put(a)
    assert store.open_file(sha1[:16]) is None                     # not validated → never served
    a.status = "validated"
    store.put(a)
    got = store.open_file(sha1[:16])
    assert got and got[1] == "image/png" and got[0] == data


@pytest.mark.parametrize("bad", ["../../etc/passwd", "ABCDEF0123456789", "abc", "", "0" * 16 + "/x"])
def test_open_file_rejects_unsafe_ids(tmp_path: Path, bad: str) -> None:
    assert MediaStore(tmp_path).open_file(bad) is None


def test_open_file_refuses_a_tampered_storage_key(tmp_path: Path) -> None:
    store = MediaStore(tmp_path)
    (tmp_path / "secret.png").write_bytes(png(800, 800))
    store.put(MediaAsset(asset_id="illus:x", story_key="x", asset_type="editorial_illustration",
                         storage_key="../secret.png", status="validated"))
    assert store.open_file("0" * 16) is None


# ---------------------------------------------------------------- engine lifecycle

def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provider: Any, stories: list[StoryView] | None = None,
         **kw: Any) -> tuple[Any, MediaStore]:
    stories = stories or [critical_story()]
    fake_intel(monkeypatch, stories, breaking=tuple(s.key for s in stories))
    store = MediaStore(tmp_path)
    res = media_engine.run([s.anchor for s in stories], store=store, provider=provider, now=NOW, **kw)
    return res, store


def test_no_provider_is_branded_card_only_and_records_no_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CYBERALERTX_IMAGE_PROVIDER", raising=False)
    res, store = _run(monkeypatch, tmp_path, NoProvider())
    assert res.provider == "none" and res.calls == 0 and not res.failed
    assert res.skipped == [{"story_key": "s:crit", "reason": "no image provider configured"}]
    assert store.get("illus:s:crit") is None
    assert not (tmp_path / "usage.jsonl").exists()


def test_successful_generation_is_validated_and_exposed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prov = MockProvider()
    res, store = _run(monkeypatch, tmp_path, prov)
    assert res.generated == ["s:crit"] and res.calls == 1 and res.cost_usd == pytest.approx(0.04)
    a = store.get("illus:s:crit")
    assert a and a.status == "validated" and (a.width, a.height) == (1536, 1024) and a.aspect_ratio == "3:2"
    assert a.public_url.endswith("/og.png") and set(a.variants) == set(media_engine.ILLUSTRATION_VARIANTS)
    assert a.generation_model == "mock-1" and a.prompt_version == "illus-1" and a.alt_text["en"]
    block = media_engine.illustration_payload(store, critical_story().anchor.fingerprint)
    assert block and block["asset_id"] == a.storage_key[:16] and block["generated"] is True
    usage = [json.loads(x) for x in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert usage[0]["ok"] is True and usage[0]["model"] == "mock-1"
    assert prov.calls[0]["width"] == 1536 and prov.calls[0]["timeout_s"] == 90.0


def test_reuse_until_inputs_change(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prov = MockProvider()
    _run(monkeypatch, tmp_path, prov)
    res, _ = _run(monkeypatch, tmp_path, prov)
    assert res.reused == ["s:crit"] and len(prov.calls) == 1               # no duplicate generation
    res, store = _run(monkeypatch, tmp_path, prov, stories=[critical_story(products=("Other Appliance",))])
    assert res.generated == ["s:crit"] and len(prov.calls) == 2            # meaningful change
    assert "Other Appliance" in (store.get("illus:s:crit") or MediaAsset("", "", "")).prompt


def test_failures_are_contained_and_retry_limited(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prov = MockProvider([ProviderError("refused"), TimeoutError("90s"),
                         GeneratedImage(b"not an image", "image/png", "mock-1")])
    for attempt in (1, 2, 3):
        res, store = _run(monkeypatch, tmp_path, prov)
        a = store.get("illus:s:crit")
        assert a and a.status == "failed" and a.attempts == attempt and res.failed
    assert "MediaValidationError" in a.last_error
    res, _ = _run(monkeypatch, tmp_path, prov)
    assert res.calls == 0 and "retry limit" in res.skipped[0]["reason"]
    assert store.open_file("0" * 16) is None and media_engine.illustration_payload(store, a.members[0]) is None


def test_per_run_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prov = MockProvider()
    stories = [critical_story(f"s:{i}") for i in range(3)]
    for i, s in enumerate(stories):
        s.members = [item(f"Widget CVE-2026-111{i} exploited, patch now", "CISA Alerts",
                          body=f"Known Exploited Vulnerabilities catalog entry: CVE-2026-111{i} is exploited. " * 5)]
        s.anchor = s.members[0]
    res, _ = _run(monkeypatch, tmp_path, prov, stories=stories, max_calls=2)
    assert res.calls == 2 and any("per-run cap" in s["reason"] for s in res.skipped)


def test_dry_run_writes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prov = MockProvider()
    res, store = _run(monkeypatch, tmp_path, prov, dry_run=True)
    assert not prov.calls and store.all() == [] and res.skipped[0]["reason"] == "dry run"


def test_storage_failure_is_recorded_not_raised(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(self: MediaStore, data: bytes, *, declared_mime: str = "") -> Any:
        raise OSError("disk full")

    monkeypatch.setattr(MediaStore, "save_bytes", boom)
    res, store = _run(monkeypatch, tmp_path, MockProvider())
    a = store.get("illus:s:crit")
    assert a and a.status == "failed" and "disk full" in a.last_error and res.failed


# ---------------------------------------------------------------- API

def test_api_serves_only_validated_files_and_adds_media_field(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    import cyberalertx.api.app as app_mod
    from cyberalertx.api.admin import AdminGuard

    store = MediaStore(tmp_path / "media")
    sha, *_ = store.save_bytes(png(1536, 1024))
    monkeypatch.setattr(app_mod, "_MEDIA_STORE", store)
    client = TestClient(app_mod.build_app(feedback_path=tmp_path / "f.jsonl", admin_guard=AdminGuard()))
    assert client.get(f"/media/{sha[:16]}").status_code == 404            # stored but not validated

    posts = client.get("/posts?limit=1").json()["items"]
    fp = posts[0]["id"] if posts else "f" * 16
    store.put(MediaAsset(asset_id="illus:s:1", story_key="s:1", asset_type="editorial_illustration",
                         storage_key=f"{sha}.png", status="validated", width=1536, height=1024,
                         alt_text={"en": "Abstract illustration.", "ua": "Абстрактна ілюстрація."}, members=[fp]))
    r = client.get(f"/media/{sha[:16]}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/media/..%2F..%2Fetc").status_code == 404
    if posts:
        post = client.get(f"/posts/{fp}").json()
        assert post["media"]["illustration"] == {"asset_id": sha[:16], "width": 1536, "height": 1024,
                                                 "alt": {"en": "Abstract illustration.", "ua": "Абстрактна ілюстрація."},
                                                 "generated": True}
        others = [p for p in client.get("/posts?limit=20").json()["items"] if p["id"] != fp]
        assert all("media" not in p for p in others)                        # additive, only when present


def test_admin_media_is_token_locked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    import cyberalertx.api.app as app_mod
    from cyberalertx.api.admin import AdminGuard

    token = "t" * 48
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", token)
    monkeypatch.delenv("CYBERALERTX_IMAGE_PROVIDER", raising=False)
    store = MediaStore(tmp_path / "media")
    store.put_many([cards.card_asset(payload(), "en", "s:1") or MediaAsset("", "", ""),
                    MediaAsset(asset_id="illus:s:1", story_key="s:1", asset_type="editorial_illustration",
                               status="failed", attempts=2, last_error="ProviderError: <refused>")])
    monkeypatch.setattr(app_mod, "_MEDIA_STORE", store)
    client = TestClient(app_mod.build_app(feedback_path=tmp_path / "f.jsonl", admin_guard=AdminGuard()))
    for path in ("/admin/media", "/admin/media.json"):
        assert client.get(path).status_code == 401
    auth = {"Authorization": "Basic " + base64.b64encode(f"ed:{token}".encode()).decode(),
            "X-Real-IP": "203.0.113.9"}
    resp = client.get("/admin/media", headers=auth)
    assert "default-src 'none'" in resp.headers.get("content-security-policy", "")
    html = resp.text
    assert "branded cards only" in html and "ProviderError: &lt;refused&gt;" in html
    assert "<script" not in html.lower()
    data = client.get("/admin/media.json", headers=auth).json()
    assert {a["asset_type"] for a in data["assets"]} == {"branded_card", "editorial_illustration"}


# ---------------------------------------------------------------- Telegram preparation

def tg_payload(fp: str, *, summary: str = "A summary.", ua: bool = False) -> dict[str, Any]:
    loc = "ua" if ua else "en"
    return {"id": fp, "source": "BleepingComputer", "threat_level": "Critical",
            "actionability_level": "urgent", "category": "vulnerability", "published_at": NOW.isoformat(),
            "translations": {loc: {"title": "Widget flaw exploited", "short_summary": summary,
                                   "plain_summary": summary, "what_to_do": ["Patch now"]}}}


class _Svc:
    def __init__(self, items: list[NewsItem], rendered: dict[tuple[str, str], dict[str, Any]]) -> None:
        self.items, self.rendered = items, rendered

    def list_items(self) -> list[NewsItem]:
        return list(self.items)

    def render_if_cached(self, item: NewsItem, *, required_locale: str | None = None) -> Any:
        return self.rendered.get((item.fingerprint, required_locale or ""))


def tg_item() -> NewsItem:
    return NewsItem(title="Widget flaw", source="BleepingComputer", url="https://e.test/w",
                    published_at=NOW, raw_content="", language="en", source_tier="trusted")


def settings(**kw: Any) -> TelegramSettings:
    base: dict[str, Any] = dict(bot_token="test-token", channels={"en": "@fake_en"}, limit=5,
                                send_delay_seconds=0.0, public_base_url="https://cyberalertx.com")
    base.update(kw)
    return TelegramSettings(**base)


def mocked_publisher(handler: Any) -> tuple[TelegramPublisher, list[tuple[str, dict[str, Any]]]]:
    seen: list[tuple[str, dict[str, Any]]] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append((req.url.path.rsplit("/", 1)[-1], json.loads(req.content)))
        return handler(req)

    client = httpx.Client(transport=httpx.MockTransport(h))
    return TelegramPublisher("123:FAKE", api_base="https://fake.invalid", client=client), seen


def ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})


def test_images_are_off_by_default(tmp_path: Path) -> None:
    it = tg_item()
    pub, seen = mocked_publisher(ok)
    res = publish_once(settings=settings(), service=_Svc([it], {(it.fingerprint, "en"): tg_payload(it.fingerprint)}),
                       ledger=PublishLedger(tmp_path / "l.jsonl"), publisher=pub)
    assert res.sent == 1 and [m for m, _ in seen] == ["sendMessage"]


def test_attach_images_sends_the_card_as_a_photo(tmp_path: Path) -> None:
    it = tg_item()
    pub, seen = mocked_publisher(ok)
    res = publish_once(settings=settings(attach_images=True),
                       service=_Svc([it], {(it.fingerprint, "en"): tg_payload(it.fingerprint)}),
                       ledger=PublishLedger(tmp_path / "l.jsonl"), publisher=pub)
    assert res.sent == 1 and [m for m, _ in seen] == ["sendPhoto"]
    body = seen[0][1]
    assert body["chat_id"] == "@fake_en" and body["parse_mode"] == "HTML"
    assert body["photo"].startswith(f"https://cyberalertx.com/en/threat/{it.fingerprint}/card/telegram.png?v=")
    assert "Widget flaw exploited" in body["caption"] and visible_length(body["caption"]) <= CAPTION_LIMIT


def test_photo_failure_falls_back_to_text(tmp_path: Path) -> None:
    it = tg_item()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("sendPhoto"):
            return httpx.Response(400, json={"ok": False, "description": "Bad Request: wrong file identifier"})
        return ok(req)

    pub, seen = mocked_publisher(handler)
    led = PublishLedger(tmp_path / "l.jsonl")
    res = publish_once(settings=settings(attach_images=True),
                       service=_Svc([it], {(it.fingerprint, "en"): tg_payload(it.fingerprint)}),
                       ledger=led, publisher=pub)
    assert [m for m, _ in seen] == ["sendPhoto", "sendMessage"] and res.sent == 1 and res.errors == 0
    assert led.is_published(it.fingerprint, "en")


def test_channel_fatal_photo_error_stops_the_channel(tmp_path: Path) -> None:
    it = tg_item()
    pub, seen = mocked_publisher(lambda r: httpx.Response(403, json={"ok": False, "description": "Forbidden"}))
    res = publish_once(settings=settings(attach_images=True),
                       service=_Svc([it], {(it.fingerprint, "en"): tg_payload(it.fingerprint)}),
                       ledger=PublishLedger(tmp_path / "l.jsonl"), publisher=pub)
    assert [m for m, _ in seen] == ["sendPhoto"] and res.sent == 0 and res.errors == 1


def test_dry_run_with_images_touches_no_network(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    it = tg_item()
    caplog.set_level("INFO")
    res = publish_once(settings=settings(attach_images=True, bot_token=None),
                       service=_Svc([it], {(it.fingerprint, "en"): tg_payload(it.fingerprint)}),
                       ledger=PublishLedger(tmp_path / "l.jsonl"), dry_run=True)
    assert res.sent == 1 and "would send photo" in caplog.text and "/card/telegram.png?v=" in caplog.text


def test_long_caption_is_trimmed_and_keeps_headline_and_link() -> None:
    long = "Атакувальники використовують ваду в сервері Widget, щоб захопити облікові записи. " * 30
    cap = render_caption(tg_payload("0123456789abcdef", summary=long, ua=True), locale="ua",
                         base_url="https://cyberalertx.com")
    assert visible_length(cap) <= CAPTION_LIMIT
    assert cap.startswith("🔴 <b>Widget flaw exploited</b>") and "🔗 <a href=" in cap and "…" in cap


def test_photo_for_has_no_card_without_the_edition() -> None:
    assert photo_for({"id": "x", "translations": {"en": {"title": "T"}}}, "ua") is None
    assert photo_for({"id": "x", "translations": {"en": {"title": "T"}}}, "en")


def test_send_photo_requires_https() -> None:
    pub, seen = mocked_publisher(ok)
    with pytest.raises(TelegramError):
        pub.send_photo("@fake", "http://insecure.example/a.png", "c")
    assert not seen
