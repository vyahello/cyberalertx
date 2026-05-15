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

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from ..ai.generator import ContentGenerator, build_default_generator
from ..ai.models import ThreatPost
from ..config import DATA_DIR, SETTINGS
from ..models import NewsItem
from ..observability import get_quality_metrics, get_source_health
from ..pipeline.signals import extract_signals, potential_impact, who_should_care
from ..storage.json_store import JsonNewsStore

logger = logging.getLogger(__name__)


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
        "title", "short_summary", "why_it_matters", "affected_users",
        "what_to_do", "what_not_to_do", "quick_facts", "reading_time_seconds",
        # New in v0.4 — extended detail-page content.
        "detail_body", "references",
    )

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
            if cache.get(item.fingerprint, required_locale) is None:
                return None
        else:
            source_lang = item.language if item.language in ("en", "ua") else "en"
            required = ("ua",) if source_lang == "ua" else ("en", "ua")
            for locale in required:
                if cache.get(item.fingerprint, locale) is None:
                    return None
        return self.render(item)

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
        for lang in locales:
            try:
                post = self._generator.generate(item, language=lang)
            except Exception as exc:
                logger.warning(
                    "locale %s generation failed for %s: %s",
                    lang, item.fingerprint, exc,
                )
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
            translations[lang] = _localized_content_dict(post)

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
        }


def _localized_content_dict(post: ThreatPost) -> dict[str, Any]:
    """Project a ThreatPost down to its localized text fields only.

    Overrides `reading_time_seconds` with a value computed from the actual
    card-tier content. AI / rule_based historically returned 60-120s — that
    estimated a full detail-page read, but the card only surfaces title +
    summary + quick_facts (~30-60 words = 10-20s). The displayed number
    was confusing the reader ("a 2-minute read? this is one paragraph").
    """
    full = post.to_dict()
    base = {k: full[k] for k in _PostService._LOCALIZED_FIELDS}
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

    def _render_many(
        items: list[NewsItem], *,
        cached_only: bool = False,
        language: str | None = None,
        limit: int | None = None,
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
                    payload = svc.render_if_cached(item, required_locale=language)
                    if payload is None:
                        continue
                else:
                    payload = svc.render(item)
                rendered.append(payload)
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
        candidates = items[: max(limit * 3, 30)]
        rendered = _render_many(candidates, cached_only=True, language=language)
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
        """Single post by fingerprint id — for /threat/[id] routes later."""
        for item in svc.list_items():
            if item.fingerprint == post_id:
                return svc.render(item)
        raise HTTPException(status_code=404, detail="post not found")

    # ----- observability ------------------------------------------------
    # These routes give a developer JSON visibility into pipeline health
    # without building an admin UI. They are intentionally namespaced
    # `/admin/*` so a reverse proxy can lock them down with one rule.

    @app.get("/admin/metrics", tags=["meta"])
    def admin_metrics() -> dict[str, Any]:
        """Quality + AI-rejection counters since the metrics file was created.

        Use cases:
          * spot a sudden spike in `plagiarism_rejects` after a prompt edit
          * track `ai_success_rate` over time
          * see which validation message dominates rejections
        """
        return get_quality_metrics().as_dict()

    @app.get("/admin/sources", tags=["meta"])
    def admin_sources() -> dict[str, Any]:
        """Per-source ingest health.

        Use cases:
          * identify dead feeds (`cycles_empty / cycles_seen` near 1.0)
          * identify noisy feeds (`relevance_rate` near 0)
          * see `last_published_at_utc` per source for stale-feed checks
        """
        return get_source_health().as_dict()

    # ----- internal feedback loop --------------------------------------
    # A tiny "was this useful?" widget on detail pages POSTs here. We
    # store one line per click in a JSONL file — append-only, no schema
    # migration, no admin UI yet. Future prompt tuning reads this.

    _FEEDBACK_SIGNALS = frozenset({
        "helpful", "too_vague", "too_technical", "incorrect", "not_relevant",
    })
    _feedback_path = DATA_DIR / "feedback.jsonl"
    _feedback_lock = threading.Lock()

    @app.post("/feedback", tags=["feedback"])
    def submit_feedback(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Append one feedback record. JSONL — one line per submission.

        Body: `{"id": "<fingerprint>", "locale": "en|uk", "signal": "<one-of>"}`

        We do NOT echo a running tally back. This endpoint is collection-
        only; analytics happens offline by reading the file.
        """
        post_id = (payload.get("id") or "").strip()
        locale = (payload.get("locale") or "").strip()
        signal = (payload.get("signal") or "").strip()
        if not post_id or len(post_id) > 64:
            raise HTTPException(status_code=400, detail="invalid id")
        if locale not in ("en", "ua"):
            raise HTTPException(status_code=400, detail="invalid locale")
        if signal not in _FEEDBACK_SIGNALS:
            raise HTTPException(status_code=400, detail="invalid signal")
        record = {
            "id": post_id,
            "locale": locale,
            "signal": signal,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            _feedback_path.parent.mkdir(parents=True, exist_ok=True)
            with _feedback_lock:
                with _feedback_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            # We never want a transient FS issue to surface as a 500 to the
            # reader. Log it; respond OK; analytics will skip this record.
            logger.warning("feedback append failed (%s)", exc)
        return {"ok": True}

    return app


# Module-level app for `uvicorn cyberalertx.api.app:app` and the serve CLI.
app = build_app()
