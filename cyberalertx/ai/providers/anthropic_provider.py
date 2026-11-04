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

import json
import logging
from typing import Any, Mapping, cast

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
            self._record_usage(usage, self._model)

        # `parsed_output` is typed `Any` by the SDK; the `output_format=`
        # contract guarantees it's a validated ThreatPostResponse here.
        return cast(ThreatPostResponse, parsed)

    def generate_json(
        self, system: str, user: str, *, schema: Mapping[str, Any],
    ) -> dict[str, Any]:
        """One structured-output call constrained by a raw JSON Schema.

        Uses `output_config={"format": {"type": "json_schema", ...}}` on
        `messages.create`, which makes the first text block valid JSON for
        the schema. The schema is first rewritten into the subset structured
        outputs accepts (see `_strict_schema`); the caller still validates the
        result against its own Pydantic model, so constraints dropped here
        are enforced there.
        """
        system_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_output_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user}],
            output_config={
                "format": {"type": "json_schema", "schema": _strict_schema(schema)},
            },
        )
        if getattr(response, "stop_reason", None) == "refusal":
            raise RuntimeError("Claude refused the structured request")
        if getattr(response, "stop_reason", None) == "max_tokens":
            raise RuntimeError("structured response truncated at max_tokens")

        usage = getattr(response, "usage", None)
        if usage is not None:
            self._record_usage(usage, self._model)

        text = next(
            (getattr(b, "text", "") for b in getattr(response, "content", [])
             if getattr(b, "type", "") == "text"),
            "",
        )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Anthropic structured output was not JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Anthropic structured output was not a JSON object")
        return data

    @staticmethod
    def _record_usage(usage: Any, model: str = "") -> None:
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
        try:
            from ...ops.usage import record_call
            record_call(provider="anthropic", model=model,
                        input_tokens=input_tokens, output_tokens=output_tokens,
                        cache_read_tokens=cache_read, cache_write_tokens=cache_write)
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("usage ledger skipped: %s", exc)


# Keywords structured outputs rejects. Dropped from the schema we send; the
# caller's Pydantic model still enforces whatever they expressed.
_UNSUPPORTED_SCHEMA_KEYS = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems",
    "default", "title", "examples",
})


def _strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Rewrite a Pydantic-style JSON Schema into the structured-outputs subset.

    Every object gets `additionalProperties: false` and lists all of its
    properties as required (a field with a default simply comes back empty),
    and unsupported constraint keywords are removed. Pure; returns a copy.
    """
    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, Mapping):
            return node
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in ("properties", "$defs", "definitions") and isinstance(v, Mapping):
                # Keys here are field / definition NAMES, not keywords — a
                # field called "title" must survive.
                out[k] = {name: walk(sub) for name, sub in v.items()}
            elif k not in _UNSUPPORTED_SCHEMA_KEYS:
                out[k] = walk(v)
        if out.get("type") == "object" or "properties" in out:
            props = out.get("properties")
            if isinstance(props, dict):
                out["required"] = list(props.keys())
            out["additionalProperties"] = False
        return out

    result = walk(schema)
    return result if isinstance(result, dict) else {}


__all__ = ["AnthropicProvider"]
