"""AI layer configuration (environment-overridable).

Why this lives separately from `cyberalertx.config`:
  * the AI layer can be disabled entirely — no API key, no problem
  * different lifecycle: API keys and model choices change more often than
    feed URLs and fetch intervals
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
    # MVP-first: rule-based offline is the default. The LLM provider is opt-in.
    # Even with ANTHROPIC_API_KEY set, the provider does NOT load unless
    # this flag is true OR the CLI passes --use-llm.
    enable_llm: bool = _bool_env("CYBERALERTX_AI_ENABLE_LLM", False)
    # "anthropic" | "openai" — only consulted when `enable_llm` is True.
    provider: str = os.getenv("CYBERALERTX_AI_PROVIDER", "anthropic")
    # Default to Opus 4.7 per Anthropic guidance. Override for cost/latency
    # via env: CYBERALERTX_AI_MODEL=claude-haiku-4-5 for high-volume runs.
    anthropic_model: str = os.getenv("CYBERALERTX_AI_MODEL", "claude-opus-4-7")
    api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    # OpenAI is stubbed in v1 — config exists so the abstraction is real.
    openai_model: str = os.getenv("CYBERALERTX_OPENAI_MODEL", "gpt-4o-mini")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    # Hard cap on output tokens — prevents runaway responses.
    max_output_tokens: int = int(os.getenv("CYBERALERTX_AI_MAX_TOKENS", "1200"))
    # Cache location for generated ThreatPosts (keyed by NewsItem fingerprint).
    cache_path: Path = DATA_DIR / "threat_posts.json"
    # If True, the generator caches LLM outputs to disk. Disable to force
    # regeneration on every call (useful when iterating on prompts).
    cache_enabled: bool = _bool_env("CYBERALERTX_AI_CACHE", True)
    # Anthropic SDK retries 429/5xx automatically; this caps its retry budget.
    max_retries: int = int(os.getenv("CYBERALERTX_AI_RETRIES", "2"))


AI_SETTINGS = AISettings()
