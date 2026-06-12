"""Hybrid cybersecurity relevance filter.

Two-stage pipeline:

    NewsItem
      │
      ├─ deterministic score (keywords.py weighted scoring)
      │
      ├─ score < REJECT_FLOOR        → REJECT (no AI cost — obvious junk)
      ├─ score >= ACCEPT_CEILING     → ACCEPT (no AI cost — obvious cyber)
      └─ REJECT_FLOOR ≤ score < ACCEPT_CEILING
                                     → AI VALIDATION
                                         ├─ is_relevant=True  → ACCEPT
                                         └─ is_relevant=False → REJECT

Why two stages:

  * The deterministic layer is free and fast. It rejects the long tail of
    clean-tech / business / war / sports false-positives with a hard floor,
    and waves through unambiguous cyber stories (multiple strong tokens)
    without paying for an API call.

  * The AI layer judges the gray zone — items with weak / mixed signal
    that humans would need to read carefully. Examples: an "AI cybersecurity
    startup raises $5M" article (mentions cybersecurity, but is funding
    news), or a generic "Apple releases iOS 19.4" piece that may or may
    not include a security patch.

  * AI decisions are cached on disk by fingerprint. The same article is
    classified once across the lifetime of the cache file — re-runs of
    the pipeline don't re-pay for it.

Cost model (typical cycle of 215 fetched items):
  * ~50% rejected by rules cheaply (score < REJECT_FLOOR)
  * ~30% accepted by rules cheaply (score >= ACCEPT_CEILING)
  * ~20% sent to Haiku — ≈40 API calls per cycle, dominated by cache hits
    on subsequent cycles. First cycle: 40 calls. Steady state: 0–5 calls
    for new items only.

External dependencies:
  * Anthropic SDK is OPTIONAL. When missing, the AI classifier is None
    and `filter_relevant_hybrid` degrades to deterministic-only — which is
    exactly the legacy behavior, so this is safe.
  * `anthropic` is *imported lazily* inside `AIRelevanceClassifier.classify`
    so importing this module from a fresh checkout always works.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from ..models import NewsItem
from .filter import _REJECTED_LANGUAGES, relevance_score

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Score bands. Calibrated against the test corpus (`tests/test_relevance_filter.py`).
#
#   REJECT_FLOOR  — below this, an item is so off-topic the AI would only
#                   confirm what the score already said. Saves API spend.
#   ACCEPT_CEILING — at this score, the item has multiple strong cyber tokens
#                   (e.g. "phishing" + "credential theft"). No AI needed.
# --------------------------------------------------------------------------
REJECT_FLOOR: int = 1
ACCEPT_CEILING: int = 5

# Threshold for the deterministic-only fallback (used when AI is disabled
# or fails). Matches the pre-hybrid behavior from filter.is_relevant().
DETERMINISTIC_THRESHOLD: int = 3


# =========================================================================
# Decision + stats records
# =========================================================================

@dataclass(frozen=True)
class RelevanceDecision:
    """The hybrid filter's verdict on one item.

    `source` traces which path made the call so we can debug false
    positives/negatives without re-running the pipeline:
       "rules-reject"  - dropped by deterministic floor
       "rules-accept"  - waved through by deterministic ceiling
       "ai-accept"     - AI said relevant (fresh call)
       "ai-reject"     - AI said NOT relevant (fresh call)
       "ai-cached"     - AI verdict served from cache
       "ai-error"      - AI raised; fell back to deterministic threshold
       "ai-disabled"   - AI off; fell back to deterministic threshold
       "language"      - rejected by language gate before anything else
    """
    is_relevant: bool
    score: int
    source: str
    confidence: float = 0.0
    category: Optional[str] = None
    threat_type: Optional[str] = None
    affected_audience: list[str] = field(default_factory=list)


@dataclass
class FilterStats:
    """Per-batch counters surfaced by the orchestrator. Cheap to log."""
    fetched: int = 0
    language_rejected: int = 0
    rules_rejected: int = 0
    rules_accepted: int = 0
    ai_validated: int = 0
    ai_rejected: int = 0
    ai_accepted: int = 0
    ai_cache_hits: int = 0
    ai_errors: int = 0

    def as_log_string(self) -> str:
        # Compact line for the orchestrator's `cycle complete` log message.
        return (
            f"fetched={self.fetched} lang_rej={self.language_rejected} "
            f"rules_rej={self.rules_rejected} rules_acc={self.rules_accepted} "
            f"ai_validated={self.ai_validated} (cache_hits={self.ai_cache_hits} "
            f"errors={self.ai_errors}) ai_acc={self.ai_accepted} ai_rej={self.ai_rejected}"
        )


# =========================================================================
# Cache — JSON file, atomic writes, thread-safe.
# =========================================================================

class RelevanceCache:
    """Per-fingerprint cache of AI relevance decisions.

    File format: `{fingerprint: {is_relevant, confidence, category, ...}, ...}`
    Atomic writes via tempfile + os.replace so a crash mid-save never
    corrupts the file. A single in-process lock guards concurrent writes
    in a multi-thread server; the file itself is the source of truth, so
    multi-process workers stay coherent via reload-on-read.
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                return raw
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("relevance cache load failed (%s); starting fresh", exc)
        return {}

    def get(self, fingerprint: str) -> Optional[RelevanceDecision]:
        entry = self._data.get(fingerprint)
        if not entry:
            return None
        try:
            return RelevanceDecision(
                is_relevant=bool(entry.get("is_relevant", False)),
                score=int(entry.get("score", 0)),
                source="ai-cached",
                confidence=float(entry.get("confidence", 0.0)),
                category=entry.get("category"),
                threat_type=entry.get("threat_type"),
                affected_audience=list(entry.get("affected_audience") or []),
            )
        except (TypeError, ValueError) as exc:
            logger.warning("malformed cache entry for %s: %s", fingerprint, exc)
            return None

    def set(self, fingerprint: str, decision: RelevanceDecision) -> None:
        # Strip the dynamic "source" field — it describes how *this* call
        # was made, not a property of the article. On re-read it's always
        # "ai-cached".
        payload = asdict(decision)
        payload.pop("source", None)
        with self._lock:
            self._data[fingerprint] = payload
            self._flush()

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a sibling temp file, then atomic-rename. Survives crashes.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False,
            dir=str(self._path.parent), prefix=".relevance_cache.", suffix=".tmp",
        ) as tmp:
            json.dump(self._data, tmp, ensure_ascii=False, indent=2)
            tmp_name = tmp.name
        os.replace(tmp_name, self._path)

    def __len__(self) -> int:
        return len(self._data)


