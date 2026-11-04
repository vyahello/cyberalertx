"""Daily Top 10, Trending and Breaking — three separate classifications.

All three work on STORIES (clusters), never on individual articles, and all
three exclude stories classified out of scope. None of them publishes
anything: they produce candidates and internal state for editors.

Daily Top 10
    Edition D covers (cutoff on D-1, cutoff on D] in the editorial timezone,
    plus `carry_over_hours` before that for late stories no edition has had.
    selection score = importance × verification multiplier
    (verified 1.0 · partially 0.9 · unverified 0.7). Stories below
    `min_selection_score` are left out — the list may be shorter than ten.
    Two candidates that share a CVE, or whose headlines overlap strongly,
    are one event: only the stronger stays. Ties: higher importance, then
    newer, then story key — fully deterministic.

Trending (default window 24 h)
    A story trends when at least `min_signals` of these fire and the weighted
    sum reaches `min_score`:
      new_information  an article joined the story inside the window
      development      exploitation confirmed, or a new independent source
                       inside the window (a change, not a repeat)
      corroboration    ≥ 2 independent sources (syndication collapsed)
      exploitation     confirmed or reported exploitation
      audience         audience-relevance component ≥ 0.75
      importance       importance ≥ 60
    Article count is never an input: five copies of one report fire nothing
    that one copy would not.

Breaking
    Explicit evidence rules; any one qualifies. Unverified stories never do.
      R1 critical_exploited   exploitation confirmed AND (CVSS ≥ 9, Critical
                              level, or KEV) AND (official source OR ≥ 2
                              independent confirmers above the reliability floor)
      R2 supply_chain         supply-chain compromise AND verified
      R3 official_warning     official government/CERT source, level ≥ High,
                              AND (exploitation confirmed OR urgent action)
      R4 ransomware_incident  ransomware incident, at least partially verified,
                              importance ≥ threshold, not claims-only
      R5 infrastructure       widely deployed product compromised, exploitation
                              confirmed, importance ≥ threshold
    Alert state per story stores the evidence fingerprint of the last alert;
    the same evidence never alerts twice, materially new evidence produces an
    "update" alert.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..pipeline import dedup
from .config import IntelConfig
from .scoring import Evaluation
from .sources import SourceTable
from .story import StoryView

_SUPPLY_CHAIN = re.compile(r"supply[- ]chain|malicious (?:update|package|version)|compromised "
                           r"(?:package|npm|pypi|build|update)|ланцюг\w* постачан", re.IGNORECASE)
_RANSOM = re.compile(r"ransomware|програм\w+-вимагач|шифрувальник", re.IGNORECASE)
WIDELY_DEPLOYED = (
    "windows", "chrome", "android", "ios", "linux", "microsoft 365", "exchange", "cisco", "vmware",
    "fortinet", "fortigate", "ivanti", "citrix", "palo alto", "openssh", "apache", "nginx",
    "wordpress", "kubernetes", "gitlab", "github", "jenkins", "aws", "azure", "telegram",
)


# ---------------------------------------------------------------- Top 10

def edition_for(now: datetime, cfg: IntelConfig) -> tuple[date, datetime, datetime]:
    """(edition date, window start, window end) in UTC for the edition that `now` belongs to."""
    tz = ZoneInfo(cfg.selection.timezone)
    hh, mm = (int(x) for x in cfg.selection.cutoff.split(":"))
    local = now.astimezone(tz)
    cut_today = datetime.combine(local.date(), time(hh, mm), tzinfo=tz)
    edition_day = local.date() if local <= cut_today else local.date() + timedelta(days=1)
    end = datetime.combine(edition_day, time(hh, mm), tzinfo=tz)
    start = end - timedelta(days=1)
    return edition_day, start.astimezone(timezone.utc), end.astimezone(timezone.utc)


@dataclass
class Pick:
    story_key: str
    title: str
    rank: int
    selection_score: float
    importance: float
    verification: str
    confidence: str
    exploitation: str
    why: list[str]
    sources: list[str]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _same_event(a: StoryView, b: StoryView, threshold: float) -> bool:
    if set(a.cves) & set(b.cves):
        return True
    ta = dedup._distinctive_tokens(a.anchor.title)  # noqa: SLF001
    tb = dedup._distinctive_tokens(b.anchor.title)  # noqa: SLF001
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= threshold


def _top_reasons(ev: Evaluation, n: int = 3) -> list[str]:
    top = sorted(ev.components.items(), key=lambda kv: -kv[1])[:n]
    return [f"{k.replace('_', ' ')} {v:.1f} pts — {ev.reasons.get(k, [''])[0]}" for k, v in top]


def daily_top(
    stories: Sequence[StoryView],
    evals: Mapping[str, Evaluation],
    now: datetime,
    cfg: IntelConfig,
) -> tuple[date, list[Pick], list[dict[str, Any]]]:
    """Return (edition date, picks, rejected-with-reason) for the edition containing `now`."""
    day, start, end = edition_for(now, cfg)
    sc = cfg.selection
    open_from = start - timedelta(hours=sc.carry_over_hours)
    scored: list[tuple[float, float, datetime, str, StoryView, Evaluation]] = []
    rejected: list[dict[str, Any]] = []
    for s in stories:
        ev = evals.get(s.key)
        if ev is None or s.relevance == "out_of_scope":
            continue
        if not (open_from < s.last_activity <= end):
            continue
        mult = float(sc.verification_multiplier.get(ev.dim("verification_status"), 0.7))
        sel = round(ev.score * mult, 2)
        if sel < sc.min_selection_score:
            rejected.append({"story_key": s.key, "title": s.title, "selection_score": sel,
                             "reason": f"below quality threshold {sc.min_selection_score}"})
            continue
        scored.append((-sel, -ev.score, s.last_activity, s.key, s, ev))
    # Deterministic order: score desc, importance desc, newer first, key.
    scored.sort(key=lambda t: (t[0], t[1], -t[2].timestamp(), t[3]))
    picks: list[Pick] = []
    kept: list[StoryView] = []
    for neg_sel, _, _, _, s, ev in scored:
        dup = next((k for k in kept if _same_event(k, s, sc.duplicate_title_jaccard)), None)
        if dup is not None:
            rejected.append({"story_key": s.key, "title": s.title, "selection_score": -neg_sel,
                             "reason": f"same event as {dup.key}"})
            continue
        if len(picks) >= sc.size:
            rejected.append({"story_key": s.key, "title": s.title, "selection_score": -neg_sel,
                             "reason": "outside the top positions"})
            continue
        kept.append(s)
        picks.append(Pick(
            story_key=s.key, title=s.title, rank=len(picks) + 1, selection_score=-neg_sel,
            importance=ev.score, verification=ev.dim("verification_status"),
            confidence=ev.dim("confidence"), exploitation=ev.dim("exploitation_status"),
            why=_top_reasons(ev), sources=s.independent_sources,
        ))
    return day, picks, rejected


# ---------------------------------------------------------------- Trending

@dataclass
class TrendResult:
    story_key: str
    title: str
    trend_score: float
    signals: list[str]
    trending: bool

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def trending(
    stories: Sequence[StoryView],
    evals: Mapping[str, Evaluation],
    now: datetime,
    cfg: IntelConfig,
    previous: Mapping[str, Evaluation] | None = None,
) -> list[TrendResult]:
    tc = cfg.trending
    since = now - timedelta(hours=tc.window_hours)
    out: list[TrendResult] = []
    for s in stories:
        ev = evals.get(s.key)
        if ev is None or s.relevance == "out_of_scope" or s.last_activity <= since:
            continue
        fired: list[str] = []
        recent = [m for m in s.members if since < (m.published_at if m.published_at.tzinfo
                                                   else m.published_at.replace(tzinfo=timezone.utc))]
        if recent and len(s.members) > len(recent):
            fired.append("new_information")
        prev = (previous or {}).get(s.key)
        recent_sources = {m.source for m in recent} & set(s.independent_sources)
        if (ev.dim("exploitation_status") == "confirmed"
                and (prev is None or prev.dim("exploitation_status") != "confirmed")) or (
                len(s.independent_sources) >= 2 and recent_sources
                and len(recent_sources) < len(s.independent_sources)):
            fired.append("development")
        if len(s.independent_sources) >= 2:
            fired.append("corroboration")
        if ev.dim("exploitation_status") in ("confirmed", "reported"):
            fired.append("exploitation")
        if ev.raw.get("audience_relevance", 0.0) >= 0.75:
            fired.append("audience")
        if ev.score >= 60:
            fired.append("importance")
        score = round(sum(tc.weights.get(sig, 0.0) for sig in fired), 1)
        out.append(TrendResult(s.key, s.title, score, fired,
                               len(fired) >= tc.min_signals and score >= tc.min_score))
    out.sort(key=lambda r: (-int(r.trending), -r.trend_score, r.story_key))
    return out


# ---------------------------------------------------------------- Breaking

@dataclass
class BreakingDecision:
    story_key: str
    title: str
    qualifies: bool
    rules: list[str]
    evidence: list[str]
    evidence_fingerprint: str
    alert: str = "none"           # none | new | update | unchanged

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _cvss(story: StoryView) -> float:
    vals = [float(getattr(c, "score", 0) or 0) for s in story.sheets
            for c in getattr(s, "cvss_scores", []) or []]
    return max(vals, default=0.0)


def _level(story: StoryView) -> str:
    levels = [str(getattr(p, "threat_level", "")) for p in story.posts.values()]
    order = ["Low", "Medium", "High", "Critical"]
    return max(levels, key=lambda lv: order.index(lv) if lv in order else -1, default="")


def classify_breaking(story: StoryView, ev: Evaluation, table: SourceTable, cfg: IntelConfig,
                      now: datetime) -> BreakingDecision:
    bc = cfg.breaking
    text = story.text
    verification = ev.dim("verification_status")
    exploitation = ev.dim("exploitation_status")
    level = _level(story)
    cvss = _cvss(story)
    official = [s for s in story.independent_sources if table.get(s).is_official]
    confirmers = [s for s in story.independent_sources if table.reliability(s) >= bc.confirmer_min_reliability]
    kev = any("known-exploited-vulnerabilities catalogue" in r
              for r in ev.dimensions.get("exploitation_status", {}).get("reasons", []))
    event_types = {str(getattr(s, "event_type", "") or "") for s in story.sheets}
    rules: list[str] = []
    evidence: list[str] = []

    recent = story.last_activity > now - timedelta(hours=bc.window_hours)
    if recent and verification != "unverified" and story.relevance != "out_of_scope":
        if exploitation == "confirmed" and (cvss >= bc.critical_cvss or level == "Critical" or kev) and (
                official or len(confirmers) >= 2):
            rules.append("R1 critical_exploited")
            evidence.append(f"exploitation confirmed; CVSS {cvss or '—'}; level {level or '—'}; "
                            f"{'official: ' + ', '.join(official) if official else 'confirmers: ' + ', '.join(confirmers)}")
        if ("supply_chain" in event_types or _SUPPLY_CHAIN.search(text)) and verification == "verified":
            rules.append("R2 supply_chain")
            evidence.append("supply-chain compromise, verified")
        order = ["Low", "Medium", "High", "Critical"]
        if official and level in order and order.index(level) >= order.index(bc.government_warning_min_level) and (
                exploitation == "confirmed" or any(m.actionability_level == "urgent_action" for m in story.members)):
            rules.append("R3 official_warning")
            evidence.append(f"official warning from {', '.join(official)} at level {level}")
        if ("ransomware" in event_types or _RANSOM.search(story.anchor.title)) and ev.score >= bc.ransomware_min_importance:
            rules.append("R4 ransomware_incident")
            evidence.append(f"ransomware incident, {verification}, importance {ev.score:.0f}")
        low = text.lower()
        hit = [p for p in WIDELY_DEPLOYED if p in low]
        if hit and exploitation == "confirmed" and ev.score >= bc.infrastructure_min_importance:
            rules.append("R5 infrastructure")
            evidence.append(f"widely deployed: {', '.join(hit[:3])}")
    fp_blob = {"rules": sorted(rules), "exploitation": exploitation, "verification": verification,
               "sources": sorted(story.independent_sources), "cves": story.cves, "cvss": cvss}
    fp = hashlib.sha256(json.dumps(fp_blob, sort_keys=True).encode()).hexdigest()[:16]
    return BreakingDecision(story.key, story.title, bool(rules), rules, evidence, fp)


def apply_alert_state(decision: BreakingDecision, state: dict[str, Any], now: datetime) -> BreakingDecision:
    """Mutates `state` (story_key -> {alerted_at, evidence_fingerprint}); sets decision.alert."""
    if not decision.qualifies:
        decision.alert = "none"
        return decision
    prev = state.get(decision.story_key)
    if prev is None:
        decision.alert = "new"
    elif prev.get("evidence_fingerprint") == decision.evidence_fingerprint:
        decision.alert = "unchanged"
        return decision
    else:
        decision.alert = "update"
    state[decision.story_key] = {
        "alerted_at": now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "evidence_fingerprint": decision.evidence_fingerprint,
        "rules": decision.rules,
    }
    return decision


def breaking(stories: Iterable[StoryView], evals: Mapping[str, Evaluation], table: SourceTable,
             cfg: IntelConfig, now: datetime, state: dict[str, Any]) -> list[BreakingDecision]:
    out = []
    for s in stories:
        ev = evals.get(s.key)
        if ev is None:
            continue
        out.append(apply_alert_state(classify_breaking(s, ev, table, cfg, now), state, now))
    return [d for d in out if d.qualifies]


__all__ = ["BreakingDecision", "Pick", "TrendResult", "WIDELY_DEPLOYED", "apply_alert_state",
           "breaking", "classify_breaking", "daily_top", "edition_for", "trending"]
