"""ContentGenerator — the AI layer's public entry point.

Execution policy (in order):

    1. If `cache_enabled` and the post is cached → return it.
    2. If a `provider` is configured → call it; on success store + return.
       On any failure (network, validation, refusal) → log + fall through.
    3. Run the rule-based fallback. Always succeeds.

This means: a caller never has to think about "is the LLM up?" — they always
get a ThreatPost. The `generated_by` field on the result tells them which
path produced it.

To wire a different provider, pass an instance that implements the
`LLMProvider` Protocol. Nothing else changes.
"""
from __future__ import annotations

import logging
from typing import Iterable, List

from ..models import NewsItem
from .config import AISettings, AI_SETTINGS
from .cache import ThreatPostCache
from .models import ThreatPost, ThreatPostResponse
from .provider import LLMProvider
from .rule_based import RuleBasedGenerator
from .templates import (
    PromptTemplate,
    TemplateRegistry,
    default_template_registry,
    render_prompts,
)

logger = logging.getLogger(__name__)


class ContentGenerator:
    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        template_registry: TemplateRegistry | None = None,
        cache: ThreatPostCache | None = None,
        rule_based: RuleBasedGenerator | None = None,
        prefer_audience: str | None = None,
        force_language: str | None = None,
    ) -> None:
        self._provider = provider
        self._templates = template_registry or default_template_registry()
        self._cache = cache
        self._fallback = rule_based or RuleBasedGenerator()
        self._prefer_audience = prefer_audience
        self._force_language = force_language

    # ----------------------- public API ------------------------------

    def generate(
        self,
        item: NewsItem,
        *,
        language: str | None = None,
    ) -> ThreatPost:
        """Generate a single ThreatPost.

        When `language` is provided, it overrides the instance-level
        `force_language` for this call only — used by the API to render
        the same item in multiple locales without juggling instance state
        across threads.
        """
        effective_lang = self._resolve_language(item, language)

        # 1. Cache lookup — cheapest path. Keyed by (fingerprint, locale)
        #    because the same item produces different text per locale.
        if self._cache is not None:
            cached = self._cache.get(item.fingerprint, effective_lang)
            if cached is not None:
                logger.debug("cache hit for %s/%s", item.fingerprint, effective_lang)
                return cached

        # 2. LLM path — try it, with a graceful fall-through on any failure.
        if self._provider is not None:
            try:
                post = self._generate_with_provider(item, effective_lang)
            except Exception as exc:
                logger.warning(
                    "AI generation failed for %s (%s); falling back to rule-based",
                    item.fingerprint, exc,
                )
            else:
                if self._cache is not None:
                    self._cache.set(item.fingerprint, effective_lang, post)
                return post

        # 3. Rule-based fallback. Never raises.
        post = self._fallback.generate(item)
        # Note: we intentionally DO NOT cache rule-based output. If the LLM
        # becomes available on the next run, we want to regenerate.
        return post

    def generate_many(self, items: Iterable[NewsItem]) -> List[ThreatPost]:
        return [self.generate(i) for i in items]

    # ----------------------- internals -------------------------------

    def _generate_with_provider(self, item: NewsItem, language: str) -> ThreatPost:
        assert self._provider is not None
        audience = self._select_audience(item)
        template = self._templates.select(language, item.category, audience)
        system_prompt, user_prompt = render_prompts(template, item, target_language=language)
        response = self._provider.generate_post(system_prompt, user_prompt)
        return self._post_from_response(response, item, template, language)

    def _resolve_language(self, item: NewsItem, override: str | None) -> str:
        """Pick the effective language for a render.

        Priority: explicit param → instance force_language → item.language
        → "en" fallback. Only "en" and "uk" are accepted; anything else
        falls through to "en".
        """
        for candidate in (override, self._force_language, item.language):
            if candidate in ("en", "uk"):
                return candidate
        return "en"

    # Backwards-compatible helper — some tests still call this.
    def _select_language(self, item: NewsItem) -> str:
        return self._resolve_language(item, None)

    def _select_audience(self, item: NewsItem) -> str:
        # If the caller pinned an audience and the item targets it, use that.
        if self._prefer_audience and self._prefer_audience in item.audience_targets:
            return self._prefer_audience
        # Otherwise pick the highest-priority audience the item has.
        if item.audience_targets:
            return item.audience_targets[0]
        return "general"

    def _post_from_response(
        self,
        response: ThreatPostResponse,
        item: NewsItem,
        template: PromptTemplate,  # noqa: ARG002 - kept for telemetry
        language: str,
    ) -> ThreatPost:
        # Clamp / normalize a few fields. Pydantic gave us types; we enforce
        # the public-contract bounds the LLM might violate.
        return ThreatPost(
            title=response.title.strip()[:160],
            short_summary=response.short_summary.strip(),
            threat_level=response.threat_level,
            why_it_matters=response.why_it_matters.strip(),
            affected_users=[s.strip() for s in response.affected_users if s.strip()],
            what_to_do=[s.strip() for s in response.what_to_do if s.strip()],
            what_not_to_do=[s.strip() for s in response.what_not_to_do if s.strip()],
            quick_facts=[s.strip() for s in response.quick_facts if s.strip()][:4],
            emotional_weight=max(0.0, min(1.0, float(response.emotional_weight))),
            reading_time_seconds=max(10, min(120, int(response.reading_time_seconds))),
            language=language,
            source_fingerprint=item.fingerprint,
            generated_by=self._provider.name if self._provider else "rule_based",
        )