# =========================================================================
# AI classifier — Anthropic Haiku, structured JSON.
# =========================================================================

_RELEVANT_CATEGORIES = (
    "phishing", "ransomware", "malware", "spyware",
    "vulnerability", "exploit", "zero-day",
    "breach", "data leak", "scam", "botnet",
    "social engineering",
)

_AUDIENCES = (
    "normal_users", "developers", "sysadmins",
    "enterprise", "mobile_users", "crypto_users",
)

# System prompt is stable across calls → prompt-cacheable.
_SYSTEM_PROMPT = """\
You are a cybersecurity content classifier for CyberAlertX, a threat-intelligence
feed. Decide whether an article is a REAL cybersecurity threat or incident that
readers (everyday users, developers, IT pros, enterprises) should act on or be
aware of.

ACCEPT articles about: phishing, scams, malware, ransomware, credential theft,
data breaches, exploits, vulnerabilities, zero-days, spyware, social
engineering, account compromise, malicious extensions/apps, cyberattacks on
infrastructure or enterprises, crypto theft, banking fraud with cyber angle,
state-actor or APT activity, malicious AI abuse (deepfakes used to defraud,
LLM-assisted exploit generation, etc.).

REJECT articles about:
  - generic technology / product announcements with no security angle
  - AI product launches, model releases, AI hype with no threat content
  - startup funding / acquisitions / IPOs / business announcements
  - renewable energy, electric vehicles, transportation
  - hardware launches, gadget reviews, benchmarks
  - cloud-service pricing, partnerships, integrations
  - generic software updates that ship features (not security fixes)
  - science news, space, climate
  - sports, entertainment, lifestyle
  - war / military / political news (even when state-actor cyber is adjacent
    — reject unless the article's primary subject is the cyber operation)

When uncertain, lean toward REJECT — false positives erode reader trust.

Return ONLY a JSON object matching this schema:

{
  "is_relevant": true|false,
  "confidence": 0.0..1.0,
  "category": one of [phishing, ransomware, malware, spyware, vulnerability,
                      exploit, zero-day, breach, data leak, scam, botnet,
                      social engineering] or null,
  "threat_type": short noun phrase describing the specific threat, or null,
  "affected_audience": list of any of [normal_users, developers, sysadmins,
                                       enterprise, mobile_users, crypto_users]
}

No prose around the JSON. No code fence.
"""


