"""AI layer configuration (environment-overridable).

Why this lives separately from `cyberalertx.config`:
  * the AI layer can be disabled entirely — no API key, no problem
  * different lifecycle: API keys and model choices change more often than
    feed URLs and fetch intervals

`enable_llm` is intentionally NOT read from the environment. Pre-2026 the
env var `CYBERALERTX_AI_ENABLE_LLM` quietly enabled paid Anthropic calls
during `generate` even when `--use-llm` wasn't passed. That violated the
project's cost-predictability invariant ("AI runs only when you explicitly
ask"). The flag stays on the dataclass for tests that opt in via kwarg,
but the canonical CLI control is `--use-llm`.

The legacy hybrid relevance classifier
(`CYBERALERTX_AI_RELEVANCE` / `CYBERALERTX_AI_RELEVANCE_MODEL`) was also
removed: `_build_pipeline` in main.py constructs a deterministic-only
pipeline and never wires the classifier, so those env vars did nothing
while suggesting they did something. The classifier *code* still lives
in `cyberalertx/pipeline/relevance.py` for possible future use.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..config import DATA_DIR


def _bool_env(name: str, default: bool) -> bool:
    """Truthy envs: '1', 'true', 'yes' (case-insensitive). Anything else → False."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class AISettings:
    # Whether the LLM provider auto-loads at `build_default_generator()`
    # construction. **Not read from env** — the only way to set this True
    # is the CLI `--use-llm` flag (which passes use_llm=True into the
    # factory, overriding this default). Tests may pass `enable_llm=True`
    # as a kwarg directly when constructing AISettings.
    enable_llm: bool = False
    # "claude_cli" | "anthropic" | "openai" — only consulted when `enable_llm`
    # is True. Default is "claude_cli": post content is rendered by the local
    # `claude` CLI (Claude Code headless) reusing its own login, NOT by a
    # metered Haiku call through ANTHROPIC_API_KEY. To switch back to the
    # Haiku 4.5 API path (which is left fully intact), set
    # CYBERALERTX_AI_PROVIDER=anthropic.
    provider: str = os.getenv("CYBERALERTX_AI_PROVIDER", "claude_cli")
    # Default to Haiku — journalist rendering is a constrained, schema-bound
    # task where Haiku 4.5 matches Opus quality at ~10x lower cost and
    # 4-5x lower latency. For experiments where you want richer prose,
    # set CYBERALERTX_AI_MODEL=claude-opus-4-7.
    anthropic_model: str = os.getenv(
        "CYBERALERTX_AI_MODEL", "claude-haiku-4-5-20251001",
    )
    api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    # --- claude_cli provider (the new default content engine) -----------
    # Path to the `claude` binary. Default resolves it on PATH. The box must
    # have Claude Code installed AND logged in (interactive `claude` once, or
    # `claude setup-token`) — otherwise every render raises "Not logged in"
    # and the generator falls back to rule-based output.
    claude_cli_bin: str = os.getenv("CYBERALERTX_CLAUDE_CLI_BIN", "claude")
    # Model alias/id for the CLI session. Empty → use the CLI's own default
    # model ("you"). Set e.g. CYBERALERTX_CLAUDE_CLI_MODEL=sonnet to pin one.
    claude_cli_model: str | None = os.getenv("CYBERALERTX_CLAUDE_CLI_MODEL") or None
    # Per-render subprocess timeout. One `claude -p` call for a single post
    # typically returns in 10-40s; 120s is a generous ceiling before we give
    # up and fall back.
    claude_cli_timeout: int = int(os.getenv("CYBERALERTX_CLAUDE_CLI_TIMEOUT", "120"))
    # Shell env file the subscription token (CLAUDE_CODE_OAUTH_TOKEN) is read
    # from when it isn't already exported — `claude setup-token` writes it to
    # `~/.config/claude/env`, which nothing loads into a headless subprocess.
    # Empty string disables the lookup (rely on env / ~/.claude credentials).
    claude_cli_env_file: str = os.getenv(
        "CYBERALERTX_CLAUDE_CLI_ENV_FILE", "~/.config/claude/env",
    )
    # OpenAI is stubbed in v1 — config exists so the abstraction is real.
    openai_model: str = os.getenv("CYBERALERTX_OPENAI_MODEL", "gpt-4o-mini")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    # Hard cap on output tokens — prevents runaway responses while leaving
    # room for the full ThreatPost schema (title + summary + why_it_matters
    # + detail_body + 3 actions + 2 avoids + quick_facts + references).
    #
    # Default 2000: comfortably fits a 120-220 word detail_body even in
    # Ukrainian, where Cyrillic tokenizes ~1.5-2x denser than Latin. The
    # earlier default of 1200 truncated UA responses mid-JSON ("EOF while
    # parsing a string at column N") and was the second-largest cause of
    # EN-source items not appearing on the UA page (after the title-
    # language slip, which the prompt now enforces explicitly). Cost
    # impact of the bump is nil — providers bill per actual output token,
    # not the cap.
    max_output_tokens: int = int(os.getenv("CYBERALERTX_AI_MAX_TOKENS", "2000"))
    # Cache location for generated ThreatPosts (keyed by NewsItem fingerprint).
    cache_path: Path = DATA_DIR / "threat_posts.json"
    # If True, the generator caches LLM outputs to disk. Disable to force
    # regeneration on every call (useful when iterating on prompts).
    cache_enabled: bool = _bool_env("CYBERALERTX_AI_CACHE", True)
    # Anthropic SDK retries 429/5xx automatically; this caps its retry budget.
    max_retries: int = int(os.getenv("CYBERALERTX_AI_RETRIES", "2"))


AI_SETTINGS = AISettings()
