"""Lightweight observability for CyberAlertX.

Two persistent counters, both JSON-backed:

  * `QualityMetrics`  — pipeline-wide AI/quality counters. Read at startup,
                         written atomically on every change. Surfaces at
                         `/admin/metrics`.
  * `SourceHealth`    — per-source ingest stats. Updated once per cycle by
                         the orchestrator. Surfaces at `/admin/sources`.

Design constraints (from the operational-simplicity brief):

  * No Redis, no Prometheus, no metrics daemon. Just JSON files.
  * Cheap-enough to write on every cycle without batching.
  * Safe under concurrent writes — both classes serialize via a `Lock`
    and use the same atomic tempfile + os.replace pattern as
    `storage/json_store.py`.
  * Read-only API access — the dev sees counters; nothing in the public
    UI consults them.
"""

from .metrics import QualityMetrics, get_quality_metrics
from .source_health import SourceHealth, get_source_health

__all__ = [
    "QualityMetrics",
    "SourceHealth",
    "get_quality_metrics",
    "get_source_health",
]
