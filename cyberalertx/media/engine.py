"""Media Engine run: cards for every eligible story, illustrations for a few.

Runs on demand (`python -m cyberalertx.tools.media run`) — no new scheduler.
It reuses the Intelligence Core for stories, scores, Top 10 and Breaking, and
the existing stores for items, renders and fact sheets.

Guarantees:
  * Never blocks publication: a story's article and its branded card do not
    depend on any illustration step; every failure is recorded and contained.
  * Cost control: at most `max_calls` provider calls per run; one illustration
    per story; an existing validated illustration is reused until its prompt
    INPUTS change (event type, confirmed exploitation, products) — headline
    edits never trigger a regeneration; failed jobs retry at most
    `max_attempts` times in total, across runs.
  * Only validated files are ever referenced by public URLs.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..models import NewsItem
from ..pipeline.signals import extract_signals
from .assets import MediaAsset, MediaStore, MediaValidationError
from .cards import card_asset, site_url
from .illustrations import (
    EligibilityConfig,
    ProviderError,
    ProviderUnavailable,
    build_prompt,
    eligibility,
    provider_from_env,
)

logger = logging.getLogger(__name__)

ILLUSTRATION_SIZE = (1536, 1024)          # one landscape source; variants are cropped
ILLUSTRATION_VARIANTS = ("article", "og", "telegram", "threads-portrait", "threads-square", "preview")


@dataclass
class MediaRunResult:
    cards: int = 0
    eligible: list[str] = field(default_factory=list)
    generated: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    calls: int = 0
    cost_usd: float = 0.0
    provider: str = "none"

    def summary(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _payload(item: NewsItem, posts: Any) -> dict[str, Any]:
    """The card-relevant slice of the API's post payload, from local stores."""
    translations: dict[str, Any] = {}
    level = ""
    for loc in ("en", "ua"):
        p = posts.get(item.fingerprint, loc) if posts is not None else None
        title = str(getattr(p, "title", "") or "") if p is not None else ""
        if title:
            translations[loc] = {"title": title}
            level = level or str(getattr(p, "threat_level", "") or "")
    return {
        "id": item.fingerprint, "translations": translations, "category": item.category,
        "threat_level": level, "published_at": item.published_at.isoformat(),
        "signals": {"active_exploitation": extract_signals(item).active_exploitation},
    }


def _illustration_urls(sha: str) -> dict[str, str]:
    aid = sha[:16]
    return {v: f"{site_url()}/media/{aid}/{v}.png" for v in ILLUSTRATION_VARIANTS}


def _record_usage(store: MediaStore, entry: Mapping[str, Any]) -> None:
    path = store.root / "usage.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(entry), ensure_ascii=False) + "\n")


