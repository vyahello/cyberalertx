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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..models import NewsItem
from ..pipeline.signals import extract_signals
from .assets import ALLOWED_MIME, MediaAsset, MediaStore, MediaValidationError
from .cards import card_asset, site_url
from .illustrations import (
    EligibilityConfig,
    ProviderError,
    ProviderUnavailable,
    build_prompt,
    eligibility,
    visual_brief,
)

logger = logging.getLogger(__name__)

ILLUSTRATION_SIZE = (1536, 864)           # one 16:9 source (multiples of 16); variants are cropped
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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Budget:
    """Spending limits for billable image generation (USD)."""
    daily_usd: float = 3.0
    monthly_usd: float = 40.0
    estimate_usd: float = 0.10     # assumed cost of the next image until real costs are recorded
    min_interval_s: float = 2.0    # rate limit between provider calls (calls are sequential)

    @classmethod
    def from_env(cls) -> "Budget":
        return cls(
            daily_usd=_env_float("CYBERALERTX_IMAGE_BUDGET_DAILY_USD", 3.0),
            monthly_usd=_env_float("CYBERALERTX_IMAGE_BUDGET_MONTHLY_USD", 40.0),
            estimate_usd=_env_float("CYBERALERTX_IMAGE_COST_ESTIMATE_USD", 0.10),
            min_interval_s=_env_float("CYBERALERTX_IMAGE_MIN_INTERVAL_S", 2.0),
        )


def spent(store: MediaStore, now: datetime) -> tuple[float, float, float]:
    """(today, this month, average cost of a successful image) from usage.jsonl."""
    path = store.root / "usage.jsonl"
    day = month = total = 0.0
    n = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                at = datetime.fromisoformat(str(e.get("at")))
            except (ValueError, TypeError):
                continue
            cost = float(e.get("cost_usd") or 0.0)
            if e.get("ok"):
                total += cost
                n += 1
            if (at.year, at.month) == (now.year, now.month):
                month += cost
                if at.date() == now.date():
                    day += cost
    return day, month, (total / n if n else 0.0)


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
    budget: Budget | None = None,
    sleep: Any = time.sleep,
) -> MediaRunResult:
    from ..intel.engine import run as intel_run

    store = store or MediaStore()
    cfg = cfg or EligibilityConfig.from_env()
    max_calls = int(os.getenv("CYBERALERTX_ILLUSTRATION_MAX_PER_RUN", "25")) if max_calls is None else max_calls
    now = now or datetime.now(timezone.utc)
    kwargs: dict[str, Any] = {"now": now, "sheets": sheets, "posts": posts, "write": False}
    if intel_dir is not None:
        kwargs["intel_dir"] = intel_dir
    intel = intel_run(items, **kwargs)
    ranks = {p["story_key"]: p["rank"] for p in intel.picks}
    breaking = {b["story_key"] for b in intel.breaking}

    # Generators, in order: a local ComfyUI worker when explicitly enabled and
    # healthy, then the server-side SVG renderer (always available, free).
    comfy = provider
    if comfy is None and os.getenv("CYBERALERTX_COMFYUI_URL"):
        try:
            from .comfyui import ComfyUIProvider
            comfy = ComfyUIProvider()
        except ProviderUnavailable as exc:
            logger.warning("media: ComfyUI disabled: %s", exc)
            comfy = None
    if comfy is not None and getattr(comfy, "name", "") == "none":
        comfy = None
    res = MediaRunResult(provider="comfyui+svg" if comfy else "svg")

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

    budget = budget or Budget.from_env()
    day_spent, month_spent, avg_cost = spent(store, now)
    next_cost = avg_cost or budget.estimate_usd
    # Newest first: currently visible stories are served before older ones.
    ordered = sorted(intel.stories, key=lambda st: st.anchor.published_at, reverse=True)
    for story in ordered:
        ev = intel.evals.get(story.key)
        elig = eligibility(story, ev, top_rank=ranks.get(story.key), breaking=story.key in breaking, cfg=cfg)
        if not elig.eligible:
            continue
        res.eligible.append(story.key)
        prompt = build_prompt(story, ev)
        brief, alt, inputs_hash = visual_brief(story)
        asset_id = f"illus:{story.key}"
        existing = store.get(asset_id)
        members = sorted(m.fingerprint for m in story.members)

        if existing and existing.content_hash == inputs_hash and existing.status in ("validated", "published"):
            if (existing.members != members or dict(existing.alt_text) != alt) and not dry_run:
                existing.members, existing.alt_text = members, alt
                store.put(existing)
            res.reused.append(story.key)
            continue
        same_inputs_failed = (existing is not None and existing.status == "failed"
                              and existing.content_hash == inputs_hash)
        attempts = existing.attempts if same_inputs_failed and existing else 0
        if attempts >= max_attempts:
            res.skipped.append({"story_key": story.key, "reason": f"retry limit reached ({attempts})"})
            continue
        if res.calls >= max_calls:
            res.skipped.append({"story_key": story.key, "reason": f"per-run cap {max_calls} reached"})
            continue
        if dry_run:
            res.skipped.append({"story_key": story.key, "reason": "dry run"})
            continue

        asset = MediaAsset(
            asset_id=asset_id, story_key=story.key, asset_type="editorial_illustration",
            alt_text=alt, generation_method="svg", prompt_version=prompt.inputs["v"],
            prompt=prompt.prompt, content_hash=inputs_hash, members=members,
            status="generating", attempts=attempts + 1, license="CyberAlertX (generated on our server)",
            source="generated:svg",
        )
        store.put(asset)
        res.calls += 1
        img = None
        errors: list[str] = []
        if comfy is not None and day_spent + res.cost_usd <= budget.daily_usd:
            if res.calls > 1 and budget.min_interval_s > 0:
                sleep(budget.min_interval_s)
            w, h = ILLUSTRATION_SIZE
            try:
                img = comfy.generate(prompt.prompt, width=w, height=h, timeout_s=timeout_s)
                store.save_bytes(img.data, declared_mime=img.mime)     # validate before accepting
            except (ProviderError, ProviderUnavailable, MediaValidationError, TimeoutError, OSError) as exc:
                errors.append(f"comfyui: {type(exc).__name__}: {exc}"[:300])
                img = None
        if img is None:
            from .illustrations import GeneratedImage
            from .svg_art import RENDERER_VERSION, render_svg
            try:
                img = GeneratedImage(data=render_svg(brief).encode("utf-8"), mime="image/svg+xml",
                                     model=RENDERER_VERSION, method="svg")
            except Exception as exc:                       # a renderer bug must not stop the run
                errors.append(f"svg: {type(exc).__name__}: {exc}"[:300])
        try:
            if img is None:
                raise MediaValidationError("; ".join(errors) or "no image")
            sha, mime, iw, ih = store.save_bytes(img.data, declared_mime=img.mime)
        except (MediaValidationError, OSError) as exc:
            asset.status, asset.last_error = "failed", f"{type(exc).__name__}: {exc}"[:500]
            store.put(asset)
            res.failed.append({"story_key": story.key, "error": asset.last_error, "attempt": asset.attempts})
            _record_usage(store, {"at": now.isoformat(), "story_key": story.key, "provider": res.provider,
                                  "ok": False, "error": asset.last_error})
            continue
        urls = _illustration_urls(sha)
        asset.storage_key = f"{sha}.{ALLOWED_MIME[mime]}"
        asset.mime_type, asset.width, asset.height = mime, iw, ih
        asset.file_size = len(img.data)
        asset.generation_method, asset.source = img.method, f"generated:{img.method}"
        asset.generation_model, asset.cost_usd = img.model, img.cost_usd
        asset.variants, asset.public_url = urls, urls["og"]
        asset.status, asset.last_error = "validated", ("; ".join(errors) if errors else "")
        store.put(asset)
        res.generated.append(story.key)
        res.cost_usd += img.cost_usd
        _record_usage(store, {"at": now.isoformat(), "story_key": story.key, "method": img.method,
                              "model": img.model, "ok": True, "cost_usd": img.cost_usd,
                              **({"fallback_from": errors} if errors else {})})
    return res


