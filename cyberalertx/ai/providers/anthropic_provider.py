"""Anthropic provider — Claude via the official SDK.

Design notes:

  * **Prompt caching.** The system prompt is identical across all items
    for a given (language, category, audience) triple, so we mark it with
    `cache_control: ephemeral`. The cache writes ~1.25x but reads ~0.1x —
    net win at >=2 requests per (template, model) pair.

  * **Structured output via `messages.parse()`.** The SDK auto-generates
    a JSON schema from `ThreatPostResponse` (Pydantic) and validates the
    response against it. Validation errors raise, the generator catches,
    fallback fires.

  * **Retries.** The SDK already retries 429 / 5xx with exponential
    backoff. We just configure `max_retries` and let it run.

  * **Soft import.** `anthropic` is an optional dependency — if it isn't
    installed, instantiating `AnthropicProvider` raises a clear error
    instead of failing at import time. The rest of the package keeps working.
"""
from __future__ import annotations

import logging
from typing import Any, cast

from ..models import ThreatPostResponse

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Sync provider backed by `anthropic.Anthropic`.

    Construction is cheap; the client is created in __init__. Reuse the
    instance across many calls so SDK-level connection pooling kicks in.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "claude-opus-4-7",
        max_output_tokens: int = 1200,
        max_retries: int = 2,
    ) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover - import-time path
            raise RuntimeError(
                "anthropic SDK is required for AnthropicProvider. "
                "Install with: pip install anthropic"
            ) from exc

        self._anthropic = __import__("anthropic")
        self._client = self._anthropic.Anthropic(api_key=api_key, max_retries=max_retries)
        self._model = model
        self._max_output_tokens = max_output_tokens
        self.name = f"anthropic:{model}"

    def generate_post(self, system: str, user: str) -> ThreatPostResponse:
        """Call Claude with structured outputs + prompt caching, return the parsed model.

        Raises on:
          * network/auth errors (caller falls back to rule-based)
          * Pydantic validation failure (caller falls back to rule-based)
        """
        # System prompt is a stable cache prefix. The user prompt carries
        # the per-item facts and is not cached (it changes every call).
        # NOTE: prompt caching is silent — if the system prompt is below the
        # model's min-cacheable-tokens threshold (4096 on Opus 4.7), it just
        # doesn't cache. No error. Check usage.cache_read_input_tokens to verify.
        system_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        response = self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_output_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user}],
            output_format=ThreatPostResponse,
        )

        if getattr(response, "stop_reason", None) == "refusal":
            raise RuntimeError(
                f"Claude refused to generate this post "
                f"(stop_details={getattr(response, 'stop_details', None)})"
            )

        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise RuntimeError("Anthropic response missing parsed_output")

        usage = getattr(response, "usage", None)
        if usage is not None:
            self._record_usage(usage)

        # `parsed_output` is typed `Any` by the SDK; the `output_format=`
        # contract guarantees it's a validated ThreatPostResponse here.
        return cast(ThreatPostResponse, parsed)

    @staticmethod
    def _record_usage(usage: Any) -> None:
        """Log usage at INFO and bump observability counters.

        Promoted to INFO from DEBUG so the prompt-cache hit ratio is
        visible in journalctl by default — without it the cost story
        is purely opinion. The counters in `observability.metrics` give
        the same data over arbitrary time windows so we can audit weekly
        spend trends without re-grepping logs.

        Counter bumps are best-effort: if the observability module is
        unavailable (test isolation, partial import), we swallow the
        error rather than fail the render path."""
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)

        logger.info(
            "anthropic usage: input=%d cache_read=%d cache_write=%d output=%d",
            input_tokens, cache_read, cache_write, output_tokens,
        )

        try:
            from ...observability.metrics import get_quality_metrics
            m = get_quality_metrics()
            m.bump("anthropic_calls")
            if input_tokens:
                m.bump("anthropic_input_tokens", input_tokens)
            if cache_read:
                m.bump("anthropic_cache_read_tokens", cache_read)
            if cache_write:
                m.bump("anthropic_cache_write_tokens", cache_write)
            if output_tokens:
                m.bump("anthropic_output_tokens", output_tokens)
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("usage counter bump skipped: %s", exc)


__all__ = ["AnthropicProvider"]
