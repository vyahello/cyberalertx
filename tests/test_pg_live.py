"""Live Postgres integration tests.

GATED BY ENV: these tests run only when `CYBERALERTX_TEST_DB_URL` is
set. Without it, the whole module is skipped at collection time so the
regular `pytest` invocation stays green on dev machines without a DB.

When enabled, each test creates a unique schema, applies migrations,
runs the assertion, and drops the schema. The shared `CYBERALERTX_PG_URL`
is taken from `CYBERALERTX_TEST_DB_URL` so production env never collides
with the test schema by accident.

Recommended setup:
    1. Create a dedicated Supabase project (or a `cyberalertx_test` db).
    2. Set CYBERALERTX_TEST_DB_URL in your shell before running pytest.
"""
from __future__ import annotations

import os
import uuid

import pytest

if not os.getenv("CYBERALERTX_TEST_DB_URL"):
    pytest.skip(
        "CYBERALERTX_TEST_DB_URL not set; skipping live PG tests.",
        allow_module_level=True,
    )

from datetime import datetime, timezone

from sqlalchemy import text

from cyberalertx.models import NewsItem
from cyberalertx.storage.pg.engine import dispose_engine, get_engine
from cyberalertx.storage.pg.news_store import PgNewsStore
from cyberalertx.tools.pg_migrate import _apply, _list_files


@pytest.fixture()
def isolated_schema(monkeypatch):
    """Run each test in a fresh Postgres schema, dropped at teardown."""
    monkeypatch.setenv("CYBERALERTX_PG_URL", os.environ["CYBERALERTX_TEST_DB_URL"])
    dispose_engine()
    schema = f"cax_test_{uuid.uuid4().hex[:8]}"
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
    # Apply all migrations into the new schema.
    # NOTE: we re-use the migration runner's `_apply`, which doesn't
    # set search_path itself; we re-apply via a session-level SET below.
    with engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.commit()
    for f in _list_files():
        # Each migration runs in its own transaction (via _apply); we
        # need search_path set per connection, so we inline here.
        sql = f.read_text(encoding="utf-8")
        with engine.begin() as conn:
            conn.execute(text(f"SET search_path TO {schema}"))
            conn.exec_driver_sql(sql)
    yield schema
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    dispose_engine()


def _item(url: str, score: float = 50.0) -> NewsItem:
    return NewsItem(
        title=f"Item from {url}",
        source="TestSource",
        url=url,
        published_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        raw_content="body",
        threat_score=score,
        tags=["a", "b"],
        language="en",
    )


def _scoped_store(schema: str) -> PgNewsStore:
    """Return a PgNewsStore that operates against `schema` by setting
    search_path on each engine checkout via an event listener."""
    from sqlalchemy import event
    store = PgNewsStore()
    engine = get_engine()
    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_conn, _):
        with dbapi_conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}")
    return store


def test_upsert_inserts_new_items(isolated_schema):
    store = _scoped_store(isolated_schema)
    items = [_item("https://e.test/1"), _item("https://e.test/2")]
    new = store.upsert_many(items)
    assert len(new) == 2
    assert store.known_fingerprints() == {i.fingerprint for i in items}


def test_upsert_returns_only_new_items_on_reinsert(isolated_schema):
    store = _scoped_store(isolated_schema)
    items = [_item("https://e.test/1")]
    store.upsert_many(items)
    new = store.upsert_many(items)
    assert new == [], "re-inserting an existing item must return no new items"


def test_upsert_threat_score_uses_greatest(isolated_schema):
    store = _scoped_store(isolated_schema)
    store.upsert_many([_item("https://e.test/1", score=80.0)])
    store.upsert_many([_item("https://e.test/1", score=20.0)])
    all_items = store.all()
    assert len(all_items) == 1
    assert all_items[0].threat_score == 80.0, (
        "re-ingest must not lower an already-bumped threat_score"
    )


def test_all_orders_by_published_at_desc(isolated_schema):
    store = _scoped_store(isolated_schema)
    old = _item("https://e.test/old")
    new = _item("https://e.test/new")
    new.published_at = datetime(2026, 5, 14, tzinfo=timezone.utc)
    store.upsert_many([old, new])
    result = store.all()
    assert [r.fingerprint for r in result] == [new.fingerprint, old.fingerprint]
