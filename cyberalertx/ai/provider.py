"""LLM provider contract.

Every concrete provider (Anthropic, OpenAI, a local model, a mock for tests)
implements this Protocol. The `ContentGenerator` knows nothing about the
underlying SDK — it just calls `provider.generate_post(system, user)`.

Cost-awareness lives below this line: caching, model choice, max_tokens
are all per-provider concerns. The generator stays simple.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import ThreatPostResponse


@runtime_checkable
class LLMProvider(Protocol):
    """Synchronous, single-shot structured-output provider.

    Implementations should:
      * apply their own retry / timeout policy
      * use prompt caching where the SDK supports it (system prompt is stable)
      * raise on parse/validation failures so the generator can fall back
    """

    name: str  # e.g. "anthropic:claude-opus-4-7", "openai:gpt-4o-mini-stub"

    def generate_post(self, system: str, user: str) -> ThreatPostResponse:
        """Return a validated ThreatPostResponse, or raise on failure."""
        ...