def illustration_payload(store: MediaStore, fingerprint: str) -> dict[str, Any] | None:
    """The `media.illustration` block the public API adds to a post — only for
    a validated illustration of the story this article belongs to."""
    a = store.illustration_for_member(fingerprint)
    if a is None:
        return None
    return {"asset_id": a.storage_key.split(".")[0][:16], "width": a.width, "height": a.height,
            "alt": dict(a.alt_text), "generated": True}


def backfill_plan(items: Sequence[NewsItem], *, store: MediaStore | None = None, posts: Any = None,
                  sheets: Any = None, now: datetime | None = None, intel_dir: Path | None = None,
                  max_attempts: int = 3) -> dict[str, Any]:
    """Read-only: how many public stories need an illustration, and what it would cost."""
    from ..intel.engine import run as intel_run

    store = store or MediaStore()
    now = now or datetime.now(timezone.utc)
    cfg = EligibilityConfig.from_env()
    budget = Budget.from_env()
    kwargs: dict[str, Any] = {"now": now, "sheets": sheets, "posts": posts, "write": False}
    if intel_dir is not None:
        kwargs["intel_dir"] = intel_dir
    intel = intel_run(items, **kwargs)
    eligible = done = failed_final = 0
    todo: list[str] = []
    for story in sorted(intel.stories, key=lambda st: st.anchor.published_at, reverse=True):
        if not eligibility(story, intel.evals.get(story.key), cfg=cfg).eligible:
            continue
        eligible += 1
        _, _, inputs_hash = visual_brief(story)
        a = store.get(f"illus:{story.key}")
        if a and a.content_hash == inputs_hash and a.status in ("validated", "published"):
            done += 1
        elif a and a.status == "failed" and a.content_hash == inputs_hash and a.attempts >= max_attempts:
            failed_final += 1
        else:
            todo.append(story.key)
    day, month, _avg = spent(store, now)
    return {"public_stories_eligible": eligible, "with_validated_illustration": done,
            "failed_at_retry_limit": failed_final, "to_generate": len(todo),
            "method": "comfyui (if healthy) else svg" if os.getenv("CYBERALERTX_COMFYUI_URL") else "svg",
            "cost_usd": 0.0,
            "estimated_cpu_seconds": round(0.05 * len(todo), 1),
            "spent_today_usd": round(day, 4), "spent_this_month_usd": round(month, 4),
            "budget_daily_usd": budget.daily_usd, "budget_monthly_usd": budget.monthly_usd,
            "next": todo[:10]}


__all__ = ["Budget", "ILLUSTRATION_SIZE", "ILLUSTRATION_VARIANTS", "MediaRunResult", "backfill_plan",
           "illustration_payload", "run", "spent"]
