"""Observability layer — QualityMetrics + SourceHealth.

These pin the persistence and aggregation behavior. We don't unit-test
the global-singleton wrappers (`get_quality_metrics`, `get_source_health`)
beyond load-once semantics; the orchestrator integration is exercised
via the existing pipeline tests.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cyberalertx.models import NewsItem
from cyberalertx.observability.metrics import QualityMetrics, _reset_singleton_for_tests as _reset_metrics
from cyberalertx.observability.source_health import (
    SourceHealth,
    _reset_singleton_for_tests as _reset_health,
)
from cyberalertx.pipeline.relevance import FilterStats


# --------------------- helpers --------------------------------------------

def _item(source: str, *, kept: bool = True, cred: float = 0.7) -> NewsItem:
    return NewsItem(
        title=f"story from {source}",
        source=source,
        url=f"https://e.test/{abs(hash(source))}",
        published_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        raw_content="",
        source_tier="trusted" if kept else "unverified",
        source_credibility_score=cred,
    )


# --------------------- QualityMetrics: counters & persistence -------------

def test_bump_increments_and_persists(tmp_path: Path):
    m = QualityMetrics.load(tmp_path / "q.json")
    m.bump("ai_renders_attempted")
    m.bump("ai_renders_attempted")
    m.bump("plagiarism_rejects")
    data = json.loads((tmp_path / "q.json").read_text())
    assert data["counters"]["ai_renders_attempted"] == 2
    assert data["counters"]["plagiarism_rejects"] == 1


def test_validation_rejection_routes_to_specific_counter(tmp_path: Path):
    """The validator's message prefix decides which counter to bump.
    Every rejection ALSO increments the generic `ai_validation_rejects`
    so totals balance regardless of message routing."""
    m = QualityMetrics.load(tmp_path / "q.json")
    m.record_validation_rejection("near-copy: 38% overlap with source")
    m.record_validation_rejection("AI cliché detected: 'evolving landscape'")
    m.record_validation_rejection("duplicate entries in what_to_do")
    m.record_validation_rejection("a message we've never seen before")
    snap = m.as_dict()
    assert snap["counters"]["ai_validation_rejects"] == 4
    assert snap["counters"]["plagiarism_rejects"] == 1
    assert snap["counters"]["cliche_rejects"] == 1
    assert snap["counters"]["dup_rec_rejects"] == 1


def test_top_failure_messages_capped(tmp_path: Path):
    """The top-failure dict is capped to 50 entries so a chatty LLM
    can't blow up the metrics file size."""
    m = QualityMetrics.load(tmp_path / "q.json")
    for i in range(80):
        m.record_validation_rejection(f"unique reason #{i}")
    snap = m.as_dict()
    # The dict is trimmed on each save to the 50 most-common; with all
    # unique messages, that means the first 50 we saw survive.
    assert len(snap["top_failure_messages"]) <= 10  # `as_dict` returns top 10
    assert m.as_dict()["counters"]["ai_validation_rejects"] == 80


def test_merge_relevance_stats_adds_cumulative(tmp_path: Path):
    m = QualityMetrics.load(tmp_path / "q.json")
    s1 = FilterStats(
        rules_rejected=10, rules_accepted=5, ai_validated=3,
        ai_accepted=2, ai_rejected=1, ai_cache_hits=2,
    )
    s2 = FilterStats(
        rules_rejected=7, rules_accepted=4, ai_validated=2,
        ai_accepted=2, ai_rejected=0, ai_cache_hits=1,
    )
    m.merge_relevance_stats(s1)
    m.merge_relevance_stats(s2)
    c = m.as_dict()["counters"]
    assert c["relevance_rules_rej"] == 17
    assert c["relevance_rules_acc"] == 9
    assert c["relevance_ai_validated"] == 5
    assert c["relevance_ai_acc"] == 4
    assert c["relevance_cache_hits"] == 3


def test_derived_rates_calculated(tmp_path: Path):
    m = QualityMetrics.load(tmp_path / "q.json")
    for _ in range(8):
        m.bump("ai_renders_attempted")
    for _ in range(6):
        m.bump("ai_renders_success")
    snap = m.as_dict()
    assert snap["counters"]["ai_success_rate"] == pytest.approx(0.75)


def test_load_tolerant_to_malformed_file(tmp_path: Path):
    path = tmp_path / "q.json"
    path.write_text("not json {{{")
    m = QualityMetrics.load(path)
    assert m.counters == {}
    # And it should be usable — write something and re-read.
    m.bump("ai_renders_attempted")
    data = json.loads(path.read_text())
    assert data["counters"]["ai_renders_attempted"] == 1


# --------------------- SourceHealth: aggregation --------------------------

