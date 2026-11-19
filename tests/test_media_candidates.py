"""V4.1 canary in quarantine (media/candidates.py): candidates are collected
outside the image index, never served or sent, and only explicitly approved
ones reach production."""
from __future__ import annotations

import hashlib
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from cyberalertx.media import candidates as C
from cyberalertx.media import engine
from cyberalertx.media.assets import MediaStore
from tests.test_media import NOW, critical_story, fake_intel

PASS = {"relevance": 5, "recognition": 5, "visual": 4, "composition": 4, "accuracy": 5, "integrity": 5,
        "thumbnail": 5}


def _weak(key: str) -> Any:
    s = critical_story(key)
    s.anchor.title, s.anchor.raw_content = "What security teams should plan for next year", ""
    return s


@pytest.fixture()
def prod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[MediaStore, list[Any]]:
    """A production index with V3 images for two existing stories."""
    monkeypatch.delenv("CYBERALERTX_ILLUSTRATION_RENDERER", raising=False)
    old = [critical_story("s:old1"), critical_story("s:old2", products=("Gadget Hub",))]
    fake_intel(monkeypatch, old)
    store = MediaStore(tmp_path / "media")
    engine.run([s.anchor for s in old], store=store, now=NOW)
    return store, old


def _session(tmp_path: Path, store: MediaStore, old: list[Any], hours: float = 6.0) -> Path:
    return C.start(tmp_path / "review", [s.key for s in old], store=store, hours=hours, now=NOW)


