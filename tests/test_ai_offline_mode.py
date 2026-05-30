"""Tests for the MVP offline-first defaults.

Two things matter here:
  1. The factory does NOT load a provider unless explicitly opted in,
     EVEN IF an ANTHROPIC_API_KEY is sitting in the environment.
  2. The `use_llm=True` opt-in re-engages the provider when configured.
  3. Templates' `rule_based` overrides actually reach the generator's output.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from cyberalertx.ai.config import AISettings
from cyberalertx.ai.generator import build_default_generator, describe_mode
from cyberalertx.ai.rule_based import RuleBasedGenerator
from cyberalertx.models import NewsItem


def _item(**overrides) -> NewsItem:
    base = dict(
        title="Phishing campaign targets Microsoft 365 users",
        source="BleepingComputer",
        url="https://e.test/abc",
        published_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        raw_content=(
            "A new phishing campaign targets Microsoft 365 accounts with fake "
            "login pages. Attackers harvest credentials and abuse them to reset "
            "MFA. Defenders should review recent sign-in events."
        ),
        threat_score=40.0,
        category="phishing",
        affected_platforms=["Outlook"],
        audience_targets=["normal_users"],
        actionability_level="recommended_action",
        actionability_score=0.55,
        source_tier="trusted",
        source_credibility_score=0.85,
        language="en",
    )
    base.update(overrides)
    return NewsItem(**base)


# --------- offline-first defaults --------------------------------------

def test_default_factory_with_api_key_in_env_still_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Setting ANTHROPIC_API_KEY alone must NOT activate the provider.

    This is the headline MVP behavior: developers can have the env var set
    from other projects without accidentally triggering API calls.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-pretend")
    cfg = AISettings(
        enable_llm=False,
        api_key="sk-pretend",
        cache_path=tmp_path / "posts.json",
    )
    gen = build_default_generator(cfg)
    assert gen._provider is None
    assert describe_mode(gen) == "mode=rule-based (offline)"


def test_use_llm_flag_overrides_env_default(tmp_path: Path) -> None:
    """The CLI `--use-llm` flag (passed as `use_llm=True`) opts in.

    Pins the legacy `anthropic` provider explicitly — the package default is
    now `claude_cli`, but this test guards the Haiku-API opt-in path that the
    `anthropic` setting preserves for an easy switch-back.
    """
    cfg = AISettings(
        enable_llm=False,
        provider="anthropic",
        api_key="sk-real",
        cache_path=tmp_path / "posts.json",
    )
    gen = build_default_generator(cfg, use_llm=True)
    # Provider IS attached (Anthropic in this case — anthropic SDK is installed in CI).
    assert gen._provider is not None
    assert gen._provider.name.startswith("anthropic:")
    assert describe_mode(gen).startswith("mode=anthropic:")


def test_enable_llm_without_api_key_stays_offline(tmp_path: Path) -> None:
    """Opting into the `anthropic` path without credentials must NOT crash —
    just stay offline."""
    cfg = AISettings(
        enable_llm=True,
        provider="anthropic",
        api_key=None,
        cache_path=tmp_path / "posts.json",
    )
    gen = build_default_generator(cfg)
    assert gen._provider is None  # no key → no provider, no error


# --------- claude_cli provider (new default content engine) -------------

def test_default_provider_is_claude_cli() -> None:
    """The package default content engine is the local `claude` CLI, NOT the
    metered Haiku API — so no ANTHROPIC_API_KEY is consumed by default."""
    assert AISettings().provider == "claude_cli"


def test_claude_cli_missing_binary_stays_offline(tmp_path: Path) -> None:
    """Opting into `claude_cli` when the CLI binary is absent must fall back
    to rule-based gracefully (RuntimeError swallowed by the factory)."""
    cfg = AISettings(
        enable_llm=True,
        provider="claude_cli",
        claude_cli_bin="claude-does-not-exist-xyz",
        cache_path=tmp_path / "posts.json",
    )
    gen = build_default_generator(cfg)
    assert gen._provider is None
    assert describe_mode(gen) == "mode=rule-based (offline)"


# --------- template-fed rule-based --------------------------------------

def test_phishing_template_override_reaches_output() -> None:
    """The phishing template ships a `rule_based.why_it_matters` override —
    the rule-based generator must pick it up for matching items.
    """
    gen = RuleBasedGenerator()
    post = gen.generate(_item(category="phishing", audience_targets=["normal_users"]))
    # Override starts with this phrase (defined in templates.py).
    assert post.why_it_matters.startswith("These campaigns aim straight at your login")


def test_phishing_template_override_what_to_do() -> None:
    """The override-specified actions should be returned verbatim."""
    gen = RuleBasedGenerator()
    post = gen.generate(_item(category="phishing", audience_targets=["normal_users"]))
    # First action from the override (templates.py).
    assert "Open the service directly" in post.what_to_do[0]


def test_developer_vuln_template_override_applies() -> None:
    """The developer vulnerability template's overrides apply when audience matches."""
    gen = RuleBasedGenerator()
    post = gen.generate(_item(
        category="vulnerability",
        audience_targets=["developers"],
        actionability_level="recommended_action",
    ))
    assert "dependencies" in post.why_it_matters.lower()
    assert any("lockfile" in s.lower() for s in post.what_to_do)


def test_unknown_category_falls_through_to_defaults() -> None:
    """An item with no matching template override gets the per-category default."""
    gen = RuleBasedGenerator()
    post = gen.generate(_item(category="other", audience_targets=[]))
    # Default `default/general` template has no rule_based field, so the
    # generator's per-category fallback kicks in (which for "other" yields
    # the generic two-line guidance).
    assert post.why_it_matters  # non-empty
    assert post.what_to_do      # non-empty


# --------- urgency-aware why_it_matters --------------------------------

def test_urgent_phishing_uses_urgent_variant() -> None:
    gen = RuleBasedGenerator()
    urgent = gen.generate(_item(
        category="phishing", actionability_level="urgent_action",
        audience_targets=["developers"],  # avoid the normal_users override
    ))
    soon = gen.generate(_item(
        category="phishing", actionability_level="recommended_action",
        audience_targets=["developers"],
    ))
    # The two urgency buckets must yield different copy.
    assert urgent.why_it_matters != soon.why_it_matters


def test_summary_strips_byline_prefix() -> None:
    """Leading bylines should not pollute the summary."""
    gen = RuleBasedGenerator()
    item = _item(
        raw_content=(
            "By Jane Reporter, May 11, 2026. A new ransomware family is hitting "
            "hospitals. Researchers traced the operators to a known group."
        ),
        category="ransomware",
    )
    post = gen.generate(item)
    assert not post.short_summary.lower().startswith("by jane")
