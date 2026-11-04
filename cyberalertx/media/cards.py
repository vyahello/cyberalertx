"""Branded card records: stable public URLs, content hash, alt text.

The pixels are rendered by the website (`frontend/lib/media/card.tsx`) from
the story's own edition, on request, at:

    {SITE}/{locale}/threat/{id}/card/{variant}.{png|webp|avif}

This module records what Telegram, Threads and admins need to know about a
card without storing bytes: the variant URLs (versioned with `?v=` = the
content hash of the visible inputs, so caches refresh exactly when the card
changes), and alt text in the card's own language. A card is only recorded
for an edition that has text — never from another language's headline.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Mapping

from .assets import MediaAsset

#: Mirrors CARD_VERSION in frontend/lib/media/spec.ts.
CARD_VERSION = "card-1"

#: Platform variants (width, height) — mirrors frontend/lib/media/card.tsx.
CARD_VARIANTS: Mapping[str, tuple[int, int]] = {
    "og": (1200, 630),
    "telegram": (1200, 675),
    "threads-portrait": (1080, 1350),
    "threads-square": (1080, 1080),
    "preview": (640, 360),
}

_LEVEL = {
    "en": {"Critical": "Critical", "High": "High", "Medium": "Medium", "Low": "Low"},
    "ua": {"Critical": "критичний", "High": "високий", "Medium": "середній", "Low": "низький"},
}


def site_url() -> str:
    return (os.getenv("CYBERALERTX_PUBLIC_BASE_URL") or os.getenv("NEXT_PUBLIC_SITE_URL")
            or "https://cyberalertx.com").rstrip("/")


def card_inputs(post: Mapping[str, Any], locale: str) -> dict[str, Any] | None:
    """The visible inputs of one edition's card, from an API post payload."""
    c = (post.get("translations") or {}).get(locale) or {}
    title = str(c.get("title") or "").strip()
    if not title:
        return None
    return {
        "v": CARD_VERSION, "locale": locale, "title": title,
        "category": post.get("category") or "", "level": post.get("threat_level") or "",
        "published_at": post.get("published_at") or "",
        "exploited": bool((post.get("signals") or {}).get("active_exploitation")),
        "art": ((post.get("media") or {}).get("illustration") or {}).get("asset_id", ""),
    }


def content_hash(inputs: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def card_url(locale: str, post_id: str, variant: str = "og", fmt: str = "png", version: str = "") -> str:
    if variant not in CARD_VARIANTS or fmt not in ("png", "webp", "avif"):
        raise ValueError(f"unknown card variant/format {variant}.{fmt}")
    q = f"?v={version}" if version else ""
    return f"{site_url()}/{locale}/threat/{post_id}/card/{variant}.{fmt}{q}"


def alt_text(inputs: Mapping[str, Any]) -> str:
    """Describes what the image shows, without restating the whole article."""
    loc = inputs["locale"]
    level = _LEVEL.get(loc, _LEVEL["en"]).get(inputs.get("level", ""), "")
    if loc == "ua":
        parts = ["Картка CyberAlertX"]
        if level:
            parts.append(f"рівень загрози {level}")
        if inputs.get("exploited"):
            parts.append("уже використовують в атаках")
        return ", ".join(parts) + f": «{inputs['title']}»"
    parts = ["CyberAlertX card"]
    if level:
        parts.append(f"{level.lower()} severity")
    if inputs.get("exploited"):
        parts.append("exploited in attacks")
    return ", ".join(parts) + f": “{inputs['title']}”"


def card_asset(post: Mapping[str, Any], locale: str, story_key: str) -> MediaAsset | None:
    inputs = card_inputs(post, locale)
    if inputs is None:
        return None
    h = content_hash(inputs)
    pid = str(post["id"])
    variants = {v: card_url(locale, pid, v, "png", h) for v in CARD_VARIANTS}
    w, ht = CARD_VARIANTS["og"]
    return MediaAsset(
        asset_id=f"card:{pid}:{locale}", story_key=story_key, asset_type="branded_card",
        locale=locale, public_url=variants["og"], variants=variants, mime_type="image/png",
        width=w, height=ht, alt_text={locale: alt_text(inputs)},
        generation_method="deterministic-svg", generation_model="satori/resvg",
        prompt_version=CARD_VERSION, content_hash=h, members=[pid], status="generated",
    )


__all__ = ["CARD_VARIANTS", "CARD_VERSION", "alt_text", "card_asset", "card_inputs", "card_url",
           "content_hash", "site_url"]
