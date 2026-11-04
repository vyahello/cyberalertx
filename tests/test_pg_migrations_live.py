"""Live Postgres migration tests — isolated database only.

Runs only with CYBERALERTX_TEST_DB_URL (a disposable Postgres; never the
production Supabase). Every test works in its own throwaway schema.

Covers: fresh initialisation, idempotent re-run, upgrade from the schema
production runs today (001–004) with existing rows preserved, deploy-order
safety for 005 (code before migration and migration before code), a failing
migration rolling back cleanly, and the review decision path under `dual`.
"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

import pytest

if not os.getenv("CYBERALERTX_TEST_DB_URL"):
    pytest.skip("CYBERALERTX_TEST_DB_URL not set; skipping live PG migration tests.", allow_module_level=True)

from sqlalchemy import text

import cyberalertx.tools.pg_migrate as pgm
from cyberalertx.models import NewsItem
from cyberalertx.storage.pg.engine import dispose_engine, get_engine
from cyberalertx.storage.pg.news_store import PgNewsStore

BASE = os.environ["CYBERALERTX_TEST_DB_URL"]
assert "supabase" not in BASE.lower(), "never point the live migration tests at Supabase"
MIGRATIONS = sorted(p for p in pgm.MIGRATIONS_DIR.glob("*.sql"))


def _url(schema: str) -> str:
    sep = "&" if "?" in BASE else "?"
    return f"{BASE}{sep}options={quote(f'-csearch_path={schema}')}"


@pytest.fixture()
def schema(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    name = f"cax_mig_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("CYBERALERTX_PG_URL", BASE)
    dispose_engine()
    with get_engine().begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {name}"))
    dispose_engine()
    monkeypatch.setenv("CYBERALERTX_PG_URL", _url(name))
    yield name
    dispose_engine()
    monkeypatch.setenv("CYBERALERTX_PG_URL", BASE)
    with get_engine().begin() as conn:
        conn.execute(text(f"DROP SCHEMA {name} CASCADE"))
    dispose_engine()


def _migrate_with(files: list[Path], tmp: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    d = tmp / f"m{uuid.uuid4().hex[:6]}"
    d.mkdir()
    for f in files:
        shutil.copy(f, d / f.name)
    monkeypatch.setattr(pgm, "MIGRATIONS_DIR", d)
    return pgm.migrate()


def _applied() -> list[str]:
    with get_engine().connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT version FROM schema_migrations ORDER BY version"))]


def _columns() -> set[str]:
    with get_engine().connect() as conn:
        return {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='news_items' "
            "AND table_schema = current_schema()"))}


def _item(n: str, relevance: str = "") -> NewsItem:
    it = NewsItem(title=f"Synthetic story {n}", source="SyntheticSource", url=f"https://synthetic.test/{n}",
                  published_at=datetime(2026, 11, 1, 12, tzinfo=timezone.utc), raw_content="synthetic body",
                  story_key=f"s:{n}")
    if relevance:
        it.relevance_status, it.relevance_reason = relevance, "synthetic reason"
    return it


def test_fresh_database_initialises_and_reruns_as_noop(schema: str, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    assert _migrate_with(MIGRATIONS, tmp_path, monkeypatch) == 0
    assert _applied() == [f.stem for f in MIGRATIONS]
    assert {"relevance_status", "relevance_reason", "relevance_override", "story_key"} <= _columns()
    assert _migrate_with(MIGRATIONS, tmp_path, monkeypatch) == 0                 # no-op
    assert len(_applied()) == len(MIGRATIONS)


def test_upgrade_from_the_current_production_schema_preserves_data(schema: str, tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    previous = [f for f in MIGRATIONS if f.stem < "005"]
    assert _migrate_with(previous, tmp_path, monkeypatch) == 0
    assert "relevance_status" not in _columns()
    # New code against the OLD schema: writes still work (columns skipped).
    store = PgNewsStore()
    assert len(store.upsert_many([_item("a", "in_scope"), _item("b")])) == 2
    assert {i.fingerprint for i in store.all()} == {_item("a").fingerprint, _item("b").fingerprint}
    with get_engine().connect() as conn:
        before = conn.execute(text("SELECT fingerprint, title, story_key FROM news_items ORDER BY 1")).all()
    # Apply 005 on the live table.
    assert _migrate_with(MIGRATIONS, tmp_path, monkeypatch) == 0
    with get_engine().connect() as conn:
        after = conn.execute(text("SELECT fingerprint, title, story_key, relevance_status FROM news_items ORDER BY 1")).all()
    assert [r[:3] for r in after] == [tuple(r) for r in before] and {r[3] for r in after} == {""}
    # The running process keeps its cached view until restart; a restart sees 005.
    dispose_engine()
    PgNewsStore().upsert_many([_item("a", "out_of_scope")])
    got = {i.fingerprint: i for i in PgNewsStore().all()}
    assert got[_item("a").fingerprint].relevance_status == "out_of_scope"
    assert got[_item("a").fingerprint].relevance_reason == "synthetic reason"
    assert got[_item("b").fingerprint].relevance_status == ""


def test_failed_migration_rolls_back_and_can_be_fixed(schema: str, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    bad = tmp_path / "006_broken.sql"
    bad.write_text("ALTER TABLE news_items ADD COLUMN IF NOT EXISTS half_done TEXT;\nTHIS IS NOT SQL;\n")
    assert _migrate_with(MIGRATIONS + [bad], tmp_path, monkeypatch) == 2
    assert "006_broken" not in _applied() and "half_done" not in _columns()     # whole file rolled back
    assert _applied() == [f.stem for f in MIGRATIONS]                              # earlier ones kept
    bad.write_text("ALTER TABLE news_items ADD COLUMN IF NOT EXISTS half_done TEXT;\n")
    assert _migrate_with(MIGRATIONS + [bad], tmp_path, monkeypatch) == 0
    assert "006_broken" in _applied() and "half_done" in _columns()


def test_review_decision_round_trips_under_dual(schema: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cyberalertx.ai.cache import ThreatPostCache
    from cyberalertx.ai.models import ThreatPost
    from cyberalertx.ai.review import apply_decision
    from cyberalertx.storage.dual_write import DualWriteThreatPostCache
    from cyberalertx.storage.pg.threat_cache import PgThreatPostStore

    assert _migrate_with(MIGRATIONS, tmp_path, monkeypatch) == 0
    fp = _item("r").fingerprint
    post = ThreatPost(title="Synthetic", short_summary="Synthetic summary.", threat_level="High", why_it_matters="x",
                      affected_users=["x"], what_to_do=["x"], language="en", source_fingerprint=fp,
                      generated_by="mock:test", review_status="pending")
    cache = DualWriteThreatPostCache(ThreatPostCache(tmp_path / "posts.json"), PgThreatPostStore())
    cache.set(fp, "en", post)
    apply_decision(cache, fp, "en", "approve", "admin:test")
    dispose_engine()                                                                # "restart"
    again = PgThreatPostStore().get(fp, "en")
    assert again is not None and again.review_status == "approved" and again.reviewed_by == "admin:test"
