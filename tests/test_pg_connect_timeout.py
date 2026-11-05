"""O36: the Postgres engine bounds connection establishment.

Without `connect_timeout`, an unreachable Supabase host made every attempt
wait for the kernel's TCP timeout (~2 min). The engine now passes libpq's
`connect_timeout` (default 10 s, `CYBERALERTX_PG_CONNECT_TIMEOUT_S`) to
psycopg, for Postgres URLs only, without touching pool settings.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from cyberalertx.storage.pg import engine as eng

# RFC 5737 TEST-NET-1: never routed, so a connect attempt hangs until a timeout.
UNROUTABLE = "postgresql://u:p@192.0.2.1:5432/db"


@pytest.fixture()
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_create_engine(url: str, **kw: Any) -> object:
        seen["url"], seen["kw"] = url, kw
        return object()

    monkeypatch.setattr(eng, "create_engine", fake_create_engine)
    eng._engine = None
    yield seen
    eng._engine = None


def _build(monkeypatch: pytest.MonkeyPatch, url: str, timeout: str | None = None) -> None:
    monkeypatch.setenv("CYBERALERTX_PG_URL", url)
    if timeout is None:
        monkeypatch.delenv("CYBERALERTX_PG_CONNECT_TIMEOUT_S", raising=False)
    else:
        monkeypatch.setenv("CYBERALERTX_PG_CONNECT_TIMEOUT_S", timeout)
    eng.get_engine()


def test_default_is_10_seconds_and_pool_settings_are_unchanged(captured: dict[str, Any],
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    _build(monkeypatch, "postgresql://u:p@db.example:5432/x?sslmode=require")
    kw = captured["kw"]
    assert kw["connect_args"] == {"connect_timeout": 10}
    assert (kw["pool_size"], kw["max_overflow"], kw["pool_pre_ping"]) == (eng._POOL_SIZE, eng._MAX_OVERFLOW, True)
    assert "pool_timeout" not in kw                      # checkout wait is a different knob
    assert captured["url"].startswith("postgresql+psycopg://")


def test_env_override(captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    _build(monkeypatch, "postgres://u:p@h/x", "3")
    assert captured["kw"]["connect_args"] == {"connect_timeout": 3}


def test_zero_means_libpq_default(captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    _build(monkeypatch, "postgresql://u:p@h/x", "0")
    assert captured["kw"]["connect_args"] == {}


def test_invalid_value_falls_back_to_the_default(captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    _build(monkeypatch, "postgresql://u:p@h/x", "ten")
    assert captured["kw"]["connect_args"] == {"connect_timeout": 10}


def test_a_timeout_in_the_url_wins(captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    _build(monkeypatch, "postgresql://u:p@h/x?sslmode=require&connect_timeout=2", "30")
    assert captured["kw"]["connect_args"] == {}


def test_non_postgres_urls_get_no_postgres_options(captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    _build(monkeypatch, "sqlite:///tmp/x.db")
    assert captured["kw"]["connect_args"] == {}


def test_an_unreachable_database_fails_within_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CYBERALERTX_PG_URL", UNROUTABLE)
    monkeypatch.setenv("CYBERALERTX_PG_CONNECT_TIMEOUT_S", "1")
    eng.dispose_engine()
    try:
        t0 = time.monotonic()
        with pytest.raises(Exception):
            with eng.get_engine().connect():
                pass
        assert time.monotonic() - t0 < 6           # was ~2 min (kernel TCP timeout)
    finally:
        eng.dispose_engine()


def test_dual_reads_and_writes_stay_bounded_when_postgres_is_unreachable(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """O27 + O36: the first feed read waits at most ~2 s for the index, a
    write fails its Postgres half within the connect timeout, JSON keeps it."""
    from cyberalertx.ai.cache import ThreatPostCache
    from cyberalertx.ai.models import ThreatPost
    from cyberalertx.storage.dual_write import DualWriteThreatPostCache
    from cyberalertx.storage.pg.threat_cache import PgThreatPostStore

    monkeypatch.setenv("CYBERALERTX_PG_URL", UNROUTABLE)
    monkeypatch.setenv("CYBERALERTX_PG_CONNECT_TIMEOUT_S", "1")
    eng.dispose_engine()
    try:
        dual = DualWriteThreatPostCache(ThreatPostCache(tmp_path / "p.json"), PgThreatPostStore(), index_ttl=60)
        t0 = time.monotonic()
        assert dual.get("missing", "en") is None
        assert time.monotonic() - t0 < 4
        post = ThreatPost(title="t", short_summary="s", threat_level="Low", why_it_matters="w",
                          affected_users=["a"], what_to_do=["b"], generated_by="mock", language="en")
        t0 = time.monotonic()
        dual.set("fp", "en", post)                    # PG half fails (logged), JSON half kept
        assert time.monotonic() - t0 < 6
        assert dual.get("fp", "en") is not None
        assert dual._load_done.wait(10)
        assert dual.index_stats["failures"] >= 1
    finally:
        eng.dispose_engine()
