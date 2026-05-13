"""Per-source health tracking.

What we capture per source, and why:

  * `last_successful_ingest`  — when did this source last yield items?
                                A dead feed surfaces here before users
                                notice the UK page is sparse.
  * `cycles_seen`              — total cycles that polled this source.
  * `cycles_empty`             — cycles where the source returned zero items
                                 (network failure, parse error, or genuinely
                                 nothing fresh — we can't always tell apart).
  * `total_fetched`            — sum of items returned across all cycles.
  * `total_relevant`           — sum of items that passed the relevance gate.
  * `relevance_rate`           — derived: total_relevant / total_fetched.
                                 Noisy feeds drift toward 0; well-targeted
                                 feeds stay >0.6.
  * `last_published_at`        — newest item we've ingested from this source,
                                 useful for stale-feed warnings.
  * `avg_credibility`          — running mean of items' credibility scores.

What we DON'T do:
  * No per-item history. We track aggregates, not events.
  * No alerting / paging. This is "look at the JSON when something feels off".
  * No automatic source disablement. Editors decide what to drop.

Persistence: same atomic JSON-file pattern as QualityMetrics. Updated
once per cycle by the orchestrator (`record_cycle(...)`).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from ..config import DATA_DIR
from ..models import NewsItem

logger = logging.getLogger(__name__)


@dataclass
class _SourceStats:
    """Per-source aggregates. Plain dict-friendly for JSON serialization."""
    cycles_seen: int = 0
    cycles_empty: int = 0
    total_fetched: int = 0
    total_relevant: int = 0
    last_successful_ingest_utc: Optional[str] = None
    last_published_at_utc: Optional[str] = None
    # Running-mean credibility — stored as a tuple-like pair so we can
    # update incrementally without keeping per-item history.
    cred_sum: float = 0.0
    cred_n: int = 0

    @property
    def relevance_rate(self) -> Optional[float]:
        if self.total_fetched == 0:
            return None
        return round(self.total_relevant / self.total_fetched, 3)

    @property
    def avg_credibility(self) -> Optional[float]:
        if self.cred_n == 0:
            return None
        return round(self.cred_sum / self.cred_n, 3)


@dataclass
class SourceHealth:
    """Whole-feed source-health snapshot. One entry per source name."""
    sources: dict[str, _SourceStats] = field(default_factory=dict)
    last_cycle_utc: Optional[str] = None

    # ---- non-serialized ----
    _path: Optional[Path] = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ----------------------- public API ----------------------------------

    def record_cycle(
        self,
        fetched_by_source: dict[str, list[NewsItem]],
        relevant_items: Iterable[NewsItem],
    ) -> None:
        """Update aggregates from one orchestrator cycle.

        `fetched_by_source` is the raw fetch output (post-dedup, pre-filter)
        keyed by source name. `relevant_items` is the post-filter set —
        we count those into `total_relevant` per source.
        """
        relevant_by_source: dict[str, list[NewsItem]] = {}
        for item in relevant_items:
            relevant_by_source.setdefault(item.source, []).append(item)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        with self._lock:
            self.last_cycle_utc = now
            for source, fetched in fetched_by_source.items():
                stats = self.sources.setdefault(source, _SourceStats())
                stats.cycles_seen += 1
                if not fetched:
                    stats.cycles_empty += 1
                    continue
                stats.total_fetched += len(fetched)
                stats.last_successful_ingest_utc = now
                # Track newest pub date across the cycle's items.
                latest = max(i.published_at for i in fetched)
                latest_iso = latest.astimezone(timezone.utc).isoformat(
                    timespec="seconds"
                )
                if (
                    stats.last_published_at_utc is None
                    or latest_iso > stats.last_published_at_utc
                ):
                    stats.last_published_at_utc = latest_iso
                # Count relevant (post-filter) items + credibility avg.
                kept = relevant_by_source.get(source, [])
                stats.total_relevant += len(kept)
                for it in kept:
                    if it.source_credibility_score > 0:
                        stats.cred_sum += it.source_credibility_score
                        stats.cred_n += 1
            self._flush()

    def as_dict(self) -> dict:
        """Serializable snapshot for the API. Includes derived rates."""
        return {
            "last_cycle_utc": self.last_cycle_utc,
            "sources": {
                name: {
                    "cycles_seen": s.cycles_seen,
                    "cycles_empty": s.cycles_empty,
                    "empty_rate": (
                        round(s.cycles_empty / s.cycles_seen, 3)
                        if s.cycles_seen else None
                    ),
                    "total_fetched": s.total_fetched,
                    "total_relevant": s.total_relevant,
                    "relevance_rate": s.relevance_rate,
                    "avg_credibility": s.avg_credibility,
                    "last_successful_ingest_utc": s.last_successful_ingest_utc,
                    "last_published_at_utc": s.last_published_at_utc,
                }
                for name, s in self.sources.items()
            },
        }

    # ----------------------- persistence ---------------------------------

    def _flush(self) -> None:
        if self._path is None:
            return
        payload = {
            "last_cycle_utc": self.last_cycle_utc,
            "sources": {
                name: {
                    "cycles_seen": s.cycles_seen,
                    "cycles_empty": s.cycles_empty,
                    "total_fetched": s.total_fetched,
                    "total_relevant": s.total_relevant,
                    "last_successful_ingest_utc": s.last_successful_ingest_utc,
                    "last_published_at_utc": s.last_published_at_utc,
                    "cred_sum": s.cred_sum,
                    "cred_n": s.cred_n,
                }
                for name, s in self.sources.items()
            },
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False,
            dir=str(self._path.parent), prefix=".source_health.", suffix=".tmp",
        ) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp_name = tmp.name
        os.replace(tmp_name, self._path)

    @classmethod
    def load(cls, path: Path) -> "SourceHealth":
        inst = cls(_path=path)
        if not path.exists():
            return inst
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                inst.last_cycle_utc = raw.get("last_cycle_utc")
                for name, data in (raw.get("sources") or {}).items():
                    s = _SourceStats(
                        cycles_seen=int(data.get("cycles_seen", 0)),
                        cycles_empty=int(data.get("cycles_empty", 0)),
                        total_fetched=int(data.get("total_fetched", 0)),
                        total_relevant=int(data.get("total_relevant", 0)),
                        last_successful_ingest_utc=data.get("last_successful_ingest_utc"),
                        last_published_at_utc=data.get("last_published_at_utc"),
                        cred_sum=float(data.get("cred_sum", 0.0)),
                        cred_n=int(data.get("cred_n", 0)),
                    )
                    inst.sources[name] = s
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("source_health load failed (%s); starting fresh", exc)
        return inst


_SINGLETON: Optional[SourceHealth] = None
_LOCK = threading.Lock()


def get_source_health() -> SourceHealth:
    global _SINGLETON
    if _SINGLETON is None:
        with _LOCK:
            if _SINGLETON is None:
                _SINGLETON = SourceHealth.load(DATA_DIR / "source_health.json")
    return _SINGLETON


def _reset_singleton_for_tests(path: Optional[Path] = None) -> None:
    global _SINGLETON
    with _LOCK:
        _SINGLETON = SourceHealth.load(path) if path else None
