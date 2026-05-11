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

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from ..ai.detail_context import detail_context_for
from ..ai.generator import ContentGenerator, build_default_generator
from ..ai.models import ThreatPost
from ..config import SETTINGS
from ..models import NewsItem
from ..storage.json_store import JsonNewsStore

logger = logging.getLogger(__name__)


# ----------- homepage ranking ------------------------------------------

# Items older than this drop off the homepage entirely. They remain
# fetchable via /posts/{id} (direct links keep working) but the feed
# stops showing stale stories — the product should feel current.
_HOMEPAGE_MAX_AGE_DAYS = 30

# Freshness decays exponentially; half-life means "an item N days old is
# worth half as much as a fresh one, all else equal". 5 days keeps the
# last week in heavy rotation and reasons gracefully about older items.
_FRESHNESS_HALF_LIFE_DAYS = 5.0

# Consumer-facing audiences get a small visibility boost — improves the
# experience for non-technical readers without suppressing infra incidents.
_CONSUMER_AUDIENCES = frozenset({"normal_users", "mobile_users", "crypto_users"})
_CONSUMER_CATEGORIES = frozenset({"phishing", "scam", "social engineering", "spyware"})


def _freshness_factor(item: NewsItem, now: datetime) -> float:
    """Exponential decay on item age. 1.0 today → 0.5 at 5 days → 0.06 at 30d."""
    age_hours = max(0.0, (now - item.published_at).total_seconds() / 3600.0)
    age_days = age_hours / 24.0
    return math.pow(0.5, age_days / _FRESHNESS_HALF_LIFE_DAYS)


def _consumer_relevance_bonus(item: NewsItem) -> float:
    """Soft +bonus for items normal users can actually act on. Caps at +0.30
    so a critical technical incident never gets buried by lighter consumer
    content — the bonus only matters at the margin.
    """
    bonus = 0.0
    if any(a in _CONSUMER_AUDIENCES for a in item.audience_targets):
        bonus += 0.20
    if item.category in _CONSUMER_CATEGORIES:
        bonus += 0.10
    return min(bonus, 0.30)


def _homepage_score(item: NewsItem, now: datetime) -> float:
    """Combined ranking signal used to sort the main feed.

    The shape of the formula reflects the product priorities, in order:
        primary   = freshness × (actionability + credibility) × consumer-relevance
        secondary = threat_score / 100

    Freshness multiplies the whole primary block so a stale Critical CVE
    can't outrank a fresh urgent phishing campaign on the homepage. Threat
    score is added (not multiplied) so it tiebreaks but doesn't dominate.
    """
    freshness = _freshness_factor(item, now)
    actionability = item.actionability_score
    credibility = item.source_credibility_score
    consumer = 1.0 + _consumer_relevance_bonus(item)
    primary = freshness * (actionability * 0.6 + credibility * 0.4) * consumer
    secondary = item.threat_score / 100.0 * 0.15
    return primary + secondary


def _within_homepage_window(item: NewsItem, now: datetime) -> bool:
    return (now - item.published_at) <= timedelta(days=_HOMEPAGE_MAX_AGE_DAYS)


# ---------- service -----------------------------------------------------

class _PostService:
    """Reads NewsItems + generates ThreatPosts on demand.

    A single instance per process; the underlying caches (ThreatPostCache,
    JsonNewsStore's in-memory dict) are file-backed so multiple uvicorn
    workers stay coherent via disk.
    """

    def __init__(
        self,
        store: JsonNewsStore | None = None,
        generator: ContentGenerator | None = None,
    ) -> None:
        self._store = store or JsonNewsStore(
            SETTINGS.storage_path, max_items=SETTINGS.max_items_retained,
        )
        self._generator = generator or build_default_generator()

    def list_items(self) -> list[NewsItem]:
        """Re-read from disk on every request so a fresh ingest cycle is
        picked up without restarting the server. The store is in-memory
        keyed by fingerprint, so this is cheap; we explicitly recreate to
        catch concurrent rewrites by the pipeline process.
        """
        store = JsonNewsStore(
            SETTINGS.storage_path, max_items=SETTINGS.max_items_retained,
        )
        return store.all()

    # Fields the generator owns (text content). Everything else is shared
    # metadata about the item and lives at the top level of the response.
    _LOCALIZED_FIELDS = (
        "title", "short_summary", "why_it_matters", "affected_users",
        "what_to_do", "what_not_to_do", "quick_facts", "reading_time_seconds",
    )

    def render(self, item: NewsItem) -> dict[str, Any]:
        """Merge a NewsItem's metadata with its localized ThreatPost(s).

        Returns the frontend `LocalizedThreatPost` shape — top-level shared
        fields (threat_level, category, platforms, …) and a `translations`
        sub-object holding the text content per locale.

        In MVP-rule-based mode we generate one locale per item (the item's
        source language). `available_locales` reflects what was actually
        produced. When the LLM path is enabled this method also generates
        the other locale; the response shape stays identical.
        """
        primary = item.language if item.language in ("en", "uk") else "en"
        translations: dict[str, dict[str, Any]] = {}

        # Always render the item's source language.
        primary_post = self._generator.generate(item, language=primary)
        translations[primary] = _attach_detail_context(
            _localized_content_dict(primary_post), item.category, primary,
        )

        # When the LLM provider is wired up, generate the OTHER locale too
        # so the frontend can render the same item in any language without
        # mixed-language artifacts. With rule-based only, we skip — the
        # generator can't translate raw_content, and we never want mixed
        # text in the UI.
        if self._generator._provider is not None:  # noqa: SLF001 — intentional
            other = "uk" if primary == "en" else "en"
            try:
                other_post = self._generator.generate(item, language=other)
                translations[other] = _attach_detail_context(
                    _localized_content_dict(other_post), item.category, other,
                )
            except Exception as exc:
                logger.warning(
                    "secondary-locale (%s) generation failed for %s: %s",
                    other, item.fingerprint, exc,
                )

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
            "available_locales": sorted(translations.keys()),
            "translations": translations,
        }


