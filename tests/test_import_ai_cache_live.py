"""O28 reconciliation tool (`tools.import_ai_cache_to_postgres`) against a REAL Postgres.

GATED like test_pg_review_live: runs only when `CYBERALERTX_TEST_DB_URL`
points at a disposable database. Each test gets its own schema.

Verified:
  * --dry-run reads PG but writes nothing, and its plan is exact (inserts,
    updates, review-status transitions, PG-only rows);
  * mapping: every (fingerprint, locale) lands on its own row, payload equal
    to the JSON entry, denormalized columns filled by the trigger;
  * review state (status, reviewer, time, quality) is carried JSON -> PG and a
    stale PG decision is overwritten;
  * idempotency: a second run writes nothing and exits 0;
  * no resurrection: the JSON file is never modified, PG-only rows are only
    reported (never deleted, never copied back), a JSON rejection reaches PG
    so the dual read path keeps the post hidden;
  * an unreadable JSON file is refused; a failed write fails the run.
"""
from __future__ import annotations

import hashlib
import json
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
from cyberalertx.ai.review import is_publicly_visible
from cyberalertx.storage.dual_write import DualWriteThreatPostCache
from cyberalertx.storage.pg.engine import dispose_engine, get_engine
from cyberalertx.storage.pg.schema import threat_posts
from cyberalertx.storage.pg.threat_cache import PgThreatPostStore
from cyberalertx.tools import import_ai_cache_to_postgres as tool
from cyberalertx.tools.pg_migrate import _list_files

BASE = os.environ["CYBERALERTX_TEST_DB_URL"]


