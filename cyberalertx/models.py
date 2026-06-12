"""Core domain models for CyberAlertX.

A single `NewsItem` flows through every layer:
    source -> filter -> ranker -> storage -> (future) AI / UI / notifier.

The output shape required by spec lives in `NewsItem.to_public_dict()`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    published_at: datetime
    raw_content: str
    # Filled in by later stages; defaulted so a Source can emit a bare item.
    threat_score: float = 0.0
    tags: list[str] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=_utcnow)
    # --- enrichment fields (added in v0.2; old JSON loads with defaults) ---
    # Current content language (BCP-47-ish: "en", "ua", "other", "unknown").
    # `original_language` preserves what the feed served, even if later layers
    # translate `title`/`raw_content` into another language.
    language: str = "unknown"
    original_language: str = "unknown"
    category: str = "other"
    category_confidence: float = 0.0
    affected_platforms: list[str] = field(default_factory=list)
    # Which audiences this story is most relevant to (multi-label, sorted).
    # Empty list = no audience matched (generic / niche story).
    audience_targets: list[str] = field(default_factory=list)
    # Confidence in the audience classification, in [0.0, 1.0].
    audience_relevance_score: float = 0.0
    # How actionable this item is for the user:
    #   "informational"      — read-only context, no action needed
    #   "recommended_action" — should patch/update/check, no fire yet
    #   "urgent_action"      — drop everything (active exploit, creds in danger)
    actionability_level: str = "informational"
    # Continuous score in [0.0, 1.0] backing the level — kept alongside so the
    # UI can render gradients, ranking, and ties without re-running classification.
    actionability_score: float = 0.0
    # How much we trust this story:
    #   "trusted"    — official advisories, established outlets
    #   "verified"   — generally reliable, possibly aggregated / second-hand
    #   "unverified" — unknown / unregistered source, blog repost, etc.
    # Default is "unverified" — safer default for a source we haven't profiled.
    source_tier: str = "unverified"
    # Continuous score in [0.0, 1.0] backing the tier. Combines registry
    # reputation, sensationalism penalty, and cross-source corroboration.
    source_credibility_score: float = 0.0
    # Names of OTHER trusted sources in the same fetch batch that reported
    # the same story. Populated by the credibility analyzer when it computes
    # the corroboration bonus. Surfaces in the API as "Also reported by …"
    # so the reader sees independent confirmation at a glance. Stays empty
    # for items in single-source coverage.
    corroborating_sources: list[str] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        """Stable ID for dedup. URL is the strongest signal; fallback to title."""
        basis = (self.url or self.title).strip().lower()
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]

    def to_public_dict(self) -> Dict[str, Any]:
        """Public-facing shape consumed by UI / AI / notifier layers.

        Original spec fields are kept verbatim; enrichments are appended so
        existing consumers don't break and new ones can opt-in.
        """
        return {
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "published_at": self.published_at.astimezone(timezone.utc).isoformat(),
            "raw_content": self.raw_content,
            "threat_score": round(float(self.threat_score), 3),
            "language": self.language,
            "original_language": self.original_language,
            "category": self.category,
            "category_confidence": round(float(self.category_confidence), 3),
            "affected_platforms": list(self.affected_platforms),
            "audience_targets": list(self.audience_targets),
            "audience_relevance_score": round(float(self.audience_relevance_score), 3),
            "actionability_level": self.actionability_level,
            "actionability_score": round(float(self.actionability_score), 3),
            "source_tier": self.source_tier,
            "source_credibility_score": round(float(self.source_credibility_score), 3),
            "corroborating_sources": list(self.corroborating_sources),
        }

    def to_storage_dict(self) -> Dict[str, Any]:
        """Lossless serialization, used by the JSON store."""
        d = asdict(self)
        d["published_at"] = self.published_at.astimezone(timezone.utc).isoformat()
        d["fetched_at"] = self.fetched_at.astimezone(timezone.utc).isoformat()
        return d

    @classmethod
    def from_storage_dict(cls, data: Dict[str, Any]) -> "NewsItem":
        """Tolerant loader. Every enrichment field uses .get(default) so older
        JSON snapshots (written before v0.2) load with safe defaults.

        Legacy locale code `uk` is silently upgraded to `ua` here so older
        on-disk items.json (written before the rename) become correct in
        memory without forcing a re-ingest.
        """
        legacy_lang = data.get("language", "unknown")
        legacy_orig = data.get("original_language", legacy_lang)
        if legacy_lang == "uk":
            legacy_lang = "ua"
        if legacy_orig == "uk":
            legacy_orig = "ua"
        return cls(
            title=data["title"],
            source=data["source"],
            url=data["url"],
            # `published_at` is required, but a corrupt/empty stored value
            # parses to None — fall back to now() so the field stays a
            # datetime (mirrors the `fetched_at` handling below).
            published_at=_parse_dt(data["published_at"]) or _utcnow(),
            raw_content=data.get("raw_content", ""),
            threat_score=float(data.get("threat_score", 0.0)),
            tags=list(data.get("tags", [])),
            fetched_at=_parse_dt(data.get("fetched_at")) or _utcnow(),
            language=legacy_lang,
            original_language=legacy_orig,
            category=data.get("category", "other"),
            category_confidence=float(data.get("category_confidence", 0.0)),
            affected_platforms=list(data.get("affected_platforms", [])),
            audience_targets=list(data.get("audience_targets", [])),
            audience_relevance_score=float(data.get("audience_relevance_score", 0.0)),
            actionability_level=data.get("actionability_level", "informational"),
            actionability_score=float(data.get("actionability_score", 0.0)),
            source_tier=data.get("source_tier", "unverified"),
            source_credibility_score=float(data.get("source_credibility_score", 0.0)),
            corroborating_sources=list(data.get("corroborating_sources", [])),
        )


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