def _localized_content_dict(post: ThreatPost) -> dict[str, Any]:
    """Project a ThreatPost down to its localized text fields only."""
    full = post.to_dict()
    return {k: full[k] for k in _PostService._LOCALIZED_FIELDS}


def _attach_detail_context(
    base: dict[str, Any], category: str, locale: str,
) -> dict[str, Any]:
    """Merge the per-category detail-page context paragraphs into `base`.

    Returns the same dict; mutates in place. Sections absent for the
    (category, locale) pair are simply omitted, so the frontend's
    presence-checks naturally collapse the unused panels.
    """
    ctx = detail_context_for(category, locale)
    if ctx:
        base.update(ctx)
    return base


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    svc = service or _PostService()

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "stored_items": len(svc.list_items()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _render_many(items: list[NewsItem]) -> list[dict[str, Any]]:
        rendered: list[dict[str, Any]] = []
        for item in items:
            try:
                rendered.append(svc.render(item))
            except Exception as exc:
                # One bad item must not break the response. Log it and
                # skip — the frontend gets the remaining valid posts.
                logger.warning(
                    "render failed for %s: %s — skipping", item.fingerprint, exc,
                )
        return rendered

    @app.get("/posts", tags=["posts"])
    def list_posts(
        limit: int = Query(15, ge=1, le=200),
        language: str | None = Query(None, pattern="^(en|uk)$"),
    ) -> dict[str, Any]:
        """Main feed — ranked by homepage_score (freshness × actionability ×
        credibility × consumer-relevance), with items >30 days old excluded.

        The default limit is 15: this is a curated awareness product, not a
        firehose. Callers needing more can ask for up to 200.

        Locale-aware filtering happens BEFORE the top-N slice so callers
        asking for `?language=uk&limit=15` get the 15 best UK items, not a
        slice of the global top-15 that happens to contain UK content.
        Without this, sparse-locale feeds (UK in our setup) would be
        starved by the much larger English firehose.
        """
        now = datetime.now(timezone.utc)
        items = [i for i in svc.list_items() if _within_homepage_window(i, now)]
        items.sort(key=lambda i: _homepage_score(i, now), reverse=True)
        if language:
            # We have to render to know `available_locales`; render only as
            # many as needed by walking the sorted list until we have `limit`
            # locale-matching items (or run out).
            rendered: list[dict[str, Any]] = []
            for item in items:
                try:
                    post = svc.render(item)
                except Exception as exc:
                    logger.warning(
                        "render failed for %s: %s — skipping", item.fingerprint, exc,
                    )
                    continue
                if language in post.get("available_locales", []):
                    rendered.append(post)
                    if len(rendered) >= limit:
                        break
            return {"items": rendered, "total": len(rendered)}
        # No language filter — take top-N then render once.
        rendered = _render_many(items[:limit])
        return {"items": rendered, "total": len(rendered)}

    @app.get("/posts/trending", tags=["posts"])
    def list_trending(limit: int = Query(5, ge=1, le=50)) -> dict[str, Any]:
        """Trending — urgent_action OR Critical, fresh-window only, ranked
        by actionability then freshness then threat_score.
        """
        now = datetime.now(timezone.utc)
        items = [
            i for i in svc.list_items()
            if (i.actionability_level == "urgent_action" or i.threat_score >= 50)
            and _within_homepage_window(i, now)
        ]
        items.sort(
            key=lambda i: (
                i.actionability_score,
                _freshness_factor(i, now),
                i.threat_score,
            ),
            reverse=True,
        )
        items = items[:limit]
        return {"items": _render_many(items), "total": len(items)}

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

    return app


# Module-level app for `uvicorn cyberalertx.api.app:app` and the serve CLI.
app = build_app()
