"""ContentGenerator — the AI layer's public entry point.

Execution policy (in order):

    1. If `cache_enabled` and the post is cached → return it.
    2. If a `provider` is configured → call it; on success store + return.
       On any failure (network, validation, refusal) → log + fall through.
    3. Run the rule-based fallback. Always succeeds.

Inside step 2, for each render:

    fact sheet (get-or-create, ONE call per story, cached per fingerprint;
    skipped if the provider has no `generate_json` or extraction failed)
      → render prompt with the sheet as a delimited block
      → UA glossary → editorial refine → hygiene → journalist validation
      → fact check vs source + sheet (a CVE / hash / public IP / CVSS score
        the source lacks raises ValidationFailure → rule-based fallback)
      → cross-locale check against the other locale already in the cache
      → scorecard → `quality` + `review_status` on the post → cache.

This means: a caller never has to think about "is the LLM up?" — they always
get a ThreatPost. The `generated_by` field on the result tells them which
path produced it.

To wire a different provider, pass an instance that implements the
`LLMProvider` Protocol. Nothing else changes.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterable, List

from ..models import NewsItem
from .config import AISettings, AI_SETTINGS
from .fact_check import FactCheckReport, Finding, check_cross_locale, check_item
from .fact_sheet import FactSheet, FactSheetCache, get_or_create_fact_sheet
from .models import ThreatPost, ThreatPostResponse
from .provider import LLMProvider
from .rule_based import RuleBasedGenerator
from .templates import (
    PromptTemplate,
    TemplateRegistry,
    default_template_registry,
    render_prompts,
)
from .validation import ValidationFailure, validate_journalist_response

if TYPE_CHECKING:
    # The cache is used only via .get()/.set(); accept any backend that
    # satisfies the ThreatPostStore Protocol (raw JSON cache OR the
    # dual-write PG wrapper), not just the concrete ThreatPostCache.
    from ..storage.dual_write import ThreatPostStore

logger = logging.getLogger(__name__)


class ContentGenerator:
    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        template_registry: TemplateRegistry | None = None,
        cache: "ThreatPostStore | None" = None,
        rule_based: RuleBasedGenerator | None = None,
        prefer_audience: str | None = None,
        force_language: str | None = None,
        fact_sheets: FactSheetCache | None = None,
        use_fact_sheet: bool = True,
    ) -> None:
        self._provider = provider
        self._templates = template_registry or default_template_registry()
        self._cache = cache
        self._fallback = rule_based or RuleBasedGenerator()
        self._prefer_audience = prefer_audience
        self._force_language = force_language
        # Fact-sheet stage. `fact_sheets` persists one sheet per story; the
        # memo keeps the two locale renders of a story in ONE process down to
        # one extraction even when no cache file is configured (tests).
        self._fact_sheets = fact_sheets
        self._use_fact_sheet = use_fact_sheet
        self._sheet_memo: dict[str, FactSheet | None] = {}

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

        # 2. LLM path — try it, with a graceful fall-through on any failure
        #    (network error, schema validation, or our journalist-quality
        #    validation rejecting AI sludge / clichés / dupes).
        if self._provider is not None:
            try:
                from ..observability import get_quality_metrics
                metrics = get_quality_metrics()
            except Exception:  # pragma: no cover — observability never blocks generation
                metrics = None
            if metrics is not None:
                metrics.bump("ai_renders_attempted")
            try:
                post = self._generate_with_provider(item, effective_lang)
            except ValidationFailure as exc:
                logger.warning(
                    "AI response failed quality validation for %s/%s (%s); "
                    "falling back to rule-based",
                    item.fingerprint, effective_lang, exc,
                )
                if metrics is not None:
                    metrics.record_validation_rejection(str(exc))
                    metrics.bump("ai_fallback_count")
            except Exception as exc:
                logger.warning(
                    "AI generation failed for %s/%s (%s); falling back to rule-based",
                    item.fingerprint, effective_lang, exc,
                )
                if metrics is not None:
                    metrics.bump("ai_provider_errors")
                    metrics.bump("ai_fallback_count")
            else:
                if self._cache is not None:
                    self._cache.set(item.fingerprint, effective_lang, post)
                if metrics is not None:
                    metrics.bump("ai_renders_success")
                return post

        # 3. Rule-based fallback. Never raises.
        post = self._fallback.generate(item, language=effective_lang)
        try:
            from ..observability import get_quality_metrics
            get_quality_metrics().bump("total_renders")
        except Exception:  # pragma: no cover
            pass
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
        # One shared fact sheet per story (the +1 call). `None` when the
        # provider can't produce one or extraction failed — the render then
        # runs exactly as it did before the stage existed.
        sheet = self._fact_sheet_for(item)
        system_prompt, user_prompt = render_prompts(
            template, item, target_language=language, fact_sheet=sheet,
        )
        from ..ops.usage import stage
        with stage("brief"):
            response = self._provider.generate_post(system_prompt, user_prompt)
        # UA-only: sweep the response through the russism glossary BEFORE
        # validation. Most "incorrect" russisms in AI output are small
        # tells like "путём" / "являться" that one regex pass fixes
        # without compromising meaning — we'd rather ship a clean post
        # than reject and fall back to rule-based for one stray word.
        # The validator still polices the *stems* that survive (i.e.,
        # ones the glossary doesn't cover) and fails the response there.
        if language == "ua":
            from .uk_glossary import normalize_ukrainian
            response.title = normalize_ukrainian(response.title)
            response.short_summary = normalize_ukrainian(response.short_summary)
            response.plain_summary = normalize_ukrainian(response.plain_summary)
            response.why_it_matters = normalize_ukrainian(response.why_it_matters)
            response.detail_body = normalize_ukrainian(response.detail_body)
            response.affected_users = [normalize_ukrainian(s) for s in response.affected_users]
            response.what_to_do = [normalize_ukrainian(s) for s in response.what_to_do]
            response.what_not_to_do = [normalize_ukrainian(s) for s in response.what_not_to_do]
            response.quick_facts = [normalize_ukrainian(s) for s in response.quick_facts]

        # Editorial refinement — strips AI fluff sentences and generic-
        # advice action items, dedups detail_body paragraphs that just
        # echo title/summary. Pure rewriting; doesn't raise. If the
        # response is so fluff-heavy that this pass empties critical
        # fields, the validator below catches it and we fall back to
        # rule_based, which is fluff-free by construction.
        from .editorial import refine_response
        refine_response(response, language)

        # Null bullets are dropped HERE, before validation, so the existing
        # "empty what_to_do list" gate below still holds the floor: a response
        # that is nothing but filler falls back to rule_based instead of being
        # cached with no actions at all. Ordering matters and is the whole
        # point — `_post_from_response` runs after the validator,
        # `ThreatPost.what_to_do` has no minimum length, and the result is
        # written to a cache keyed by `(fingerprint, locale)` with no prompt
        # version in it. Anything that slips through is permanent.
        #
        # Same predicates the render layer uses, so a fresh render and a
        # cached one are judged identically. `refine_response` covers most of
        # this already; `if_already_affected` is only covered here, and
        # keeping the block adjacent to the validator is what makes the
        # ordering guarantee readable.
        from .hygiene import is_null_action, is_null_check
        response.what_to_do = [
            s for s in response.what_to_do
            if s.strip() and not is_null_action(s, language)
        ]
        response.what_not_to_do = [
            s for s in response.what_not_to_do
            if s.strip() and not is_null_action(s, language)
        ]
        response.am_i_affected = [
            s for s in (response.am_i_affected or [])
            if s.strip() and not is_null_check(s, language)
        ]
        response.if_already_affected = [
            s for s in (response.if_already_affected or [])
            if s.strip() and not is_null_action(s, language)
        ]

        # Semantic validation. Pydantic already caught structural issues
        # (wrong types, missing required fields). Here we check that the
        # AI produced human-quality content: non-empty fields, no AI
        # clichés, no duplicate recommendations, and not a near-copy of
        # the source article. On any failure, we raise and the outer
        # `generate()` catches → falls back to the deterministic
        # editorial brief, which by construction never reuses source body.
        validate_journalist_response(
            response, source_title=item.title, source_body=item.raw_content,
            language=language,
        )
        post = self._post_from_response(response, item, template, language)

        # Factual validation. Hard violations — a CVE id, file hash, public IP
        # or CVSS score that neither the source nor the fact sheet contains —
        # reject the render like any other validation failure. A bug in the
        # checker must not cost the post, so only a REPORT can reject.
        report: FactCheckReport | None
        try:
            report = check_item(post, item, sheet)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("fact check crashed for %s/%s: %s", item.fingerprint, language, exc)
            report = None
        if report is not None and not report.ok:
            raise ValidationFailure(report.failure_message())

        self._attach_quality(post, item, language, sheet, report)
        return post

    # ----------------------- fact sheet / quality --------------------

    def _fact_sheet_for(self, item: NewsItem) -> FactSheet | None:
        if (
            not self._use_fact_sheet
            or self._provider is None
            or getattr(self._provider, "generate_json", None) is None
        ):
            return None
        return get_or_create_fact_sheet(
            self._provider, item, self._fact_sheets, self._sheet_memo,
        )

    def _cross_locale_findings(
        self, item: NewsItem, language: str, post: ThreatPost,
    ) -> list[Finding]:
        """Compare with the other locale of this story, if it is already cached
        (i.e. this is the second locale being written)."""
        if self._cache is None:
            return []
        other = "ua" if language == "en" else "en"
        try:
            other_post = self._cache.get(item.fingerprint, other)
        except Exception:  # pragma: no cover - cache backends are best-effort here
            return []
        if other_post is None or other_post.generated_by == "rule_based":
            return []
        if language == "en":
            return check_cross_locale(post, other_post, locale_a="en", locale_b="ua")
        return check_cross_locale(other_post, post, locale_a="en", locale_b="ua")

    def _attach_quality(
        self,
        post: ThreatPost,
        item: NewsItem,
        language: str,
        sheet: FactSheet | None,
        report: FactCheckReport | None,
    ) -> None:
        """Scorecard + findings onto the post, and its initial review status.

        Never raises: a scorecard problem leaves the post `auto` with no
        quality record rather than failing a render that already passed every
        gate.
        """
        from .review import initial_status
        from .scorecard import quality_record, score_post
        try:
            cross = self._cross_locale_findings(item, language, post)
            card = score_post(
                post, language=language, item=item, sheet=sheet,
                fact_report=report, cross_locale=cross,
            )
            post.quality = quality_record(
                card, fact_report=report, cross_locale=cross,
                fact_sheet_used=sheet is not None,
            )
            post.review_status = initial_status(card.needs_review)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("scorecard failed for %s/%s: %s", item.fingerprint, language, exc)

    def _resolve_language(self, item: NewsItem, override: str | None) -> str:
        """Pick the effective language for a render.

        Priority: explicit param → instance force_language → item.language
        → "en" fallback. Only "en" and "ua" are accepted; anything else
        falls through to "en".
        """
        for candidate in (override, self._force_language, item.language):
            if candidate in ("en", "ua"):
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
        from .models import Reference
        from .references import (
            drop_source_host_refs,
            drop_unverified_id_refs,
            extract_references,
            merge_references,
        )

        # Combine deterministic + AI-provided references. Deterministic
        # first so its (verifiable) entries take precedence on dup.
        # Then drop anything pointing back at the source's own host — the
        # post already exposes that as "Read on source", so a same-host
        # reference (model hallucination or CISA-on-CISA dup) is noise.
        # Finally drop refs whose label promises a specific advisory ID
        # the URL doesn't actually link to (e.g. "Cisco Security Advisory
        # CVE-2026-20182" → /CiscoSecurityAdvisory root).
        deterministic_refs = extract_references(item.raw_content or "")
        ai_refs = [
            Reference(type=r.type, label=r.label.strip(), url=r.url.strip())
            for r in (response.references or [])
            if r.label.strip() and r.url.strip()
        ]
        refs = drop_unverified_id_refs(
            drop_source_host_refs(
                merge_references(deterministic_refs, ai_refs),
                item.url,
            )
        )

        # Hard caps enforced silently (the prompt asks for these; the caps
        # are a safety net for occasional model over-production). Operational
        # briefing rules: ≤3 actions, ≤2 anti-patterns, ≤5 quick_facts.
        return ThreatPost(
            title=response.title.strip()[:160],
            short_summary=response.short_summary.strip(),
            plain_summary=response.plain_summary.strip(),
            threat_level=response.threat_level,
            why_it_matters=response.why_it_matters.strip(),
            affected_users=[s.strip() for s in response.affected_users if s.strip()],
            what_to_do=[s.strip() for s in response.what_to_do if s.strip()][:3],
            what_not_to_do=[s.strip() for s in response.what_not_to_do if s.strip()][:2],
            quick_facts=[s.strip() for s in response.quick_facts if s.strip()][:5],
            emotional_weight=max(0.0, min(1.0, float(response.emotional_weight))),
            reading_time_seconds=max(10, min(120, int(response.reading_time_seconds))),
            detail_body=(response.detail_body or "").strip(),
            # Reader-1 fields. Capped like the action lists above — the
            # prompt asks for 2-3 and 0-3 respectively, these are the safety
            # net for occasional over-production.
            am_i_affected=[
                s.strip() for s in (response.am_i_affected or []) if s.strip()
            ][:3],
            if_already_affected=[
                s.strip() for s in (response.if_already_affected or []) if s.strip()
            ][:3],
            severity_reason=(response.severity_reason or "").strip(),
            references=refs,
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
    an API key is present in the environment. The LLM is opt-in via the
    `use_llm=True` argument (driven by the CLI `--use-llm` flag). There is
    intentionally no env var that auto-enables paid calls — previous
    versions had `CYBERALERTX_AI_ENABLE_LLM=1` for this and it surprised
    operators with unexpected bills when set "just in case".

    When opted in, `AISettings.provider` selects which engine:
      * "claude_cli" — ClaudeCliProvider: renders via the local `claude` CLI
        (Claude Code headless), reusing its own login. No ANTHROPIC_API_KEY.
        This is the default. Falls back to rule-based if the CLI is missing
        or not logged in.
      * "anthropic" — AnthropicProvider (Haiku 4.5 API) if SDK + API key
        present. The legacy path, kept intact for an easy switch-back.
      * "openai"    — stub (calls fall back to rule-based, by design)
      * anything else — no provider (rule-based)
    """
    cfg = settings or AI_SETTINGS
    enable = use_llm if use_llm is not None else cfg.enable_llm
    provider: LLMProvider | None = None

    if enable:
        if cfg.provider == "claude_cli":
            try:
                from .providers import ClaudeCliProvider
                provider = ClaudeCliProvider(
                    binary=cfg.claude_cli_bin,
                    model=cfg.claude_cli_model,
                    timeout_seconds=cfg.claude_cli_timeout,
                    oauth_env_file=cfg.claude_cli_env_file or None,
                )
            except RuntimeError as exc:
                logger.warning("Claude CLI provider not available: %s", exc)
        elif cfg.provider == "anthropic" and cfg.api_key:
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

    # Cache backend chosen by CYBERALERTX_STORAGE_BACKEND. Default `json`
    # returns a raw ThreatPostCache (same as before). `dual` wraps it
    # with DualWriteThreatPostCache (PG-preferred reads, fan-out writes).
    if cfg.cache_enabled:
        from ..storage import build_threat_post_cache
        cache = build_threat_post_cache(cfg.cache_path)
    else:
        cache = None
    # The fact-sheet file is only opened when a provider exists: offline and
    # serve-path generators never extract, so they never touch it.
    fact_sheets = (
        FactSheetCache(cfg.fact_sheet_path)
        if provider is not None and cfg.fact_sheet_enabled else None
    )
    return ContentGenerator(
        provider=provider, cache=cache, fact_sheets=fact_sheets,
        use_fact_sheet=cfg.fact_sheet_enabled,
    )


def describe_mode(generator: ContentGenerator) -> str:
    """One-line human description of the generator's current mode.

    Used by the CLI to print a clear banner. The leading prefix is stable
    so log scrapers can grep for `mode=`.
    """
    if generator._provider is None:  # noqa: SLF001 — read-only introspection
        return "mode=rule-based (offline)"
    return f"mode={generator._provider.name}"  # noqa: SLF001


__all__ = ["ContentGenerator", "build_default_generator", "describe_mode"]
