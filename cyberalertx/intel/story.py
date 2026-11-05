"""Stories as the intelligence layer sees them.

A story is a cluster from `pipeline.dedup.cluster_items` — the same
clustering the feed already uses; this module does not cluster again. It
joins each cluster with what the rest of the system already knows about its
articles: fact sheets (`ai.fact_sheet`), AI renders (`ai.cache`), relevance
(`pipeline.relevance`), and computes which sources are INDEPENDENT.

Independence: several outlets repeating one original report are one origin.
When `pipeline.dedup.independent_sources` exists it is authoritative; the
fallback here collapses (a) identical article bodies and (b) an article whose
text attributes the story to another outlet in the same cluster
("according to BleepingComputer", "як повідомляє dev.ua").
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from ..models import NewsItem
from ..pipeline import dedup

_ATTRIBUTION = (
    r"(?:according to|reported by|as reported by|first reported by|via|citing|"
    r"за даними|як повідомляє|як повідомило|повідомляє|з посиланням на)\s+(?:the\s+)?{src}"
)


@dataclass
class StoryView:
    key: str
    anchor: NewsItem
    members: list[NewsItem]
    independent_sources: list[str]
    relevance: str = "in_scope"
    sheets: list[Any] = field(default_factory=list)        # ai.fact_sheet.FactSheet
    posts: dict[str, Any] = field(default_factory=dict)    # locale -> ThreatPost
    decisions: list[dict[str, Any]] = field(default_factory=list)
    #: `ai.fact_sheet.cluster_evidence` over the members' sheets — the one
    #: merged, syndication-aware reading of the story's evidence.
    evidence: Any = None

    @property
    def sources(self) -> list[str]:
        seen: list[str] = []
        for m in self.members:
            if m.source not in seen:
                seen.append(m.source)
        return seen

    @property
    def first_seen(self) -> datetime:
        return min(_aware(m.published_at) for m in self.members)

    @property
    def last_activity(self) -> datetime:
        return max(_aware(m.published_at) for m in self.members)

    @property
    def title(self) -> str:
        post = self.posts.get("en") or self.posts.get("ua")
        return str(getattr(post, "title", "") or self.anchor.title)

    @property
    def text(self) -> str:
        return "\n".join(f"{m.title}\n{m.raw_content or ''}" for m in self.members)

    @property
    def cves(self) -> list[str]:
        found: set[str] = set()
        for m in self.members:
            found |= dedup.extract_cves(f"{m.title} {m.raw_content or ''}")
        for s in self.sheets:
            found |= {c.upper() for c in getattr(s, "cve_ids", []) or []}
        return sorted(found)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fallback_independent(members: Sequence[NewsItem]) -> list[str]:
    """Distinct origins: identical bodies collapse; attributed copies collapse."""
    names = {m.source for m in members}
    origin: dict[str, str] = {}
    digests: dict[str, str] = {}
    for m in sorted(members, key=lambda x: (_aware(x.published_at), x.source)):
        digest = dedup._body_digest(m.raw_content)  # noqa: SLF001 — same identity rule as clustering
        if digest and digest in digests and digests[digest] != m.source:
            origin[m.source] = digests[digest]
            continue
        if digest:
            digests.setdefault(digest, m.source)
        text = f"{m.title} {m.raw_content or ''}"
        for other in names - {m.source}:
            if re.search(_ATTRIBUTION.format(src=re.escape(other)), text, flags=re.IGNORECASE):
                origin[m.source] = other
                break
    out: list[str] = []
    for m in members:
        root = m.source
        hops = 0
        while root in origin and hops < 5:
            root, hops = origin[root], hops + 1
        if root not in out:
            out.append(root)
    return out


def _independent(cluster: Any, members: Sequence[NewsItem]) -> list[str]:
    fn = getattr(dedup, "independent_sources", None)
    if callable(fn):
        try:
            got = fn(cluster)
            if got:
                return [str(x) for x in got]
        except Exception:  # pragma: no cover — fall back rather than fail scoring
            pass
    return _fallback_independent(members)


def _relevance(item: NewsItem) -> str:
    try:
        from ..pipeline.relevance import effective_relevance
    except ImportError:
        return str(getattr(item, "relevance_override", "") or getattr(item, "relevance_status", "")
                   or "in_scope")
    return str(effective_relevance(item))


def stable_key(cluster_key: str, members: Sequence[NewsItem], used: set[str]) -> str:
    """The story's durable identity.

    `cluster_items` anchors a cluster on its NEWEST article, so its key moves
    every time newer coverage joins. Ingest (`dedup.assign_incremental`)
    assigns `story_key` first-seen-wins and never moves it — that is the key
    publication jobs, score history, Breaking state and illustrations must
    hang on, or a story re-keys and gets scored, alerted, illustrated and
    posted again. Use the stored key the members agree on (most common; ties →
    the oldest member's), unless another story in this run already took it,
    in which case fall back to the cluster key so keys stay unique."""
    counts: dict[str, int] = {}
    for m in members:
        if getattr(m, "story_key", ""):
            counts[m.story_key] = counts.get(m.story_key, 0) + 1
    if counts:
        oldest = sorted(members, key=lambda m: (m.published_at, m.fingerprint))
        order = {m.story_key: i for i, m in reversed(list(enumerate(oldest))) if m.story_key}
        best = max(counts, key=lambda k: (counts[k], -order.get(k, 0)))
        if best not in used:
            return best
    if cluster_key not in used:
        return cluster_key
    # The fallback is taken too (another story's stored key can equal this
    # cluster's key): derive a deterministic key from the members, never a
    # duplicate. Two stories sharing a key share jobs and the illustration.
    digest = hashlib.sha1("|".join(sorted(m.fingerprint for m in members)).encode()).hexdigest()
    n = 0
    while True:
        key = f"s:{hashlib.sha1(f'{digest}:{n}'.encode()).hexdigest()[:14]}"
        if key not in used:
            return key
        n += 1


def build_stories(
    items: Iterable[NewsItem],
    *,
    sheets: Any = None,          # ai.fact_sheet.FactSheetCache | None
    posts: Any = None,           # ai.cache.ThreatPostCache-like | None
) -> list[StoryView]:
    by_fp = {i.fingerprint: i for i in items}
    out: list[StoryView] = []
    used: set[str] = set()
    for cluster in dedup.cluster_items(list(by_fp.values())):
        members = [by_fp[f.fingerprint] for f in cluster.members if f.fingerprint in by_fp]
        if not members:
            continue
        anchor = by_fp.get(cluster.anchor.fingerprint, members[0])
        key = stable_key(cluster.key, members, used)
        used.add(key)
        story = StoryView(
            key=key,
            anchor=anchor,
            members=members,
            independent_sources=_independent(cluster, members),
            decisions=[_decision_dict(d) for d in getattr(cluster, "decisions", []) or []],
        )
        # A story is in scope when any member is; out of scope only when all are.
        statuses = {_relevance(m) for m in members}
        story.relevance = ("in_scope" if "in_scope" in statuses
                           else "needs_review" if "needs_review" in statuses else "out_of_scope")
        if sheets is not None:
            by_member: dict[str, Any] = {}
            for m in members:
                entry = sheets.get(m.fingerprint)
                sheet = getattr(entry, "sheet", None)
                if sheet is not None:
                    story.sheets.append(sheet)
                    by_member[m.fingerprint] = sheet
            if by_member:
                from ..ai.fact_sheet import cluster_evidence
                story.evidence = cluster_evidence(members, by_member)
        if posts is not None:
            for locale in ("en", "ua"):
                for m in [anchor, *members]:
                    post = posts.get(m.fingerprint, locale)
                    if post is not None:
                        story.posts[locale] = post
                        break
        out.append(story)
    return out


def _decision_dict(d: Any) -> dict[str, Any]:
    if isinstance(d, Mapping):
        return dict(d)
    return {k: getattr(d, k) for k in ("fingerprint", "anchor", "rule", "confidence", "reason")
            if hasattr(d, k)}


__all__ = ["StoryView", "build_stories"]
