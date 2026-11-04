"""FastAPI app for CyberAlertX.

Routes (all GET):
  /healthz              — basic liveness probe (returns {"ok": true, ...})
  /posts                — main feed, ranked by threat_score desc
  /posts/trending       — urgent_action OR Critical, ranked by score
  /posts/latest         — most recently published

Shared concerns live in `_PostService`:
  * loading NewsItems from disk
  * passing each through the ContentGenerator (cache-aware)
  * merging the NewsItem metadata with the generated ThreatPost shape
  * returning the merged dict directly (it already matches the frontend
    `ThreatPost` TypeScript type byte-for-byte — see `frontend/lib/types.ts`)

The merge is done once per item per request. The expensive step — actually
running an LLM or the rule-based generator — is amortized via
`ThreatPostCache` on disk, so the second-and-onward requests for the same
fingerprint are essentially free.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, quote, urlencode

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasicCredentials
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..ai.detail_context import detail_context_for
from ..ai.generator import ContentGenerator, build_default_generator
from ..ai.hygiene import clean_localized_content
from ..ai.models import ThreatPost
from ..ai.review import (
    DECISIONS,
    apply_decision,
    is_publicly_visible,
    parse_key,
    post_key,
    review_mode,
)
from ..ai.scorecard import review_threshold
from ..config import DATA_DIR, SETTINGS
from ..feedback import FeedbackError, append_record, parse_submission, read_records, summarize
from .admin.guard import client_address
from .admin import (
    CSP as ADMIN_CSP,
    CSP_FORMS as ADMIN_CSP_FORMS,
    REVIEW_TABS,
    AdminGuard,
    FeedStatus,
    ReviewEntry,
    render_feedback,
    render_intel,
    render_not_found,
    render_overview,
    render_quality,
    render_review,
    render_sources,
    same_origin,
)
from ..models import NewsItem
from ..observability import get_quality_metrics, get_source_health
from ..pipeline.dedup import collapse_duplicates
from ..pipeline.signals import extract_signals, potential_impact, who_should_care
from ..storage.json_store import JsonNewsStore

logger = logging.getLogger(__name__)

#: /feedback is the only public write. These bound what a flood can cost.
#: The rate is site-wide rather than per client on purpose: the origin is
#: reachable directly, so any client address the app sees can be forged, and
#: a per-IP limit would be one header away from useless. 120 votes a minute
#: is far beyond organic traffic for this site.
_FEEDBACK_MAX_PER_MINUTE = 120
#: ~150 bytes a record, so this is over 100k votes — well past organic volume.
#: Past it, writes stop rather than fill the disk.
_FEEDBACK_MAX_BYTES = 20 * 1024 * 1024


# ----------- homepage ranking ------------------------------------------

# Items older than this drop off the homepage entirely. They remain
# fetchable via /posts/{id} (direct links keep working) but the feed
# stops showing stale stories — the product should feel current.
#
# Per-locale windows: tuned to the volume each pool produces.
#   EN  → 14 days. The English firehose (BleepingComputer, THN, Krebs,
#         Securelist, CISA) easily fills the feed at a 2-week ceiling;
#         anything older feels stale next to fresher coverage.
#   UA  → 45 days (≈1.5 months). Ukrainian cyber coverage is sparser
#         and bursty (itc.ua, ain.ua, dev.ua, dou.ua aren't pure-cyber
#         beats), so we keep items visible longer to maintain feed
#         density on the UA homepage.
_HOMEPAGE_MAX_AGE_DAYS_EN = 30
_HOMEPAGE_MAX_AGE_DAYS_UA = 90
_HOMEPAGE_MAX_AGE_DAYS_DEFAULT = _HOMEPAGE_MAX_AGE_DAYS_EN

# Legacy alias kept for tests that still reference the single-constant name.
_HOMEPAGE_MAX_AGE_DAYS = _HOMEPAGE_MAX_AGE_DAYS_DEFAULT

def _max_age_days_for(language: str | None) -> int:
    """Pick the freshness ceiling that matches the requested locale.
    Accepts the legacy `uk` code as an alias for `ua` so old links don't
    silently fall through to the EN default window."""
    if language in ("ua", "uk"):
        return _HOMEPAGE_MAX_AGE_DAYS_UA
    if language == "en":
        return _HOMEPAGE_MAX_AGE_DAYS_EN
    return _HOMEPAGE_MAX_AGE_DAYS_DEFAULT


def _within_homepage_window(
    item: NewsItem, now: datetime, *, language: str | None = None,
) -> bool:
    """Filter items by age. The ceiling depends on the requested locale —
    Ukrainian gets a wider window because its source pool is sparser."""
    # Prefer the locale passed by the caller; otherwise key off the item's
    # own source language so a mixed (un-filtered) sweep behaves sensibly.
    lang = language or item.language
    return (now - item.published_at) <= timedelta(days=_max_age_days_for(lang))


# ---------- service -----------------------------------------------------

class PostHidden(RuntimeError):
    """Every locale of an item is withheld by editorial review.

    Distinct from "all renders failed" so `/posts/{id}` can answer 404 and the
    list endpoints can skip the item without logging it as a failure.
    """


class _PostService:
    """Reads NewsItems + generates ThreatPosts on demand.

    A single instance per process; the underlying caches (ThreatPostCache,
    JsonNewsStore's in-memory dict) are file-backed so multiple uvicorn
    workers stay coherent via disk.

    **Cost-safety contract:** the API server NEVER calls Anthropic. The
    generator is constructed without a provider regardless of any env
    configuration:
      * cache hit  → return cached AI output (paid for previously by `generate`)
      * cache miss → fall through to rule_based (offline, $0)

    There is no escape hatch. AI calls happen exclusively from the
    `generate --use-llm` CLI — explicit, bounded, operator-controlled.
    Anyone who genuinely needs live serving forks this constructor.
    """

    def __init__(
        self,
        store: JsonNewsStore | None = None,
        generator: ContentGenerator | None = None,
    ) -> None:
        self._store = store or JsonNewsStore(
            SETTINGS.storage_path, max_items=SETTINGS.max_items_retained,
        )
        if generator is None:
            # No provider on the serve path, ever. Cache + rule_based only.
            generator = build_default_generator(use_llm=False)
            generator._provider = None  # noqa: SLF001 — belt-and-suspenders
        self._generator = generator

    # mtime-tracked snapshot of items.json. We keep the parsed store in
    # memory between requests and only re-read disk when the file actually
    # changed — saves ~10-20ms of JSON parse on every /posts hit at 100+
    # items. The pipeline process writes via atomic temp+rename, so an
    # mtime jump is a complete file, never a partial read.
    _items_store_cached: JsonNewsStore | None = None
    _items_store_mtime: float = 0.0

    def list_items(self) -> list[NewsItem]:
        """Return all NewsItems. Cached in-memory; only re-reads disk when
        items.json mtime changes (catches concurrent pipeline cycles
        without paying the parse cost on every request)."""
        try:
            mtime = SETTINGS.storage_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        if (
            self._items_store_cached is None
            or mtime > self._items_store_mtime
        ):
            self._items_store_cached = JsonNewsStore(
                SETTINGS.storage_path, max_items=SETTINGS.max_items_retained,
            )
            self._items_store_mtime = mtime
        return self._items_store_cached.all()

    # Fields the generator owns (text content). Everything else is shared
    # metadata about the item and lives at the top level of the response.
    _LOCALIZED_FIELDS = (
        "title", "short_summary", "plain_summary", "why_it_matters",
        "affected_users", "what_to_do", "what_not_to_do", "quick_facts",
        "reading_time_seconds",
        # New in v0.4 — extended detail-page content.
        "detail_body", "references",
        # New in v0.5 — the reader-facing self-check, recovery steps, and
        # the plain-language reason behind the severity badge.
        "am_i_affected", "if_already_affected", "severity_reason",
    )

    def has_cached_render(self, item: NewsItem, locale: str | None) -> bool:
        """True when this item already has a persisted AI render.

        Used as the `prefer` signal for duplicate collapsing: when several
        articles cover one story, show the one we can actually render rather
        than the one that merely scores best on paper.
        """
        cache = getattr(self._generator, "_cache", None)
        if cache is None:
            return True
        if locale is not None:
            return self._cached_visible(cache, item.fingerprint, locale)
        source_lang = item.language if item.language in ("en", "ua") else "en"
        required = ("ua",) if source_lang == "ua" else ("en", "ua")
        return all(self._cached_visible(cache, item.fingerprint, loc) for loc in required)

    @staticmethod
    def _cached_visible(cache: Any, fingerprint: str, locale: str) -> bool:
        """A cached render readers may see. Under CYBERALERTX_REVIEW_MODE a
        post held for review counts as not rendered, so the feed, trending,
        dedup survivor choice and Telegram all skip it the same way they skip
        a post that was never generated."""
        post = cache.get(fingerprint, locale)
        return post is not None and is_publicly_visible(post)

    def render_if_cached(
        self, item: NewsItem, *, required_locale: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the same shape as `render()` ONLY if the AI cache covers
        what the caller actually needs. Otherwise return None.

        `required_locale` selects WHAT "covered" means:
          * Given (e.g. "en") → only that specific locale must be cached.
            Used by the homepage feed `/posts?language=en`: an item is
            shown iff the EN translation was deliberately AI-rendered.
          * None → ALL locales the item would normally render in must be
            cached. Used by related-threats / pool fetches that don't
            target a single locale.

        Why this exists:
          * The homepage demands a clean "I ran generate, only show me
            what I rendered" experience. cached_only=True + a locale
            filter delivers exactly that.
          * The related-threats pool wants speculative items dropped
            entirely; the broader "all locales" gate fits there.
          * `/posts/{id}` and the warm-up CLI deliberately use the full
            `render()` because they DO want generation when missing.
        """
        cache = getattr(self._generator, "_cache", None)
        if cache is None:
            return self.render(item)

        if required_locale is not None:
            # Just check the one locale the caller cares about.
            if not self._cached_visible(cache, item.fingerprint, required_locale):
                return None
        else:
            source_lang = item.language if item.language in ("en", "ua") else "en"
            required = ("ua",) if source_lang == "ua" else ("en", "ua")
            for locale in required:
                if not self._cached_visible(cache, item.fingerprint, locale):
                    return None
        try:
            return self.render(item)
        except PostHidden:
            return None

    def _media_block(self, item: NewsItem) -> dict[str, Any]:
        """`{"media": {"illustration": …}}` when the story has a VALIDATED
        editorial illustration; otherwise nothing (additive, optional field).
        Branded cards need no field: their URL derives from the post id."""
        try:
            from ..media.engine import illustration_payload
            store = _media_store()
            block = illustration_payload(store, item.fingerprint) if store else None
        except Exception:  # media must never break a post render
            return {}
        return {"media": {"illustration": block}} if block else {}

    def render(self, item: NewsItem) -> dict[str, Any]:
        """Merge a NewsItem's metadata with its localized ThreatPost(s).

        Returns the frontend `LocalizedThreatPost` shape — top-level shared
        fields (threat_level, category, platforms, …) and a `translations`
        sub-object holding the text content per locale.

        Asymmetric multilingual rule (product decision, not technical):

          EN-sourced item → render BOTH `en` and `uk`. The UK page can
                            still surface the highest-signal English cyber
                            stories (CISA advisories, BleepingComputer
                            scoops); the rule-based generator localizes
                            metadata and headlines stay in source language.

          UK-sourced item → render `uk` ONLY. We do NOT auto-translate
                            Ukrainian news to English. The English feed
                            stays clean, and the UK feed retains its
                            domestic voice. Frontend's source-language
                            filter (`/posts?language=en`) excludes UK
                            items from the EN page anyway.

          Other / unknown → treat as EN (matches the language gate that
                            would have dropped the item if it weren't
                            tolerated as "unknown" earlier).
        """
        source_lang = item.language if item.language in ("en", "ua") else "en"
        translations: dict[str, dict[str, Any]] = {}

        locales: tuple[str, ...]
        if source_lang == "ua":
            locales = ("ua",)
        else:
            # EN or unknown — render both. EN first so it's always the
            # "primary" for available_locales sort order.
            locales = ("en", "ua")

        # `primary_post` is what we read top-level metadata from
        # (threat_level, emotional_weight, generated_by). For UA-only items
        # we use the UA post; for EN-source items we use the EN post.
        primary_post = None
        hidden = 0
        for lang in locales:
            try:
                post = self._generator.generate(item, language=lang)
            except Exception as exc:
                logger.warning(
                    "locale %s generation failed for %s: %s",
                    lang, item.fingerprint, exc,
                )
                continue
            # Editorial review gate (CYBERALERTX_REVIEW_MODE). A held or
            # rejected locale is dropped here — the one funnel the site, RSS
            # and Telegram all share — rather than in each endpoint.
            if not is_publicly_visible(post):
                hidden += 1
                continue
            # Half-translated quality gate: if this locale is a TRANSLATION
            # (not the source language) AND the renderer fell back to
            # rule_based (i.e. AI couldn't produce a valid response), DON'T
            # include this locale in the response. Rule_based for a non-
            # source locale produces a Ukrainian brief alongside an English
            # title/source body — feels half-translated to the reader.
            # We'd rather hide the item from the target locale than ship
            # broken-looking content.
            #
            # The source-language locale ALWAYS uses what we get, including
            # rule_based fallback, because rule_based natively writes in
            # the source language by construction.
            is_translation = lang != source_lang
            is_rule_based = getattr(post, "generated_by", "") == "rule_based"
            if is_translation and is_rule_based:
                logger.info(
                    "skipping rule_based %s translation for EN-source %s "
                    "(would read as half-translated)",
                    lang, item.fingerprint,
                )
                continue
            # Read-time language gate: defend against stale cache entries
            # that pre-date the title-language validator in ai/validation.py.
            # Anthropic occasionally returns a UA-target render with a UA
            # body but an English title; until the title-language gate
            # existed (added 2026-05), those entries got cached as
            # `anthropic` provenance and slipped past the half-translated
            # filter above. We check again here so the API never serves a
            # hybrid-language card even if such an entry is still in cache.
            # Re-run `generate` with cache deleted to repopulate cleanly.
            from ..ai.validation import _wrong_script_for_language
            if _wrong_script_for_language(post.title, lang):
                logger.info(
                    "stale cache: %s/%s title is in wrong script (%r); "
                    "dropping locale. Re-run `generate` to refresh.",
                    item.fingerprint, lang, post.title[:60],
                )
                continue
            if primary_post is None:
                primary_post = post
            translations[lang] = _localized_content_dict(post, lang)

        if primary_post is None and hidden:
            raise PostHidden(f"{item.fingerprint} is withheld by editorial review")
        if primary_post is None:
            # Every render failed — surface a clear error rather than
            # returning a half-empty dict. The /posts endpoint catches
            # this and skips the item.
            raise RuntimeError(
                f"all locale renders failed for {item.fingerprint}"
            )

        # Threat-signal layer. Computed at render time (pure function on
        # the item's enrichment metadata), so adding/removing signals
        # never requires a storage migration. The two derived UX fields
        # (who_should_care, potential_impact) collapse the signal bundle
        # into something a reader can scan in a glance.
        signals = extract_signals(item)
        who_care = {
            "en": who_should_care(item, signals, language="en"),
            "ua": who_should_care(item, signals, language="ua"),
        }
        impact = {
            "en": potential_impact(signals, language="en"),
            "ua": potential_impact(signals, language="ua"),
        }

        # Category-level background, hand-written and never LLM-generated.
        # This is the layer that carries plain-language explanation for the
        # ~27% of posts that fall back to the rule-based renderer (see
        # `ai_fallback_count` in data/quality_metrics.json), whose
        # item-specific copy is a one-line template and whose `detail_body`
        # is always empty. Because it's keyed on category rather than the
        # incident, it's honest on every post: it explains how this FAMILY
        # of attack works, never claims incident-specific facts we don't
        # have, and reads the same in both locales.
        detail_context = {
            "en": detail_context_for(item.category, "en"),
            "ua": detail_context_for(item.category, "ua"),
        }

        return {
            "id": item.fingerprint,
            "source": item.source,
            "source_url": item.url,
            "source_tier": item.source_tier,
            "source_credibility_score": round(item.source_credibility_score, 3),
            "published_at": item.published_at.astimezone(timezone.utc).isoformat(),
            "threat_level": primary_post.threat_level,
            "category": item.category,
            "affected_platforms": list(item.affected_platforms),
            "audience_targets": list(item.audience_targets),
            "actionability_level": item.actionability_level,
            "actionability_score": round(item.actionability_score, 3),
            "emotional_weight": round(primary_post.emotional_weight, 3),
            "generated_by": primary_post.generated_by,
            # `source_language` is the language of the original article body.
            # Canonical signal for "which audience does this item belong to"
            # and for the asymmetric render rule (EN-source → both locales,
            # UK-source → UK only). Distinct from `available_locales`, which
            # lists locales we actually rendered metadata in.
            "source_language": source_lang,
            "available_locales": sorted(translations.keys()),
            **self._media_block(item),
            "translations": translations,
            # --- intelligence layer (post-architecture-stable refinement) ---
            # Boolean signals describing the *shape* of the threat. Stable
            # field names; UI binds directly. Powers ranking, filtering, and
            # future personalization.
            "signals": signals.to_dict(),
            # One-liner answering "does this affect me?" — keyed by locale.
            "who_should_care": who_care,
            # Ranked list of realistic-impact labels (e.g. "Account takeover",
            # "Credential compromise"). Capped at 3 per locale so the card
            # doesn't drown.
            "potential_impact": impact,
            # Names of other trusted sources reporting the same story. Empty
            # for single-source items. The frontend surfaces this as
            # "Also reported by …" to anchor reader trust.
            "corroborating_sources": list(item.corroborating_sources),
            # Per-category background paragraphs, keyed by locale. Detail
            # page only — cards never show them.
            "detail_context": detail_context,
        }


def _merge_story_sources(
    payload: dict[str, Any], sources: list[str] | None,
) -> None:
    """Fold cluster-derived corroboration into a rendered payload, in place.

    `corroborating_sources` was previously filled by the credibility
    analyzer's title-similarity heuristic, which only ever saw one fetch
    batch. Story clustering is strictly better evidence — those sources
    published the same story, we verified it — so cluster results are listed
    first, with anything the heuristic found appended if it isn't already
    there.

    `story_source_count` counts the outlets covering the story INCLUDING the
    one we're showing, which is the number the UI puts on a "3 sources"
    badge.
    """
    existing = list(payload.get("corroborating_sources") or [])
    merged = list(sources or [])
    for name in existing:
        if name not in merged and name != payload.get("source"):
            merged.append(name)
    payload["corroborating_sources"] = merged
    payload["story_source_count"] = len(merged) + 1


def _localized_content_dict(post: ThreatPost, locale: str = "en") -> dict[str, Any]:
    """Project a ThreatPost down to its localized text fields only.

    Runs the deterministic content-hygiene pass on the way out. This is the
    one place every render funnels through — the website and the Telegram
    publisher both consume `_PostService.render()` — so filtering here is
    what lets a contract fix reach posts that were cached before the fix
    existed. The AI cache is keyed by `(fingerprint, locale)` with no prompt
    version, so nothing else would ever repair them.

    Overrides `reading_time_seconds` with a value computed from the actual
    card-tier content. AI / rule_based historically returned 60-120s — that
    estimated a full detail-page read, but the card only surfaces title +
    summary + quick_facts (~30-60 words = 10-20s). The displayed number
    was confusing the reader ("a 2-minute read? this is one paragraph").
    Computed AFTER hygiene, so the estimate reflects the text that ships.
    """
    full = post.to_dict()
    base = {k: full[k] for k in _PostService._LOCALIZED_FIELDS}
    base = clean_localized_content(base, locale)
    base["reading_time_seconds"] = _compute_card_reading_time(base)
    return base


def _compute_card_reading_time(content: dict[str, Any]) -> int:
    """Estimate how long it takes to read the CARD-tier content (not the
    full detail page). Word-based at ~3 wps (≈180 wpm — comfortable
    technical reading pace), rounded to the nearest 5s, never below 5s.

    Card-tier content = the fields a reader actually sees in the feed:
    title, short_summary, quick_facts. The detail-page extras
    (why_it_matters, detail_body, action lists) are intentionally NOT
    counted — the reader hasn't committed to opening the detail yet, so
    the displayed "X min Y s" should reflect the scan, not the deep read.
    """
    title = content.get("title", "") or ""
    summary = content.get("short_summary", "") or ""
    facts = " ".join(content.get("quick_facts", []) or [])
    words = len((title + " " + summary + " " + facts).split())
    if words == 0:
        return 5
    seconds = words / 3.0  # 3 words/sec ≈ 180 wpm
    # Round to nearest 5s. Floor at 5s — anything below is just visually
    # dishonest (a card always takes at least a few seconds to register).
    return max(5, int(round(seconds / 5) * 5))


# ---------- app factory -------------------------------------------------

def build_app(
    *,
    service: _PostService | None = None,
    cors_origins: list[str] | None = None,
    feedback_path: Path | None = None,
    admin_guard: AdminGuard | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    `service` injectable for tests (so we can pass a service backed by an
    in-memory store / fixture data). `cors_origins` defaults to a permissive
    development list — narrow it in production via env / deploy config.
    """
    app = FastAPI(
        title="CyberAlertX API",
        description="Read-only threat intelligence feed.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )

    # CORS — only matters for browser-side calls. Next.js server fetches
    # never trigger CORS, but enabling these origins lets the API be hit
    # from the browser during local development and from the frontend's
    # client-side debugging tools.
    #
    # `allow_methods` must include POST (and OPTIONS for the preflight)
    # because `/feedback` is the only write endpoint and the browser
    # sends an OPTIONS preflight before any POST that carries a JSON body.
    # Without POST/OPTIONS here the preflight 400s and the feedback widget
    # never reaches the server.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    svc = service or _PostService()

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, Any]:
        """Liveness probe + feed-freshness telemetry.

        The freshness fields are the source of truth for the frontend's
        "Updated X ago" indicator. They're cheap to compute (one pass
        over the store, which is already in memory), so we surface them
        on healthz rather than building a dedicated route.
        """
        items = svc.list_items()
        now = datetime.now(timezone.utc)
        latest_published = max(
            (i.published_at for i in items), default=None,
        )
        latest_urgent = max(
            (i.published_at for i in items if i.actionability_level == "urgent_action"),
            default=None,
        )
        return {
            "ok": True,
            "stored_items": len(items),
            "timestamp": now.isoformat(),
            "latest_published_at": (
                latest_published.astimezone(timezone.utc).isoformat()
                if latest_published else None
            ),
            "latest_urgent_at": (
                latest_urgent.astimezone(timezone.utc).isoformat()
                if latest_urgent else None
            ),
            # Minutes since the last urgent_action item. The UI uses this
            # to render a subtle "Quiet day" badge when the feed has gone
            # >12h without an urgent threat — never an alarm.
            "minutes_since_last_urgent": (
                int((now - latest_urgent).total_seconds() // 60)
                if latest_urgent else None
            ),
        }

    def _dedupe_stories(
        items: list[NewsItem], language: str | None,
        cache_probe: dict[str, bool] | None = None,
    ) -> tuple[list[NewsItem], dict[str, list[str]]]:
        """Collapse multi-source coverage down to one item per story.

        The pipeline already tags items with a `story_key` at ingest, but we
        re-derive the grouping here for two reasons: items stored before
        clustering existed carry no key (they degrade to one-story-each), and
        this is the layer that knows which article we can actually render in
        the requested locale — so the survivor is chosen with that in mind.

        Returns the survivors plus, per surviving fingerprint, the other
        sources that covered the same story.

        The `prefer` lookup hits the AI cache, which is a Postgres round-trip
        in the dual-write configuration. Results are recorded in `cache_probe`
        so the render loop that runs next can reuse them instead of asking
        about the same fingerprint a second time — the two stages together
        now cost one lookup per item, not two.
        """
        seen = cache_probe if cache_probe is not None else {}

        def _renderable(item: NewsItem) -> bool:
            cached = seen.get(item.fingerprint)
            if cached is None:
                cached = svc.has_cached_render(item, language)
                seen[item.fingerprint] = cached
            return cached

        # Optional public relevance gate (off by default; see
        # pipeline.relevance.hide_out_of_scope_publicly). Feed paths only —
        # `/posts/{id}` does not come through here, so links keep working.
        from ..pipeline.relevance import hide_out_of_scope_publicly, is_renderable
        if hide_out_of_scope_publicly():
            items = [i for i in items if is_renderable(i)]
        return collapse_duplicates(items, prefer=_renderable)

    def _render_many(
        items: list[NewsItem], *,
        cached_only: bool = False,
        language: str | None = None,
        limit: int | None = None,
        extra_sources: dict[str, list[str]] | None = None,
        cache_probe: dict[str, bool] | None = None,
    ) -> list[dict[str, Any]]:
        """Render a batch.

        `cached_only=True` makes us skip items that aren't AI-cached
        instead of triggering fresh AI generation OR falling through to
        a rule_based placeholder. Used by:
          * homepage feed — pairs with `language` so an item shows iff
            the SPECIFIC locale was deliberately AI-rendered.
          * related-threats pool — `language` is None there so we drop
            items missing in ANY required locale.
        `/posts/{id}` skips cached_only because that's an explicit
        navigation — the user wants content even if rule_based fallback.

        `limit` early-stops the loop once enough renders are collected.
        Critical for the feed path: callers pass the full filtered store
        (not a pre-sliced top-N) so a freshly-ingested but not-yet-rendered
        item doesn't burn the slot that an older-but-AI-rendered item
        could have filled.
        """
        rendered: list[dict[str, Any]] = []
        for item in items:
            if limit is not None and len(rendered) >= limit:
                break
            try:
                if cached_only:
                    # The dedup stage already asked the cache about some of
                    # these fingerprints. Reuse a negative answer rather than
                    # paying for the same round-trip twice.
                    if cache_probe is not None and cache_probe.get(item.fingerprint) is False:
                        continue
                    payload = svc.render_if_cached(item, required_locale=language)
                    if payload is None:
                        continue
                else:
                    payload = svc.render(item)
                # Note `is not None`, not truthiness: a batch where nothing
                # merged still needs every item stamped with
                # `story_source_count = 1`, or the field is absent exactly
                # when the feed happens to hold no duplicates and the
                # frontend can't tell "single source" from "old API shape".
                if extra_sources is not None:
                    _merge_story_sources(payload, extra_sources.get(item.fingerprint))
                rendered.append(payload)
            except PostHidden:
                continue  # held for review — not a failure
            except Exception as exc:
                # One bad item must not break the response. Log it and
                # skip — the frontend gets the remaining valid posts.
                logger.warning(
                    "render failed for %s: %s — skipping", item.fingerprint, exc,
                )
        return rendered

    @app.get("/posts", tags=["posts"])
    def list_posts(
        limit: int = Query(30, ge=1, le=200),
        language: str | None = Query(
            None, pattern="^(en|ua|uk)$",
            description="Locale filter. 'uk' accepted for legacy URLs, "
                        "normalized to 'ua' internally.",
        ),
        cached_only: bool = Query(
            True,
            description="Default TRUE — the homepage feed serves only items "
                        "with a persisted AI render in the requested locale. "
                        "Items still in rule-based-only state never leak to "
                        "the public feed. Pass `cached_only=false` for "
                        "internal / debugging views that want everything.",
        ),
    ) -> dict[str, Any]:
        """Main feed — strict reverse-chronological (newest first).

        Returns up to `limit` items (default 30, max 200), all of them
        AI-rendered when `cached_only=True`. Older items remain available
        as long as they're in the AI cache — there is no freshness cutoff
        on the feed itself. The growing archive is by design: as cache
        accumulates over weeks, readers can scroll deeper for context.
        Trending (`/posts/trending`) keeps a freshness window because its
        semantic is "currently dangerous", not "everything we have".

        `?language=X` filters by which locale the post can be RENDERED in:
          * `?language=ua`  →  EN-source items (UA metadata via translation)
                              PLUS UA-source items. English headlines may
                              appear on the UA page; the metadata layer is
                              always Ukrainian.
          * `?language=en`  →  EN-source items only. UA-source items are
                              NOT auto-translated to English, so the EN
                              feed is editorially clean.

        `uk` is accepted as a legacy alias for `ua` so old bookmarks still
        resolve.
        """
        now = datetime.now(timezone.utc)
        if language == "uk":
            language = "ua"
        # No freshness window — every AI-rendered item is fair game on the
        # feed, sorted newest-first. Items naturally fall out the bottom as
        # newer ones arrive (capped at `limit`); deeper history accessible
        # via direct `/posts/{id}` links.
        items = list(svc.list_items())
        if language == "en":
            # English page is strict: only items whose source IS English.
            items = [i for i in items if (i.language or "en") == "en"]
        elif language == "ua":
            # Ukrainian page is inclusive — every item we can render in UA.
            # That's EN-source (rendered in both en+ua) plus UA-source.
            # `other`/`unknown` languages were already dropped at ingest.
            items = [i for i in items if (i.language or "en") in ("en", "ua")]
        # Reverse-chronological. The diversifier intentionally not run here:
        # users expect "newest at the top" and any reorder for variety
        # breaks that mental model.
        items.sort(key=lambda i: i.published_at, reverse=True)
        # One card per story. When BleepingComputer, The Hacker News and CISA
        # all cover the same zero-day, the reader gets a single post that says
        # three sources reported it — not three near-identical cards.
        cache_probe: dict[str, bool] = {}
        items, story_sources = _dedupe_stories(items, language, cache_probe)
        # Walk the full filtered store, collecting up to `limit` items that
        # actually satisfy `cached_only` for the requested locale. NOT a
        # `items[:limit]` slice — that would let a freshly-ingested item
        # that hasn't been generated yet eat a slot reserved for an older
        # post the reader can actually read. The generate timer renders
        # only 2 items per 6h fire (cost control), so raw-store churn
        # outpaces rendering; this iteration is what keeps the public feed
        # from going half-empty between fires.
        rendered = _render_many(
            items, cached_only=cached_only, language=language, limit=limit,
            extra_sources=story_sources, cache_probe=cache_probe,
        )
        # Post-render filter: when `?language=X` is set, drop items that
        # ended up without a rendered translation in X. This catches the
        # "EN-source item with rule_based UA fallback got filtered in
        # render()" case — the API contract should be "items returned
        # under ?language=X are renderable in X".
        if language:
            rendered = [
                r for r in rendered
                if language in r.get("available_locales", [])
            ]
        return {"items": rendered, "total": len(rendered)}

    # Severity weights — must mirror frontend `LEVEL_WEIGHT` in
    # `components/trending/TrendingSection.tsx`. Both layers sort by the
    # same key so what the API returns is what the user sees.
    _LEVEL_WEIGHT = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}

    @app.get("/posts/trending", tags=["posts"])
    def list_trending(
        limit: int = Query(5, ge=1, le=50),
        language: str | None = Query(None, pattern="^(en|ua|uk)$"),
    ) -> dict[str, Any]:
        """Trending — top-N most-dangerous items in the requested locale.

        Sort key matches the frontend's `dangerSort` exactly:
            1. AI-assigned threat_level (Critical > High > Medium > Low)
            2. actionability_score (continuous tiebreaker)
            3. published_at DESC (final tiebreaker — newer wins)

        Why severity-first, not actionability-first: a Critical CVE from
        last week with active exploitation is more important than a fresh
        Medium-tier advisory. Time is a weak signal in security
        prioritization; we use it only to break ties within a severity tier.
        """
        now = datetime.now(timezone.utc)
        if language == "uk":
            language = "ua"
        items = [
            i for i in svc.list_items()
            if _within_homepage_window(i, now, language=language)
        ]
        if language == "en":
            items = [i for i in items if (i.language or "en") == "en"]
        elif language == "ua":
            items = [i for i in items if (i.language or "en") in ("en", "ua")]
        # Pre-sort by source-side severity so the render set is biased
        # toward dangerous items; the post-render sort uses the AI-assigned
        # threat_level for the final ordering.
        items.sort(
            key=lambda i: (i.threat_score, i.actionability_score, i.published_at),
            reverse=True,
        )
        # Render a generous candidate pool, then sort the rendered shape
        # by the same key the frontend uses. `cached_only=True` means
        # items without AI renders never appear in trending.
        cache_probe: dict[str, bool] = {}
        items, story_sources = _dedupe_stories(items, language, cache_probe)
        candidates = items[: max(limit * 3, 30)]
        rendered = _render_many(
            candidates, cached_only=True, language=language,
            extra_sources=story_sources, cache_probe=cache_probe,
        )
        if language:
            rendered = [
                r for r in rendered
                if language in r.get("available_locales", [])
            ]
        # Final sort — severity-first, exactly matching frontend dangerSort.
        rendered.sort(
            key=lambda r: (
                _LEVEL_WEIGHT.get(r.get("threat_level", "Low"), 0),
                r.get("actionability_score", 0.0),
                r.get("published_at", ""),
            ),
            reverse=True,
        )
        rendered = rendered[:limit]
        return {"items": rendered, "total": len(rendered)}

    @app.get("/posts/latest", tags=["posts"])
    def list_latest(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
        """Latest — most recently published. Useful for 'what's new' UIs."""
        items = svc.list_items()
        items.sort(key=lambda i: i.published_at, reverse=True)
        items = items[:limit]
        return {"items": _render_many(items), "total": len(items)}

    @app.get("/posts/{post_id}", tags=["posts"])
    def get_post(post_id: str) -> dict[str, Any]:
        """Single post by fingerprint id — backs the /threat/[id] route.

        Unlike the feed, this never collapses: a deep link to a specific
        article must keep resolving even when that article is later coverage
        of a story we show under a different id. Instead we attach the rest
        of the cluster as `story_coverage` so the detail page can offer every
        outlet's original reporting — the payoff of having recognized the
        duplicate in the first place.
        """
        all_items = svc.list_items()
        target = next((i for i in all_items if i.fingerprint == post_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="post not found")

        try:
            payload = svc.render(target)
        except PostHidden as exc:
            # Held or rejected in review: the same answer as an unknown id,
            # so a withheld post can't be read by guessing its URL.
            raise HTTPException(status_code=404, detail="post not found") from exc

        # Sibling articles = same story, different article. Items without a
        # story key have no siblings by definition.
        siblings = [
            i for i in all_items
            if target.story_key
            and i.story_key == target.story_key
            and i.fingerprint != target.fingerprint
        ]
        _merge_story_sources(
            payload,
            list(dict.fromkeys(
                i.source for i in siblings if i.source != target.source
            )),
        )
        payload["story_coverage"] = [
            {
                "source": i.source,
                "url": i.url,
                "title": i.title,
                "published_at": i.published_at.astimezone(timezone.utc).isoformat(),
            }
            for i in sorted(siblings, key=lambda x: x.published_at, reverse=True)
        ]
        return payload

    # ----- reader feedback (public write) --------------------------------
    # The 👍 / 👎 widget under every post POSTs here. Validation and
    # aggregation live in `cyberalertx/feedback.py`; this is the HTTP edge.

    _feedback_path = feedback_path or (DATA_DIR / "feedback.jsonl")
    _feedback_lock = threading.Lock()
    _feedback_recent: deque[float] = deque()

    @app.post("/feedback", tags=["feedback"])
    def submit_feedback(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Append one feedback record.

        v2 body: `{id, locale, kind: "vote", vote, previous}` or
        `{id, locale, kind: "reason", reason}`. The v1 `{id, locale, signal}`
        shape is still accepted, because cached copies of the old page keep
        posting it for a while after a deploy.

        Collection only — nothing is echoed back. Readers never see a tally.
        """
        try:
            record = parse_submission(payload)
        except FeedbackError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with _feedback_lock:
            now = time.monotonic()
            while _feedback_recent and now - _feedback_recent[0] > 60.0:
                _feedback_recent.popleft()
            if len(_feedback_recent) >= _FEEDBACK_MAX_PER_MINUTE:
                raise HTTPException(status_code=429, detail="too many requests")
            _feedback_recent.append(now)
        try:
            if _feedback_path.exists() and _feedback_path.stat().st_size >= _FEEDBACK_MAX_BYTES:
                logger.warning("feedback log at size cap; dropping writes")
                raise HTTPException(status_code=429, detail="feedback is paused")
            with _feedback_lock:
                append_record(_feedback_path, record)
        except OSError as exc:
            # A transient FS error must not surface to the reader as a 500.
            logger.warning("feedback append failed (%s)", exc)
        return {"ok": True}

    # ----- admin ----------------------------------------------------------
    # Everything under /admin is gated in a MIDDLEWARE, before routing, not
    # by per-route dependencies. Routing runs first otherwise, so `POST
    # /admin` would answer 405 and an unknown path 404 to anyone, which tells
    # a scanner exactly which admin routes exist. Gating first means every
    # method and every path under the prefix gets the same 401 until the
    # password is right. See `admin/guard.py` for the lockout and why the
    # client address it keys on can be trusted.

    guard = admin_guard or AdminGuard()

    @app.middleware("http")
    async def _admin_gate(request: Request, call_next: Any) -> Response:
        if not _is_admin_path(request.url.path):
            response: Response = await call_next(request)
            return response
        try:
            guard.check(request, _basic_credentials(request))
        except HTTPException as exc:
            response = PlainTextResponse(str(exc.detail), status_code=exc.status_code,
                                         headers=exc.headers)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Referrer-Policy"] = "no-referrer"
        if response.headers.get("content-type", "").startswith("text/html"):
            # Only the review queue and the Threads account page carry forms;
            # everywhere else forms stay forbidden outright.
            response.headers["Content-Security-Policy"] = (
                ADMIN_CSP_FORMS if request.url.path.startswith(("/admin/review", "/admin/threads"))
                else ADMIN_CSP
            )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def _http_errors(request: Request, exc: StarletteHTTPException) -> Response:
        # Plain text under /admin. FastAPI's default `{"detail": ...}` JSON
        # names the framework for anyone who asks.
        if _is_admin_path(request.url.path):
            return PlainTextResponse(str(exc.detail), status_code=exc.status_code,
                                     headers=getattr(exc, "headers", None))
        return await http_exception_handler(request, exc)

    def _title_for(post_id: str, locale: str) -> str:
        """The headline the reader actually saw, falling back to the source
        title, then to the bare id. Cache-only: never triggers a render."""
        cache = getattr(getattr(svc, "_generator", None), "_cache", None)
        if cache is not None:
            try:
                post = cache.get(post_id, locale)
            except Exception:  # pragma: no cover - defensive, cache is local
                post = None
            if post is not None and post.title:
                return str(post.title)
        for item in svc.list_items():
            if item.fingerprint == post_id:
                return item.title
        return ""

    def _feedback_summary() -> Any:
        with _feedback_lock:
            records = list(read_records(_feedback_path))
        return summarize(records)

    def _feed_status() -> FeedStatus:
        items = svc.list_items()
        return FeedStatus(
            stored_items=len(items),
            latest_published_at=max((i.published_at for i in items), default=None),
            latest_urgent_at=max(
                (i.published_at for i in items if i.actionability_level == "urgent_action"),
                default=None,
            ),
        )

    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _post_cache() -> Any:
        return getattr(getattr(svc, "_generator", None), "_cache", None)

    def _review_posts() -> list[ThreatPost]:
        cache = _post_cache()
        if cache is None:
            return []
        try:
            return list(cache.all())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("review queue: cache scan failed (%s)", exc)
            return []

    @app.get("/admin", tags=["admin"], response_class=HTMLResponse, include_in_schema=False)
    @app.get("/admin/", tags=["admin"], response_class=HTMLResponse)
    def admin_overview() -> HTMLResponse:
        """How the site is doing right now, and what needs a look."""
        return HTMLResponse(render_overview(
            feed=_feed_status(),
            metrics=get_quality_metrics().as_dict(),
            health=get_source_health().as_dict(),
            feedback=_feedback_summary(),
            logins=guard.stats(),
            title_for=_title_for,
            now=_now(),
            pending_review=sum(1 for p in _review_posts() if p.review_status == "pending"),
            review_mode=review_mode(),
            sections=_overview_sections(),
        ))

    # ---- Phase 6 control room helpers -------------------------------------------

    def _ops_src() -> Any:
        from ..ops.readmodel import OpsSources
        return OpsSources(items=svc.list_items, posts=_review_posts, post_cache=_post_cache(),
                          data_dir=_ops_data_dir())

    def _jobs() -> list[Any]:
        from ..publish.jobs import JobStore
        try:
            return JobStore(_publish_jobs_path()).all()
        except RuntimeError:
            return []

    def _audit() -> Any:
        from ..ops.audit import AuditLog
        return AuditLog(_ops_data_dir() / "admin_audit.jsonl")

    def _actor(request: Request) -> tuple[str, str]:
        creds = _basic_credentials(request)
        name = (creds.username.strip() if creds and creds.username else "") or "admin"
        return name[:60], client_address(request)

    def _record(request: Request, action: str, target: str, result: str, **meta: Any) -> None:
        actor, address = _actor(request)
        try:
            _audit().record(actor=actor, address=address, action=action, target=target, result=result, **meta)
        except OSError as exc:                     # auditing must not hide the action's outcome
            logger.error("audit log write failed for %s %s: %s", action, target, exc)

    async def _admin_form(request: Request, limit: int = 4096) -> tuple[dict[str, str], Response | None]:
        """Parsed POST form after same-origin + CSRF checks (as the review queue)."""
        if not same_origin(request):
            return {}, PlainTextResponse("Cross-site request refused.", status_code=403)
        body = await request.body()
        if len(body) > limit:
            return {}, PlainTextResponse("Request too large.", status_code=413)
        form = {k: (v[0] if v else "").strip() for k, v in
                parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}
        if not guard.csrf_ok(form.get("csrf", "")):
            return {}, PlainTextResponse("This form has expired. Reload the page and try again.", status_code=403)
        return form, None

    def _threads_state() -> tuple[Any, dict[str, Any]]:
        ts, accounts, _ = _threads()
        return ts, {a.slot: a for a in accounts.all()}

    def _overview_sections() -> str:
        from ..ops import readmodel as rm
        from .admin.ops_pages import overview_sections
        try:
            src, now = _ops_src(), _now()
            res, jobs = rm.intel_view(src, now), _jobs()
            from ..publish.config import build_telegram_settings
            ts, accounts = _threads_state()
            return overview_sections(
                m=rm.overview_metrics(src, res, jobs, now),
                stages=rm.pipeline(src, res, jobs, now, health=get_source_health().as_dict(),
                                   metrics=get_quality_metrics().as_dict()),
                dests=rm.destinations(src, jobs, telegram=build_telegram_settings(), threads_settings=ts,
                                      threads_accounts=accounts),
                res=res, rows=rm.story_rows(res),
                events=rm.activity(src, jobs, audit=_audit().recent(100), res=res, now=now), now=now)
        except Exception as exc:                   # noqa: BLE001 - the health view above still renders
            logger.exception("overview sections failed")
            return (f'<div class="banner bad full"><span class="dot bad"></span><p>Control-room sections '
                    f'unavailable ({type(exc).__name__}). The checks above are unaffected.</p></div>')

    # ----- review queue ------------------------------------------------------
    # Reads and writes go through the generator's cache backend, so a
    # decision lands in JSON and — under dual-write — in Postgres too.

    _REVIEW_PAGE_LIMIT = 60
    _review_statuses = {key for key, _ in REVIEW_TABS}

    def _review_selection(status: str) -> tuple[list[ReviewEntry], dict[str, int], int]:
        posts = _review_posts()
        counts: dict[str, int] = {}
        for p in posts:
            counts[p.review_status or "auto"] = counts.get(p.review_status or "auto", 0) + 1
        chosen = [p for p in posts if (p.review_status or "auto") == status]
        chosen.sort(
            key=lambda p: (str((p.quality or {}).get("scored_at") or p.reviewed_at or ""),
                           post_key(p)),
            reverse=True,
        )
        total = len(chosen)
        items = {i.fingerprint: i for i in svc.list_items()}
        entries: list[ReviewEntry] = []
        for p in chosen[:_REVIEW_PAGE_LIMIT]:
            item = items.get(p.source_fingerprint)
            entries.append(ReviewEntry(
                key=post_key(p),
                post=p,
                source_title=item.title if item else "",
                source_url=item.url if item else "",
                source_name=item.source if item else "",
                published_at=item.published_at if item else None,
            ))
        return entries, counts, total

    @app.get("/admin/review", tags=["admin"], response_class=HTMLResponse)
    def admin_review_page(
        status: str = Query("pending"), done: str = Query(""),
    ) -> HTMLResponse:
        """Posts waiting for the editor, with the evidence and Approve / Reject."""
        status = status if status in _review_statuses else "pending"
        entries, counts, total = _review_selection(status)
        notice = ""
        verb, _, key = done.partition(":")
        if verb in ("approved", "rejected") and key:
            notice = f"{verb.capitalize()} {key}."
        return HTMLResponse(render_review(
            entries, status=status, counts=counts, csrf=guard.csrf_token(),
            mode=review_mode(), threshold=review_threshold(), now=_now(),
            notice=notice, total=total,
        ))

    @app.get("/admin/review.json", tags=["admin"])
    def admin_review_json(status: str = Query("pending")) -> dict[str, Any]:
        """The same queue, for scripts."""
        status = status if status in _review_statuses else "pending"
        entries, counts, total = _review_selection(status)
        return {
            "mode": review_mode(),
            "threshold": review_threshold(),
            "status": status,
            "counts": counts,
            "total": total,
            "posts": [
                {
                    "key": e.key, "title": e.post.title, "review_status": e.post.review_status,
                    "reviewed_by": e.post.reviewed_by, "reviewed_at": e.post.reviewed_at,
                    "source_url": e.source_url, "quality": e.post.quality,
                }
                for e in entries
            ],
        }

    @app.post("/admin/review/decide", tags=["admin"], include_in_schema=False)
    async def admin_review_decide(request: Request) -> Response:
        """Approve or reject one post. Form POST from the review page only:
        same-origin check + CSRF token (see admin/guard.py)."""
        if not same_origin(request):
            return PlainTextResponse("Cross-site request refused.", status_code=403)
        body = await request.body()
        if len(body) > 4096:
            return PlainTextResponse("Request too large.", status_code=413)
        form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)

        def field(name: str) -> str:
            return (form.get(name) or [""])[0].strip()

        if not guard.csrf_ok(field("csrf")):
            return PlainTextResponse("This form has expired. Reload the page and try again.",
                                     status_code=403)
        decision = field("decision")
        if decision not in DECISIONS:
            return PlainTextResponse("Unknown decision.", status_code=400)
        try:
            fingerprint, locale = parse_key(field("key"))
        except ValueError:
            return PlainTextResponse("Unknown post.", status_code=400)
        cache = _post_cache()
        if cache is None:
            return PlainTextResponse("No post cache configured.", status_code=503)
        credentials = _basic_credentials(request)
        reviewer = (credentials.username.strip() if credentials and credentials.username
                    else "") or "editor"
        previous = getattr(cache.get(fingerprint, locale), "review_status", "") if hasattr(cache, "get") else ""
        try:
            apply_decision(cache, fingerprint, locale, decision, f"admin:{reviewer}")
        except KeyError:
            _record(request, f"review.{decision}", f"{fingerprint}:{locale}", "not_found")
            return PlainTextResponse("Unknown post.", status_code=404)
        _record(request, f"review.{decision}", f"{fingerprint}:{locale}", "ok", previous=previous)
        logger.info("review: %s %s:%s by admin:%s", decision, fingerprint, locale, reviewer)
        back = field("back")
        back = back if back in _review_statuses else "pending"
        done = quote(f"{DECISIONS[decision]}:{fingerprint}:{locale}", safe=":")
        return RedirectResponse(f"/admin/review?status={back}&done={done}", status_code=303)

    @app.get("/admin/feedback", tags=["admin"], response_class=HTMLResponse)
    def admin_feedback_page() -> HTMLResponse:
        """What readers thought of each post, worst first."""
        return HTMLResponse(render_feedback(_feedback_summary(), title_for=_title_for, now=_now()))

    @app.get("/admin/feedback.json", tags=["admin"])
    def admin_feedback_json() -> dict[str, Any]:
        """The same numbers as the feedback page, for scripts."""
        summary = _feedback_summary()
        return {
            "up": summary.up,
            "down": summary.down,
            "helpful_rate": summary.helpful_rate,
            "votes_last_7d": summary.votes_last_7d,
            "reasons": dict(summary.reasons),
            "by_locale": {k: {"up": u, "down": d} for k, (u, d) in summary.by_locale.items()},
            "posts": [
                {
                    "id": p.id, "locale": p.locale, "title": _title_for(p.id, p.locale),
                    "up": p.up, "down": p.down, "reasons": dict(p.reasons),
                    "last_at": p.last_at,
                }
                for p in summary.posts
            ],
        }

    @app.get("/admin/metrics", tags=["admin"], response_class=HTMLResponse)
    def admin_metrics_page() -> HTMLResponse:
        """How often the AI writes a post we publish, and why it doesn't."""
        return HTMLResponse(render_quality(get_quality_metrics().as_dict(), now=_now()))

    @app.get("/admin/metrics.json", tags=["admin"])
    def admin_metrics() -> dict[str, Any]:
        """Quality + AI-rejection counters since the metrics file was created."""
        return get_quality_metrics().as_dict()

    @app.get("/admin/sources", tags=["admin"], response_class=HTMLResponse)
    def admin_sources_page(done: str = Query("", max_length=200), failed: str = Query("", max_length=200)) -> HTMLResponse:
        """Every feed the site ingests, worst first — feed health, connector,
        the Intelligence Core reliability profile and stored-content health."""
        from urllib.parse import urlparse as _up

        from ..intel.sources import SourceTable
        table = SourceTable()
        health = get_source_health().as_dict()
        names = set((health.get("sources") or {}).keys()) | {c.name for c in SETTINGS.sources}
        items = svc.list_items()
        extra: dict[str, dict[str, Any]] = {}
        for name in names:
            mine = [i for i in items if i.source == name]
            cfg = next((c for c in SETTINGS.sources if c.name == name), None)
            prof = table.get(name)
            extra[name] = {
                "connector": f"{cfg.kind} feed" if cfg else "", "host": _up(cfg.url).netloc if cfg else "",
                "kind": prof.kind, "reliability": prof.reliability, "note": prof.note,
                "stored": len(mine),
                "thin": (sum(1 for i in mine if len((i.raw_content or "").strip()) < 300) / len(mine)) if mine else None,
            }
        return HTMLResponse(render_sources(health, now=_now(), extra=extra, csrf=guard.csrf_token(),
                                           notice=done, error=failed))

    @app.post("/admin/sources/test", tags=["admin"], include_in_schema=False)
    async def admin_sources_test(request: Request) -> Response:
        """One live fetch through the existing RSS connector; nothing is stored."""
        from ..sources.registry import build_sources
        form, refused = await _admin_form(request)
        if refused is not None:
            return refused
        name = form.get("source", "")
        cfg = next((c for c in SETTINGS.sources if c.name == name), None)
        if cfg is None or form.get("confirm") != "yes":
            return PlainTextResponse("Unknown source or not confirmed.", status_code=400)
        try:
            fetched = build_sources([cfg])[0].fetch()
        except Exception as exc:                   # noqa: BLE001 - report, never raise
            _record(request, "source.test_fetch", name, "failed", error=type(exc).__name__)
            return RedirectResponse("/admin/sources?" + urlencode({"failed": f"{name}: fetch failed ({type(exc).__name__})"}),
                                    status_code=303)
        _record(request, "source.test_fetch", name, "ok", items=len(fetched))
        return RedirectResponse("/admin/sources?" + urlencode({"done": f"{name}: fetch returned {len(fetched)} items (nothing stored)"}),
                                status_code=303)

    @app.get("/admin/sources.json", tags=["admin"])
    def admin_sources() -> dict[str, Any]:
        """Per-source ingest health."""
        return get_source_health().as_dict()

    # Registered last so every real admin route wins. Only reachable after
    # the gate, so an unknown path is a 404 for the editor and a 401 for
    # everyone else.
    @app.get("/admin/intel", tags=["admin"], response_class=HTMLResponse)
    def admin_intel_page() -> HTMLResponse:
        """Shadow intelligence run: Top 10 / Trending / Breaking candidates,
        scores with explanations, relevance and failures. Read-only."""
        from ..intel.engine import load_latest, load_scores

        return HTMLResponse(render_intel(load_latest(), load_scores(), now=_now()))

    @app.get("/admin/intel.json", tags=["admin"])
    def admin_intel_json() -> dict[str, Any]:
        from ..intel.engine import load_latest, load_scores

        return {"latest": dict(load_latest()), "scores": dict(load_scores())}

    @app.get("/media/{asset_id}", include_in_schema=False)
    def media_file(asset_id: str) -> Response:
        """Validated illustration bytes, for the website's /media route only.
        Not routed by nginx (only posts|healthz|admin|feedback reach the API),
        so the public URL is always the website's, which re-validates."""
        store = _media_store()
        found = store.open_file(asset_id) if store else None
        if found is None:
            return PlainTextResponse("Not found", status_code=404)
        data, mime = found
        return Response(content=data, media_type=mime,
                        headers={"Cache-Control": "private, max-age=3600",
                                 "X-Content-Type-Options": "nosniff"})

    @app.get("/admin/media", tags=["admin"], response_class=HTMLResponse)
    def admin_media_page(q: str = Query("", max_length=120), done: str = Query("", max_length=200),
                         failed: str = Query("", max_length=200)) -> HTMLResponse:
        """Media Engine assets: status, variants, errors, retries, usage."""
        from .admin.media_page import render_media
        store = _media_store()
        return HTMLResponse(render_media(store.all() if store else [], _media_usage(store), now=_now(),
                                         q=q.strip(), csrf=guard.csrf_token(), notice=done, error=failed))

    @app.post("/admin/media/regenerate", tags=["admin"], include_in_schema=False)
    async def admin_media_regenerate(request: Request) -> Response:
        """Queue a story's illustration for the next media run — exactly what
        `tools.media regenerate` does. No provider is called from here."""
        form, refused = await _admin_form(request)
        if refused is not None:
            return refused
        story = form.get("story", "")
        store = _media_store()
        asset = store.get(f"illus:{story}") if store and story else None
        if asset is None or form.get("confirm") != "yes":
            return PlainTextResponse("Unknown illustration or not confirmed.", status_code=400)
        asset.status, asset.content_hash, asset.attempts, asset.last_error = "pending", "", 0, ""
        store.put(asset)
        _record(request, "media.regenerate", story, "ok")
        return RedirectResponse("/admin/media?" + urlencode({"q": story, "done": f"{story}: queued for the next media run"}),
                                status_code=303)

    @app.get("/admin/media.json", tags=["admin"])
    def admin_media_json() -> dict[str, Any]:
        store = _media_store()
        return {"assets": [a.to_dict() for a in (store.all() if store else [])],
                "usage": _media_usage(store)}

    # ---- Threads accounts (connect / callback / verify / disconnect) ----------

    def _threads() -> tuple[Any, Any, Any]:
        from ..threads import accounts as acc_mod
        from ..threads.config import ThreadsSettings
        ts = ThreadsSettings.from_env()
        return (ts, acc_mod.AccountStore(acc_mod.ACCOUNTS_PATH, key=ts.token_key, mapping=ts.accounts),
                acc_mod.StateStore(acc_mod.STATES_PATH))

    def _threads_page(notice: str = "", error: str = "", status_code: int = 200) -> HTMLResponse:
        from .admin.threads_page import render_threads
        ts, accounts, _ = _threads()
        import importlib.util
        crypto = importlib.util.find_spec("cryptography") is not None
        status = {"app_id_set": bool(ts.app_id), "app_secret_set": bool(ts.app_secret),
                  "redirect_ok": ts.redirect_uri.startswith("https://"), "redirect_uri": ts.redirect_uri,
                  "key_set": bool(ts.token_key), "crypto_available": crypto, "publish_enabled": ts.publish_enabled}
        from ..publish.config import build_telegram_settings
        tg = build_telegram_settings()
        telegram = {   # safe view only: never the token, numeric chat ids shown as "configured"
            "token_set": bool(tg.bot_token),
            "channels": {loc: ((tg.channels[loc] if tg.channels[loc].startswith("@") else "configured")
                               if loc in tg.channels else "not configured") for loc in ("en", "ua")},
            "attach_images": tg.attach_images, "min_level": tg.min_level, "limit": tg.limit,
        }
        return HTMLResponse(render_threads([a.to_public(_now()) for a in accounts.all()], status,
                                           csrf=guard.csrf_token(), now=_now(), notice=notice, error=error,
                                           telegram=telegram),
                            status_code=status_code)

    async def _threads_form(request: Request) -> tuple[str, Response | None]:
        if not same_origin(request):
            return "", PlainTextResponse("Cross-site request refused.", status_code=403)
        body = await request.body()
        if len(body) > 2048:
            return "", PlainTextResponse("Request too large.", status_code=413)
        form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
        if not guard.csrf_ok((form.get("csrf") or [""])[0]):
            return "", PlainTextResponse("This form has expired. Reload the page and try again.", status_code=403)
        slot = (form.get("slot") or [""])[0].strip().lower()
        ts, _, _ = _threads()
        if slot not in ts.accounts:
            return "", PlainTextResponse("Unknown Threads slot.", status_code=400)
        return slot, None

    @app.get("/admin/threads", tags=["admin"], response_class=HTMLResponse)
    def admin_threads_page(done: str = Query("", max_length=40)) -> HTMLResponse:
        return _threads_page(notice=f"Slot {done} updated." if done else "")

    @app.get("/admin/threads.json", tags=["admin"])
    def admin_threads_json() -> dict[str, Any]:
        ts, accounts, _ = _threads()
        return {"publish_enabled": ts.publish_enabled, "accounts": [a.to_public(_now()) for a in accounts.all()]}

    @app.post("/admin/threads/connect", tags=["admin"], include_in_schema=False)
    async def admin_threads_connect(request: Request) -> Response:
        from ..threads.oauth import OAuthError, start_connect
        from .admin.threads_page import render_connect
        slot, refused = await _threads_form(request)
        if refused is not None:
            return refused
        ts, _, states = _threads()
        try:
            url = start_connect(slot, settings=ts, states=states, now=_now())
        except OAuthError as exc:
            _record(request, "threads.connect_start", slot, "refused", reason=str(exc))
            return _threads_page(error=str(exc), status_code=400)
        _record(request, "threads.connect_start", slot, "ok")
        logger.info("threads: connect started for slot %s", slot)
        return HTMLResponse(render_connect(slot, url, now=_now()))

    @app.get("/admin/threads/callback", tags=["admin"], include_in_schema=False)
    def admin_threads_callback(request: Request) -> Response:
        """OAuth redirect target. The slot comes from the one-time state, never
        from the request; the code is used once and never logged or echoed."""
        from ..threads.client import ThreadsClient
        from ..threads.oauth import OAuthError, complete_callback
        params = {k: v for k, v in request.query_params.items()
                  if k in ("code", "state", "error", "error_reason", "error_description")}
        ts, accounts, states = _threads()
        api = _threads_client_factory()
        try:
            acc = complete_callback(params, settings=ts, states=states, accounts=accounts, client=api, now=_now())
        except OAuthError as exc:
            _record(request, "threads.connect", "callback", "refused", reason=str(exc))
            return _threads_page(error=str(exc), status_code=400)
        finally:
            api.close()
        _record(request, "threads.connect", acc.slot, "ok", username=acc.username)
        return RedirectResponse(f"/admin/threads?done={quote(acc.slot)}", status_code=303)

    @app.post("/admin/threads/verify", tags=["admin"], include_in_schema=False)
    async def admin_threads_verify(request: Request) -> Response:
        from ..threads.oauth import verify
        slot, refused = await _threads_form(request)
        if refused is not None:
            return refused
        _, accounts, _ = _threads()
        api = _threads_client_factory()
        try:
            acc = verify(slot, accounts, api, _now())
        finally:
            api.close()
        _record(request, "threads.verify", slot, "failed" if acc.last_error else "ok", status=acc.status)
        if acc.last_error:
            return _threads_page(error=f"Slot {slot}: {acc.last_error}", status_code=200)
        return RedirectResponse(f"/admin/threads?done={quote(slot)}", status_code=303)

    @app.post("/admin/threads/disconnect", tags=["admin"], include_in_schema=False)
    async def admin_threads_disconnect(request: Request) -> Response:
        slot, refused = await _threads_form(request)
        if refused is not None:
            return refused
        _, accounts, _ = _threads()
        accounts.disconnect(slot, _now())
        logger.info("threads: slot %s disconnected by admin", slot)
        _record(request, "threads.disconnect", slot, "ok")
        return RedirectResponse(f"/admin/threads?done={quote(slot)}", status_code=303)

    @app.get("/admin/publishing", tags=["admin"], response_class=HTMLResponse)
    def admin_publishing_page(request: Request) -> HTMLResponse:
        """Publication jobs for all six destinations, filtered and paginated."""
        from .admin.publishing_page import JobQuery, render_publishing
        params = {k: v[:120] for k, v in request.query_params.items()}
        return HTMLResponse(render_publishing(_jobs(), now=_now(), query=JobQuery.from_params(params),
                                              csrf=guard.csrf_token(), notice=params.get("done", ""),
                                              error=params.get("failed", "")))

    @app.post("/admin/publishing/action", tags=["admin"], include_in_schema=False)
    async def admin_publishing_action(request: Request) -> Response:
        """retry / cancel / reconcile through the existing Publication Engine."""
        import re as _re

        from ..publish.jobs import JobStore
        from ..publish.orchestrator import ActionError, cancel_job, reconcile_job, retry_job
        form, refused = await _admin_form(request)
        if refused is not None:
            return refused
        jid, action, back = form.get("job", ""), form.get("action", ""), form.get("back", "")
        back = back if back.startswith("/admin/publishing") and "//" not in back else "/admin/publishing"
        if form.get("confirm") != "yes":
            return PlainTextResponse("Please tick 'confirm' to change a delivery state.", status_code=400)
        if action not in ("retry", "cancel", "reconcile_sent", "reconcile_not_sent") or len(jid) > 300:
            return PlainTextResponse("Unknown action.", status_code=400)
        store, now = JobStore(_publish_jobs_path()), _now()
        sep = "&" if "?" in back else "?"
        try:
            if action == "retry":
                job = retry_job(store, jid, now)
            elif action == "cancel":
                job = cancel_job(store, jid, now, reason="cancelled by admin")
            elif action == "reconcile_not_sent":
                job = reconcile_job(store, jid, now, not_sent=True)
            else:
                ext = form.get("external_id", "")
                if not _re.fullmatch(r"[A-Za-z0-9_:.-]{1,64}", ext):
                    raise ActionError("give the delivered post / message id")

                def ledger(j: Any, mid: str) -> None:
                    if j.destination == "telegram" and mid.isdigit():
                        from ..publish.config import build_telegram_settings
                        from ..publish.ledger import PublishLedger
                        from ..publish.service import DEFAULT_LEDGER_PATH
                        PublishLedger(DEFAULT_LEDGER_PATH).record(
                            fingerprint=j.fingerprint, locale=j.locale,
                            channel=build_telegram_settings().chat_id_for(j.locale) or "", message_id=int(mid))
                job = reconcile_job(store, jid, now, sent_id=ext, ledger_record=ledger)
        except ActionError as exc:
            _record(request, f"publication.{action}", jid, "refused", reason=str(exc))
            return RedirectResponse(back + sep + urlencode({"failed": str(exc)}), status_code=303)
        _record(request, f"publication.{action}", jid, "ok", status=job.status)
        return RedirectResponse(back + sep + urlencode({"done": f"{jid}: now {job.status}"}), status_code=303)

    @app.get("/admin/publishing.json", tags=["admin"])
    def admin_publishing_json() -> dict[str, Any]:
        from ..publish.jobs import JobStore
        from ..publish.orchestrator import status_counts
        jobs = JobStore(_publish_jobs_path()).all()
        return {"counts": status_counts(jobs), "jobs": [j.to_dict() for j in jobs]}

    @app.get("/admin/assets/{name}", include_in_schema=False)
    def admin_asset(name: str) -> Response:
        """The site's interface font (Fira Sans Condensed, OFL) for the admin shell."""
        file = _FONTS.get(name)
        path = _FONT_DIR / file if file else None
        if path is None or not path.is_file():
            return PlainTextResponse("Not found", status_code=404)
        return Response(path.read_bytes(), media_type="font/ttf",
                        headers={"Cache-Control": "private, max-age=604800"})

    @app.get("/admin/stories", tags=["admin"], response_class=HTMLResponse)
    def admin_stories(request: Request) -> HTMLResponse:
        from ..ops import readmodel as rm
        from .admin.ops_pages import render_stories
        res = rm.intel_view(_ops_src(), _now())
        rows = rm.story_rows(res)
        q = rm.StoryQuery.from_params({k: v[:120] for k, v in request.query_params.items()})
        page_rows, total = rm.filter_stories(rows, q)
        return HTMLResponse(render_stories(page_rows, total, q, categories=sorted({r.category for r in rows}),
                                           available=res is not None, now=_now()))

    @app.get("/admin/stories/{key}", tags=["admin"], response_class=HTMLResponse)
    def admin_story(key: str) -> HTMLResponse:
        from ..ops import readmodel as rm
        from .admin.ops_pages import render_story
        if len(key) > 80:
            return HTMLResponse(render_not_found(now=_now()), status_code=404)
        detail = rm.story_detail(rm.intel_view(_ops_src(), _now()), key)
        if detail is None:
            return HTMLResponse(render_not_found(now=_now()), status_code=404)
        members = {m.fingerprint for m in detail["story"].members}
        jobs = [j for j in _jobs() if j.story_key == key or j.fingerprint in members]
        store = _media_store()
        assets = [a.to_dict() for a in (store.all() if store else []) if a.story_key == key or set(a.members) & members]
        return HTMLResponse(render_story(detail, jobs=jobs, assets=assets[:20], now=_now()))

    @app.get("/admin/usage", tags=["admin"], response_class=HTMLResponse)
    def admin_usage(period: str = Query("day", max_length=8)) -> HTMLResponse:
        import os as _os

        from ..ops import usage as us
        from .admin.ops_pages import render_usage
        rows = us.load(_ops_data_dir() / "ai_usage.jsonl")
        metrics = get_quality_metrics().as_dict()
        store = _media_store()
        env = _os.getenv
        controls = [
            ("Text AI provider", env("CYBERALERTX_AI_PROVIDER", "") or "not set (rule-based)", "CYBERALERTX_AI_PROVIDER"),
            ("Image provider", env("CYBERALERTX_IMAGE_PROVIDER", "") or "none", "branded cards only when none"),
            ("Illustrations per run", env("CYBERALERTX_ILLUSTRATION_MAX_PER_RUN", "3"), "Media Engine cap"),
            ("Illustration min score", env("CYBERALERTX_ILLUSTRATION_MIN_SCORE", "55"), "eligibility"),
            ("Publication retries", env("CYBERALERTX_PUBLISH_MAX_ATTEMPTS", "5"), "per job"),
            ("Review mode", review_mode(), "CYBERALERTX_REVIEW_MODE"),
            ("Briefs per hour", "set by `generate --limit` in cyberalertx-generate.service", "systemd unit"),
        ]
        return HTMLResponse(render_usage(
            counters=metrics.get("counters") or {}, first_seen=str(metrics.get("first_seen_utc") or ""),
            daily=us.aggregate(rows, period="day"), monthly=us.aggregate(rows, period="month"),
            ledger_start=str(rows[0]["at"]) if rows else "", media_usage=_media_usage(store),
            controls=controls, rates_configured=bool(us.operator_rates()),
            period="day" if period != "month" else "month", now=_now()))

    def _system_report() -> Any:
        from ..ops import readmodel as rm
        from ..ops.health import system_report
        from ..publish.config import build_telegram_settings
        src, now = _ops_src(), _now()
        ts, accounts = _threads_state()
        return system_report(src, _jobs(), now=now, health=get_source_health().as_dict(),
                             metrics=get_quality_metrics().as_dict(), threads_settings=ts, threads_accounts=accounts,
                             telegram=build_telegram_settings(), intel_ok=rm.intel_view(src, now) is not None)

    @app.get("/admin/system", tags=["admin"], response_class=HTMLResponse)
    def admin_system() -> HTMLResponse:
        from .admin.ops_pages import render_system
        return HTMLResponse(render_system(_system_report(), _audit().recent(50), now=_now()))

    @app.get("/admin/system.json", tags=["admin"])
    def admin_system_json() -> dict[str, Any]:
        r = _system_report()
        return {"overall": r.overall,
                "checks": [{"group": c.group, "name": c.name, "status": c.status, "detail": c.detail,
                            "last": c.last.isoformat() if c.last else None} for c in r.checks],
                "failures": r.failures}

    @app.get("/admin/search", tags=["admin"], response_class=HTMLResponse)
    def admin_search(q: str = Query("", max_length=120)) -> HTMLResponse:
        from ..ops import readmodel as rm
        from .admin.ops_pages import render_search
        found = rm.search(q, rm.intel_view(_ops_src(), _now()), _jobs()) if q.strip() else {}
        return HTMLResponse(render_search(q.strip(), found, now=_now()))

    @app.get("/admin/{rest:path}", include_in_schema=False)
    def admin_not_found(rest: str) -> HTMLResponse:
        return HTMLResponse(render_not_found(now=_now()), status_code=404)

    return app



def _media_usage(store: Any) -> list[dict[str, Any]]:
    if store is None:
        return []
    path = store.root / "usage.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-200:]
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _ops_data_dir() -> Path:
    """Where the control room reads operational records (tests point it at tmp)."""
    return DATA_DIR


_FONTS = {"fira-500.ttf": "FiraSansCondensed-Medium.ttf", "fira-600.ttf": "FiraSansCondensed-SemiBold.ttf"}
_FONT_DIR = Path(__file__).resolve().parents[2] / "frontend" / "assets" / "fonts"


def _threads_client_factory() -> Any:
    from ..threads.client import ThreadsClient
    return ThreadsClient()


def _publish_jobs_path() -> Any:
    from ..publish.jobs import JOBS_PATH
    return JOBS_PATH


_MEDIA_STORE: Any = None


def _media_store() -> Any:
    """Process-wide MediaStore, created on first use (None if unavailable)."""
    global _MEDIA_STORE
    if _MEDIA_STORE is None:
        try:
            from ..media.assets import MediaStore
            _MEDIA_STORE = MediaStore()
        except OSError:
            return None
    return _MEDIA_STORE


def _is_admin_path(path: str) -> bool:
    return path == "/admin" or path.startswith("/admin/")


def _basic_credentials(request: Request) -> HTTPBasicCredentials | None:
    """Parse an `Authorization: Basic …` header, or None when there is none.

    A header that is present but malformed is returned as empty credentials
    rather than None, so it counts as a failed attempt instead of being
    treated like a browser that hasn't been asked to log in yet.
    """
    header = request.headers.get("authorization", "")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic":
        return HTTPBasicCredentials(username="", password="")
    try:
        decoded = base64.b64decode(value.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return HTTPBasicCredentials(username="", password="")
    username, _, password = decoded.partition(":")
    return HTTPBasicCredentials(username=username, password=password)

# Module-level app for `uvicorn cyberalertx.api.app:app` and the serve CLI.
app = build_app()
