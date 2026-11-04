"""O28: editorial review state when the API runs on the JSON store and the
generator / publisher run in `dual` mode (the Stage C production layout).

Real objects only: the JSON cache file, a real Postgres schema (live tests are
gated on CYBERALERTX_TEST_DB_URL, a disposable database), the real FastAPI
review endpoint, the real ContentGenerator cache-hit path, the real public
visibility gate, and separate OS processes for the concurrency test.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import uuid
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from cyberalertx.ai.cache import ThreatPostCache
from cyberalertx.ai.generator import ContentGenerator
from cyberalertx.ai.models import ThreatPost
from cyberalertx.ai.review import apply_decision, is_publicly_visible
from cyberalertx.api.admin import AdminGuard
from cyberalertx.api.app import _PostService, build_app
from tests.test_ai_generator import MockProvider
from tests.test_review import TOKEN, _auth, _csrf, _item, _post

LIVE = bool(os.getenv("CYBERALERTX_TEST_DB_URL"))
needs_pg = pytest.mark.skipif(not LIVE, reason="CYBERALERTX_TEST_DB_URL not set")


# --------------------------------------------------------------------- fixtures
@pytest.fixture()
def schema(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    from sqlalchemy import text

    from cyberalertx.storage.pg.engine import dispose_engine, get_engine
    from cyberalertx.tools.pg_migrate import _list_files
    base = os.environ["CYBERALERTX_TEST_DB_URL"]
    name = f"cax_o28_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("CYBERALERTX_PG_URL", base)
    dispose_engine()
    with get_engine().begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {name}"))
    dispose_engine()
    sep = "&" if "?" in base else "?"
    monkeypatch.setenv("CYBERALERTX_PG_URL", f"{base}{sep}options={quote(f'-csearch_path={name}')}")
    for f in _list_files():
        with get_engine().begin() as conn:
            conn.exec_driver_sql(f.read_text(encoding="utf-8"))
    yield name
    dispose_engine()
    monkeypatch.setenv("CYBERALERTX_PG_URL", base)
    with get_engine().begin() as conn:
        conn.execute(text(f"DROP SCHEMA {name} CASCADE"))
    dispose_engine()


class _Svc(_PostService):
    def __init__(self, items: list[Any], cache: Any) -> None:
        self._items = items
        self._generator = ContentGenerator(provider=None, cache=cache)

    def list_items(self) -> list[Any]:
        return list(self._items)


def _api(tmp: Path, items: list[Any], monkeypatch: pytest.MonkeyPatch, *, raise_errors: bool = True) -> TestClient:
    """The production API: JSON store only (the Stage C drop-in)."""
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", TOKEN)
    cache = ThreatPostCache(tmp / "threat_posts.json")
    app = build_app(service=_Svc(items, cache), feedback_path=tmp / "f.jsonl", admin_guard=AdminGuard())
    return TestClient(app, raise_server_exceptions=raise_errors)


def _decide(c: TestClient, key: str, decision: str) -> Any:
    page = next(h for h in (c.get(f"/admin/review?status={st}", headers=_auth()).text
                            for st in ("pending", "auto", "approved", "rejected")) if 'name="csrf"' in h)
    token = _csrf(page)
    return c.post("/admin/review/decide", headers=_auth(**{"Sec-Fetch-Site": "same-origin", "Origin": "null"}),
                  data={"key": key, "decision": decision, "csrf": token}, follow_redirects=False)


def _dual(path: Path) -> Any:
    """The production generator / publisher cache: JSON first, PG fallback and shadow."""
    from cyberalertx.storage.dual_write import DualWriteThreatPostCache
    from cyberalertx.storage.pg.threat_cache import PgThreatPostStore
    return DualWriteThreatPostCache(ThreatPostCache(path), PgThreatPostStore())


def _seed(path: Path, items: list[Any], status: str = "pending", *, also_pg: bool = True) -> None:
    """A generate run in dual mode wrote these posts to JSON and PG."""
    cache = _dual(path) if also_pg else ThreatPostCache(path)
    for it in items:
        for loc in ("en", "ua"):
            cache.set(it.fingerprint, loc, _post(it, loc, status))


def _pg_status(fp: str, loc: str) -> str:
    from cyberalertx.storage.pg.threat_cache import PgThreatPostStore
    p = PgThreatPostStore().get(fp, loc)
    return p.review_status if p else "missing"


# ------------------------------------------------------- 1-2, 4-5, 7: live PG
@needs_pg
def test_approve_in_json_api_is_respected_by_dual_generator(schema: str, tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    it = _item("approve")
    _seed(tmp_path / "threat_posts.json", [it])
    r = _decide(_api(tmp_path, [it], monkeypatch), f"{it.fingerprint}:en", "approve")
    assert r.status_code == 303
    assert _pg_status(it.fingerprint, "en") == "pending"          # O28: PG not mirrored (expected)
    provider = MockProvider()
    gen = ContentGenerator(provider=provider, cache=_dual(tmp_path / "threat_posts.json"))   # generator restart
    post = gen.generate(it, language="en")
    assert post.review_status == "approved" and provider.calls == []   # cache hit, JSON wins, no AI call
    assert _PostService._cached_visible(_dual(tmp_path / "threat_posts.json"), it.fingerprint, "en")


@needs_pg
def test_reject_in_json_api_is_never_generated_or_published_by_dual(schema: str, tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    it = _item("reject")
    _seed(tmp_path / "threat_posts.json", [it], status="auto")
    assert _decide(_api(tmp_path, [it], monkeypatch), f"{it.fingerprint}:ua", "reject").status_code == 303
    assert _pg_status(it.fingerprint, "ua") == "auto"             # stale PG says visible
    dual = _dual(tmp_path / "threat_posts.json")
    provider = MockProvider()
    assert ContentGenerator(provider=provider, cache=dual).generate(it, language="ua").review_status == "rejected"
    assert provider.calls == []
    assert not _PostService._cached_visible(dual, it.fingerprint, "ua")      # site, RSS, Telegram gate
    from cyberalertx.publish.orchestrator import EditionSource               # the new publisher's source
    svc = _Svc([it], dual)
    assert EditionSource(svc).review_status(it.fingerprint, "ua") == "rejected"
    assert EditionSource(svc).payload(it, "ua") is None                       # nothing to publish


@needs_pg
def test_decisions_survive_api_and_generator_restarts(schema: str, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = _item("ra"), _item("rb")
    _seed(tmp_path / "threat_posts.json", [a, b])
    c = _api(tmp_path, [a, b], monkeypatch)
    assert _decide(c, f"{a.fingerprint}:en", "approve").status_code == 303
    assert _decide(c, f"{b.fingerprint}:en", "reject").status_code == 303
    c2 = _api(tmp_path, [a, b], monkeypatch)                       # API restart: new process state
    assert ThreatPostCache(tmp_path / "threat_posts.json").get(a.fingerprint, "en").review_status == "approved"
    detail = c2.get(f"/posts/{b.fingerprint}").json()               # UA still visible, EN rejected
    assert "en" not in (detail.get("translations") or {}) and "ua" in detail["translations"]
    for _ in range(2):                                             # generator restarts
        d = _dual(tmp_path / "threat_posts.json")
        assert d.get(a.fingerprint, "en").review_status == "approved"
        assert d.get(b.fingerprint, "en").review_status == "rejected"


@needs_pg
def test_stale_pg_never_overrides_a_newer_json_decision(schema: str, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    it = _item("stale")
    _seed(tmp_path / "threat_posts.json", [it])
    apply_decision(ThreatPostCache(tmp_path / "threat_posts.json"), it.fingerprint, "en", "reject", "admin:t")
    from cyberalertx.storage.pg.threat_cache import PgThreatPostStore
    PgThreatPostStore().set(it.fingerprint, "en", _post(it, "en", "approved"))   # conflicting, wrong PG
    d = _dual(tmp_path / "threat_posts.json")
    assert d.get(it.fingerprint, "en").review_status == "rejected"
    assert not _PostService._cached_visible(d, it.fingerprint, "en")


def _run_refresh(monkeypatch: pytest.MonkeyPatch, items: list[Any], cache: Any, provider: Any) -> int:
    """Run the real `generate --refresh` command (main.cmd_generate) with a mock
    provider on the given cache; only the AI provider and the item list are
    substituted."""
    import cyberalertx.ai.generator as gen_mod
    import cyberalertx.main as main_mod
    monkeypatch.setattr(gen_mod, "build_default_generator",
                        lambda **_: ContentGenerator(provider=provider, cache=cache))
    monkeypatch.setattr(_PostService, "list_items", lambda self: list(items))
    return main_mod.main(["generate", "--refresh"])


@needs_pg
def test_refresh_keeps_the_editor_decision(schema: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`generate --refresh` (main.py) must not bring a rejected edition back
    and must not discard an approval."""
    rej, ok = _item("refresh-rej"), _item("refresh-app")
    _seed(tmp_path / "threat_posts.json", [rej, ok], status="auto")
    j = ThreatPostCache(tmp_path / "threat_posts.json")
    apply_decision(j, rej.fingerprint, "en", "reject", "admin:t")
    apply_decision(j, ok.fingerprint, "en", "approve", "admin:t")
    d = _dual(tmp_path / "threat_posts.json")
    provider = MockProvider()
    assert _run_refresh(monkeypatch, [rej, ok], d, provider) == 0
    d = _dual(tmp_path / "threat_posts.json")
    assert d.get(rej.fingerprint, "en").review_status == "rejected"          # not deleted, not re-rendered
    assert d.get(rej.fingerprint, "en").generated_by == "mock:test" and d.get(rej.fingerprint, "en").title == _post(rej, "en").title
    assert not _PostService._cached_visible(d, rej.fingerprint, "en")
    approved = d.get(ok.fingerprint, "en")
    assert approved.review_status == "approved" and approved.reviewed_by == "admin:t"
    assert approved.title != _post(ok, "en").title                          # re-rendered with the new text
    assert _pg_status(ok.fingerprint, "en") == "approved"                   # carried strictly to PG too
    ua = d.get(ok.fingerprint, "ua")     # unreviewed edition: refreshed as before (the mock's English UA
    assert ua is None or ua.review_status in ("auto", "pending")           # answer fails validation -> not cached)