# ------------------------- factory --------------------------------------

def build_default_generator(
    settings: AISettings | None = None,
    *,
    use_llm: bool | None = None,
) -> ContentGenerator:
    """Convenience factory.

    MVP default is **offline-first**: no provider is constructed, even when
    an API key is present in the environment. The LLM is opt-in via:
      * `CYBERALERTX_AI_ENABLE_LLM=1` (env), OR
      * `use_llm=True` passed here (e.g. from a `--use-llm` CLI flag).

    When opted in, `AISettings.provider` selects which vendor:
      * "anthropic" — AnthropicProvider if SDK + API key present
      * "openai"    — stub (calls fall back to rule-based, by design)
      * anything else — no provider (rule-based)
    """
    cfg = settings or AI_SETTINGS
    enable = use_llm if use_llm is not None else cfg.enable_llm
    provider: LLMProvider | None = None

    if enable:
        if cfg.provider == "anthropic" and cfg.api_key:
            try:
                from .providers import AnthropicProvider
                provider = AnthropicProvider(
                    api_key=cfg.api_key,
                    model=cfg.anthropic_model,
                    max_output_tokens=cfg.max_output_tokens,
                    max_retries=cfg.max_retries,
                )
            except RuntimeError as exc:
                logger.warning("Anthropic provider not available: %s", exc)
        elif cfg.provider == "openai" and cfg.openai_api_key:
            from .providers import OpenAIProvider
            provider = OpenAIProvider(
                api_key=cfg.openai_api_key,
                model=cfg.openai_model,
                max_output_tokens=cfg.max_output_tokens,
            )
        elif cfg.provider == "anthropic" and not cfg.api_key:
            logger.warning(
                "AI enabled but ANTHROPIC_API_KEY is not set — staying offline."
            )

    cache = ThreatPostCache(cfg.cache_path) if cfg.cache_enabled else None
    return ContentGenerator(provider=provider, cache=cache)


def describe_mode(generator: ContentGenerator) -> str:
    """One-line human description of the generator's current mode.

    Used by the CLI to print a clear banner. The leading prefix is stable
    so log scrapers can grep for `mode=`.
    """
    if generator._provider is None:  # noqa: SLF001 — read-only introspection
        return "mode=rule-based (offline)"
    return f"mode={generator._provider.name}"  # noqa: SLF001


__all__ = ["ContentGenerator", "build_default_generator", "describe_mode"]
