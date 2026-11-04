"""Story importance score, 0–100. Deterministic and explainable.

score = Σ component_i × weight_i      (weights from `config.Weights`, rescaled to 100)

Each component is a value in 0..1 computed from stored fields — no model
returns a number here:

potential_impact (25)
    0.7 × severity + 0.3 × reach.
    severity = max(rendered threat level: Critical 1.0 / High 0.75 /
    Medium 0.45 / Low 0.2 — or, with no render, ingest threat_score/100;
    highest CVSS in the fact sheets / 10). reach = min(1, (affected
    platforms + audiences + products) / 4).
confirmed_exploitation (20)
    confirmed 1.0 · reported 0.6 · poc_available 0.4 · unknown 0.
source_reliability (15)
    best INDEPENDENT source's reliability (`sources.py`) + 0.1 per further
    independent source above 0.45 (max +0.2). Syndicated copies add nothing.
timeliness (15)
    0.5 ** (age / half_life), age = hours since the newest article, counted
    in whole buckets so re-runs inside a bucket are identical.
audience_relevance (10)
    highest of: enterprise/sysadmins 0.9, everyday users 0.85, developers 0.8,
    phone users 0.75, crypto holders 0.6; no audience 0.3.
novelty (10)
    1.0 new; featured in an earlier edition 0.2, or 0.6 if material new
    evidence arrived since; a digest/roundup headline 0.3.
practical_usefulness (5)
    1.0 when the brief carries concrete actions AND a fix/mitigation exists
    (fact sheet patch status or mitigations); 0.5 actions only; 0 none.

Confidence, verification and exploitation status are reported next to the
score (`dimensions.py`) but never multiplied into it.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .config import CALCULATION_VERSION, IntelConfig
from .dimensions import Dimension, all_dimensions, as_json
from .sources import SourceTable
from .story import StoryView

LEVEL_SEVERITY: Mapping[str, float] = {"Critical": 1.0, "High": 0.75, "Medium": 0.45, "Low": 0.2}
EXPLOITATION_VALUE: Mapping[str, float] = {
    "confirmed": 1.0, "reported": 0.6, "poc_available": 0.4, "unknown": 0.0,
}
AUDIENCE_VALUE: Mapping[str, float] = {
    "enterprise": 0.9, "sysadmins": 0.9, "normal_users": 0.85, "developers": 0.8,
    "mobile_users": 0.75, "crypto_users": 0.6,
}
_DIGEST = re.compile(r"weekly|recap|roundup|digest|news #\d+|огляд|дайджест|випуск", re.IGNORECASE)


@dataclass
class Evaluation:
    story_key: str
    score: float
    components: dict[str, float]           # weighted points per component
    raw: dict[str, float]                  # 0..1 per component
    reasons: dict[str, list[str]]
    dimensions: dict[str, dict[str, Any]]
    input_hash: str
    calculation_version: str = CALCULATION_VERSION
    evaluated_at: str = ""
    changes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "story_key": self.story_key, "score": self.score, "components": self.components,
            "raw": self.raw, "reasons": self.reasons, "dimensions": self.dimensions,
            "input_hash": self.input_hash, "calculation_version": self.calculation_version,
            "evaluated_at": self.evaluated_at, "changes": self.changes,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Evaluation":
        return cls(
            story_key=str(d["story_key"]), score=float(d["score"]),
            components={k: float(v) for k, v in d.get("components", {}).items()},
            raw={k: float(v) for k, v in d.get("raw", {}).items()},
            reasons={k: list(v) for k, v in d.get("reasons", {}).items()},
            dimensions=dict(d.get("dimensions", {})), input_hash=str(d.get("input_hash", "")),
            calculation_version=str(d.get("calculation_version", "")),
            evaluated_at=str(d.get("evaluated_at", "")), changes=list(d.get("changes", [])),
        )

    def dim(self, name: str) -> str:
        return str(self.dimensions.get(name, {}).get("value", ""))


def _hours(a: datetime, b: datetime) -> float:
    return max(0.0, (a - b).total_seconds() / 3600.0)


def _severity(story: StoryView) -> tuple[float, list[str]]:
    levels = [str(getattr(p, "threat_level", "")) for p in story.posts.values()]
    sev = max((LEVEL_SEVERITY.get(lv, 0.0) for lv in levels), default=0.0)
    why = [f"rendered level {max(levels, key=lambda lv: LEVEL_SEVERITY.get(lv, 0))}"] if sev else []
    if not sev:
        sev = max(m.threat_score for m in story.members) / 100.0
        why.append(f"no render; ingest threat score {sev * 100:.0f}")
    cvss = [float(getattr(c, "score", 0) or 0) for s in story.sheets
            for c in getattr(s, "cvss_scores", []) or []]
    if cvss and max(cvss) / 10.0 > sev:
        sev = max(cvss) / 10.0
        why.append(f"CVSS {max(cvss):.1f}")
    return min(1.0, sev), why


def _reach(story: StoryView) -> float:
    platforms = {p for m in story.members for p in m.affected_platforms}
    audiences = {a for m in story.members for a in m.audience_targets}
    products = {getattr(p, "product", "") for s in story.sheets for p in getattr(s, "affected_products", []) or []}
    return min(1.0, (len(platforms) + len(audiences) + len(products - {""})) / 4.0)


def components(
    story: StoryView,
    dims: Mapping[str, Dimension],
    table: SourceTable,
    cfg: IntelConfig,
    now: datetime,
    *,
    featured_before: bool = False,
    new_evidence_since_featured: bool = False,
) -> tuple[dict[str, float], dict[str, list[str]]]:
    raw: dict[str, float] = {}
    why: dict[str, list[str]] = {}

    sev, sev_why = _severity(story)
    reach = _reach(story)
    raw["potential_impact"] = round(0.7 * sev + 0.3 * reach, 4)
    why["potential_impact"] = sev_why + [f"reach {reach:.2f}"]

    ex = dims["exploitation_status"]
    raw["confirmed_exploitation"] = EXPLOITATION_VALUE.get(ex.value, 0.0)
    why["confirmed_exploitation"] = [ex.value, *ex.reasons]

    rel = sorted((table.reliability(s) for s in story.independent_sources), reverse=True)
    extra = min(0.2, 0.1 * len([r for r in rel[1:] if r >= 0.45]))
    raw["source_reliability"] = round(min(1.0, (rel[0] if rel else 0.0) + extra), 4)
    why["source_reliability"] = [
        f"independent sources: {', '.join(story.independent_sources)}",
        f"all reporting outlets: {len(story.sources)} (syndicated copies not counted)",
    ]

    bucket = cfg.scoring.age_bucket_hours or 1.0
    age = int(_hours(now, story.last_activity) // bucket) * bucket
    raw["timeliness"] = round(0.5 ** (age / cfg.scoring.half_life_hours), 4)
    why["timeliness"] = [f"{age:.0f} h since the newest article"]

    auds = {a for m in story.members for a in m.audience_targets}
    raw["audience_relevance"] = max((AUDIENCE_VALUE.get(a, 0.5) for a in auds), default=0.3)
    why["audience_relevance"] = [", ".join(sorted(auds)) or "no audience detected"]

    if _DIGEST.search(story.anchor.title):
        raw["novelty"], nv = cfg.scoring.digest_novelty, "digest/roundup headline"
    elif featured_before:
        raw["novelty"] = (cfg.scoring.repeat_with_new_evidence_novelty if new_evidence_since_featured
                          else cfg.scoring.repeat_novelty)
        nv = "featured before" + (" — new evidence since" if new_evidence_since_featured else "")
    else:
        raw["novelty"], nv = 1.0, "not featured before"
    why["novelty"] = [nv]

    actions = any(getattr(p, "what_to_do", None) for p in story.posts.values())
    fix = any(str(getattr(s, "patch_status", "unknown")) in ("available", "partial", "workaround_only")
              or getattr(s, "mitigations", None) for s in story.sheets)
    raw["practical_usefulness"] = 1.0 if actions and fix else 0.5 if actions else 0.0
    why["practical_usefulness"] = [("actions" if actions else "no actions")
                                   + (" + fix/mitigation available" if fix else "")]
    return raw, why


def input_hash(story: StoryView, cfg: IntelConfig, table: SourceTable, now: datetime,
               featured_before: bool, new_evidence: bool) -> str:
    bucket = cfg.scoring.age_bucket_hours or 1.0
    blob = {
        "v": CALCULATION_VERSION, "cfg": cfg.config_hash(), "src": table.fingerprint(),
        "members": sorted((m.fingerprint, m.source, m.threat_score) for m in story.members),
        "indep": sorted(story.independent_sources),
        "sheets": sorted(json.dumps(s.model_dump() if hasattr(s, "model_dump") else str(s),
                                    sort_keys=True, default=str) for s in story.sheets),
        "posts": sorted((k, str(getattr(p, "threat_level", "")), bool(getattr(p, "what_to_do", None)))
                        for k, p in story.posts.items()),
        "age": int(_hours(now, story.last_activity) // bucket),
        "featured": featured_before, "new_evidence": new_evidence,
    }
    return hashlib.sha256(json.dumps(blob, sort_keys=True, default=str).encode()).hexdigest()[:16]


def evaluate(
    story: StoryView,
    cfg: IntelConfig,
    table: SourceTable,
    now: datetime,
    *,
    previous: Evaluation | None = None,
    featured_before: bool = False,
    new_evidence_since_featured: bool = False,
) -> Evaluation:
    """Score one story. Returns `previous` unchanged when nothing it depends
    on changed (same input hash), so unchanged stories are not recalculated."""
    h = input_hash(story, cfg, table, now, featured_before, new_evidence_since_featured)
    if previous is not None and previous.input_hash == h and previous.calculation_version == CALCULATION_VERSION:
        return previous
    dims = all_dimensions(story, table)
    raw, why = components(story, dims, table, cfg, now, featured_before=featured_before,
                          new_evidence_since_featured=new_evidence_since_featured)
    weights = cfg.normalized_weights()
    pts = {k: round(raw[k] * weights[k], 2) for k in weights}
    score = round(min(100.0, max(0.0, sum(pts.values()))), 1)
    ev = Evaluation(
        story_key=story.key, score=score, components=pts, raw=raw, reasons=why,
        dimensions={k: as_json(v) for k, v in dims.items()}, input_hash=h,
        evaluated_at=now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
    )
    ev.changes = diff(previous, ev)
    return ev


def diff(old: Evaluation | None, new: Evaluation) -> list[str]:
    if old is None:
        return ["first evaluation"]
    out: list[str] = []
    if abs(old.score - new.score) >= 0.5:
        out.append(f"score {old.score:.1f} → {new.score:.1f}")
    for k, v in new.components.items():
        if abs(old.components.get(k, 0.0) - v) >= 1.0:
            out.append(f"{k} {old.components.get(k, 0.0):.1f} → {v:.1f}")
    for k in ("exploitation_status", "verification_status", "confidence"):
        if old.dim(k) != new.dim(k):
            out.append(f"{k} {old.dim(k) or '—'} → {new.dim(k)}")
    if old.calculation_version != new.calculation_version:
        out.append(f"calculation {old.calculation_version} → {new.calculation_version}")
    return out or ["inputs changed, score unchanged"]


__all__ = ["AUDIENCE_VALUE", "EXPLOITATION_VALUE", "Evaluation", "LEVEL_SEVERITY", "components",
           "diff", "evaluate", "input_hash"]