@needs_pg
def test_refresh_render_failure_restores_an_approved_post(schema: str, tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    ok = _item("refresh-fail")
    _seed(tmp_path / "threat_posts.json", [ok], status="auto")
    apply_decision(ThreatPostCache(tmp_path / "threat_posts.json"), ok.fingerprint, "en", "approve", "admin:t")
    import cyberalertx.api.app as app_mod
    monkeypatch.setattr(app_mod._PostService, "render", lambda self, item: (_ for _ in ()).throw(RuntimeError("boom")))
    _run_refresh(monkeypatch, [ok], _dual(tmp_path / "threat_posts.json"), MockProvider())
    back = _dual(tmp_path / "threat_posts.json").get(ok.fingerprint, "en")
    assert back is not None and back.review_status == "approved" and back.title == _post(ok, "en").title


# ------------------------------------------------------------- 6: concurrency
def _decider(path: str, keys: list[str], q: Any) -> None:
    c = ThreatPostCache(Path(path))
    for k in keys:
        fp, loc = k.split(":")
        apply_decision(c, fp, loc, "reject", "admin:p")
    q.put(len(keys))


def _renderer(path: str, n: int, q: Any) -> None:
    c = ThreatPostCache(Path(path))
    for i in range(n):
        it = _item(f"new{i}")
        c.set(it.fingerprint, "en", _post(it, "en"))
    q.put(n)


def test_concurrent_api_decisions_and_generator_writes_lose_nothing(tmp_path: Path) -> None:
    path = tmp_path / "threat_posts.json"
    items = [_item(f"c{i}") for i in range(60)]
    _seed(path, items, also_pg=False)
    keys = [f"{it.fingerprint}:{loc}" for it in items for loc in ("en", "ua")]
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    procs = [ctx.Process(target=_decider, args=(str(path), keys[0::2], q)),
             ctx.Process(target=_decider, args=(str(path), keys[1::2], q)),
             ctx.Process(target=_renderer, args=(str(path), 80, q))]
    for p in procs:
        p.start()
    for p in procs:
        p.join(120)
        assert p.exitcode == 0
    final = json.loads(path.read_text())["posts"]
    assert all(final[k]["review_status"] == "rejected" for k in keys)      # no decision lost
    assert sum(1 for k in final if k not in keys) == 80                    # no render lost


# ------------------------------------------------------------- 3: flag / hold
def test_flag_and_hold_policy_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    it = _item("policy")
    p = _post(it, "en", "pending")
    monkeypatch.delenv("CYBERALERTX_REVIEW_MODE", raising=False)
    assert is_publicly_visible(p)                                   # flag (default): pending stays up
    assert not is_publicly_visible(_post(it, "en", "rejected"))
    monkeypatch.setenv("CYBERALERTX_REVIEW_MODE", "hold")
    assert not is_publicly_visible(p)
    assert is_publicly_visible(_post(it, "en", "approved"))


# ------------------------------------------------ 8: malformed / missing JSON
def test_unreadable_cache_file_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "threat_posts.json"
    _seed(path, [_item("m1"), _item("m2")], also_pg=False)
    good = path.read_text()
    path.write_text(good[: len(good) // 2])                         # truncated / malformed
    broken = path.read_text()
    c = ThreatPostCache(path)
    it = _item("m3")
    with pytest.raises(Exception):
        c.set(it.fingerprint, "en", _post(it, "en"))                # a new render must not wipe the file
    with pytest.raises(Exception):
        apply_decision(c, _item("m1").fingerprint, "en", "approve", "admin:t")
    assert path.read_text() == broken                               # every post still recoverable


def test_unreadable_cache_fails_safe_for_readers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    it = _item("ro")
    path = tmp_path / "threat_posts.json"
    _seed(path, [it], status="auto", also_pg=False)
    apply_decision(ThreatPostCache(path), it.fingerprint, "en", "reject", "admin:t")
    path.write_text("{ not json")
    c = _api(tmp_path, [it], monkeypatch)
    r = c.get(f"/posts/{it.fingerprint}?language=en")
    assert r.status_code == 404 or r.json().get("generated_by") == "rule_based"   # rejected AI text never served
    assert c.get("/posts").json()["items"] == []                                  # feed (cached only) empty
    assert 'name="csrf"' not in c.get("/admin/review?status=rejected", headers=_auth()).text  # nothing to decide on
    with pytest.raises(KeyError):                                                 # and the store refuses quietly-wrong writes
        apply_decision(ThreatPostCache(path), it.fingerprint, "en", "approve", "admin:t")
    assert path.read_text() == "{ not json"


# ------------------------------------------------------ 9: write failures
def test_json_write_failure_is_reported_not_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    it = _item("wf")
    _seed(tmp_path / "threat_posts.json", [it], also_pg=False)
    c = _api(tmp_path, [it], monkeypatch, raise_errors=False)
    token = _csrf(c.get("/admin/review", headers=_auth()).text)
    os.chmod(tmp_path, 0o500)                                       # directory read-only: no temp file
    try:
        r = c.post("/admin/review/decide", headers=_auth(**{"Sec-Fetch-Site": "same-origin", "Origin": "null"}),
                   data={"key": f"{it.fingerprint}:en", "decision": "approve", "csrf": token}, follow_redirects=False)
    finally:
        os.chmod(tmp_path, 0o700)
    assert r.status_code >= 500 and r.status_code != 303
    assert ThreatPostCache(tmp_path / "threat_posts.json").get(it.fingerprint, "en").review_status == "pending"


@needs_pg
def test_pg_write_failure_in_dual_mode_is_raised(schema: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cyberalertx.storage.dual_write import SecondaryWriteError
    from cyberalertx.storage.pg.engine import dispose_engine
    it = _item("pgdown")
    _seed(tmp_path / "threat_posts.json", [it])
    d = _dual(tmp_path / "threat_posts.json")
    monkeypatch.setenv("CYBERALERTX_PG_URL", "postgresql://u:p@127.0.0.1:1/none")
    dispose_engine()
    with pytest.raises(SecondaryWriteError):
        apply_decision(d, it.fingerprint, "en", "approve", "admin:t")
    assert ThreatPostCache(tmp_path / "threat_posts.json").get(it.fingerprint, "en").review_status == "approved"


@needs_pg
def test_unreadable_json_never_falls_back_to_stale_pg_review_state(schema: str, tmp_path: Path) -> None:
    """While the API runs JSON-only, PG lags on decisions. If the JSON file
    became unreadable, a dual reader (generator, Stage D publisher) must not
    serve PG's stale copy of a post the editor rejected: fail closed."""
    it = _item("stale-fallback")
    path = tmp_path / "threat_posts.json"
    _seed(path, [it], status="auto")                                  # PG: auto (visible)
    apply_decision(ThreatPostCache(path), it.fingerprint, "en", "reject", "admin:t")   # JSON only
    assert _pg_status(it.fingerprint, "en") == "auto"
    path.write_text("{ not json")
    d = _dual(path)
    assert d.get(it.fingerprint, "en") is None                        # no stale resurrection
    from cyberalertx.publish.orchestrator import EditionSource
    assert EditionSource(_Svc([it], d)).payload(it, "en") is None      # nothing publishable
    with pytest.raises(Exception):
        d.set(it.fingerprint, "en", _post(it, "en"))                   # and nothing overwrites the file
    assert path.read_text() == "{ not json"
