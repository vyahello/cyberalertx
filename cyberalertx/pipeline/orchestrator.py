"""Single-cycle pipeline.

Stage order (each stage is a pure function/method + a plug-in point):

    fetch -> normalize -> filter -> categorize -> platforms -> audience -> actionability -> credibility -> rank -> persist

Why this order:
  * normalize must come before filter/categorize so they see clean UTF-8
    and have `language` available for future language-aware logic.
  * filter culls before the (slightly) heavier enrichment stages —
    we don't classify items we're going to throw away.
  * audience runs AFTER platforms and categorize because it uses both as
    signals — e.g. `Kubernetes` platform → developers + sysadmins.
  * rank runs last on the survivors so the cross-source bonus operates
    over the smallest possible candidate set.

To insert a new stage (e.g. AI summarization, NER entity extraction):
  add a method here, call it in `run_once()`, and add a CycleResult counter.
  No other module needs to change.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Iterable, List, Sequence

from ..models import NewsItem
from ..observability import get_quality_metrics, get_source_health
from ..sources.base import Source
from ..storage.json_store import NewsRepository
from .actionability import analyze_all as analyze_actionability_all
from .audience import classify_all as classify_audience_all
from .category import categorize_all
from .credibility import analyze_all as analyze_credibility_all
from .filter import filter_relevant
from .normalize import normalize_all
from .platforms import extract_all
from .ranker import score_items
from .relevance import (
    AIRelevanceClassifier,
    RelevanceCache,
    filter_relevant_hybrid,
)

logger = logging.getLogger(__name__)

# A post-processor takes the freshly-stored *new* items and does something
# with them — summarize, push, email, etc. Plugin point for future stages.
PostProcessor = Callable[[Sequence[NewsItem]], None]


@dataclass
class CycleResult:
    fetched: int
    relevant: int
    new: int
    categorized: int = 0
    audience_tagged: int = 0
    actionable: int = 0  # items at recommended_action or urgent_action
    trusted: int = 0  # items whose computed credibility tier is "trusted"

    def __str__(self) -> str:
        return (
            f"fetched={self.fetched} relevant={self.relevant} "
            f"categorized={self.categorized} audience={self.audience_tagged} "
            f"actionable={self.actionable} trusted={self.trusted} "
            f"new={self.new}"
        )


class Pipeline:
    def __init__(
        self,
        sources: Sequence[Source],
        repository: NewsRepository,
        post_processors: Iterable[PostProcessor] = (),
        max_workers: int = 8,
        *,
        ai_classifier: AIRelevanceClassifier | None = None,
        relevance_cache: RelevanceCache | None = None,
    ) -> None:
        self._sources = list(sources)
        self._repo = repository
        self._post_processors = list(post_processors)
        self._max_workers = max_workers
        # Optional AI relevance layer. When None, the filter stage uses the
        # legacy deterministic-only path. When set, items in the score
        # gray zone are routed through Haiku for a final yes/no.
        self._ai_classifier = ai_classifier
        self._relevance_cache = relevance_cache

    def run_once(self) -> CycleResult:
        fetched, fetched_by_source = self._fetch_all_with_source_map()
        # Pre-filter dedup against what's already on disk → don't waste
        # downstream work on items we've already processed.
        known = self._repo.known_fingerprints()
        fresh = [it for it in fetched if it.fingerprint not in known]
        # Stage: normalize. Cleans UTF-8, sets language / original_language.
        # Runs on EVERY fresh item so language is recorded even on items the
        # filter rejects — useful for telemetry on what we're dropping.
        normalize_all(fresh)
        # Stage: filter. Hybrid scoring + optional AI for the gray zone.
        # When neither classifier nor cache is configured AND we want the
        # exact legacy behavior, fall back to filter_relevant() — keeps
        # unit tests stable when AI is off.
        if self._ai_classifier is not None or self._relevance_cache is not None:
            relevant, stats = filter_relevant_hybrid(
                fresh,
                classifier=self._ai_classifier,
                cache=self._relevance_cache,
            )
            logger.info("relevance stats: %s", stats.as_log_string())
            # Roll the cycle's counts into the cumulative metrics file.
            # Done synchronously per cycle — the JSON write is microseconds
            # and the data is invaluable for "is the AI getting worse?".
            try:
                get_quality_metrics().merge_relevance_stats(stats)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("metrics rollup failed: %s", exc)
        else:
            relevant = filter_relevant(fresh)
        # Stage: categorize + extract platforms. Cheap pure-text passes.
        categorize_all(relevant)
        extract_all(relevant)
        # Stage: audience. Depends on category + platforms so runs after both.
        # Drives personalized feeds / UI prioritization downstream.
        classify_audience_all(relevant)
        # Stage: actionability. Reuses category (urgency bias) + the severity
        # vocabulary already shared with the ranker, so the upstream stages
        # have to run first.
        analyze_actionability_all(relevant)
        # Stage: credibility. Needs the full batch so the cross-source
        # corroboration bonus can find trusted peers reporting the same story.
        analyze_credibility_all(relevant)
        # Stage: rank. Sees the WHOLE batch so cross-source bonus can fire.
        score_items(relevant)
        new_items = self._repo.upsert_many(relevant)
        self._notify(new_items)
        # Per-source health update — runs after the full pipeline so it
        # can split fetched-vs-kept counts by source. Cheap (one JSON
        # write); never raises into the cycle.
        try:
            get_source_health().record_cycle(fetched_by_source, relevant)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("source health update failed: %s", exc)
        result = CycleResult(
            fetched=len(fetched),
            relevant=len(relevant),
            new=len(new_items),
            categorized=sum(1 for i in relevant if i.category != "other"),
            audience_tagged=sum(1 for i in relevant if i.audience_targets),
            actionable=sum(
                1 for i in relevant if i.actionability_level != "informational"
            ),
            trusted=sum(1 for i in relevant if i.source_tier == "trusted"),
        )
        logger.info("cycle complete: %s", result)
        return result

    def _fetch_all(self) -> List[NewsItem]:
        """Convenience wrapper — for callers that don't need the
        source-keyed map."""
        items, _ = self._fetch_all_with_source_map()
        return items

    def _fetch_all_with_source_map(
        self,
    ) -> tuple[List[NewsItem], dict[str, List[NewsItem]]]:
        """Fan out across sources. Returns (flat_list, by_source_map).

        The map is needed by `source_health` so it can attribute fetch
        counts back to individual feeds; we build it once here instead
        of having downstream code re-group by `item.source`.
        """
        items: List[NewsItem] = []
        by_source: dict[str, List[NewsItem]] = {}
        if not self._sources:
            return items, by_source
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            for src, batch in zip(
                self._sources,
                pool.map(self._safe_fetch, self._sources),
            ):
                logger.info("source %s -> %d items", src.name, len(batch))
                by_source[src.name] = batch
                items.extend(batch)
        return items, by_source

    @staticmethod
    def _safe_fetch(source: Source) -> List[NewsItem]:
        try:
            return source.fetch()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("source %s crashed: %s", source.name, exc)
            return []

    def _notify(self, new_items: Sequence[NewsItem]) -> None:
        if not new_items or not self._post_processors:
            return
        for proc in self._post_processors:
            try:
                proc(new_items)
            except Exception:  # pragma: no cover - defensive
                logger.exception("post-processor %r failed", proc)
