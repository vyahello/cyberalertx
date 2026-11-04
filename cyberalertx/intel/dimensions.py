"""Exploitation, verification and confidence — kept apart from importance.

Importance asks "how significant would this be?". These three ask different
questions and are never folded into that number:

  exploitation_status   confirmed | reported | poc_available | unknown
      Is anyone exploiting it?
  verification_status   verified | partially_verified | unverified
      Has the core claim been established by a source that is in a position
      to know (an official/primary source), or independently corroborated?
  confidence            high | medium | low   (+ a 0..1 value)
      How much weight can the available information bear? Lowered by
      contradictions, thin source text and claims that are only claims.

A high-impact story with low confidence stays high-impact and low-confidence;
the UI and editors see both.

Every decision returns its reasons, so `/admin/intel` can show why.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..pipeline.signals import extract_signals
from .sources import SourceTable
from .story import StoryView

_KEV = re.compile(r"known exploited vulnerabilit|\bKEV\b|каталог\w* .{0,20}експлуат", re.IGNORECASE)
_EXPLOITED = re.compile(
    r"actively exploited|exploited in the wild|in-the-wild|under (?:active )?attack|"
    r"zero-day attacks|being exploited|exploitation (?:has been |was )?(?:observed|detected)|"
    r"вже використовують|активно використовують|використовують в атаках|атакують",
    re.IGNORECASE,
)
_POC = re.compile(r"proof[- ]of[- ]concept|\bPoC\b|exploit code|public exploit|"
                  r"експлойт\w* (?:опубліковано|оприлюднено)|публічн\w+ експлойт", re.IGNORECASE)
_CLAIM_ONLY = re.compile(
    r"\bclaim(?:s|ed)?\b|\balleg(?:es|ed|edly)\b|unconfirmed|заяви(?:в|ли|ла)|стверджу|"
    r"нібито|не підтвердж", re.IGNORECASE,
)


@dataclass(frozen=True)
class Dimension:
    value: str
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0           # confidence only: 0..1


def exploitation_status(story: StoryView, table: SourceTable) -> Dimension:
    reasons: list[str] = []
    ev = story.evidence
    sheet_values = ({str(ev.exploitation_status)} if ev is not None
                    else {str(getattr(s, "exploitation_status", "unknown")) for s in story.sheets})
    official_says = [m.source for m in story.members
                     if table.get(m.source).is_official and _EXPLOITED.search(f"{m.title} {m.raw_content or ''}")]
    kev = [m.source for m in story.members if _KEV.search(f"{m.title} {m.raw_content or ''}")
           and table.get(m.source).is_official]
    if "confirmed" in sheet_values:
        reasons.append("fact sheet: exploitation confirmed by the source")
    if official_says:
        reasons.append(f"official source reports exploitation: {', '.join(sorted(set(official_says)))}")
    if kev:
        reasons.append("listed in a known-exploited-vulnerabilities catalogue")
    if reasons:
        return Dimension("confirmed", reasons)

    reported = [m.source for m in story.members
                if extract_signals(m).active_exploitation or _EXPLOITED.search(f"{m.title} {m.raw_content or ''}")]
    if "reported" in sheet_values or reported:
        who = ", ".join(sorted(set(reported))) or "fact sheet"
        return Dimension("reported", [f"exploitation reported, not confirmed by an official source ({who})"])
    if any(_POC.search(f"{m.title} {m.raw_content or ''}") for m in story.members):
        return Dimension("poc_available", ["proof-of-concept or public exploit code mentioned"])
    return Dimension("unknown", ["no source says it is exploited"])


def _contradictions(story: StoryView) -> list[str]:
    if story.evidence is not None:
        # Merged across the story with syndication collapsed (cluster_evidence).
        return [str(getattr(c, "statement", "") or getattr(c, "topic", "") or c)
                for c in story.evidence.contradictions]
    out: list[str] = []
    for s in story.sheets:
        for c in getattr(s, "contradictions", []) or []:
            out.append(str(getattr(c, "statement", c)))
    # Sheets of different members disagreeing on exploitation is a contradiction too.
    values = {str(getattr(s, "exploitation_status", "unknown")) for s in story.sheets} - {"unknown"}
    if {"confirmed", "not_reported"} <= values:
        out.append("members disagree on whether it is exploited")
    return out


def verification_status(story: StoryView, table: SourceTable) -> Dimension:
    indep = story.independent_sources
    official = [s for s in indep if table.get(s).is_official or table.get(s).is_primary]
    reliable = [s for s in indep if table.reliability(s) >= 0.45]
    claim_only = all(_CLAIM_ONLY.search(m.title) for m in story.members)
    contradictions = _contradictions(story)

    if official and not contradictions:
        return Dimension("verified", [f"primary/official source: {', '.join(official)}"])
    if len(reliable) >= 2 and not contradictions and not claim_only:
        return Dimension("verified", [f"{len(reliable)} independent reliable sources: {', '.join(reliable)}"])
    if len(indep) >= 3 and not contradictions and not claim_only:
        # Several outlets reporting independently (syndication already
        # collapsed) establish the core event even when none of them clears
        # the reliability floor — typical of domestic incidents covered first
        # by regional media.
        return Dimension("partially_verified",
                         [f"{len(indep)} independent outlets, none an official/primary source"])
    if reliable and not claim_only:
        why = [f"one independent reliable source ({reliable[0]})" if len(reliable) == 1
               else f"{len(reliable)} sources but contradictions present"]
        why += [f"contradiction: {c}" for c in contradictions[:3]]
        return Dimension("partially_verified", why)
    why = []
    if claim_only:
        why.append("headlines report claims, not established facts")
    if not reliable:
        why.append("no independent source above the reliability floor")
    why += [f"contradiction: {c}" for c in contradictions[:3]]
    return Dimension("unverified", why or ["insufficient evidence"])


def confidence(story: StoryView, table: SourceTable) -> Dimension:
    indep = story.independent_sources
    best = max((table.reliability(s) for s in indep), default=0.0)
    value = best
    reasons = [f"best independent source reliability {best:.2f}"]
    extra = [s for s in indep if table.reliability(s) >= 0.45][1:]
    if extra:
        bonus = min(0.2, 0.1 * len(extra))
        value += bonus
        reasons.append(f"+{bonus:.2f} independent corroboration ({', '.join(extra)})")
    weak = [s for s in indep if table.reliability(s) < 0.45][(0 if extra or best >= 0.45 else 1):]
    if weak:
        bonus = min(0.15, 0.05 * len(weak))
        value += bonus
        reasons.append(f"+{bonus:.2f} further independent outlets below the reliability floor")
    if any(table.get(s).is_official for s in indep):
        value += 0.1
        reasons.append("+0.10 official source")
    contradictions = _contradictions(story)
    if contradictions:
        value -= 0.25
        reasons.append(f"-0.25 contradictions ({len(contradictions)})")
    body = max((len(m.raw_content or "") for m in story.members), default=0)
    if body < 300:
        value -= 0.15
        reasons.append(f"-0.15 thin source text ({body} chars)")
    if all(_CLAIM_ONLY.search(m.title) for m in story.members):
        value -= 0.15
        reasons.append("-0.15 only claims reported")
    value = round(max(0.0, min(1.0, value)), 3)
    level = "high" if value >= 0.7 else "medium" if value >= 0.45 else "low"
    return Dimension(level, reasons, value)


def all_dimensions(story: StoryView, table: SourceTable) -> dict[str, Dimension]:
    return {
        "exploitation_status": exploitation_status(story, table),
        "verification_status": verification_status(story, table),
        "confidence": confidence(story, table),
    }


def as_json(d: Dimension) -> dict[str, Any]:
    out: dict[str, Any] = {"value": d.value, "reasons": list(d.reasons)}
    if d.score:
        out["score"] = d.score
    return out


__all__ = ["Dimension", "all_dimensions", "as_json", "confidence", "exploitation_status",
           "verification_status"]