@pytest.fixture()
def schema(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    name = f"cax_import_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("CYBERALERTX_PG_URL", BASE)
    dispose_engine()
    with get_engine().begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {name}"))
    dispose_engine()
    sep = "&" if "?" in BASE else "?"
    monkeypatch.setenv("CYBERALERTX_PG_URL", f"{BASE}{sep}options={quote(f'-csearch_path={name}')}")
    for f in _list_files():
        with get_engine().begin() as conn:
            conn.exec_driver_sql(f.read_text(encoding="utf-8"))
    yield name
    dispose_engine()
    monkeypatch.setenv("CYBERALERTX_PG_URL", BASE)
    with get_engine().begin() as conn:
        conn.execute(text(f"DROP SCHEMA {name} CASCADE"))
    dispose_engine()


def _post(fp: str, loc: str, status: str = "auto", **kw: object) -> ThreatPost:
    return ThreatPost(
        title=f"{fp} {loc}", short_summary="s", threat_level="High", why_it_matters="w",
        affected_users=["u"], what_to_do=["d"], language=loc, source_fingerprint=fp,
        generated_by="mock:test", review_status=status, **kw,  # type: ignore[arg-type]
    )


def _rows() -> dict[str, dict]:  # type: ignore[type-arg]
    with get_engine().connect() as conn:
        rows = conn.execute(select(threat_posts.c.fingerprint, threat_posts.c.locale, threat_posts.c.payload))
        return {f"{fp}:{loc}": dict(p) for fp, loc, p in rows}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scenario(tmp_path: Path) -> Path:
    """JSON (authoritative) and a drifted PG, as after the Stage C JSON-only API period."""
    path = tmp_path / "threat_posts.json"
    js = ThreatPostCache(path)
    js.set("a1", "en", _post("a1", "en"))                                   # missing in PG -> insert
    js.set("a1", "ua", _post("a1", "ua", "approved", reviewed_by="ed", reviewed_at="2026-11-04T10:00:00+00:00",
                             quality={"score": 72, "issues": [{"code": "x"}]}))  # PG pending -> update
    js.set("b2", "en", _post("b2", "en", "rejected", reviewed_by="ed2"))    # PG auto -> update (hide)
    js.set("c3", "en", _post("c3", "en"))                                   # identical -> unchanged
    pg = PgThreatPostStore()
    pg.set("a1", "ua", _post("a1", "ua", "pending"))
    pg.set("b2", "en", _post("b2", "en", "auto"))
    pg.set("c3", "en", _post("c3", "en"))
    pg.set("z9", "en", _post("z9", "en", "approved"))                       # PG-only
    return path


def test_dry_run_reports_the_exact_plan_and_writes_nothing(schema: str, tmp_path: Path,
                                                           capsys: pytest.CaptureFixture[str]) -> None:
    path = _scenario(tmp_path)
    before, sha = _rows(), _sha(path)
    report = tmp_path / "plan.json"
    assert tool.main(["--dry-run", "--cache", str(path), "--report", str(report)]) == 0
    assert _rows() == before and _sha(path) == sha
    plan = json.loads(report.read_text())
    assert plan["insert"] == ["a1:en"]
    assert sorted(plan["update"]) == ["a1:ua", "b2:en"]
    assert plan["unchanged"] == 1
    assert plan["update_format_only"] == 0                               # real changes, not format
    assert plan["status_transitions"] == {"pending->approved": 1, "auto->rejected": 1}
    assert plan["pg_only"] == [{"key": "z9:en", "pg": "approved"}]
    assert "title" not in report.read_text()                               # no content in the report
    assert "PG-only rows 1" in capsys.readouterr().err


def test_import_maps_rows_and_carries_review_state(schema: str, tmp_path: Path) -> None:
    path = _scenario(tmp_path)
    assert tool.main(["--cache", str(path)]) == 0
    rows = _rows()
    js = ThreatPostCache(path)
    for key in ("a1:en", "a1:ua", "b2:en", "c3:en"):
        fp, _, loc = key.partition(":")
        assert rows[key] == js.get(fp, loc).to_dict()  # type: ignore[union-attr]
    assert rows["a1:ua"]["review_status"] == "approved"
    assert rows["a1:ua"]["reviewed_by"] == "ed" and rows["a1:ua"]["reviewed_at"] == "2026-11-04T10:00:00+00:00"
    assert rows["a1:ua"]["quality"] == {"score": 72, "issues": [{"code": "x"}]}
    assert rows["b2:en"]["review_status"] == "rejected"
    with get_engine().connect() as conn:                                     # one row per key
        n = conn.execute(text("SELECT count(*) FROM threat_posts")).scalar_one()
    assert n == 5                                                            # 4 JSON keys + PG-only z9


def test_second_run_is_a_no_op(schema: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _scenario(tmp_path)
    assert tool.main(["--cache", str(path)]) == 0
    first = _rows()
    capsys.readouterr()
    assert tool.main(["--cache", str(path)]) == 0
    assert _rows() == first
    assert "Upserted 0 of 0 changed entries" in capsys.readouterr().err


def test_no_resurrection(schema: str, tmp_path: Path) -> None:
    path = _scenario(tmp_path)
    sha = _sha(path)
    assert tool.main(["--cache", str(path)]) == 0
    assert _sha(path) == sha                                                 # JSON never written
    assert "z9:en" in _rows()                                                # PG-only kept, not deleted
    assert ThreatPostCache(path).get("z9", "en") is None                     # ... and not copied back
    dual = DualWriteThreatPostCache(ThreatPostCache(path), PgThreatPostStore(), index_ttl=3600)
    rejected = dual.get("b2", "en")
    assert rejected is not None and not is_publicly_visible(rejected, "flag")
    assert PgThreatPostStore().get("b2", "en").review_status == "rejected"  # type: ignore[union-attr]


def test_unreadable_json_is_refused(schema: str, tmp_path: Path) -> None:
    path = tmp_path / "threat_posts.json"
    path.write_text("{broken", encoding="utf-8")
    before = _rows()
    assert tool.main(["--cache", str(path)]) == 3
    assert _rows() == before


def test_a_failed_write_fails_the_run(schema: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _scenario(tmp_path)

    def boom(self: PgThreatPostStore, fp: str, loc: str, post: ThreatPost) -> None:
        raise RuntimeError("simulated outage")

    monkeypatch.setattr(PgThreatPostStore, "set", boom)
    assert tool.main(["--cache", str(path)]) == 2