def test_collect_writes_candidates_outside_the_index_and_never_serves_them(prod: Any, tmp_path: Path,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    store, old = prod
    session = _session(tmp_path, store, old)
    before = (store.index.read_bytes(), sorted(p.name for p in store.files.iterdir()))
    new = critical_story("s:new1", products=("Fresh Router",))
    res = C.collect(session, old + [new], store=store, eligible=lambda s: True, now=NOW)
    assert res["added"] == ["s:new1"] and res["candidates"] == 1
    assert (store.index.read_bytes(), sorted(p.name for p in store.files.iterdir())) == before   # untouched
    m = C._read(session / C.MANIFEST, {})["s:new1"]
    svg = (session / m["file"]).read_bytes()
    assert hashlib.sha256(svg).hexdigest() == m["svg_sha256"] and m["alt_problems"] == []
    assert store.open_file(m["svg_sha256"][:16]) is None              # no public /media URL
    assert store.get("illus:s:new1") is None                          # nothing for Telegram/Threads to send
    assert (session / "index.html").exists() is False
    assert "176 px feed crop" in C.gallery(session).read_text()


def test_existing_stories_are_not_candidates_unless_asked_and_v3_routing_is_kept(prod: Any, tmp_path: Path) -> None:
    store, old = prod
    session = _session(tmp_path, store, old)
    weak = _weak("s:weak")
    res = C.collect(session, old + [weak], store=store, eligible=lambda s: True, now=NOW)
    assert res["added"] == [] and res["routed_to_v3"] == ["s:weak"]   # hybrid policy: no V4 for a weak story
    res2 = C.collect(session, old, store=store, eligible=lambda s: True, now=NOW, recent=1)
    assert len(res2["added"]) == 1 and res2["added"][0] in {"s:old1", "s:old2"}


def test_an_expired_session_refuses_to_collect(prod: Any, tmp_path: Path) -> None:
    store, old = prod
    session = _session(tmp_path, store, old, hours=6)
    with pytest.raises(C.CandidateError, match="expired"):
        C.collect(session, old, store=store, eligible=lambda s: True, now=NOW + timedelta(hours=6, seconds=1))
    with pytest.raises(C.CandidateError):
        C.start(tmp_path / "r2", [], store=store, hours=24, now=NOW)        # no open-ended sessions


def test_review_enforces_the_gates(prod: Any, tmp_path: Path) -> None:
    store, old = prod
    session = _session(tmp_path, store, old)
    C.collect(session, old + [critical_story("s:new1", products=("Fresh Router",))], store=store,
              eligible=lambda s: True, now=NOW)
    with pytest.raises(C.CandidateError, match="gates failed"):
        C.review(session, "s:new1", scores={**PASS, "integrity": 4}, verdict="approved", reviewer="t")
    with pytest.raises(C.CandidateError, match="missing"):
        C.review(session, "s:new1", scores={"accuracy": 5}, verdict="approved", reviewer="t")
    assert C.review(session, "s:new1", scores={**PASS, "accuracy": 2}, verdict="rejected", reviewer="t")


def test_promote_publishes_only_approved_candidates_and_keeps_old_urls(prod: Any, tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    store, old = prod
    new1, new2 = critical_story("s:new1", products=("Fresh Router",)), critical_story("s:new2", products=("Edge Box",))
    stories = old + [new1, new2]
    fake_intel(monkeypatch, stories)
    engine.run([s.anchor for s in stories], store=store, now=NOW)        # production V3 for the new stories too
    v3_new1 = store.get("illus:s:new1").storage_key                        # type: ignore[union-attr]
    session = _session(tmp_path, store, old)
    C.collect(session, stories, store=store, eligible=lambda s: True, now=NOW)
    with pytest.raises(C.CandidateError, match="not approved"):
        C.promote(session, ["s:new1"], items=[s.anchor for s in stories], store=store, now=NOW)
    C.review(session, "s:new1", scores=PASS, verdict="approved", reviewer="owner")
    C.review(session, "s:new2", scores={**PASS, "accuracy": 2}, verdict="rejected", reviewer="owner")
    with pytest.raises(C.CandidateError, match="not approved"):
        C.promote(session, ["s:new2"], items=[s.anchor for s in stories], store=store, now=NOW)
    before = C.illustrations(store)
    out = C.promote(session, ["s:new1"], items=[s.anchor for s in stories], store=store, now=NOW)
    after = C.illustrations(store)
    assert {a for a in after if after[a] != before[a]} == {"illus:s:new1"}  # nothing else changed
    a = store.get("illus:s:new1")
    m = C._read(session / C.MANIFEST, {})["s:new1"]
    assert a is not None and a.generation_model == "cax-editorial-4" and a.storage_key.startswith(m["svg_sha256"])
    assert v3_new1 in a.previous_storage_keys and store.open_file(v3_new1[:16]) is not None   # old URL works
    assert out["promoted"][0]["story"] == "s:new1"
    assert os.environ.get("CYBERALERTX_ILLUSTRATION_RENDERER") is None        # production setting restored


def test_promote_refuses_a_candidate_the_deployed_code_no_longer_draws(prod: Any, tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    store, old = prod
    new1 = critical_story("s:new1", products=("Fresh Router",))
    fake_intel(monkeypatch, old + [new1])
    session = _session(tmp_path, store, old)
    C.collect(session, old + [new1], store=store, eligible=lambda s: True, now=NOW)
    C.review(session, "s:new1", scores=PASS, verdict="approved", reviewer="owner")
    data = C._read(session / C.MANIFEST, {})
    data["s:new1"]["svg_sha256"] = "0" * 64                                  # what was reviewed differs
    C._write(session / C.MANIFEST, data)
    with pytest.raises(C.CandidateError):
        C.promote(session, ["s:new1"], items=[s.anchor for s in old + [new1]], store=store, now=NOW)
    assert store.get("illus:s:new1") is None


def test_rollback_and_cleanup_restore_the_index_exactly(prod: Any, tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    store, old = prod
    new1 = critical_story("s:new1", products=("Fresh Router",))
    stories = old + [new1]
    fake_intel(monkeypatch, stories)
    engine.run([s.anchor for s in stories], store=store, now=NOW)
    backup = store.index.read_bytes()
    session = _session(tmp_path, store, old)
    C.collect(session, stories, store=store, eligible=lambda s: True, now=NOW)
    C.review(session, "s:new1", scores=PASS, verdict="approved", reviewer="owner")
    C.promote(session, ["s:new1"], items=[s.anchor for s in stories], store=store, now=NOW)
    assert store.index.read_bytes() != backup
    store.index.write_bytes(backup)                                          # documented exact restore
    assert store.get("illus:s:new1").generation_model == "cax-svg-3"         # type: ignore[union-attr]
    digest = C.cleanup(session, store=store)
    assert not session.exists() and digest == C.index_digest(store)
    assert store.index.read_bytes() == backup


def test_engine_only_touches_the_listed_stories(prod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    store, old = prod
    monkeypatch.setenv("CYBERALERTX_ILLUSTRATION_RENDERER", "editorial-4")
    before = C.illustrations(store)
    res = engine.run([s.anchor for s in old], store=store, now=NOW, upgrade_renderer=True, only=frozenset({"s:old2"}))
    assert res.generated == ["s:old2"] and "s:old1" not in res.reused
    after = C.illustrations(store)
    assert after["illus:s:old1"] == before["illus:s:old1"] and after["illus:s:old2"] != before["illus:s:old2"]
