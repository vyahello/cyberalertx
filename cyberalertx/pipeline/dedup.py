"""Cross-source story clustering.

The problem this solves
----------------------
`NewsItem.fingerprint` is `sha256(url)` — it identifies an *article*, not a
*story*. When BleepingComputer, The Hacker News and Krebs all report the same
SharePoint zero-day, we ingest three articles with three fingerprints and the
reader sees the same news three times in the feed and three times in the
Telegram channel.

This module assigns every item a `story_key`: a stable id shared by all
articles covering the same underlying story. The feed, the detail pool and
the publisher then show ONE canonical article per story and surface the rest
as corroboration ("Also reported by The Hacker News, Krebs on Security"),
which turns a duplicate into a trust signal.

Design constraints
------------------
1. **A false merge is much worse than a missed duplicate.** Collapsing two
   genuinely different advisories hides real news from the reader. Every
   threshold below is tuned to be conservative, and the veto rules exist
   specifically to make certain merges impossible rather than unlikely.
2. **Pure Python, no ML.** No embeddings, no vector store, no new dependency.
   Everything here is set arithmetic over tokens the pipeline already has.
3. **Pure functions.** `same_story()` and `cluster_items()` take data and
   return data. No I/O, no globals, so the whole thing is unit-testable and
   can run at ingest time, at read time, or in a backfill CLI unchanged.

The matching rules
------------------
Two articles are the same story when they pass the time window AND satisfy
one of the positive rules, AND trip none of the vetoes.

  TIME WINDOW
      Published within `_WINDOW_DAYS` of each other. Coverage of one event
      lands within a few days; two "Patch Tuesday" stories a month apart are
      different stories that happen to share a headline.

  VETO 1 — disjoint CVEs
      If BOTH articles name CVEs and share NONE of them, they are different
      stories no matter how similar the headlines read. This is what keeps
      the seven separate "CISA Adds One Known Exploited Vulnerability to
      Catalog" advisories — identical titles, different CVEs — from
      collapsing into one and silently deleting six real advisories.

  VETO 2 — one source, one headline, no CVE agreement
      Same source, byte-identical headline, and no positive CVE evidence
      linking them. A newsroom does not publish the same headline twice for
      the same story; advisory feeds, on the other hand, title entries after
      the affected product. CISA ships "Siemens SIMATIC" repeatedly, each
      time for a different advisory. Without this veto, the pair where only
      one entry happens to name a CVE slips past VETO 1 and merges.

  RULE A — identical CVE sets
      Both name exactly the same CVEs. The strongest signal available;
      no textual support required.

  RULE B — overlapping CVEs with textual support
      CVE Jaccard >= 0.5 AND a shared entity AND some title overlap.
      The support requirement is deliberate: a "CISA Adds Two Known
      Exploited Vulnerabilities to Catalog" roundup shares one CVE with a
      vendor story but names no shared entity, so it stays its own item —
      correct, because a KEV catalog addition really is separate news.
      Without this rule a multi-CVE roundup would act as a bridge and
      transitively merge every unrelated story it lists.

  RULE C — distinctive-title match
      No CVEs to compare, so fall back to text. Jaccard over *distinctive*
      tokens only, plus a shared named entity. Generic security vocabulary
      ("critical", "flaw", "exploited", "remote code execution") is stripped
      first — those words are what make two unrelated advisories look alike.
      With them removed, "JetBrains warns of critical TeamCity remote code
      execution flaw" and "Critical ServiceNow AI Platform Flaw Exploited for
      Unauthenticated Code Execution" share nothing and stay apart.

      Both headlines must also carry at least `_MIN_DISTINCTIVE_FOR_TEXT`
      distinctive tokens. A two-word title like "Siemens SIMATIC" names a
      product, not a story, and matching on it alone merges unrelated
      advisories. Real reporting headlines clear the bar easily — the
      narrowest true merge in the production corpus ("VMware fixes three
      critical flaws allowing auth bypass, VM escapes") retains three.

Known limits
------------
Precision is carried by CVE identifiers whenever both articles name one.
Where neither does, RULE C is a bet: two headlines that share this much
distinctive vocabulary within five days are the same story. That bet was
checked against 377 real stored articles (the 200-item live store plus a
177-item earlier snapshot) and produced no false merges, but it is a
heuristic and not a proof. Two outlets writing near-identical CVE-less
headlines about different vendors in the same week would merge incorrectly.

If that starts happening, the fix is inverse-document-frequency weighting —
score shared tokens by how rare they are across the batch, so "firmware"
counts for little and "vBulletin" counts for a lot — rather than more
hand-tuned thresholds. `cluster_items` already sees the whole batch, so the
statistics are available without new infrastructure.

Clustering strategy
-------------------
Single-link union-find would let one weak edge chain unrelated stories
together. Instead we use **anchor-based greedy assignment**: items are
processed in a deterministic order and each one either joins an existing
cluster by matching that cluster's anchor directly, or becomes a new anchor.
Membership is therefore always a direct pairwise decision against one
representative article — chains cannot form.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Iterable, Sequence

from ..models import NewsItem

# --------------------------------------------------------------------------
# Tuning knobs. These were calibrated against the live 200-item production
# store: every merge the defaults produce was inspected by hand, and the
# known false-positive pair (TeamCity RCE vs ServiceNow RCE — different
# products, near-identical generic phrasing) stays unmerged.
# --------------------------------------------------------------------------

#: Articles further apart than this are never the same story.
_WINDOW_DAYS = 5

#: RULE B — how much of the two CVE sets must coincide.
_CVE_JACCARD_MIN = 0.5

#: RULE C — primary threshold on distinctive-token Jaccard.
_TITLE_JACCARD_STRONG = 0.45
#: RULE C — relaxed threshold, allowed only with more shared tokens.
_TITLE_JACCARD_WEAK = 0.33
#: Shared distinctive tokens required at each threshold.
_MIN_SHARED_STRONG = 2
_MIN_SHARED_WEAK = 3
#: RULE B — minimum title overlap required to support a partial CVE match.
_TITLE_JACCARD_SUPPORT = 0.20
#: RULE C — a headline this short names a product, not a story. Advisory
#: feeds ("Siemens SIMATIC", "MikroTik RouterOS") sit below the bar; real
#: reporting headlines clear it.
_MIN_DISTINCTIVE_FOR_TEXT = 3

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[^\W_]+(?:[-.][^\W_]+)*", flags=re.UNICODE)

# Ordinary English/Ukrainian function words. Same list the ranker and the
# credibility analyzer use, kept local so this module has no cross-stage
# import and can be reasoned about on its own.
_STOPWORDS: frozenset[str] = frozenset({
    # English
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with",
    "is", "are", "was", "were", "be", "been", "by", "as", "at", "from",
    "that", "this", "it", "its", "new", "more", "than", "into", "after",
    "has", "have", "had", "over", "said", "says", "can", "could", "will",
    "would", "may", "might", "but", "not", "all", "how", "why", "what",
    "when", "who", "amid", "via", "out", "off", "up", "down", "now",
    # Ukrainian
    "та", "і", "й", "у", "в", "на", "до", "з", "із", "зі", "для", "про",
    "що", "як", "це", "цей", "ця", "які", "яка", "який", "від", "за",
    "по", "при", "не", "але", "його", "її", "їх", "був", "була", "було",
    "буде", "може", "можуть", "після", "під", "над", "через", "уже", "вже",
})

# Security vocabulary that appears in a large share of all headlines. These
# words carry almost no discriminating power — two completely unrelated
# advisories will both say "critical", "flaw" and "exploited" — so leaving
# them in inflates similarity and causes false merges. Stripped before the
# RULE C comparison.
_GENERIC_SECURITY_TERMS: frozenset[str] = frozenset({
    # English
    "critical", "high", "severe", "serious", "major", "important",
    "flaw", "flaws", "bug", "bugs", "vulnerability", "vulnerabilities",
    "vuln", "vulns", "issue", "issues", "hole", "holes", "weakness",
    "exploit", "exploits", "exploited", "exploiting", "exploitation",
    "attack", "attacks", "attacker", "attackers", "hacker", "hackers",
    "hacked", "hacking", "breach", "breached", "threat", "threats",
    "security", "cyber", "cybersecurity", "infosec",
    "patch", "patches", "patched", "patching", "fix", "fixes", "fixed",
    "update", "updates", "updated", "release", "released", "releases",
    "warn", "warns", "warning", "warned", "alert", "alerts", "advisory",
    "advisories", "disclose", "disclosed", "disclosure", "report",
    "reports", "reported", "reveal", "reveals", "revealed", "confirm",
    "confirms", "confirmed", "detail", "details", "found", "discover",
    "discovers", "discovered", "affect", "affects", "affected", "impact",
    "impacts", "impacted", "target", "targets", "targeted", "targeting",
    "allow", "allows", "allowing", "enable", "enables", "let", "lets",
    "use", "uses", "used", "using", "abuse", "abuses", "abused",
    "remote", "code", "execution", "rce", "unauthenticated", "auth",
    "authentication", "bypass", "privilege", "privileges", "escalation",
    "injection", "overflow", "traversal", "deserialization", "xss", "ssrf",
    "zero", "day", "zeroday", "0day", "poc", "cve", "cvss", "kev",
    "risk", "risks", "danger", "dangerous", "active", "actively",
    "public", "publicly", "million", "millions", "thousand", "thousands",
    "user", "users", "customer", "customers", "system", "systems",
    "server", "servers", "device", "devices", "account", "accounts",
    "data", "access", "malicious", "attacks", "campaign", "campaigns",
    "researcher", "researchers", "vendor", "vendors", "company",
    "companies", "firm", "firms", "team", "teams",
    # Ukrainian equivalents
    "критичн", "критична", "критичний", "вразливість", "вразливості",
    "вразливо", "експлойт", "експлуатація", "атака", "атаки", "атакують",
    "зловмисник", "зловмисники", "хакер", "хакери", "витік", "загроза",
    "загрози", "безпеки", "безпека", "кібербезпеки", "патч", "оновлення",
    "виправлення", "попереджає", "попередження", "повідомляє",
    "виявлено", "виявили", "дослідники", "користувачі", "користувачів",
    "система", "системи", "сервер", "сервери", "дані", "доступ",
})

# Tokens that look like entities but are too common to anchor a merge on.
_ENTITY_BLOCKLIST: frozenset[str] = frozenset({
    "the", "new", "cisa", "cert", "nvd", "mitre", "google", "microsoft",
    "apple", "linux", "windows", "android", "ios", "chrome", "firefox",
    "safari", "edge", "aws", "azure", "cloud", "web", "app", "apps",
    "software", "hardware", "internet", "online", "ai", "llm",
})


def _norm_token(tok: str) -> str:
    """Lowercase and strip a trailing English plural.

    Crude on purpose: "escapes"/"escape" and "flaws"/"flaw" must compare
    equal or a headline pair like "VM escapes" vs "VM escape" scores far
    lower than it should. We only strip a trailing "s" when the stem is
    still substantial and doesn't already end in "s"/"u", which avoids
    mangling "https", "sas", "ios", "cms".
    """
    t = tok.lower()
    if len(t) > 4 and t.endswith("s") and not t.endswith(("ss", "us", "is", "os")):
        return t[:-1]
    return t


def extract_cves(text: str) -> frozenset[str]:
    """Uppercased CVE ids found in `text`. Empty set when there are none."""
    return frozenset(m.group(0).upper() for m in _CVE_RE.finditer(text or ""))


def _title_tokens(title: str) -> set[str]:
    """All content tokens from a title (stopwords removed, plurals folded)."""
    return {
        _norm_token(t)
        for t in _TOKEN_RE.findall(title or "")
        if len(t) > 2 and t.lower() not in _STOPWORDS
    }


def _distinctive_tokens(title: str) -> set[str]:
    """Title tokens with generic security vocabulary removed.

    What's left is the part of a headline that actually identifies the
    story: product names, vendor names, malware families, actor names,
    version numbers.
    """
    return {t for t in _title_tokens(title) if t not in _GENERIC_SECURITY_TERMS}


def _entities(title: str) -> set[str]:
    """Tokens that plausibly name a specific product, vendor or malware family.

    Heuristic, and deliberately so: anything that survived the generic-term
    filter and either starts with a capital letter in the original headline
    or contains a digit/hyphen (version strings, "wp2shell", "CVE-like"
    product codes). Ukrainian headlines rarely capitalize products, so we
    also accept any surviving distinctive token of length >= 5 — Ukrainian
    coverage is low-volume and the time window plus title threshold carry
    the safety there.
    """
    found: set[str] = set()
    for raw in _TOKEN_RE.findall(title or ""):
        norm = _norm_token(raw)
        if len(raw) <= 2:
            continue
        if norm in _STOPWORDS or norm in _GENERIC_SECURITY_TERMS:
            continue
        if norm in _ENTITY_BLOCKLIST:
            continue
        looks_like_entity = (
            raw[0].isupper()
            or any(ch.isdigit() for ch in raw)
            or "-" in raw
            or "." in raw
            or len(raw) >= 5
        )
        if looks_like_entity:
            found.add(norm)
    return found


def _jaccard(a: set[str] | frozenset[str], b: set[str] | frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True)
class StoryFeatures:
    """Everything `same_story` needs about one article, computed once.

    Building these up front turns clustering from O(n^2) tokenizations into
    O(n) tokenizations plus O(n^2) cheap set intersections.
    """

    fingerprint: str
    source: str
    title: str
    published_at: object  # datetime; typed loosely to keep the dataclass import-light
    cves: frozenset[str]
    distinctive: frozenset[str]
    entities: frozenset[str]

    @classmethod
    def from_item(cls, item: NewsItem) -> "StoryFeatures":
        # Scan the whole body for CVE ids, not just the lede. Every CVE we
        # find is a chance for VETO 1 to keep two advisories apart, and
        # `normalize.clean_article_body` already caps bodies at 3000 chars
        # so "whole body" is bounded. Measured on the production corpus:
        # scanning past the lede is what gives the second "ABB Symphony
        # Plus" advisory its own CVE, which is what stops it merging into
        # the first one.
        cve_text = f"{item.title}\n{item.raw_content or ''}"
        return cls(
            fingerprint=item.fingerprint,
            source=item.source,
            title=item.title,
            published_at=item.published_at,
            cves=extract_cves(cve_text),
            distinctive=frozenset(_distinctive_tokens(item.title)),
            entities=frozenset(_entities(item.title)),
        )


def _within_window(a: StoryFeatures, b: StoryFeatures, *, days: int) -> bool:
    try:
        delta = abs(a.published_at - b.published_at)  # type: ignore[operator]
    except TypeError:  # pragma: no cover - defensive against naive/aware mix
        return False
    return bool(delta <= timedelta(days=days))


def same_story(
    a: StoryFeatures,
    b: StoryFeatures,
    *,
    window_days: int = _WINDOW_DAYS,
) -> bool:
    """Pairwise "are these the same underlying story?" decision.

    Pure and symmetric: `same_story(a, b) == same_story(b, a)`. See the
    module docstring for the rule table and the reasoning behind each
    threshold.
    """
    if a.fingerprint == b.fingerprint:
        return True
    if not _within_window(a, b, days=window_days):
        return False

    both_have_cves = bool(a.cves) and bool(b.cves)
    shared_cves = a.cves & b.cves

    # VETO 1 — both name CVEs and none coincide. Different advisories.
    if both_have_cves and not shared_cves:
        return False

    # RULE A — identical CVE sets.
    if both_have_cves and a.cves == b.cves:
        return True

    shared_entities = a.entities & b.entities
    title_j = _jaccard(a.distinctive, b.distinctive)

    # RULE B — partial CVE overlap, but only with textual support so that a
    # multi-CVE roundup can't bridge unrelated stories.
    if both_have_cves and _jaccard(a.cves, b.cves) >= _CVE_JACCARD_MIN:
        if shared_entities and title_j >= _TITLE_JACCARD_SUPPORT:
            return True

    # VETO 2 — same source republishing one headline, with no CVE agreement
    # to vouch for the match. Product-named advisory entries, not one story.
    if a.source == b.source and a.title.strip().lower() == b.title.strip().lower():
        return False

    # RULE C — text-only match. Always requires a shared named entity, so
    # two stories must at minimum be about the same product or actor.
    if not shared_entities:
        return False
    if (
        len(a.distinctive) < _MIN_DISTINCTIVE_FOR_TEXT
        or len(b.distinctive) < _MIN_DISTINCTIVE_FOR_TEXT
    ):
        return False
    shared_tokens = len(a.distinctive & b.distinctive)
    if title_j >= _TITLE_JACCARD_STRONG and shared_tokens >= _MIN_SHARED_STRONG:
        return True
    if title_j >= _TITLE_JACCARD_WEAK and shared_tokens >= _MIN_SHARED_WEAK:
        return True
    return False


@dataclass
class StoryCluster:
    """One real-world story and every article we have about it."""

    key: str
    anchor: StoryFeatures
    members: list[StoryFeatures] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        """Distinct source names in first-seen order."""
        seen: list[str] = []
        for m in self.members:
            if m.source not in seen:
                seen.append(m.source)
        return seen


def story_key_for(anchor: StoryFeatures) -> str:
    """Stable cluster id derived from the anchor article.

    Deriving it from the anchor's fingerprint (rather than from the token
    set) keeps the key stable across runs even as new members join and the
    shared vocabulary shifts. The `s:` prefix makes a story key visually
    distinguishable from a fingerprint in logs and stored JSON.
    """
    return "s:" + hashlib.sha256(anchor.fingerprint.encode("utf-8")).hexdigest()[:14]


def cluster_items(
    items: Sequence[NewsItem],
    *,
    window_days: int = _WINDOW_DAYS,
) -> list[StoryCluster]:
    """Group articles into stories using anchor-based greedy assignment.

    Ordering is deterministic — newest first, then fingerprint — so the same
    input always produces the same clusters and the same anchors, which is
    what makes `story_key` stable between pipeline runs.

    Each item is compared against existing cluster ANCHORS only, never
    against arbitrary members. That is what prevents transitive chaining:
    every membership decision is one direct pairwise comparison.
    """
    feats = [StoryFeatures.from_item(i) for i in items]
    feats.sort(key=lambda f: (f.published_at, f.fingerprint), reverse=True)

    clusters: list[StoryCluster] = []
    for f in feats:
        for cluster in clusters:
            if same_story(cluster.anchor, f, window_days=window_days):
                cluster.members.append(f)
                break
        else:
            clusters.append(
                StoryCluster(key=story_key_for(f), anchor=f, members=[f]),
            )
    return clusters


# --------------------------------------------------------------------------
# Canonical selection
# --------------------------------------------------------------------------

# Headlines that describe a bureaucratic action rather than the story.
# CISA's KEV catalog posts are the live example: "CISA Adds One Known
# Exploited Vulnerability to Catalog" is authoritative but tells a reader
# nothing about what was actually found. When such an item clusters with
# real reporting ("Cisco warns of FMC static credential flaw exploited in
# zero-day attacks"), the reporting headline must win — otherwise raw source
# credibility hands the feed its least informative title.
_INDEX_HEADLINE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\badds?\b.*\bto\b.*\bcatalog\b", re.IGNORECASE),
    re.compile(r"\bknown exploited vulnerabilit(?:y|ies)\b", re.IGNORECASE),
    re.compile(r"\b(?:weekly|monthly)\s+(?:recap|roundup|summary)\b", re.IGNORECASE),
)

#: Headline quality tiers used to rank canonical candidates.
_HEADLINE_INDEX = 0     # bureaucratic index entry — worst canonical
_HEADLINE_TERSE = 1     # bare product name ("Siemens SIMATIC")
_HEADLINE_NORMAL = 2    # ordinary reporting headline


def headline_quality(title: str) -> int:
    """How well a headline stands on its own as the face of a story.

    Used only for canonical selection — it never affects whether two
    articles match.
    """
    if any(rx.search(title or "") for rx in _INDEX_HEADLINE_RES):
        return _HEADLINE_INDEX
    if len(_distinctive_tokens(title)) < _MIN_DISTINCTIVE_FOR_TEXT:
        return _HEADLINE_TERSE
    return _HEADLINE_NORMAL


def choose_canonical(
    members: Sequence[NewsItem],
    *,
    prefer: Callable[[NewsItem], bool] | None = None,
) -> NewsItem:
    """Pick the article that represents a story to the reader.

    Ranking, highest priority first:
      1. `prefer(item)` is True. The API passes "already has an AI render in
         this locale" here — showing a story we can actually render beats
         showing the theoretically-best source as an empty card.
      2. A headline that tells the story. A KEV-catalog entry is the most
         authoritative item in its cluster and simultaneously the worst one
         to show a reader, so this outranks credibility deliberately.
      3. Higher source credibility. A CISA advisory outranks an aggregator.
      4. Most recent publication. A story develops — "flaw disclosed"
         becomes "flaw now exploited in the wild" three days later. The
         latest article carries the current state of the story, which beats
         giving the scoop credit and showing the reader stale news.
      5. Longer body. More source material means a better brief, and it's a
         decent proxy for original reporting over a two-paragraph rewrite.
      6. Fingerprint, purely so the result is deterministic.
    """
    if not members:
        raise ValueError("choose_canonical() needs at least one member")

    def sort_key(item: NewsItem) -> tuple[int, int, float, float, int, str]:
        return (
            1 if (prefer is not None and prefer(item)) else 0,
            headline_quality(item.title),
            round(float(item.source_credibility_score), 3),
            item.published_at.timestamp(),
            len(item.raw_content or ""),
            item.fingerprint,
        )

    return max(members, key=sort_key)


def assign_story_keys(
    items: Sequence[NewsItem],
    *,
    window_days: int = _WINDOW_DAYS,
) -> list[StoryCluster]:
    """Cluster `items` and write `story_key` / `duplicate_of` back onto them.

    The canonical member gets `duplicate_of = ""` (it is not a duplicate of
    anything); every other member points at the canonical's fingerprint.
    Both fields are also written on singleton clusters so that every item in
    the store carries a story key and downstream code never has to special-
    case "not yet clustered".

    Returns the clusters so callers can log or report on what merged.
    """
    by_fp = {i.fingerprint: i for i in items}
    clusters = cluster_items(items, window_days=window_days)
    for cluster in clusters:
        member_items = [by_fp[m.fingerprint] for m in cluster.members if m.fingerprint in by_fp]
        if not member_items:
            continue
        canonical = choose_canonical(member_items)
        for item in member_items:
            item.story_key = cluster.key
            item.duplicate_of = (
                "" if item.fingerprint == canonical.fingerprint else canonical.fingerprint
            )
    return clusters


def assign_incremental(
    new_items: Sequence[NewsItem],
    known_items: Sequence[NewsItem],
    *,
    window_days: int = _WINDOW_DAYS,
) -> list[NewsItem]:
    """Assign story keys to a fresh batch without disturbing stored items.

    This is the pipeline's entry point. Coverage of one story arrives across
    several ingest cycles — BleepingComputer at 09:00, The Hacker News at
    11:30 — so a fresh item has to be matched against what is already in the
    store, not just against its own batch.

    Re-running the full `assign_story_keys` over everything would work but
    would let a newly-arrived article re-anchor an existing cluster and
    change its `story_key`, breaking any reference already handed out. Here
    each existing story keeps its key, and a new item either joins one or
    starts its own.

    New items are matched against each known story's canonical article only,
    which preserves the no-transitive-chaining property.

    An item joining a story we already have is ALWAYS marked a duplicate,
    even when its headline or recency would win `choose_canonical`. The
    stored `duplicate_of` drives cost and broadcast decisions — "we have
    already rendered and published this story, don't do it again" — and
    first-seen-wins is the only rule that keeps those idempotent. Picking
    the nicest member to actually display is a separate, read-time decision
    made by `collapse_duplicates`, which is free to prefer the newer article.

    Returns the subset of `new_items` that were identified as duplicates of
    something (either stored or elsewhere in the same batch).
    """
    # Group what we already have by story, so each known story is
    # represented by exactly one article for matching purposes.
    groups: dict[str, list[NewsItem]] = {}
    for item in known_items:
        key = item.story_key or f"fp:{item.fingerprint}"
        groups.setdefault(key, []).append(item)

    known_anchors: list[tuple[str, StoryFeatures]] = []
    for key, members in groups.items():
        canonical = choose_canonical(members)
        known_anchors.append((key, StoryFeatures.from_item(canonical)))

    # Newest first so the batch's own anchors are chosen the same way
    # `cluster_items` would choose them.
    ordered = sorted(new_items, key=lambda i: (i.published_at, i.fingerprint), reverse=True)

    batch_anchors: list[tuple[str, StoryFeatures, NewsItem]] = []
    duplicates: list[NewsItem] = []

    for item in ordered:
        feats = StoryFeatures.from_item(item)

        # 1. Does it belong to a story we already know about? If so it is
        #    later coverage of something we have already handled.
        for key, anchor in known_anchors:
            if same_story(anchor, feats, window_days=window_days):
                item.story_key = key
                item.duplicate_of = choose_canonical(groups[key]).fingerprint
                groups[key].append(item)
                duplicates.append(item)
                break
        else:
            # 2. Does it belong to a story earlier in this same batch?
            for key, anchor, anchor_item in batch_anchors:
                if same_story(anchor, feats, window_days=window_days):
                    item.story_key = key
                    item.duplicate_of = anchor_item.fingerprint
                    duplicates.append(item)
                    break
            else:
                # 3. New story.
                item.story_key = story_key_for(feats)
                item.duplicate_of = ""
                batch_anchors.append((item.story_key, feats, item))

    return duplicates


def collapse_duplicates(
    items: Iterable[NewsItem],
    *,
    prefer: Callable[[NewsItem], bool] | None = None,
) -> tuple[list[NewsItem], dict[str, list[str]]]:
    """Read-time collapse: one item per story, plus who else reported it.

    Returns `(canonical_items, extra_sources_by_fingerprint)` where the map
    holds, for each surviving item, the names of the OTHER sources that
    covered the same story. Input order is preserved among survivors so
    callers keep whatever sort they applied.

    This is the defensive half of the design. `assign_story_keys` runs at
    ingest and is the cheap path; this function re-derives grouping from the
    stored `story_key` at read time so that items ingested before the
    feature existed — or ingested in separate cycles that never saw each
    other — still collapse correctly in the feed.

    Items without a `story_key` are treated as their own story, so a store
    that predates clustering degrades to today's behavior rather than
    collapsing everything into one bucket.
    """
    items = list(items)
    groups: dict[str, list[NewsItem]] = {}
    order: list[str] = []
    for item in items:
        key = getattr(item, "story_key", "") or f"fp:{item.fingerprint}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    survivors: list[NewsItem] = []
    extra_sources: dict[str, list[str]] = {}
    for key in order:
        members = groups[key]
        if len(members) == 1:
            # Nothing to choose between, so don't invoke `prefer` at all.
            # This matters more than it looks: `prefer` is backed by the AI
            # cache, which is a network round-trip against Postgres. Running
            # it over every item turned one feed request into hundreds of
            # queries. The overwhelming majority of stories are single-source,
            # so skipping them here removes almost all of that cost.
            survivors.append(members[0])
            continue
        canonical = choose_canonical(members, prefer=prefer)
        survivors.append(canonical)
        others: list[str] = []
        for m in members:
            if m.fingerprint == canonical.fingerprint:
                continue
            if m.source != canonical.source and m.source not in others:
                others.append(m.source)
        if others:
            extra_sources[canonical.fingerprint] = others

    # Restore the caller's ordering.
    rank = {i.fingerprint: n for n, i in enumerate(items)}
    survivors.sort(key=lambda i: rank.get(i.fingerprint, 0))
    return survivors, extra_sources


__all__ = [
    "StoryFeatures",
    "StoryCluster",
    "same_story",
    "cluster_items",
    "assign_story_keys",
    "collapse_duplicates",
    "choose_canonical",
    "story_key_for",
    "extract_cves",
]
