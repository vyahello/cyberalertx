"""Configuration for the intelligence layer.

Every number that shapes a score, a selection or an alert lives here, with
its default in code. An optional JSON file (`data/intel/config.json`) can
override any of them; keys mirror the dataclass fields, nested by section:

    {"weights": {"timeliness": 20, "novelty": 5},
     "selection": {"timezone": "Europe/Kyiv", "cutoff": "06:00"}}

Unknown keys are ignored (and reported by `load_config`). The config's own
hash is part of every score's input hash, so changing a weight forces a
recalculation and the history records it as a config change.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

#: Bumped whenever a formula changes. Stored with every evaluation, so a
#: score is always explainable by the code version that produced it.
CALCULATION_VERSION = "intel-1.0"


@dataclass(frozen=True)
class Weights:
    """Importance components, in points. Defaults sum to 100."""

    potential_impact: float = 25.0
    confirmed_exploitation: float = 20.0
    source_reliability: float = 15.0
    timeliness: float = 15.0
    audience_relevance: float = 10.0
    novelty: float = 10.0
    practical_usefulness: float = 5.0

    def as_dict(self) -> dict[str, float]:
        return {f.name: float(getattr(self, f.name)) for f in fields(self)}


@dataclass(frozen=True)
class ScoringConfig:
    #: Timeliness halves every `half_life_hours` since the story's last
    #: material development (newest independent article).
    half_life_hours: float = 24.0
    #: Age is measured in whole buckets of this many hours, so re-running the
    #: evaluation inside one bucket reproduces the same input hash and skips.
    age_bucket_hours: float = 1.0
    #: Novelty of a story already featured in an earlier edition, without /
    #: with material new evidence since.
    repeat_novelty: float = 0.2
    repeat_with_new_evidence_novelty: float = 0.6
    #: Novelty of a labelled digest / weekly roundup headline.
    digest_novelty: float = 0.3
    #: How many history entries each story keeps.
    history_limit: int = 20


@dataclass(frozen=True)
class SelectionConfig:
    timezone: str = "Europe/Kyiv"
    #: Local time an edition closes. Edition D covers (cutoff on D-1, cutoff on D].
    cutoff: str = "06:00"
    #: Stories whose last activity falls up to this many hours BEFORE the
    #: edition window opens are still considered (late-evening stories that
    #: no edition has featured yet). Repeats are handled by novelty.
    carry_over_hours: float = 12.0
    size: int = 10
    #: Quality threshold on the selection score; fewer than `size` picks
    #: when fewer stories clear it.
    min_selection_score: float = 35.0
    #: Selection score = importance x this multiplier.
    verification_multiplier: Mapping[str, float] = field(default_factory=lambda: {
        "verified": 1.0, "partially_verified": 0.9, "unverified": 0.7,
    })
    #: Two candidate clusters sharing a CVE, or whose headlines overlap this
    #: much (distinctive-token Jaccard), are treated as one event.
    duplicate_title_jaccard: float = 0.6


@dataclass(frozen=True)
class TrendingConfig:
    window_hours: float = 24.0
    min_score: float = 40.0
    #: At least this many distinct trend signals must fire (see trending.py),
    #: so no single input — least of all coverage volume — can make a story trend.
    min_signals: int = 2
    size: int = 10
    weights: Mapping[str, float] = field(default_factory=lambda: {
        "new_information": 20.0,
        "development": 25.0,
        "corroboration": 15.0,
        "exploitation": 15.0,
        "audience": 10.0,
        "importance": 15.0,
    })


@dataclass(frozen=True)
class BreakingConfig:
    #: Only stories with activity inside this window can be breaking.
    window_hours: float = 24.0
    critical_cvss: float = 9.0
    #: Minimum reliability for a source to count as an independent confirmer.
    confirmer_min_reliability: float = 0.45
    #: Minimum importance for the ransomware and infrastructure rules.
    ransomware_min_importance: float = 55.0
    infrastructure_min_importance: float = 55.0
    government_warning_min_level: str = "High"


@dataclass(frozen=True)
class IntelConfig:
    weights: Weights = field(default_factory=Weights)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    trending: TrendingConfig = field(default_factory=TrendingConfig)
    breaking: BreakingConfig = field(default_factory=BreakingConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]

    def normalized_weights(self) -> dict[str, float]:
        """Weights rescaled to sum to exactly 100 (a hand-edited config that
        sums to 90 still yields a 0-100 score)."""
        raw = self.weights.as_dict()
        total = sum(max(0.0, v) for v in raw.values())
        if total <= 0:
            return Weights().as_dict()
        return {k: max(0.0, v) * 100.0 / total for k, v in raw.items()}


def _merge(obj: Any, overrides: Mapping[str, Any], path: str, unknown: list[str]) -> Any:
    if not is_dataclass(obj) or isinstance(obj, type):
        return obj
    changes: dict[str, Any] = {}
    names = {f.name for f in fields(obj)}
    for key, value in overrides.items():
        if key not in names:
            unknown.append(f"{path}{key}")
            continue
        current = getattr(obj, key)
        if is_dataclass(current) and isinstance(value, Mapping):
            changes[key] = _merge(current, value, f"{path}{key}.", unknown)
        elif isinstance(current, Mapping) and isinstance(value, Mapping):
            changes[key] = {**current, **{str(k): float(v) for k, v in value.items()}}
        elif isinstance(current, bool):
            changes[key] = bool(value)
        elif isinstance(current, int) and not isinstance(current, bool):
            changes[key] = int(value)
        elif isinstance(current, float):
            changes[key] = float(value)
        else:
            changes[key] = str(value)
    return replace(obj, **changes)


def config_from_mapping(data: Mapping[str, Any]) -> tuple[IntelConfig, list[str]]:
    unknown: list[str] = []
    merged = _merge(IntelConfig(), data, "", unknown)
    assert isinstance(merged, IntelConfig)
    return merged, unknown


def load_config(path: Path | None) -> IntelConfig:
    """Code defaults, overlaid with `path` when it exists. Never raises on a
    bad file: logs and falls back to the defaults."""
    if path is None or not Path(path).exists():
        return IntelConfig()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("config root must be an object")
        cfg, unknown = config_from_mapping(data)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("intel config %s unreadable (%s) — using defaults", path, exc)
        return IntelConfig()
    if unknown:
        logger.warning("intel config %s: unknown keys ignored: %s", path, ", ".join(unknown))
    return cfg


__all__ = [
    "CALCULATION_VERSION", "BreakingConfig", "IntelConfig", "ScoringConfig", "SelectionConfig",
    "TrendingConfig", "Weights", "config_from_mapping", "load_config",
]
