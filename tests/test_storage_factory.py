"""Factory selection — env var controls which backend wraps the store.

These tests never touch Postgres. The 'dual' path imports PgNewsStore
lazily inside the factory; when the env says 'dual' but no PG URL is
present, we expect graceful fallback to JSON-only (with a logged warning).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cyberalertx.storage import build_news_repository
from cyberalertx.storage.dual_write import DualWriteNewsStore
from cyberalertx.storage.json_store import JsonNewsStore


def _empty_store(tmp_path: Path) -> Path:
    return tmp_path / "items.json"


def test_default_backend_is_json_only(tmp_path, monkeypatch):
    monkeypatch.delenv("CYBERALERTX_STORAGE_BACKEND", raising=False)
    repo = build_news_repository(storage_path=_empty_store(tmp_path), max_items=10)
    assert isinstance(repo, JsonNewsStore), (
        "Without the env flag, factory must return raw JsonNewsStore — "
        "no wrapping, no PG import."
    )


def test_explicit_json_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("CYBERALERTX_STORAGE_BACKEND", "json")
    repo = build_news_repository(storage_path=_empty_store(tmp_path), max_items=10)
    assert isinstance(repo, JsonNewsStore)


def test_unknown_backend_falls_back_to_json(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("CYBERALERTX_STORAGE_BACKEND", "redis")  # not a thing
    with caplog.at_level("WARNING"):
        repo = build_news_repository(storage_path=_empty_store(tmp_path), max_items=10)
    assert isinstance(repo, JsonNewsStore)
    assert any("Unknown" in r.message for r in caplog.records)


def test_dual_without_pg_url_falls_back_gracefully(tmp_path, monkeypatch, caplog):
    """The product invariant: ingest never breaks because PG is misconfigured."""
    monkeypatch.setenv("CYBERALERTX_STORAGE_BACKEND", "dual")
    monkeypatch.delenv("CYBERALERTX_PG_URL", raising=False)
    # Dispose any cached engine from earlier test runs.
    from cyberalertx.storage.pg.engine import dispose_engine
    dispose_engine()
    with caplog.at_level("WARNING"):
        repo = build_news_repository(storage_path=_empty_store(tmp_path), max_items=10)
    # We get the JSON store (raw, not wrapped) because PG init failed.
    assert isinstance(repo, JsonNewsStore)
    assert not isinstance(repo, DualWriteNewsStore)


@pytest.mark.skipif(
    "CYBERALERTX_TEST_DB_URL" not in __import__("os").environ,
    reason="live PG test — set CYBERALERTX_TEST_DB_URL to enable",
)
def test_dual_returns_wrapper_when_pg_reachable(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("CYBERALERTX_STORAGE_BACKEND", "dual")
    monkeypatch.setenv("CYBERALERTX_PG_URL", os.environ["CYBERALERTX_TEST_DB_URL"])
    from cyberalertx.storage.pg.engine import dispose_engine
    dispose_engine()
    repo = build_news_repository(storage_path=_empty_store(tmp_path), max_items=10)
    assert isinstance(repo, DualWriteNewsStore)
