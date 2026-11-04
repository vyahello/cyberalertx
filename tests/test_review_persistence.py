"""Review-state persistence: the guarantees an editor relies on.

No database needed — Postgres is stood in for by small fake stores here; the
same flow against a real Postgres lives in `test_pg_review_live.py`.

Covered:
  * status transitions pending → approved → rejected, with reviewer + time
  * a "restart" (fresh cache objects on the same files) reads the decision back
  * two processes writing the JSON cache at once never drop each other's keys
  * under dual-write, a failed Postgres write is REPORTED (SecondaryWriteError),
    JSON still holds the decision, and a retry brings Postgres in line
  * a plain render write (`set`) keeps its old shadow semantics
"""
from __future__ import annotations

import multiprocessing as mp
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pytest

from cyberalertx.ai.cache import ThreatPostCache
from cyberalertx.ai.models import ThreatPost
from cyberalertx.ai.review import apply_decision, is_publicly_visible
from cyberalertx.storage.dual_write import DualWriteThreatPostCache, SecondaryWriteError


def _post(fp: str, status: str = "pending") -> ThreatPost:
    return ThreatPost(
        title="Attackers hit Widget servers",
        short_summary="BleepingComputer reports attacks on Widget servers.",
        threat_level="High", why_it_matters="x", affected_users=["x"], what_to_do=["x"],
        language="en", source_fingerprint=fp, generated_by="mock:test",
        review_status=status, quality={"score": 40},
    )


class _MemStore:
    """Stand-in for PgThreatPostStore; `fail` makes every write raise."""

    def __init__(self) -> None:
        self.rows: dict[str, ThreatPost] = {}
        self.fail = False

    def get(self, fingerprint: str, locale: str = "en") -> ThreatPost | None:
        return self.rows.get(f"{fingerprint}:{locale}")

    def set(self, fingerprint: str, locale: str, post: ThreatPost) -> None:
        if self.fail:
            raise ConnectionError("simulated Postgres outage")
        # Round-trip through the payload, like the JSONB column does.
        self.rows[f"{fingerprint}:{locale}"] = ThreatPost.from_dict(post.to_dict())

    def delete(self, fingerprint: str, locale: str) -> bool:
        return self.rows.pop(f"{fingerprint}:{locale}", None) is not None

    def all(self) -> Iterable[ThreatPost]:
        return list(self.rows.values())

    def __len__(self) -> int:
        return len(self.rows)


T0 = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


def test_transitions_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "posts.json"
    cache = ThreatPostCache(path)
    cache.set("a" * 16, "en", _post("a" * 16))

    approved = apply_decision(cache, "a" * 16, "en", "approve", "editor", now=T0)
    assert approved.review_status == "approved" and approved.reviewed_by == "editor"

    # "Restart": a fresh object on the same file sees the decision.
    assert ThreatPostCache(path).get("a" * 16, "en").review_status == "approved"  # type: ignore[union-attr]

    rejected = apply_decision(ThreatPostCache(path), "a" * 16, "en", "reject", "editor2")
    assert rejected.review_status == "rejected"
    reread = ThreatPostCache(path).get("a" * 16, "en")
    assert reread is not None and reread.review_status == "rejected" and reread.reviewed_by == "editor2"
    assert reread.title == "Attackers hit Widget servers"   # text untouched
    assert not is_publicly_visible(reread, "flag")


def _writer(path: str, prefix: str, n: int) -> None:
    cache = ThreatPostCache(Path(path))
    for i in range(n):
        fp = f"{prefix}{i:015d}"[:16]
        cache.set(fp, "en", _post(fp, "auto"))


def test_concurrent_writers_never_drop_each_others_keys(tmp_path: Path) -> None:
    path = tmp_path / "posts.json"
    # A big existing store makes every flush slow enough to overlap.
    seed = ThreatPostCache(path)
    for i in range(400):
        fp = f"s{i:015d}"
        seed._store[f"{fp}:en"] = _post(fp, "auto").to_dict()  # noqa: SLF001
    seed._flush()  # noqa: SLF001

    ctx = mp.get_context("fork")
    procs = [ctx.Process(target=_writer, args=(str(path), p, 25)) for p in ("a", "b", "c")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0

    keys = {post.source_fingerprint for post in ThreatPostCache(path).all()}
    for prefix in ("a", "b", "c"):
        for i in range(25):
            assert f"{prefix}{i:015d}"[:16] in keys
    assert len(keys) == 400 + 75


def test_dual_write_failed_postgres_is_reported_not_silent(tmp_path: Path) -> None:
    json_cache = ThreatPostCache(tmp_path / "posts.json")
    pg = _MemStore()
    cache = DualWriteThreatPostCache(json_cache, pg)
    fp = "b" * 16
    cache.set(fp, "en", _post(fp))                    # pending in both
    assert pg.get(fp, "en").review_status == "pending"  # type: ignore[union-attr]

    pg.fail = True
    with pytest.raises(SecondaryWriteError):
        apply_decision(cache, fp, "en", "approve", "editor", now=T0)
    # JSON (authoritative, read first) already holds the decision ...
    assert json_cache.get(fp, "en").review_status == "approved"  # type: ignore[union-attr]
    # ... Postgres still has the old one — which is exactly why it must not be silent.
    assert pg.get(fp, "en").review_status == "pending"  # type: ignore[union-attr]

    pg.fail = False
    apply_decision(cache, fp, "en", "approve", "editor", now=T0)   # retry
    assert pg.get(fp, "en").review_status == "approved"  # type: ignore[union-attr]
    assert pg.get(fp, "en").reviewed_at == json_cache.get(fp, "en").reviewed_at  # type: ignore[union-attr]


def test_dual_write_restart_and_pg_fallback_keep_the_decision(tmp_path: Path) -> None:
    path = tmp_path / "posts.json"
    pg = _MemStore()
    fp = "c" * 16
    DualWriteThreatPostCache(ThreatPostCache(path), pg).set(fp, "en", _post(fp))
    apply_decision(DualWriteThreatPostCache(ThreatPostCache(path), pg), fp, "en", "reject", "ed")

    # Restart: fresh wrapper, same files.
    fresh = DualWriteThreatPostCache(ThreatPostCache(path), pg)
    assert fresh.get(fp, "en").review_status == "rejected"  # type: ignore[union-attr]
    # JSON lost (e.g. rebuilt from an older backup): the PG fallback must
    # still serve the decision, not resurrect "pending".
    path.unlink()
    assert DualWriteThreatPostCache(ThreatPostCache(path), pg).get(fp, "en").review_status == "rejected"  # type: ignore[union-attr]


def test_render_writes_keep_shadow_semantics(tmp_path: Path) -> None:
    pg = _MemStore()
    pg.fail = True
    cache = DualWriteThreatPostCache(ThreatPostCache(tmp_path / "posts.json"), pg)
    cache.set("d" * 16, "en", _post("d" * 16, "auto"))     # must not raise
    assert cache.shadow_stats["failures"] == 1