def run(
    items: Sequence[NewsItem],
    *,
    store: MediaStore | None = None,
    sheets: Any = None,
    posts: Any = None,
    now: datetime | None = None,
    provider: Any = None,
    cfg: EligibilityConfig | None = None,
    max_calls: int | None = None,
    max_attempts: int = 3,
    timeout_s: float = 90.0,
    dry_run: bool = False,
    intel_dir: Path | None = None,
) -> MediaRunResult:
    from ..intel.engine import run as intel_run

    store = store or MediaStore()
    cfg = cfg or EligibilityConfig.from_env()
    max_calls = int(os.getenv("CYBERALERTX_ILLUSTRATION_MAX_PER_RUN", "3")) if max_calls is None else max_calls
    now = now or datetime.now(timezone.utc)
    kwargs: dict[str, Any] = {"now": now, "sheets": sheets, "posts": posts, "write": False}
    if intel_dir is not None:
        kwargs["intel_dir"] = intel_dir
    intel = intel_run(items, **kwargs)
    ranks = {p["story_key"]: p["rank"] for p in intel.picks}
    breaking = {b["story_key"] for b in intel.breaking}

    if provider is None:
        try:
            provider = provider_from_env()
        except ProviderUnavailable as exc:
            logger.warning("media: %s", exc)
            provider = None
    if provider is not None and getattr(provider, "name", "") == "none":
        provider = None          # branded-card-only mode: no call, no failure recorded
    res = MediaRunResult(provider=getattr(provider, "name", "none") if provider else "none")

    cards: list[MediaAsset] = []
    for story in intel.stories:
        if story.relevance == "out_of_scope":
            continue
        payload = _payload(story.anchor, posts)
        for loc in ("en", "ua"):
            card = card_asset(payload, loc, story.key)
            if card is not None:
                cards.append(card)
    if not dry_run:
        store.put_many(cards)
    res.cards = len(cards)

    for story in intel.stories:
        ev = intel.evals.get(story.key)
        elig = eligibility(story, ev, top_rank=ranks.get(story.key), breaking=story.key in breaking, cfg=cfg)
        if not elig.eligible:
            continue
        res.eligible.append(story.key)
        prompt = build_prompt(story, ev)
        asset_id = f"illus:{story.key}"
        existing = store.get(asset_id)
        members = sorted(m.fingerprint for m in story.members)

        if existing and existing.content_hash == prompt.inputs_hash and existing.status in ("validated", "published"):
            if existing.members != members and not dry_run:
                existing.members = members
                store.put(existing)
            res.reused.append(story.key)
            continue
        same_inputs_failed = (existing is not None and existing.status == "failed"
                              and existing.content_hash == prompt.inputs_hash)
        attempts = existing.attempts if same_inputs_failed and existing else 0
        if attempts >= max_attempts:
            res.skipped.append({"story_key": story.key, "reason": f"retry limit reached ({attempts})"})
            continue
        if provider is None:
            res.skipped.append({"story_key": story.key, "reason": "no image provider configured"})
            continue
        if res.calls >= max_calls:
            res.skipped.append({"story_key": story.key, "reason": f"per-run cap {max_calls} reached"})
            continue
        if dry_run:
            res.skipped.append({"story_key": story.key, "reason": "dry run"})
            continue

        asset = MediaAsset(
            asset_id=asset_id, story_key=story.key, asset_type="editorial_illustration",
            alt_text=prompt.alt, generation_method="ai-image", prompt_version=prompt.inputs["v"],
            prompt=prompt.prompt, content_hash=prompt.inputs_hash, members=members,
            status="generating", attempts=attempts + 1, license="CyberAlertX (generated)",
            source=f"generated:{res.provider}",
        )
        store.put(asset)
        res.calls += 1
        w, h = ILLUSTRATION_SIZE
        try:
            img = provider.generate(prompt.prompt, width=w, height=h, timeout_s=timeout_s)
            sha, mime, iw, ih = store.save_bytes(img.data, declared_mime=img.mime)
        except (ProviderError, ProviderUnavailable, MediaValidationError, TimeoutError, OSError) as exc:
            asset.status, asset.last_error = "failed", f"{type(exc).__name__}: {exc}"[:500]
            store.put(asset)
            res.failed.append({"story_key": story.key, "error": asset.last_error, "attempt": asset.attempts})
            _record_usage(store, {"at": now.isoformat(), "story_key": story.key, "provider": res.provider,
                                  "ok": False, "error": asset.last_error})
            continue
        urls = _illustration_urls(sha)
        asset.storage_key = f"{sha}.{ {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[mime] }"
        asset.mime_type, asset.width, asset.height = mime, iw, ih
        asset.file_size = len(img.data)
        asset.generation_model, asset.cost_usd = img.model, img.cost_usd
        asset.variants, asset.public_url = urls, urls["og"]
        asset.status, asset.last_error = "validated", ""
        store.put(asset)
        res.generated.append(story.key)
        res.cost_usd += img.cost_usd
        _record_usage(store, {"at": now.isoformat(), "story_key": story.key, "provider": res.provider,
                              "model": img.model, "ok": True, "cost_usd": img.cost_usd})
    return res


def illustration_payload(store: MediaStore, fingerprint: str) -> dict[str, Any] | None:
    """The `media.illustration` block the public API adds to a post — only for
    a validated illustration of the story this article belongs to."""
    a = store.illustration_for_member(fingerprint)
    if a is None:
        return None
    return {"asset_id": a.storage_key.split(".")[0][:16], "width": a.width, "height": a.height,
            "alt": dict(a.alt_text), "generated": True}


__all__ = ["ILLUSTRATION_SIZE", "ILLUSTRATION_VARIANTS", "MediaRunResult", "illustration_payload", "run"]
