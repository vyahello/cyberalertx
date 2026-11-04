"""Shared test isolation.

The observability singletons persist to `data/quality_metrics.json` and
`data/source_health.json` on every bump. Any test that runs the generator
(directly, or through the API) bumps them, so without this the suite rewrote
the real data files on every run. Each test now gets its own throwaway files.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture(autouse=True)
def _isolated_observability(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    from cyberalertx.observability import metrics, source_health

    base: Path = tmp_path_factory.mktemp("observability")
    metrics._reset_singleton_for_tests(base / "quality_metrics.json")
    reset_health = getattr(source_health, "_reset_singleton_for_tests", None)
    if reset_health is not None:
        reset_health(base / "source_health.json")
    yield
    metrics._reset_singleton_for_tests(None)
    if reset_health is not None:
        reset_health(None)


@pytest.fixture(autouse=True)
def _isolated_ops_ledgers(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 6 ledgers (AI usage, admin audit) and the control room's data
    directory: never the real `data/` from a test."""
    import cyberalertx.api.app as app_mod
    from cyberalertx.ops import readmodel, usage

    base: Path = tmp_path_factory.mktemp("ops")
    monkeypatch.setattr(usage, "USAGE_PATH", base / "ai_usage.jsonl")
    monkeypatch.setattr(app_mod, "_ops_data_dir", lambda: base)
    readmodel.clear_cache()
