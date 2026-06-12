"""Quality metrics — AI pipeline counters for dev visibility.

What we track and WHY:

  * `ai_renders_attempted`  — how many times we tried the AI path.
  * `ai_renders_success`    — how many succeeded (post-validation).
  * `ai_fallback_count`     — failed → rule-based fallback (any reason).
  * `ai_validation_rejects` — validation gate rejected the AI output.
  * `plagiarism_rejects`    — specifically: near-copy of source body.
  * `cliche_rejects`        — specifically: AI cliché / chatbot disclaimer.
  * `empty_field_rejects`   — specifically: empty title/summary/etc.
  * `dup_rec_rejects`       — specifically: duplicate recommendations.
  * `title_echo_rejects`    — specifically: summary echoes title.
  * `ai_provider_errors`    — network / API / schema errors (not validation).
  * `relevance_rules_rej`   — items rejected by deterministic scoring floor.
  * `relevance_rules_acc`   — items accepted by ceiling without AI.
  * `relevance_ai_validated`— items routed to AI relevance classifier.
  * `relevance_ai_acc/rej`  — AI relevance accepts / rejects.
  * `total_renders`         — overall render call count (success or fallback).

The goal isn't a dashboard. It's "early warning when AI output starts
degrading" — if `plagiarism_rejects` suddenly jumps, the prompt drifted.

Persistence:
  * Single JSON file (`data/quality_metrics.json`).
  * Atomic write on every increment via tempfile + `os.replace`.
  * In-process lock to serialize concurrent writes from FastAPI workers
    (FastAPI is async; the underlying pipeline writes are sync).
  * Tolerant load — if the file is missing or malformed, we start clean.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    from ..pipeline.relevance import FilterStats

from ..config import DATA_DIR

logger = logging.getLogger(__name__)

# Names of every counter we track. Centralized here so adding a new metric
# is one line, and so the API can iterate the canonical set.
_COUNTERS: tuple[str, ...] = (
    "total_renders",
    "ai_renders_attempted",
    "ai_renders_success",
    "ai_fallback_count",
    "ai_validation_rejects",
    "ai_provider_errors",
    "plagiarism_rejects",
    "cliche_rejects",
    "empty_field_rejects",
    "dup_rec_rejects",
    "title_echo_rejects",
    "hallucinated_threat_level",
    "relevance_rules_rej",
    "relevance_rules_acc",
    "relevance_ai_validated",
    "relevance_ai_acc",
    "relevance_ai_rej",
    "relevance_ai_errors",
    "relevance_cache_hits",
    "language_rejected",
    # Anthropic per-call token accounting. Lets us check the prompt-cache
    # actually kicks in (cache_read should approach input on the 2nd+ call
    # within a 5-min window). Without this the cost story is opinion;
    # with it, weekly numbers are auditable.
    "anthropic_calls",
    "anthropic_input_tokens",
    "anthropic_cache_read_tokens",
    "anthropic_cache_write_tokens",
    "anthropic_output_tokens",
)

# Validation-failure phrases we treat as a known reason. The validator's
# `ValidationFailure.message` is the human-readable cause; the prefix is
# stable and we use it to route to the right counter.
_VALIDATION_PREFIXES: Mapping[str, str] = {
    "near-copy": "plagiarism_rejects",
    "AI cliché": "cliche_rejects",
    "empty": "empty_field_rejects",
    "duplicate entries": "dup_rec_rejects",
    "summary echoes title": "title_echo_rejects",
    "hallucinated threat_level": "hallucinated_threat_level",
}


@dataclass
class QualityMetrics:
    """In-memory mirror of the on-disk counter file.

    Mutation is single-threaded internally; concurrent callers serialize on
    `_lock`. Counters are exposed via `as_dict()` for the API.
    """
    counters: dict[str, int] = field(default_factory=dict)
    # Top failing phrases — bounded counter so the file doesn't grow
    # unbounded if a flaky LLM keeps producing new junk strings.
    top_failure_messages: dict[str, int] = field(default_factory=dict)
    # First-seen / last-touched timestamps so the dev knows whether the
    # metrics file is current or rotted.
    first_seen_utc: Optional[str] = None
    last_updated_utc: Optional[str] = None

    # ---- non-serialized internals ----
    _path: Optional[Path] = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ----------------------- public API ----------------------------------

    def bump(self, name: str, by: int = 1) -> None:
        """Increment a named counter and persist."""
        with self._lock:
            self.counters[name] = self.counters.get(name, 0) + by
            self._stamp()
            self._flush()

    def record_validation_rejection(self, message: str) -> None:
        """Bump the right reject counter based on the validator message.

        Falls back to the generic `ai_validation_rejects` counter when the
        message prefix isn't in the known set, so a new failure mode shows
        up in the totals even before we wire a specific bucket.
        """
        message = (message or "").strip()
        with self._lock:
            self.counters["ai_validation_rejects"] = (
                self.counters.get("ai_validation_rejects", 0) + 1
            )
            for prefix, counter in _VALIDATION_PREFIXES.items():
                if message.lower().startswith(prefix.lower()):
                    self.counters[counter] = self.counters.get(counter, 0) + 1
                    break
            # Cap the failure-message dictionary so a chatty LLM doesn't
            # blow the file size. We keep the 50 most-frequent messages.
            self.top_failure_messages[message] = (
                self.top_failure_messages.get(message, 0) + 1
            )
            if len(self.top_failure_messages) > 50:
                trimmed = Counter(self.top_failure_messages).most_common(50)
                self.top_failure_messages = dict(trimmed)
            self._stamp()
            self._flush()

    def merge_relevance_stats(self, stats: "FilterStats") -> None:
        """Roll one cycle's `FilterStats` into the cumulative counters.

        Called from the orchestrator immediately after a cycle completes.
        Cheap — one disk write per cycle, dominated by the JSON dump.
        """
        with self._lock:
            self.counters["relevance_rules_rej"] = (
                self.counters.get("relevance_rules_rej", 0) + stats.rules_rejected
            )
            self.counters["relevance_rules_acc"] = (
                self.counters.get("relevance_rules_acc", 0) + stats.rules_accepted
            )
            self.counters["relevance_ai_validated"] = (
                self.counters.get("relevance_ai_validated", 0) + stats.ai_validated
            )
            self.counters["relevance_ai_acc"] = (
                self.counters.get("relevance_ai_acc", 0) + stats.ai_accepted
            )
            self.counters["relevance_ai_rej"] = (
                self.counters.get("relevance_ai_rej", 0) + stats.ai_rejected
            )
            self.counters["relevance_ai_errors"] = (
                self.counters.get("relevance_ai_errors", 0) + stats.ai_errors
            )
            self.counters["relevance_cache_hits"] = (
                self.counters.get("relevance_cache_hits", 0) + stats.ai_cache_hits
            )
            self.counters["language_rejected"] = (
                self.counters.get("language_rejected", 0) + stats.language_rejected
            )
            self._stamp()
            self._flush()

    def as_dict(self) -> dict[str, Any]:
        """Serializable snapshot — used by the API and tests."""
        # Always returns every known counter (zero when never bumped) so
        # the API consumer doesn't have to handle "missing key" cases.
        # Values are mostly int counters plus a few derived float|None rates.
        full: dict[str, Any] = {name: self.counters.get(name, 0) for name in _COUNTERS}
        full.update(self.counters)  # in case we've added unknown counters
        # Derived rates — cheap to compute, far more useful than raw counts.
        attempts = full.get("ai_renders_attempted", 0)
        full["ai_success_rate"] = (
            round(full.get("ai_renders_success", 0) / attempts, 4)
            if attempts else None
        )
        ai_validated = full.get("relevance_ai_validated", 0)
        full["ai_relevance_accept_rate"] = (
            round(full.get("relevance_ai_acc", 0) / ai_validated, 4)
            if ai_validated else None
        )
        return {
            "counters": full,
            "top_failure_messages": dict(
                Counter(self.top_failure_messages).most_common(10)
            ),
            "first_seen_utc": self.first_seen_utc,
            "last_updated_utc": self.last_updated_utc,
        }

    # ----------------------- persistence ---------------------------------

    def _stamp(self) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self.first_seen_utc:
            self.first_seen_utc = now
        self.last_updated_utc = now

    def _flush(self) -> None:
        if self._path is None:
            return
        payload = {
            "counters": dict(self.counters),
            "top_failure_messages": dict(self.top_failure_messages),
            "first_seen_utc": self.first_seen_utc,
            "last_updated_utc": self.last_updated_utc,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False,
            dir=str(self._path.parent), prefix=".quality_metrics.", suffix=".tmp",
        ) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp_name = tmp.name
        os.replace(tmp_name, self._path)

    @classmethod
    def load(cls, path: Path) -> "QualityMetrics":
        """Tolerant loader. Returns an empty (but file-bound) instance if
        the file is missing or malformed."""
        inst = cls(_path=path)
        if not path.exists():
            return inst
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                inst.counters = dict(raw.get("counters", {}))
                inst.top_failure_messages = dict(raw.get("top_failure_messages", {}))
                inst.first_seen_utc = raw.get("first_seen_utc")
                inst.last_updated_utc = raw.get("last_updated_utc")
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("quality_metrics load failed (%s); starting fresh", exc)
        return inst


# Process-wide singleton. Lazy-init so importing the module doesn't touch
# disk; the first caller pays the load cost.
_SINGLETON: Optional[QualityMetrics] = None
_SINGLETON_LOCK = threading.Lock()


def get_quality_metrics() -> QualityMetrics:
    """Return the process-wide metrics instance. Thread-safe."""
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = QualityMetrics.load(DATA_DIR / "quality_metrics.json")
    return _SINGLETON


# For test isolation — let a test point the singleton at a tmp path.
def _reset_singleton_for_tests(path: Optional[Path] = None) -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = QualityMetrics.load(path) if path else None
