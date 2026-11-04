"""Review-state persistence against a REAL Postgres.

GATED: runs only when `CYBERALERTX_TEST_DB_URL` points at a disposable test
database (never production). Each test gets its own schema, selected for
every connection through the URL's `options=-csearch_path=…`, so the app's
own `get_engine()` / `PgThreatPostStore` code path is exercised unchanged.

Verified here:
  * the JSONB payload round-trips review_status / reviewed_by / reviewed_at /
    quality exactly;
  * a decision made through dual-write is in BOTH stores;
  * after a "restart" (engine disposed, fresh objects) PG returns the
    decision, and with the JSON file gone the PG fallback serves it;
  * transitions pending → approved → rejected update the same row;
  * when Postgres is unreachable the decision is reported
    (SecondaryWriteError), JSON keeps it, PG keeps the old value, and a retry
    after recovery syncs PG.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

import pytest

if not os.getenv("CYBERALERTX_TEST_DB_URL"):
    pytest.skip("CYBERALERTX_TEST_DB_URL not set; skipping live PG tests.",
                allow_module_level=True)

from sqlalchemy import select, text

from cyberalertx.ai.cache import ThreatPostCache
from cyberalertx.ai.models import ThreatPost
from cyberalertx.ai.review import apply_decision, posts_with_status
from cyberalertx.storage.dual_write import DualWriteThreatPostCache, SecondaryWriteError
from cyberalertx.storage.pg.engine import dispose_engine, get_engine
from cyberalertx.storage.pg.schema import threat_posts
from cyberalertx.storage.pg.threat_cache import PgThreatPostStore
from cyberalertx.tools.pg_migrate import _list_files

BASE = os.environ["CYBERALERTX_TEST_DB_URL"]


def _url_with_schema(schema: str) -> str:
    sep = "&" if "?" in BASE else "?"
    return f"{BASE}{sep}options={quote(f'-csearch_path={schema}')}"


@pytest.fixture()
def schema(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    name = f"cax_review_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("CYBERALERTX_PG_URL", BASE)
    dispose_engine()
    with get_engine().begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {name}"))
    dispose_engine()
    monkeypatch.setenv("CYBERALERTX_PG_URL", _url_with_schema(name))
    for f in _list_files():
        with get_engine().begin() as conn:
            conn.exec_driver_sql(f.read_text(encoding="utf-8"))
    yield name
    dispose_engine()
    monkeypatch.setenv("CYBERALERTX_PG_URL", BASE)
    with get_engine().begin() as conn:
        conn.execute(text(f"DROP SCHEMA {name} CASCADE"))
    dispose_engine()


def _post(fp: str, status: str = "pending") -> ThreatPost:
    return ThreatPost(
        title="Зловмисники атакують сервери Widget",
        short_summary="BleepingComputer повідомляє про атаки на Widget.",
        threat_level="Critical", why_it_matters="x", affected_users=["x"], what_to_do=["x"],
        language="ua", source_fingerprint=fp, generated_by="mock:test",
        review_status=status,
        quality={"score": 41, "issues": [{"code": "unsourced_cve", "detail": "CVE-2026-0001"}]},
    )


def _pg_row(fp: str, locale: str) -> dict:  # type: ignore[type-arg]
    with get_engine().connect() as conn:
        payload = conn.execute(
            select(threat_posts.c.payload).where(
                threat_posts.c.fingerprint == fp, threat_posts.c.locale == locale)
        ).scalar_one()
    return dict(payload)


def test_decision_persists_in_both_stores_and_survives_restart(schema: str, tmp_path: Path) -> None:
    path = tmp_path / "posts.json"
    fp = "a1" * 8
    cache = DualWriteThreatPostCache(ThreatPostCache(path), PgThreatPostStore())
    cache.set(fp, "ua", _post(fp))
    raw = _pg_row(fp, "ua")
    assert raw["review_status"] == "pending"
    assert raw["quality"]["issues"][0]["detail"] == "CVE-2026-0001"      # JSONB round-trip

    apply_decision(cache, fp, "ua", "approve", "editor")
    raw = _pg_row(fp, "ua")
    assert raw["review_status"] == "approved" and raw["reviewed_by"] == "editor" and raw["reviewed_at"]

    # Restart: new engine, new objects.
    dispose_engine()
    fresh = DualWriteThreatPostCache(ThreatPostCache(path), PgThreatPostStore())
    assert fresh.get(fp, "ua").review_status == "approved"  # type: ignore[union-attr]
    # JSON gone → PG fallback still serves the decision.
    path.unlink()
    dispose_engine()
    fallback = DualWriteThreatPostCache(ThreatPostCache(path), PgThreatPostStore())
    got = fallback.get(fp, "ua")
    assert got is not None and got.review_status == "approved" and got.reviewed_by == "editor"


def test_transitions_update_the_same_row(schema: str, tmp_path: Path) -> None:
    fp = "b2" * 8
    cache = DualWriteThreatPostCache(ThreatPostCache(tmp_path / "p.json"), PgThreatPostStore())
    cache.set(fp, "ua", _post(fp))
    apply_decision(cache, fp, "ua", "approve", "ed1")
    apply_decision(cache, fp, "ua", "reject", "ed2")
    with get_engine().connect() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM threat_posts WHERE fingerprint = :fp AND locale = 'ua'"
        ), {"fp": fp}).scalar_one()
    assert n == 1
    assert _pg_row(fp, "ua")["review_status"] == "rejected"
    assert _pg_row(fp, "ua")["reviewed_by"] == "ed2"
    assert [p.review_status for p in posts_with_status(cache, ["rejected"])] == ["rejected"]


def test_unreachable_postgres_is_reported_and_retry_syncs(
    schema: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fp = "c3" * 8
    path = tmp_path / "p.json"
    cache = DualWriteThreatPostCache(ThreatPostCache(path), PgThreatPostStore())
    cache.set(fp, "ua", _post(fp))
    good_url = os.environ["CYBERALERTX_PG_URL"]

    # Outage: point the engine at a closed port.
    dispose_engine()
    monkeypatch.setenv("CYBERALERTX_PG_URL", "postgresql+psycopg://x:y@127.0.0.1:1/none?connect_timeout=2")
    with pytest.raises(SecondaryWriteError):
        apply_decision(cache, fp, "ua", "approve", "editor")
    assert ThreatPostCache(path).get(fp, "ua").review_status == "approved"  # type: ignore[union-attr]

    # Recovery: PG still has the old status until the retry.
    dispose_engine()
    monkeypatch.setenv("CYBERALERTX_PG_URL", good_url)
    assert _pg_row(fp, "ua")["review_status"] == "pending"
    apply_decision(cache, fp, "ua", "approve", "editor")
    assert _pg_row(fp, "ua")["review_status"] == "approved"