@dataclass(frozen=True)
class _AIVerdict:
    is_relevant: bool
    confidence: float
    category: Optional[str]
    threat_type: Optional[str]
    affected_audience: list[str]


class AIRelevanceClassifier:
    """Anthropic-backed relevance classifier.

    Lazy-imports `anthropic` so this module is safe to import without the
    SDK installed. If the SDK is missing or the API key is unset, you'll
    get a clear RuntimeError on construction — wire it accordingly.

    Decisions are deterministic per article (Haiku at temperature=0) and
    cached on disk; same fingerprint always returns the same verdict.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 220,
        max_retries: int = 2,
        timeout: float = 12.0,
    ) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "anthropic SDK required for AIRelevanceClassifier. "
                "pip install anthropic — or run without "
                "CYBERALERTX_AI_RELEVANCE to stay deterministic-only."
            ) from exc
        self._anthropic = __import__("anthropic")
        self._client = self._anthropic.Anthropic(
            api_key=api_key, max_retries=max_retries, timeout=timeout,
        )
        self._model = model
        self._max_tokens = max_tokens
        self.name = f"anthropic:{model}"

    def classify(self, item: NewsItem) -> _AIVerdict:
        """Send the item to Haiku. Returns the parsed verdict.

        Raises on:
          * network/auth errors (caller catches → falls back to deterministic)
          * malformed JSON (caller catches → falls back to deterministic)
        """
        user_prompt = self._build_user_prompt(item)
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=0.0,
            system=[
                # Cacheable — same string every call.
                {"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}},
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = self._extract_text(response)
        verdict = self._parse_verdict(text)
        return verdict

    @staticmethod
    def _build_user_prompt(item: NewsItem) -> str:
        # Keep the prompt compact — Haiku is fast but tokens still cost.
        body = (item.raw_content or "")[:1200]
        return (
            f"SOURCE: {item.source}\n"
            f"LANGUAGE: {item.language}\n"
            f"TITLE: {item.title}\n\n"
            f"BODY:\n{body}\n\n"
            "Classify."
        )

    @staticmethod
    def _extract_text(response: Any) -> str:
        # The SDK's `messages.create` returns a Message; concatenate all
        # text blocks. Robust against a future shape change.
        blocks = getattr(response, "content", None) or []
        out: list[str] = []
        for block in blocks:
            text = getattr(block, "text", None)
            if text:
                out.append(text)
        return "".join(out).strip()

    @staticmethod
    def _parse_verdict(text: str) -> _AIVerdict:
        # Pull the first JSON object from the response. Haiku is usually
        # well-behaved, but markdown fences and stray prose still happen.
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError(f"no JSON object in classifier response: {text[:200]!r}")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed JSON: {exc}: {text[:200]!r}") from exc
        category = data.get("category")
        if category not in _RELEVANT_CATEGORIES:
            category = None
        audience = [
            a for a in (data.get("affected_audience") or [])
            if a in _AUDIENCES
        ]
        return _AIVerdict(
            is_relevant=bool(data.get("is_relevant", False)),
            confidence=float(data.get("confidence", 0.0)),
            category=category,
            threat_type=data.get("threat_type") or None,
            affected_audience=audience,
        )


# =========================================================================
# Public entry point — hybrid filter.
# =========================================================================

def classify_relevance(
    item: NewsItem,
    *,
    classifier: Optional[AIRelevanceClassifier] = None,
    cache: Optional[RelevanceCache] = None,
    stats: Optional[FilterStats] = None,
) -> RelevanceDecision:
    """Decide whether one item is relevant. Used by the batch function but
    also exposed so the API layer / tests can run the classifier on a
    single item.

    The decision is always populated (`is_relevant`, `score`, `source`).
    Optional AI fields are filled in when the AI path runs.
    """
    # 1. Language gate. Cheaper than scoring.
    if item.language in _REJECTED_LANGUAGES:
        if stats is not None:
            stats.language_rejected += 1
        return RelevanceDecision(False, 0, "language")

    score = relevance_score(item)

    # 2. Deterministic reject — score below the floor is junk.
    if score < REJECT_FLOOR:
        if stats is not None:
            stats.rules_rejected += 1
        return RelevanceDecision(False, score, "rules-reject")

    # 3. Deterministic accept — score above the ceiling is unambiguously cyber.
    if score >= ACCEPT_CEILING:
        if stats is not None:
            stats.rules_accepted += 1
        return RelevanceDecision(True, score, "rules-accept")

    # 4. Gray zone. Try cache → AI → deterministic fallback.
    if cache is not None:
        cached = cache.get(item.fingerprint)
        if cached is not None:
            if stats is not None:
                stats.ai_cache_hits += 1
                stats.ai_validated += 1
                if cached.is_relevant:
                    stats.ai_accepted += 1
                else:
                    stats.ai_rejected += 1
            # Preserve `score` from THIS call but keep AI fields from cache.
            return RelevanceDecision(
                is_relevant=cached.is_relevant, score=score, source="ai-cached",
                confidence=cached.confidence, category=cached.category,
                threat_type=cached.threat_type,
                affected_audience=list(cached.affected_audience),
            )

    if classifier is None:
        # AI is off; fall back to the legacy deterministic threshold.
        accepted = score >= DETERMINISTIC_THRESHOLD
        if stats is not None:
            if accepted:
                stats.ai_accepted += 1
            else:
                stats.ai_rejected += 1
        return RelevanceDecision(accepted, score, "ai-disabled")

    try:
        verdict = classifier.classify(item)
    except Exception as exc:
        logger.warning(
            "AI relevance classification failed for %s: %s — falling back to score",
            item.fingerprint, exc,
        )
        accepted = score >= DETERMINISTIC_THRESHOLD
        if stats is not None:
            stats.ai_errors += 1
            # We DID make a decision, just via the fallback path. Counting
            # it as accepted/rejected (in addition to the error counter)
            # keeps the per-item totals balanced for telemetry.
            if accepted:
                stats.ai_accepted += 1
            else:
                stats.ai_rejected += 1
        return RelevanceDecision(accepted, score, "ai-error")

    if stats is not None:
        stats.ai_validated += 1
        if verdict.is_relevant:
            stats.ai_accepted += 1
        else:
            stats.ai_rejected += 1

    decision = RelevanceDecision(
        is_relevant=verdict.is_relevant,
        score=score,
        source="ai-accept" if verdict.is_relevant else "ai-reject",
        confidence=verdict.confidence,
        category=verdict.category,
        threat_type=verdict.threat_type,
        affected_audience=list(verdict.affected_audience),
    )
    if cache is not None:
        cache.set(item.fingerprint, decision)
    return decision


def filter_relevant_hybrid(
    items: Iterable[NewsItem],
    *,
    classifier: Optional[AIRelevanceClassifier] = None,
    cache: Optional[RelevanceCache] = None,
) -> tuple[list[NewsItem], FilterStats]:
    """Apply the hybrid filter to a batch. Returns kept items + stats.

    The orchestrator calls this once per cycle. When `classifier` is None,
    it degrades to deterministic scoring with the legacy threshold (so
    enabling AI is a single setting flip, not a code change).
    """
    stats = FilterStats()
    kept: list[NewsItem] = []
    for item in items:
        stats.fetched += 1
        decision = classify_relevance(
            item, classifier=classifier, cache=cache, stats=stats,
        )
        # Stamp the decision metadata on the item so downstream layers
        # (categorizer, ranker, generator) can read it without re-running.
        if decision.category and not getattr(item, "category", None):
            item.category = decision.category
        if decision.is_relevant:
            kept.append(item)
    return kept, stats


# =========================================================================
# Factory — build a classifier from AISettings, or return None.
# =========================================================================

def build_default_classifier(
    *,
    enabled: bool,
    api_key: Optional[str],
    model: str,
    cache_path: Optional[Path] = None,
) -> tuple[Optional[AIRelevanceClassifier], Optional[RelevanceCache]]:
    """Build (classifier, cache) per the supplied flags.

    Returns (None, cache) when AI is disabled — the cache is still useful
    for legacy fingerprints. Returns (None, None) when both are off.
    The caller passes both into `filter_relevant_hybrid`.
    """
    cache = RelevanceCache(cache_path) if cache_path else None
    if not enabled:
        return None, cache
    if not api_key:
        logger.warning(
            "AI relevance requested but ANTHROPIC_API_KEY is unset — "
            "staying deterministic-only."
        )
        return None, cache
    try:
        classifier = AIRelevanceClassifier(api_key=api_key, model=model)
    except RuntimeError as exc:
        logger.warning("AI relevance disabled: %s", exc)
        return None, cache
    return classifier, cache


__all__ = [
    "REJECT_FLOOR",
    "ACCEPT_CEILING",
    "DETERMINISTIC_THRESHOLD",
    "RelevanceDecision",
    "FilterStats",
    "RelevanceCache",
    "AIRelevanceClassifier",
    "classify_relevance",
    "filter_relevant_hybrid",
    "build_default_classifier",
]
