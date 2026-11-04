"""Fact-sheet stage: schema, sanitization, cache, the +1-call budget, and the
generator wiring. No network: providers are mocks, the CLI subprocess and the
Anthropic client are stubbed."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from cyberalertx.ai.cache import ThreatPostCache
from cyberalertx.ai.fact_sheet import (
    FactSheet,
    FactSheetCache,
    build_fact_sheet_prompts,
    get_or_create_fact_sheet,
    sanitize_fact_sheet,
)
from cyberalertx.ai.generator import ContentGenerator
from cyberalertx.ai.models import ThreatPostResponse
from cyberalertx.models import NewsItem

BODY = ("BleepingComputer reports that attackers exploited CVE-2026-44338 (CVSS 7.3) in "
        "PraisonAI 2.4.58 on 1 November. Version 2.4.59 fixes it.")


def _item(**over: Any) -> NewsItem:
    base: dict[str, Any] = dict(
        title="PraisonAI flaw exploited hours after disclosure",
        source="BleepingComputer", url="https://bc.test/praison",
        published_at=datetime(2026, 11, 2, 9, tzinfo=timezone.utc),
        raw_content=BODY, category="vulnerability", language="en",
        audience_targets=["developers"], affected_platforms=["Linux"],
        source_tier="trusted", source_credibility_score=0.9,
    )
    base.update(over)
    return NewsItem(**base)


SHEET_JSON: dict[str, Any] = {
    "summary": "Attackers exploited a PraisonAI auth flaw.",
    "affected_products": [{"vendor": "PraisonAI", "product": "PraisonAI", "versions": ["2.4.58"]}],
    "cve_ids": ["cve-2026-44338", "CVE-2026-99999"],
    "cvss_scores": [{"score": 7.3, "cve_id": "CVE-2026-44338"}, {"score": 9.9}],
    "dates": [{"date": "2026-11-01", "event": "exploitation began"}],
    "key_numbers": [],
    "exploitation_status": "Confirmed",
    "patch_status": "fixed upstream",          # not an enum value → "unknown"
    "claims": [{"statement": "Exploited within hours", "attribution": "BleepingComputer",
                "status": "rumour"}],          # not an enum value → default "reported" (v1 "claimed")
    "open_questions": ["Who is behind it"],
    "unexpected": "ignored",
}


def _response(**over: Any) -> ThreatPostResponse:
    base: dict[str, Any] = dict(
        title="PraisonAI servers are being taken over right now",
        short_summary=("BleepingComputer reports attackers exploiting CVE-2026-44338 in "
                       "PraisonAI 2.4.58; version 2.4.59 fixes the flaw."),
        plain_summary="Anyone running PraisonAI 2.4.58 should update today, attackers already use the bug.",
        threat_level="High",
        why_it_matters="An exposed PraisonAI server runs attacker tasks with its own API keys.",
        affected_users=["PraisonAI operators"],
        what_to_do=["Upgrade PraisonAI to 2.4.59."],
        what_not_to_do=[],
        quick_facts=["CVE-2026-44338", "Fixed in 2.4.59"],
        emotional_weight=0.6, reading_time_seconds=20,
    )
    base.update(over)
    return ThreatPostResponse(**base)


@dataclass
class JsonProvider:
    """Mock provider with the generic JSON method."""
    name: str = "mock:json"
    sheet: dict[str, Any] | None = None
    fail_json: bool = False
    responses: dict[str, ThreatPostResponse] = field(default_factory=dict)
    post_calls: list[tuple[str, str]] = field(default_factory=list)
    json_calls: list[tuple[str, str]] = field(default_factory=list)

    def generate_post(self, system: str, user: str) -> ThreatPostResponse:
        self.post_calls.append((system, user))
        lang = "ua" if "OUTPUT_LANGUAGE: ua" in system else "en"
        return self.responses.get(lang) or _response()

    def generate_json(self, system: str, user: str, *, schema: dict[str, Any]) -> dict[str, Any]:
        self.json_calls.append((system, user))
        assert "properties" in schema
        if self.fail_json:
            raise RuntimeError("simulated extraction failure")
        return dict(self.sheet if self.sheet is not None else SHEET_JSON)


UA_RESPONSE = _response(
    title="Сервери PraisonAI захоплюють просто зараз",
    short_summary=("BleepingComputer повідомляє про атаки на CVE-2026-44338 у PraisonAI 2.4.58; "
                   "версія 2.4.59 виправляє вразливість."),
    plain_summary="Якщо у вас PraisonAI 2.4.58, оновіть його сьогодні: зловмисники вже атакують.",
    why_it_matters="Відкритий сервер PraisonAI виконує завдання зловмисника з власними ключами API.",
    affected_users=["Оператори PraisonAI"],
    what_to_do=["Оновіть PraisonAI до 2.4.59."],
    quick_facts=["CVE-2026-44338", "Виправлено у 2.4.59"],
)


# ---------------------------------------------------------------------------
# Schema + sanitization
# ---------------------------------------------------------------------------

def test_free_form_statuses_are_coerced_not_fatal() -> None:
    sheet = FactSheet.model_validate(SHEET_JSON)
    assert sheet.exploitation_status == "confirmed"
    assert sheet.patch_status == "unknown"
    # v1 "claimed" maps to the v2 "reported" (a party asserts it).
    assert sheet.claims[0].status == "reported"


def test_sanitize_drops_identifiers_the_source_lacks() -> None:
    sheet, dropped = sanitize_fact_sheet(FactSheet.model_validate(SHEET_JSON),
                                         _item().title, BODY)
    assert sheet.cve_ids == ["CVE-2026-44338"]
    assert [c.score for c in sheet.cvss_scores] == [7.3]
    assert set(dropped) == {"cve:CVE-2026-99999", "cvss:9.9"}


def test_prompt_block_is_delimited_and_compact() -> None:
    block = FactSheet.model_validate(SHEET_JSON).to_prompt_block()
    assert block.startswith("FACT SHEET") and "<<<FACT_SHEET" in block and block.endswith("FACT_SHEET>>>")
    payload = json.loads(block.split("<<<FACT_SHEET\n", 1)[1].rsplit("\nFACT_SHEET>>>", 1)[0])
    assert "key_numbers" not in payload        # empty fields are left out
    assert "patch_status" not in payload       # "unknown" adds nothing


def test_extraction_prompt_carries_the_source_and_forbids_background() -> None:
    system, user = build_fact_sheet_prompts(_item())
    assert "Add nothing you know from" in system
    assert BODY in user and "PUBLISHED: 2026-11-02" in user


# ---------------------------------------------------------------------------
# Cache + budget
# ---------------------------------------------------------------------------

def test_one_extraction_per_story_and_it_is_cached(tmp_path: Path) -> None:
    cache = FactSheetCache(tmp_path / "fact_sheets.json")
    provider = JsonProvider()
    first = get_or_create_fact_sheet(provider, _item(), cache, {})
    second = get_or_create_fact_sheet(provider, _item(), FactSheetCache(tmp_path / "fact_sheets.json"), {})
    assert first is not None and second is not None
    assert first.cve_ids == second.cve_ids == ["CVE-2026-44338"]
    assert len(provider.json_calls) == 1
    stored = json.loads((tmp_path / "fact_sheets.json").read_text())
    assert stored["sheets"][_item().fingerprint]["dropped"]


def test_a_failed_extraction_is_remembered_and_never_retried(tmp_path: Path) -> None:
    cache = FactSheetCache(tmp_path / "fact_sheets.json")
    provider = JsonProvider(fail_json=True)
    assert get_or_create_fact_sheet(provider, _item(), cache, {}) is None
    assert get_or_create_fact_sheet(provider, _item(), FactSheetCache(tmp_path / "fact_sheets.json"), {}) is None
    assert len(provider.json_calls) == 1


def test_constructing_the_cache_creates_no_file(tmp_path: Path) -> None:
    FactSheetCache(tmp_path / "nope" / "fact_sheets.json")
    assert not (tmp_path / "nope").exists()


# ---------------------------------------------------------------------------
# Generator wiring
# ---------------------------------------------------------------------------

def test_both_locales_share_one_sheet_and_see_it_in_the_prompt(tmp_path: Path) -> None:
    provider = JsonProvider(responses={"ua": UA_RESPONSE})
    gen = ContentGenerator(provider=provider, cache=ThreatPostCache(tmp_path / "p.json"),
                           fact_sheets=FactSheetCache(tmp_path / "s.json"))
    en = gen.generate(_item(), language="en")
    ua = gen.generate(_item(), language="ua")
    assert len(provider.json_calls) == 1                 # the whole +1 budget
    assert len(provider.post_calls) == 2
    for system, user in provider.post_calls:
        assert "<<<FACT_SHEET" in user and "CVE-2026-44338" in user
        assert "<<<FACT_SHEET" not in system             # system prompt stays cacheable
    assert en.generated_by == ua.generated_by == "mock:json"
    assert en.quality["fact_sheet"] is True and ua.quality["fact_sheet"] is True
    assert ua.quality["cross_locale"] == []


def test_extraction_failure_renders_exactly_as_before(tmp_path: Path) -> None:
    provider = JsonProvider(fail_json=True)
    gen = ContentGenerator(provider=provider, cache=ThreatPostCache(tmp_path / "p.json"),
                           fact_sheets=FactSheetCache(tmp_path / "s.json"))
    post = gen.generate(_item(), language="en")
    assert post.generated_by == "mock:json"
    assert "<<<FACT_SHEET" not in provider.post_calls[0][1]
    assert post.quality["fact_sheet"] is False


def test_a_provider_without_generate_json_is_untouched(tmp_path: Path) -> None:
    @dataclass
    class Legacy:
        name: str = "mock:legacy"
        calls: int = 0

        def generate_post(self, system: str, user: str) -> ThreatPostResponse:
            self.calls += 1
            return _response()

    legacy = Legacy()
    post = ContentGenerator(provider=legacy, cache=None).generate(_item(), language="en")
    assert legacy.calls == 1 and post.generated_by == "mock:legacy"


def test_an_invented_cve_falls_back_to_rule_based_and_is_not_cached(tmp_path: Path) -> None:
    bad = _response(quick_facts=["CVE-2026-44338", "Same bug as CVE-2023-22518"])
    provider = JsonProvider(responses={"en": bad})
    cache = ThreatPostCache(tmp_path / "p.json")
    post = ContentGenerator(provider=provider, cache=cache).generate(_item(), language="en")
    assert post.generated_by == "rule_based"
    assert cache.get(_item().fingerprint, "en") is None


def test_rule_based_path_never_extracts(tmp_path: Path) -> None:
    gen = ContentGenerator(provider=None, cache=None,
                           fact_sheets=FactSheetCache(tmp_path / "s.json"))
    assert gen.generate(_item(), language="en").generated_by == "rule_based"
    assert not (tmp_path / "s.json").exists()


def test_render_prompts_without_a_sheet_is_unchanged() -> None:
    from cyberalertx.ai.templates import default_template_registry, render_prompts
    template = default_template_registry().select("en", "vulnerability", "developers")
    _, without = render_prompts(template, _item(), target_language="en")
    _, with_sheet = render_prompts(template, _item(), target_language="en",
                                   fact_sheet=FactSheet(summary="x"))
    assert "FACT SHEET" not in without
    assert with_sheet.startswith(without.split("\nProduce the structured")[0])


# ---------------------------------------------------------------------------
# Providers' generate_json (no network)
# ---------------------------------------------------------------------------

def test_claude_cli_generate_json_parses_the_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    from cyberalertx.ai.providers import claude_cli_provider as mod

    seen: dict[str, Any] = {}

    class Proc:
        returncode = 0
        stderr = ""
        stdout = json.dumps({"type": "result", "subtype": "success", "is_error": False,
                             "result": "```json\n" + json.dumps(SHEET_JSON) + "\n```",
                             "usage": {}})

    def fake_run(cmd: list[str], **kw: Any) -> Proc:
        seen["system"] = cmd[cmd.index("--system-prompt") + 1]
        seen["env"] = kw.get("env")
        return Proc()

    monkeypatch.setattr(mod.shutil, "which", lambda b: "/usr/bin/claude")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-leak")
    provider = mod.ClaudeCliProvider(oauth_env_file=None)
    data = provider.generate_json("SYS", "USER", schema=FactSheet.model_json_schema())
    assert data["summary"] == SHEET_JSON["summary"]
    assert '"cve_ids"' in seen["system"]                      # schema spelled out
    assert "ANTHROPIC_API_KEY" not in seen["env"]              # billing guard intact


def test_anthropic_generate_json_uses_structured_outputs() -> None:
    from cyberalertx.ai.providers.anthropic_provider import AnthropicProvider, _strict_schema

    captured: dict[str, Any] = {}

    class Block:
        type = "text"
        text = json.dumps(SHEET_JSON)

    class Resp:
        stop_reason = "end_turn"
        content = [Block()]
        usage = None

    class Messages:
        def create(self, **kw: Any) -> Resp:
            captured.update(kw)
            return Resp()

    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._client = type("C", (), {"messages": Messages()})()  # type: ignore[attr-defined]
    provider._model = "claude-test"  # type: ignore[attr-defined]
    provider._max_output_tokens = 1000  # type: ignore[attr-defined]
    provider.name = "anthropic:test"
    data = provider.generate_json("SYS", "USER", schema=FactSheet.model_json_schema())
    assert data["open_questions"] == ["Who is behind it"]
    fmt = captured["output_config"]["format"]
    assert fmt["type"] == "json_schema"

    def objects(node: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if isinstance(node, dict):
            if node.get("type") == "object":
                out.append(node)
            for v in node.values():
                out.extend(objects(v))
        elif isinstance(node, list):
            for v in node:
                out.extend(objects(v))
        return out

    for obj in objects(fmt["schema"]):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
    # Unsupported keywords go; a FIELD that happens to be named like one stays.
    strict = _strict_schema({"type": "object", "properties": {
        "default": {"type": "string", "default": "x", "maxLength": 5}}})
    assert strict["properties"] == {"default": {"type": "string"}}
    assert strict["required"] == ["default"]


def test_openai_stub_generate_json_raises() -> None:
    from cyberalertx.ai.providers import OpenAIProvider
    with pytest.raises(NotImplementedError):
        OpenAIProvider().generate_json("s", "u", schema={})
