"""LLM provider contract.

Every concrete provider (Anthropic, OpenAI, a local model, a mock for tests)
implements this Protocol. The `ContentGenerator` knows nothing about the
underlying SDK — it just calls `provider.generate_post(system, user)`.

Cost-awareness lives below this line: caching, model choice, max_tokens
are all per-provider concerns. The generator stays simple.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

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

    def generate_json(
        self, system: str, user: str, *, schema: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return one JSON object shaped by `schema` (a JSON Schema), or raise.

        Generic structured-output call, used by the fact-sheet stage
        (`ai/fact_sheet.py`). The provider only guarantees "a JSON object";
        the caller validates it against its own model, so a provider that
        cannot enforce the schema server-side may simply describe it in the
        prompt.

        Providers written before this method existed do not have it. The
        generator checks with `getattr` and skips the fact sheet for them,
        so they keep working unchanged.
        """
        ...
