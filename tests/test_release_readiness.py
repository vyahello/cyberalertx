"""Release-readiness checks that must hold on the production venv as it is
today (no `cryptography` installed) and on defaults alone.

* The API imports and serves without `cryptography`; Threads fails closed.
* A token can never be stored in plaintext — not even when encryption is
  unavailable.
* Every publication path stays off by default; `--limit` means what the
  scheduler plan says it means; no new schedule appears from defaults.
"""
from __future__ import annotations

import builtins
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def no_cryptography(monkeypatch: pytest.MonkeyPatch) -> None:
    real = builtins.__import__

    def fake(name: str, *a: Any, **k: Any) -> Any:
        if name == "cryptography" or name.startswith("cryptography."):
            raise ImportError("simulated: cryptography not installed")
        return real(name, *a, **k)
    for mod in [m for m in sys.modules if m == "cryptography" or m.startswith("cryptography.")]:
        monkeypatch.delitem(sys.modules, mod)
    monkeypatch.setattr(builtins, "__import__", fake)


def test_token_storage_fails_closed_without_cryptography(no_cryptography: None, tmp_path: Path) -> None:
    from cyberalertx.threads.accounts import AccountStore, TokenStorageError
    store = AccountStore(tmp_path / "a.json", key="any-key-value")
    with pytest.raises(TokenStorageError, match="not installed"):
        store.save_connection("en", token="THLONG-plaintext-token", expires_in=60, user_id="1", username="u",
                              name="n", now=NOW)
    assert not (tmp_path / "a.json").exists()                     # nothing written at all


def test_no_plaintext_fallback_without_a_key(tmp_path: Path) -> None:
    from cyberalertx.threads.accounts import AccountStore, TokenStorageError
    with pytest.raises(TokenStorageError):
        AccountStore(tmp_path / "a.json", key="").save_connection(
            "en", token="THLONG-plaintext-token", expires_in=60, user_id="1", username="u", name="n", now=NOW)
    assert not (tmp_path / "a.json").exists()


def test_api_serves_and_threads_page_reports_missing_package(no_cryptography: None, tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    from fastapi.testclient import TestClient

    import cyberalertx.api.app as app_mod
    import cyberalertx.threads.accounts as acc_mod
    from cyberalertx.api.admin import AdminGuard
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", "r" * 48)
    monkeypatch.setattr(acc_mod, "ACCOUNTS_PATH", tmp_path / "acc.json")
    import importlib.util
    real_find = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: None if name == "cryptography" else real_find(name, *a))
    c = TestClient(app_mod.build_app(feedback_path=tmp_path / "f.jsonl", admin_guard=AdminGuard()))
    assert c.get("/healthz").status_code == 200 and c.get("/posts?limit=1").status_code == 200
    auth = {"Authorization": "Basic " + base64.b64encode(b"a:" + b"r" * 48).decode()}
    page = c.get("/admin/threads", headers=auth).text
    assert "cryptography package" in page and "missing" in page


def test_every_publication_path_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("CYBERALERTX_THREADS_PUBLISH", "CYBERALERTX_TELEGRAM_ATTACH_IMAGES", "CYBERALERTX_PUBLISH_TOP10_AT",
                "CYBERALERTX_PUBLISH_BREAKING_UPDATES", "CYBERALERTX_IMAGE_PROVIDER", "CYBERALERTX_HIDE_OUT_OF_SCOPE",
                "CYBERALERTX_REVIEW_MODE"):
        monkeypatch.delenv(var, raising=False)
    from cyberalertx.ai.review import review_mode
    from cyberalertx.media.illustrations import provider_from_env
    from cyberalertx.pipeline.relevance import hide_out_of_scope_publicly
    from cyberalertx.publish.config import build_telegram_settings
    from cyberalertx.publish.orchestrator import PublishPolicy
    from cyberalertx.threads.config import ThreadsSettings
    from cyberalertx.tools.publish import _threads_destinations
    assert ThreadsSettings.from_env().publish_enabled is False and _threads_destinations("https://x") == {}
    assert build_telegram_settings().attach_images is False
    p = PublishPolicy.from_env(None)
    assert p.top10_at == "" and p.breaking_updates is False
    assert provider_from_env().name == "none"
    assert hide_out_of_scope_publicly() is False and review_mode() == "flag"


def test_limit_semantics_for_the_scheduler_plan(tmp_path: Path) -> None:
    """`cycle --limit N` caps TELEGRAM jobs per channel per run; website jobs
    use their own cap (500) and Threads its own (CYBERALERTX_THREADS_LIMIT)."""
    from cyberalertx.publish.jobs import PublicationJob
    from cyberalertx.publish.orchestrator import PublishPolicy, _selector

    class On:
        def enabled(self, locale: str) -> bool:
            return True
    jobs = [PublicationJob(job_id=f"s:{i}:{loc}:{d}:initial", story_key=f"s:{i}", fingerprint=f"f{i}", locale=loc,
                           destination=d) for i in range(5) for loc in ("en", "ua")
            for d in ("website", "telegram", "threads@en" if loc == "en" else "threads@ua")]
    chosen = _selector({"website": On(), "telegram": On(), "threads@en": On(), "threads@ua": On()},
                       PublishPolicy(threads_per_run=1), limit=1)(jobs)
    count: dict[tuple[str, str], int] = {}
    for j in chosen:
        count[(j.destination, j.locale)] = count.get((j.destination, j.locale), 0) + 1
    assert count == {("website", "en"): 5, ("website", "ua"): 5, ("telegram", "en"): 1, ("telegram", "ua"): 1,
                     ("threads@en", "en"): 1, ("threads@ua", "ua"): 1}


def test_cycle_without_send_is_a_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    """The scheduler command is safe to rehearse: without --send, nothing is
    written to the job store and nothing is delivered."""
    import cyberalertx.tools.publish as cli
    from tests.test_publication import Bot, item, setup
    it = item(1)
    bot = Bot()
    store, src, d, _ = setup(tmp_path, it, bot=bot)
    (tmp_path / "jobs.json").unlink()
    monkeypatch.setattr(cli, "_source", lambda: src)
    monkeypatch.setattr(cli, "_destinations", lambda s: d)
    monkeypatch.setattr(cli, "_ledger_has", lambda: (lambda fp, loc: False))
    assert cli.main(["--jobs", str(tmp_path / "jobs.json"), "cycle", "--limit", "1"]) == 0
    assert not (tmp_path / "jobs.json").exists() and not bot.calls
    assert "preview only" in capsys.readouterr().err


def test_refused_send_writes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Stage B finding: `cycle --send` without a bot token used to plan (and
    write jobs) before refusing. A refused command must not write."""
    import cyberalertx.tools.publish as cli
    from tests.test_publication import item, source_for
    monkeypatch.setenv("CYBERALERTX_TELEGRAM_CHANNEL_EN", "@fake_en")
    monkeypatch.delenv("CYBERALERTX_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(cli, "_source", lambda: source_for(item(1)))
    monkeypatch.setattr(cli, "_ledger_has", lambda: (lambda fp, loc: False))
    assert cli.main(["--jobs", str(tmp_path / "jobs.json"), "cycle", "--send", "--limit", "1"]) == 2
    assert not (tmp_path / "jobs.json").exists() and not (tmp_path / "jobs.lock").exists()