def test_source_health_first_cycle_records_baseline(tmp_path: Path):
    h = SourceHealth.load(tmp_path / "h.json")
    fetched = {
        "CISA": [_item("CISA"), _item("CISA")],
        "tsn.ua": [],  # dead this cycle
    }
    relevant = [fetched["CISA"][0]]  # only one passed the filter
    h.record_cycle(fetched, relevant)
    snap = h.as_dict()["sources"]
    assert snap["CISA"]["cycles_seen"] == 1
    assert snap["CISA"]["total_fetched"] == 2
    assert snap["CISA"]["total_relevant"] == 1
    assert snap["CISA"]["relevance_rate"] == 0.5
    assert snap["tsn.ua"]["cycles_empty"] == 1
    assert snap["tsn.ua"]["empty_rate"] == 1.0
    assert snap["tsn.ua"]["total_fetched"] == 0


def test_source_health_cumulates_across_cycles(tmp_path: Path):
    h = SourceHealth.load(tmp_path / "h.json")
    h.record_cycle({"A": [_item("A")]}, [_item("A")])
    h.record_cycle({"A": [_item("A"), _item("A")]}, [_item("A")])
    snap = h.as_dict()["sources"]["A"]
    assert snap["cycles_seen"] == 2
    assert snap["total_fetched"] == 3
    assert snap["total_relevant"] == 2


def test_source_health_avg_credibility_running_mean(tmp_path: Path):
    h = SourceHealth.load(tmp_path / "h.json")
    items = [_item("A", cred=0.6), _item("A", cred=0.8), _item("A", cred=1.0)]
    h.record_cycle({"A": items}, items)
    snap = h.as_dict()["sources"]["A"]
    assert snap["avg_credibility"] == pytest.approx(0.8)


def test_source_health_persists_to_disk(tmp_path: Path):
    h = SourceHealth.load(tmp_path / "h.json")
    h.record_cycle({"A": [_item("A")]}, [_item("A")])
    raw = json.loads((tmp_path / "h.json").read_text())
    assert "A" in raw["sources"]
    assert raw["last_cycle_utc"] is not None
    # Reload — counters survive.
    h2 = SourceHealth.load(tmp_path / "h.json")
    snap = h2.as_dict()["sources"]["A"]
    assert snap["total_fetched"] == 1


# --------------------- singleton wrappers ---------------------------------

def test_get_quality_metrics_returns_singleton(tmp_path: Path):
    _reset_metrics(tmp_path / "q.json")
    from cyberalertx.observability import get_quality_metrics
    a = get_quality_metrics()
    b = get_quality_metrics()
    assert a is b
    _reset_metrics(None)  # cleanup


def test_get_source_health_returns_singleton(tmp_path: Path):
    _reset_health(tmp_path / "h.json")
    from cyberalertx.observability import get_source_health
    a = get_source_health()
    b = get_source_health()
    assert a is b
    _reset_health(None)


# --------------------- Anthropic usage recording --------------------------

class _FakeUsage:
    """Minimal stand-in for `anthropic.types.Usage`. Real SDK objects expose
    the same attributes; we only need attribute access via `getattr`."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_anthropic_usage_bumps_token_counters(tmp_path: Path):
    """The Anthropic provider records per-call token accounting so cache-
    hit ratio is auditable. This pins that `_record_usage` writes to the
    singleton counters and that zero-valued fields are skipped (so the
    'cache_write' counter only grows on actual cache writes)."""
    _reset_metrics(tmp_path / "q.json")
    try:
        from cyberalertx.ai.providers.anthropic_provider import AnthropicProvider
        from cyberalertx.observability import get_quality_metrics

        AnthropicProvider._record_usage(_FakeUsage(
            input_tokens=4500,
            cache_read_input_tokens=4200,
            cache_creation_input_tokens=0,
            output_tokens=800,
        ))
        AnthropicProvider._record_usage(_FakeUsage(
            input_tokens=4500,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=4200,
            output_tokens=750,
        ))

        m = get_quality_metrics()
        assert m.counters["anthropic_calls"] == 2
        assert m.counters["anthropic_input_tokens"] == 9000
        assert m.counters["anthropic_cache_read_tokens"] == 4200
        assert m.counters["anthropic_cache_write_tokens"] == 4200
        assert m.counters["anthropic_output_tokens"] == 1550
    finally:
        _reset_metrics(None)


def test_anthropic_usage_tolerates_missing_attributes(tmp_path: Path):
    """A degraded usage object (older SDK shape, mock response) must not
    take down the render path. Missing attrs default to 0 and we still
    bump the call counter."""
    _reset_metrics(tmp_path / "q.json")
    try:
        from cyberalertx.ai.providers.anthropic_provider import AnthropicProvider
        from cyberalertx.observability import get_quality_metrics

        AnthropicProvider._record_usage(_FakeUsage())  # no attrs at all

        m = get_quality_metrics()
        assert m.counters["anthropic_calls"] == 1
        # Zero-valued fields are skipped (we only bump on >0 to keep the
        # counter meaningful — `anthropic_input_tokens=0` would imply
        # a degraded SDK response, not a real zero).
        assert m.counters.get("anthropic_input_tokens", 0) == 0
    finally:
        _reset_metrics(None)
