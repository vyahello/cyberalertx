"""O48: the test suite can never use production database settings.

The production checkout has a `.env` with the real Postgres URL and
`CYBERALERTX_STORAGE_BACKEND=dual`. Importing `cyberalertx.api.app` builds the
app at import time; before the fix that cached a Postgres engine from `.env`,
and later test overrides were ignored. These tests prove the isolation in
tests/conftest.py and the engine's URL-following cache close that path."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import tests.conftest as conftest
from cyberalertx.storage.pg import engine as eng

REPO = Path(__file__).resolve().parents[1]
SENTINEL = "postgresql://prod_user:prod-SECRET@db.prod-sentinel.invalid:5432/production"


def test_the_session_carries_no_production_settings() -> None:
    assert os.environ.get("CYBERALERTX_NO_DOTENV") == "1"
    assert os.environ.get("CYBERALERTX_STORAGE_BACKEND") == "json"
    assert "CYBERALERTX_PG_URL" not in os.environ and "DATABASE_URL" not in os.environ
    assert not [k for k in os.environ if k.startswith("PG") and k.isupper()]
    assert eng.url_guard is conftest.guard_database_url


def test_the_guard_refuses_production_and_remote_databases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conftest, "_PROD_DBS", {("db.prod-sentinel.invalid", 5432, "production")})
    with pytest.raises(conftest.ProductionDatabaseRefused, match="production"):
        conftest.guard_database_url(SENTINEL)
    with pytest.raises(conftest.ProductionDatabaseRefused):
        conftest.guard_database_url("postgresql://u:p@db.some-provider.com:5432/db")
    conftest.guard_database_url("postgresql://u:p@127.0.0.1:1/none")          # loopback sentinel: allowed
    # A test-database URL pointing at production is still refused.
    monkeypatch.setenv("CYBERALERTX_TEST_DB_URL", SENTINEL)
    with pytest.raises(conftest.ProductionDatabaseRefused, match="production"):
        conftest.guard_database_url(SENTINEL)


def test_no_engine_is_built_for_a_refused_url(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []
    monkeypatch.setattr(eng, "create_engine", lambda url, **kw: built.append(str(url)))
    eng.dispose_engine()
    monkeypatch.setenv("CYBERALERTX_PG_URL", "postgresql://u:p@db.some-provider.com:5432/db")
    with pytest.raises(conftest.ProductionDatabaseRefused):
        eng.get_engine()
    assert built == [] and eng._engine is None


def test_a_cached_engine_never_outlives_a_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """The O48 mechanism: an engine built from one URL must not serve another."""
    eng.dispose_engine()
    monkeypatch.setenv("CYBERALERTX_PG_URL", "postgresql://u:p@127.0.0.1:1/first")
    first = eng.get_engine()
    assert eng.get_engine() is first                                       # same URL: cached
    monkeypatch.setenv("CYBERALERTX_PG_URL", "postgresql://u:p@127.0.0.1:2/second")
    second = eng.get_engine()
    assert second is not first and second.url.port == 2 and second.url.database == "second"
    eng.dispose_engine()


def _run(cwd: Path, code: str, *, isolate: bool) -> str:
    env = {k: v for k, v in os.environ.items() if k != "CYBERALERTX_NO_DOTENV"}
    env.pop("CYBERALERTX_STORAGE_BACKEND", None)
    env["PYTHONPATH"] = str(REPO)
    prelude = "import tests.conftest\n" if isolate else ""
    out = subprocess.run([sys.executable, "-c", prelude + textwrap.dedent(code)], cwd=cwd, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout


def test_a_production_env_file_next_to_the_checkout_cannot_be_used(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"CYBERALERTX_STORAGE_BACKEND=dual\nCYBERALERTX_PG_URL={SENTINEL}\n"
                                   "CYBERALERTX_O48_MARKER=loaded\n", encoding="utf-8")
    probe = """
        import os
        import cyberalertx
        print("marker", os.environ.get("CYBERALERTX_O48_MARKER"))
        """
    # Control: without the isolation, the package loader picks this .env up.
    assert "marker loaded" in _run(tmp_path, probe, isolate=False)

    out = _run(tmp_path, """
        import os
        import cyberalertx.api.app                      # builds the app at import time
        from cyberalertx.storage.pg import engine as eng
        from cyberalertx.ops import health
        print("marker", os.environ.get("CYBERALERTX_O48_MARKER"))
        print("backend", os.environ.get("CYBERALERTX_STORAGE_BACKEND"))
        print("pg_url_set", "CYBERALERTX_PG_URL" in os.environ)
        print("engine_cached", eng._engine is not None)
        os.environ["CYBERALERTX_PG_URL"] = %r
        try:
            eng.get_engine()
            print("refused no")
        except Exception as exc:
            print("refused", type(exc).__name__)
        os.environ["CYBERALERTX_STORAGE_BACKEND"] = "dual"
        print("probe", health.probe_database()[0])
        """ % SENTINEL, isolate=True)
    assert "marker None" in out and "backend json" in out
    assert "pg_url_set False" in out and "engine_cached False" in out
    assert "refused ProductionDatabaseRefused" in out
    assert "probe critical" in out                    # the O48 test's expectation, with no connection made
