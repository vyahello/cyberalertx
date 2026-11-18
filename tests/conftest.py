"""Shared test isolation.

The observability singletons persist to `data/quality_metrics.json` and
`data/source_health.json` on every bump. Any test that runs the generator
(directly, or through the API) bumps them, so without this the suite rewrote
the real data files on every run. Each test now gets its own throwaway files.
"""
from __future__ import annotations

# ---------------------------------------------------------------- configuration isolation (O48)
# Runs when pytest loads this file, before any test module imports the app.
# A run inside the production checkout must never see production settings:
#   1. the package's .env loader is switched off (CYBERALERTX_NO_DOTENV=1);
#   2. every variable a nearby .env defines is removed from the process
#      environment (a shell may have loaded it), as are libpq's PG* defaults;
#   3. storage is forced to the JSON backend, so importing `api.app` (which
#      builds the app at import time) cannot create a Postgres engine;
#   4. a guard on the engine refuses any database URL except the dedicated
#      test database (CYBERALERTX_TEST_DB_URL) or a loopback sentinel, and
#      always refuses the database the production .env points at.
import os
from pathlib import Path
from urllib.parse import urlsplit

_KEEP = {"CYBERALERTX_TEST_DB_URL"}


def _find_dotenvs() -> list[Path]:
    found: list[Path] = []
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        for d in (start, *start.parents):
            f = d / ".env"
            if f.is_file() and f not in found:
                found.append(f)
                break
    return found


def _dotenv_items(path: Path) -> dict[str, str]:
    items: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return items
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        items[key.strip()] = value.strip().strip("'\"")
    return items


def _db_identity(url: str) -> tuple[str, int, str]:
    u = urlsplit(url.replace("postgresql+psycopg://", "postgresql://"))
    return ((u.hostname or "").lower(), u.port or 5432, u.path.lstrip("/"))


_PROD_DBS: set[tuple[str, int, str]] = set()
os.environ["CYBERALERTX_NO_DOTENV"] = "1"
for _f in _find_dotenvs():
    _items = _dotenv_items(_f)
    if _items.get("CYBERALERTX_PG_URL"):
        _PROD_DBS.add(_db_identity(_items["CYBERALERTX_PG_URL"]))
    for _k in _items:
        if _k not in _KEEP:
            os.environ.pop(_k, None)
for _k in list(os.environ):
    if (_k.startswith("PG") and _k.isupper()) or _k in ("DATABASE_URL", "CYBERALERTX_PG_URL"):
        os.environ.pop(_k, None)
os.environ["CYBERALERTX_STORAGE_BACKEND"] = "json"

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
#: Never production: RFC 5737 documentation networks and RFC 2606 reserved names.
_DOC_NETS = ("192.0.2.", "198.51.100.", "203.0.113.")
_RESERVED_TLDS = (".example", ".invalid", ".test", ".localhost")


class ProductionDatabaseRefused(RuntimeError):
    pass


def guard_database_url(url: str) -> None:
    """Allow only the test database or a loopback sentinel; never production."""
    ident = _db_identity(url)
    if ident in _PROD_DBS:
        raise ProductionDatabaseRefused("tests may not connect to the production database")
    test_url = os.environ.get("CYBERALERTX_TEST_DB_URL", "")
    host = ident[0]
    allowed = ((test_url and ident == _db_identity(test_url)) or host in _LOOPBACK
               or host.startswith(_DOC_NETS) or host.endswith(_RESERVED_TLDS))
    if not allowed:
        raise ProductionDatabaseRefused(f"tests may only use the test database or loopback, not {ident[0]!r}")


from cyberalertx.storage.pg import engine as _pg_engine  # noqa: E402  (after the environment is clean)

_pg_engine.url_guard = guard_database_url
_pg_engine.dispose_engine()

from typing import Iterator  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_observability(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    from cyberalertx.observability import metrics, source_health

    base: Path = tmp_path_factory.mktemp("observability")
    metrics._reset_singleton_for_tests(base / "quality_metrics.json")
    reset_health = getattr(source_health, "_reset_singleton_for_tests", None)
    if reset_health is not None:
        reset_health(base / "source_health.json")
    yield
    metrics._reset_singleton_for_tests(None)
    if reset_health is not None:
        reset_health(None)


@pytest.fixture(autouse=True)
def _isolated_ops_ledgers(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 6 ledgers (AI usage, admin audit) and the control room's data
    directory: never the real `data/` from a test."""
    import cyberalertx.api.app as app_mod
    from cyberalertx.ops import readmodel, usage

    base: Path = tmp_path_factory.mktemp("ops")
    monkeypatch.setattr(usage, "USAGE_PATH", base / "ai_usage.jsonl")
    monkeypatch.setattr(app_mod, "_ops_data_dir", lambda: base)
    readmodel.clear_cache()


@pytest.fixture(autouse=True)
def _isolated_media_and_telegram_marker(tmp_path_factory: pytest.TempPathFactory,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """The media store (assets, files, image usage log) and the Telegram
    activation marker: never the real `data/media` or the host's marker."""
    import cyberalertx.api.app as app_mod
    from cyberalertx.media import assets

    base: Path = tmp_path_factory.mktemp("media")
    monkeypatch.setattr(assets, "MEDIA_DIR", base)
    monkeypatch.setattr(app_mod, "_MEDIA_STORE", None)
    monkeypatch.setenv("CYBERALERTX_TELEGRAM_MARKER", str(base / "no-marker"))
    monkeypatch.delenv("CYBERALERTX_TELEGRAM_ACTIVATED_AT", raising=False)
