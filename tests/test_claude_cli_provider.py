"""ClaudeCliProvider — subprocess wiring, billing-env stripping, JSON parsing.

The headline guarantee here is the *billing* one: the `claude` CLI must run
without ANTHROPIC_API_KEY in its environment so it authenticates against the
OAuth subscription, not the metered API. `.env` / systemd inject that key into
the process, so the provider has to actively strip it from the subprocess env.
"""
from __future__ import annotations

import json

import pytest

from cyberalertx.ai.providers.claude_cli_provider import (
    ClaudeCliProvider,
    _extract_json_object,
)


def _valid_payload() -> dict:
    return {
        "title": "Test post",
        "short_summary": "A short summary of the test threat.",
        "threat_level": "Low",
        "why_it_matters": "It matters for the test.",
        "affected_users": ["Testers"],
        "what_to_do": ["Run the test"],
        "what_not_to_do": [],
        "quick_facts": ["A fact"],
        "emotional_weight": 0.2,
        "reading_time_seconds": 20,
    }


def _fake_envelope(payload: dict) -> str:
    return json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": json.dumps(payload),
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "total_cost_usd": 0,
    })


class _FakeProc:
    def __init__(self, stdout: str) -> None:
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


def _patch_run(monkeypatch, capture: dict, payload: dict):
    """Stub subprocess.run to capture the env it was called with."""
    def fake_run(cmd, **kwargs):
        capture["cmd"] = cmd
        capture["env"] = kwargs.get("env")
        return _FakeProc(_fake_envelope(payload))
    monkeypatch.setattr(
        "cyberalertx.ai.providers.claude_cli_provider.subprocess.run", fake_run
    )


def test_strips_api_key_from_subprocess_env(monkeypatch):
    """Default: ANTHROPIC_API_KEY / AUTH_TOKEN must NOT reach the CLI, so it
    bills the subscription rather than the metered API."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-should-not-leak")
    cap: dict = {}
    _patch_run(monkeypatch, cap, _valid_payload())

    provider = ClaudeCliProvider(binary="sh")  # any binary that resolves
    out = provider.generate_post("system", "user")

    assert out.title == "Test post"
    assert "ANTHROPIC_API_KEY" not in cap["env"]
    assert "ANTHROPIC_AUTH_TOKEN" not in cap["env"]
    # Non-billing env still passes through (PATH etc.).
    assert "PATH" in cap["env"]


def test_injects_oauth_token_from_env_file(monkeypatch, tmp_path):
    """The subscription token (CLAUDE_CODE_OAUTH_TOKEN) is loaded from the
    Claude env file when it isn't already exported — that's what makes a
    headless render authenticate on the subscription."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-billed")
    env_file = tmp_path / "env"
    env_file.write_text('export CLAUDE_CODE_OAUTH_TOKEN="oauth-sub-123"\n')
    cap: dict = {}
    _patch_run(monkeypatch, cap, _valid_payload())

    provider = ClaudeCliProvider(binary="sh", oauth_env_file=str(env_file))
    provider.generate_post("system", "user")

    # token injected, API key stripped → subscription billing
    assert cap["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-sub-123"
    assert "ANTHROPIC_API_KEY" not in cap["env"]


def test_existing_oauth_token_not_overwritten(monkeypatch, tmp_path):
    """A token already in the environment wins over the file."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "from-env")
    env_file = tmp_path / "env"
    env_file.write_text("CLAUDE_CODE_OAUTH_TOKEN=from-file\n")
    cap: dict = {}
    _patch_run(monkeypatch, cap, _valid_payload())

    provider = ClaudeCliProvider(binary="sh", oauth_env_file=str(env_file))
    provider.generate_post("system", "user")

    assert cap["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "from-env"


def test_use_subscription_false_keeps_api_key(monkeypatch):
    """Opt-out keeps the key for callers who deliberately want API billing."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-keep")
    cap: dict = {}
    _patch_run(monkeypatch, cap, _valid_payload())

    provider = ClaudeCliProvider(binary="sh", use_subscription=False)
    provider.generate_post("system", "user")

    assert cap["env"]["ANTHROPIC_API_KEY"] == "sk-keep"


def test_resolves_binary_from_fallback_dir_when_not_on_path(monkeypatch, tmp_path):
    """When `claude` isn't on PATH (the systemd-minimal-PATH case), the
    provider still finds it in a known install dir like ~/.local/bin."""
    import cyberalertx.ai.providers.claude_cli_provider as mod

    # Simulate a fake `claude` living in a dir that's NOT on PATH.
    bindir = tmp_path / "localbin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)

    monkeypatch.setattr(mod.shutil, "which", lambda _b: None)  # nothing on PATH
    monkeypatch.setattr(mod, "_FALLBACK_BIN_DIRS", (str(bindir),))

    provider = ClaudeCliProvider(binary="claude")
    assert provider._binary == str(fake)


def test_missing_binary_everywhere_raises(monkeypatch):
    import cyberalertx.ai.providers.claude_cli_provider as mod
    monkeypatch.setattr(mod.shutil, "which", lambda _b: None)
    monkeypatch.setattr(mod, "_FALLBACK_BIN_DIRS", ())
    with pytest.raises(RuntimeError, match="claude CLI not found"):
        ClaudeCliProvider(binary="claude")


def test_extract_json_object_handles_fences_and_prose():
    fenced = "prelude\n```json\n{\"a\": {\"b\": 1}}\n```\ntrailer"
    assert _extract_json_object(fenced) == '{"a": {"b": 1}}'
    prose = 'Here you go: {"x": "}{ tricky \\" str"} done'
    assert _extract_json_object(prose) == '{"x": "}{ tricky \\" str"}'


def test_extract_json_object_raises_without_object():
    with pytest.raises(RuntimeError):
        _extract_json_object("no json here")
