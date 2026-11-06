"""Two Threads accounts through one Meta app: env tokens, /me mapping, token
lifecycle, the setup helper, daily cap, no backlog, and secret hygiene.
All API traffic is mocked; nothing is published."""
from __future__ import annotations

import argparse
import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from cyberalertx.threads.accounts import AccountStore, SlotConflict
from cyberalertx.threads.client import ThreadsClient, ThreadsError, scrub
from cyberalertx.threads.config import ThreadsSettings
from cyberalertx.threads.credentials import (check_pair, check_token, refresh_tokens, register,
                                             verify_accounts)
from cyberalertx.threads.envfile import EnvFileError, read_env, update_env

NOW = datetime.now(timezone.utc).replace(microsecond=0)
EN_TOK = "THAAEnTokenAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1"
UA_TOK = "THAAUaTokenBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2"
USERS = {EN_TOK: ("17841400000000001", "cyberalertx"), UA_TOK: ("17841400000000002", "cyberalertx_ua")}


class Graph:
    """A mocked Threads Graph API: /me, debug_token, refresh_access_token, access_token."""

    def __init__(self) -> None:
        self.users: dict[str, tuple[str, str]] = dict(USERS)
        self.scopes = ["threads_basic", "threads_content_publish"]
        self.lifetime = timedelta(days=60)
        self.issued = NOW - timedelta(days=40)
        self.fail: dict[str, httpx.Response] = {}
        self.calls: list[str] = []
        self.refreshed: dict[str, str] = {}

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        q = dict(req.url.params)
        self.calls.append(path)
        if path in self.fail:
            return self.fail[path]
        if path == "/v1.0/me":
            u = self.users.get(q.get("access_token", ""))
            return httpx.Response(200, json={"id": u[0], "username": u[1]}) if u else \
                httpx.Response(400, json={"error": {"message": "Invalid OAuth access token", "code": 190}})
        if path == "/v1.0/debug_token":
            u = self.users.get(q.get("input_token", ""))
            if not u:
                return httpx.Response(200, json={"data": {"is_valid": False}})
            tok = q.get("input_token", "")
            issued, life = (NOW, timedelta(days=60)) if tok.endswith("LONG") else (self.issued, self.lifetime)
            return httpx.Response(200, json={"data": {
                "type": "USER", "application": "CyberAlertX Publisher", "is_valid": True, "user_id": u[0],
                "scopes": self.scopes, "issued_at": int(issued.timestamp()),
                "expires_at": int((issued + life).timestamp()),
                "data_access_expires_at": int((NOW + timedelta(days=90)).timestamp())}})
        if path == "/refresh_access_token":
            old = q.get("access_token", "")
            new = old[:-1] + "R"
            self.users[new] = self.users[old]
            self.refreshed[old] = new
            return httpx.Response(200, json={"access_token": new, "token_type": "bearer", "expires_in": 5183944})
        if path == "/access_token":
            short = q.get("access_token", "")
            long = short + "LONG"
            self.users[long] = self.users[short]
            return httpx.Response(200, json={"access_token": long, "token_type": "bearer", "expires_in": 5183944})
        return httpx.Response(404, json={"error": {"message": "unhandled"}})

    def client(self) -> ThreadsClient:
        return ThreadsClient(client=httpx.Client(transport=httpx.MockTransport(self.handler)))


def store(tmp_path: Path, tokens: dict[str, str] | None = None) -> AccountStore:
    return AccountStore(tmp_path / "threads_accounts.json", mapping={"en": "en", "ua": "ua"},
                        env_tokens=tokens if tokens is not None else {"en": EN_TOK, "ua": UA_TOK})


def settings(**kw: Any) -> ThreadsSettings:
    base: dict[str, Any] = dict(app_id="1000000000000001", publish_enabled=True,
                                usernames={"en": "cyberalertx", "ua": "cyberalertx_ua"},
                                env_tokens={"en": EN_TOK, "ua": UA_TOK})
    base.update(kw)
    return ThreadsSettings(**base)


# ------------------------------------------------------------------ configuration

def test_one_shared_app_id_and_per_account_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in {"THREADS_ENABLED": "0", "THREADS_APP_ID": "1000000000000001", "THREADS_EN_USERNAME": "cyberalertx",
                 "THREADS_EN_ACCESS_TOKEN": EN_TOK, "THREADS_UA_USERNAME": "cyberalertx_ua",
                 "THREADS_UA_ACCESS_TOKEN": UA_TOK, "THREADS_EN_APP_ID": "9", "THREADS_UA_USER_ID": "8"}.items():
        monkeypatch.setenv(k, v)
    ts = ThreadsSettings.from_env()
    assert ts.app_id == "1000000000000001" and ts.publish_enabled is False
    assert ts.env_tokens == {"en": EN_TOK, "ua": UA_TOK} and ts.env_mode
    assert ts.usernames == {"en": "cyberalertx", "ua": "cyberalertx_ua"}
    assert EN_TOK not in repr(ts) and UA_TOK not in repr(ts)
    s = store(Path(os.environ.get("TMPDIR", "/tmp")) / "unused", ts.env_tokens)
    assert s.token("en") == EN_TOK and s.token("ua") == UA_TOK


def test_threads_enabled_is_the_switch_and_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THREADS_ENABLED", raising=False)
    monkeypatch.delenv("CYBERALERTX_THREADS_PUBLISH", raising=False)
    assert ThreadsSettings.from_env().publish_enabled is False
    monkeypatch.setenv("THREADS_ENABLED", "1")
    monkeypatch.setenv("CYBERALERTX_THREADS_PUBLISH", "0")
    assert ThreadsSettings.from_env().publish_enabled is True      # the new name wins


# ------------------------------------------------------------------ /me mapping and token info

def test_each_token_maps_to_its_own_account_with_different_ids() -> None:
    g = Graph()
    api = g.client()
    en, ua = check_token("en", EN_TOK, "cyberalertx", api), check_token("ua", UA_TOK, "cyberalertx_ua", api)
    assert en.ok and ua.ok and en.user_id != ua.user_id and check_pair([en, ua]) == []
    assert en.user_id == "17841400000000001" and en.user_id != "1000000000000001"   # never the app id
    assert en.expires_at and abs((en.expires_at - (g.issued + g.lifetime)).total_seconds()) < 2
    assert set(en.scopes) == {"threads_basic", "threads_content_publish"} and en.token_type == "USER"
    assert not en.short_lived()


def test_a_swapped_or_shared_token_is_refused() -> None:
    api = Graph().client()
    wrong = check_token("en", UA_TOK, "cyberalertx", api)
    assert not wrong.ok and any("@cyberalertx_ua, expected @cyberalertx" in p for p in wrong.problems)
    same = [check_token("en", EN_TOK, "cyberalertx", api), check_token("ua", EN_TOK, "cyberalertx", api)]
    assert check_pair(same) == ["both tokens belong to the same Threads user"]


def test_missing_permission_invalid_and_expired_tokens_are_refused() -> None:
    g = Graph()
    g.scopes = ["threads_basic"]
    assert any("missing permissions: threads_content_publish" in p
               for p in check_token("en", EN_TOK, "cyberalertx", g.client()).problems)
    assert not check_token("en", "THAAbogus" + "X" * 30, "cyberalertx", Graph().client()).ok
    g2 = Graph()
    g2.issued = NOW - timedelta(days=70)
    assert any("expired" in p for p in check_token("en", EN_TOK, "cyberalertx", g2.client()).problems)


def test_short_lived_tokens_are_detected() -> None:
    g = Graph()
    g.issued, g.lifetime = NOW - timedelta(minutes=5), timedelta(hours=1)
    assert check_token("en", EN_TOK, "cyberalertx", g.client()).short_lived()


@pytest.mark.parametrize("status, category", [(429, "rate_limit"), (500, "temporary"), (503, "temporary")])
def test_api_errors_are_classified_and_redacted(status: int, category: str) -> None:
    g = Graph()
    g.fail["/v1.0/me"] = httpx.Response(status, json={"error": {"message": f"boom access_token={EN_TOK}"}})
    with pytest.raises(ThreadsError) as exc:
        g.client().me(EN_TOK)
    assert exc.value.category == category and EN_TOK not in str(exc.value)


def test_timeouts_are_network_or_unknown_and_never_leak() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout(f"timed out {req.url}")
    api = ThreadsClient(client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(ThreadsError) as exc:
        api.me(EN_TOK)
    assert exc.value.category == "network" and EN_TOK not in str(exc.value)
    assert scrub(f"x access_token={EN_TOK}&y") == "x access_token=[redacted]&y"


# ------------------------------------------------------------------ registry and verification

def test_registry_holds_no_secret_and_refuses_identity_swaps(tmp_path: Path) -> None:
    api = Graph().client()
    s = store(tmp_path)
    register(s, check_token("en", EN_TOK, "cyberalertx", api), EN_TOK, NOW)
    register(s, check_token("ua", UA_TOK, "cyberalertx_ua", api), UA_TOK, NOW)
    raw = (tmp_path / "threads_accounts.json").read_text()
    assert EN_TOK not in raw and UA_TOK not in raw and "17841400000000002" in raw
    assert stat.S_IMODE((tmp_path / "threads_accounts.json").stat().st_mode) == 0o600
    with pytest.raises(SlotConflict):
        register(s, check_token("ua", EN_TOK, "cyberalertx", api), EN_TOK, NOW)
    assert s.get("ua").threads_user_id == "17841400000000002"


def test_verify_stops_only_the_mismatched_account(tmp_path: Path) -> None:
    g = Graph()
    s = store(tmp_path)
    register(s, check_token("en", EN_TOK, "cyberalertx", g.client()), EN_TOK, NOW)
    register(s, check_token("ua", UA_TOK, "cyberalertx_ua", g.client()), UA_TOK, NOW)
    g.users[UA_TOK] = ("17841400000000009", "someone_else")              # UA token now another profile
    res = {r.slot: r.outcome for r in verify_accounts(settings(), s, g.client(), NOW)}
    assert res == {"en": "ok", "ua": "mismatch"}
    assert s.get("en").status == "connected" and s.get("ua").status == "needs_reconnect"


def test_an_unregistered_account_is_never_guessed(tmp_path: Path) -> None:
    s = store(tmp_path)
    res = {r.slot: (r.outcome, r.detail) for r in verify_accounts(settings(), s, Graph().client(), NOW)}
    assert res["en"] == ("mismatch", "unregistered") and s.get("en").status == "needs_reconnect"


# ------------------------------------------------------------------ refresh

def _env(tmp_path: Path) -> Path:
    p = tmp_path / ".env"
    p.write_text(f"# app\nCYBERALERTX_TELEGRAM_BOT_TOKEN=keepme\nTHREADS_ENABLED=0\nTHREADS_EN_ACCESS_TOKEN={EN_TOK}\n"
                 f"THREADS_UA_ACCESS_TOKEN={UA_TOK}\n")
    p.chmod(0o600)
    return p


def test_refresh_writes_env_atomically_and_isolates_accounts(tmp_path: Path) -> None:
    g = Graph()
    s = store(tmp_path)
    register(s, check_token("en", EN_TOK, "cyberalertx", g.client()), EN_TOK, NOW)
    register(s, check_token("ua", UA_TOK, "cyberalertx_ua", g.client()), UA_TOK, NOW)
    env = _env(tmp_path)
    g.fail["/refresh_access_token"] = httpx.Response(500, json={"error": {"message": "temporary"}})
    res = {r.slot: r.outcome for r in refresh_tokens(settings(), s, g.client(), NOW, env_path=env,
                                                    backup_dir=tmp_path / "bk")}
    assert res == {"en": "failed", "ua": "failed"} and read_env(env)["THREADS_EN_ACCESS_TOKEN"] == EN_TOK
    del g.fail["/refresh_access_token"]
    res = {r.slot: r.outcome for r in refresh_tokens(settings(), s, g.client(), NOW, env_path=env,
                                                    backup_dir=tmp_path / "bk")}
    assert res == {"en": "refreshed", "ua": "refreshed"}
    vals = read_env(env)
    assert vals["THREADS_EN_ACCESS_TOKEN"] == g.refreshed[EN_TOK] and vals["CYBERALERTX_TELEGRAM_BOT_TOKEN"] == "keepme"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600 and s.token("en") == g.refreshed[EN_TOK]
    assert list((tmp_path / "bk").iterdir()) == []                      # old-token backups removed once confirmed
    assert stat.S_IMODE((tmp_path / "bk").stat().st_mode) == 0o700


def test_refresh_waits_for_24h_and_for_the_due_window(tmp_path: Path) -> None:
    g = Graph()
    g.issued = NOW - timedelta(hours=2)
    s = store(tmp_path)
    register(s, check_token("en", EN_TOK, "cyberalertx", g.client()), EN_TOK, NOW)
    out = refresh_tokens(settings(), s, g.client(), NOW, env_path=_env(tmp_path), backup_dir=tmp_path / "bk")
    assert {r.slot: r.outcome for r in out}["en"] == "not_due"
    out = refresh_tokens(settings(), s, g.client(), NOW, env_path=_env(tmp_path), backup_dir=tmp_path / "bk",
                         when_left=timedelta(days=90))
    assert {r.slot: r.outcome for r in out}["en"] == "too_new" and "/refresh_access_token" not in g.calls


def test_env_updater_refuses_unsafe_values(tmp_path: Path) -> None:
    env = _env(tmp_path)
    for bad in ('a b', 'a"b', "a$b", "a#b", "a\\b"):
        with pytest.raises(EnvFileError) as exc:
            update_env(env, {"THREADS_EN_ACCESS_TOKEN": bad}, backup_dir=tmp_path / "bk")
        assert bad not in str(exc.value)


# ------------------------------------------------------------------ setup helper

def _setup(tmp_path: Path, answers: list[str], g: Graph, **kw: Any) -> tuple[int, Path, AccountStore]:
    from cyberalertx.tools import threads as tool
    env = tmp_path / ".env"
    if not env.exists():
        env.write_text("CYBERALERTX_TELEGRAM_BOT_TOKEN=keepme\n# comment stays\nTHREADS_APP_ID=1000000000000001\n")
        env.chmod(0o600)
    reg = AccountStore(tmp_path / "threads_accounts.json", mapping={"en": "en", "ua": "ua"})
    it = iter(answers)
    rc = tool.cmd_setup(argparse.Namespace(env=str(env), allow_identity_change=kw.get("allow", False)),
                        ask=lambda prompt: next(it), client=g.client(), store=reg)
    return rc, env, reg


def test_setup_validates_both_then_writes_env_and_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    rc, env, reg = _setup(tmp_path, [EN_TOK, UA_TOK], Graph())
    out = capsys.readouterr()
    assert rc == 0
    vals = read_env(env)
    assert vals["THREADS_APP_ID"] == "1000000000000001" and vals["THREADS_ENABLED"] == "0"
    assert vals["THREADS_EN_ACCESS_TOKEN"] == EN_TOK and vals["CYBERALERTX_TELEGRAM_BOT_TOKEN"] == "keepme"
    assert "# comment stays" in env.read_text() and "THREADS_APP_SECRET" not in vals
    assert not any(k.startswith(("THREADS_EN_USER_ID", "THREADS_UA_USER_ID", "THREADS_EN_APP", "THREADS_UA_APP"))
                   for k in vals)
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    backups = list((tmp_path / "backups" / "threads").iterdir())
    assert len(backups) == 1 and stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    assert reg.get("en").threads_user_id == "17841400000000001" and reg.get("ua").username == "cyberalertx_ua"
    assert EN_TOK not in out.out + out.err and UA_TOK not in out.out + out.err


def test_setup_changes_nothing_when_one_account_maps_wrong(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    rc, env, reg = _setup(tmp_path, [EN_TOK, EN_TOK], Graph())
    assert rc == 1 and "THREADS_EN_ACCESS_TOKEN" not in env.read_text()
    assert not (tmp_path / "backups").exists() and reg.get("en").threads_user_id == ""


def test_setup_never_enables_and_keeps_an_existing_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    env = tmp_path / ".env"
    env.write_text("THREADS_ENABLED=1\nTHREADS_APP_ID=1000000000000001\n")
    env.chmod(0o600)
    rc, env, _ = _setup(tmp_path, [EN_TOK, UA_TOK], Graph())
    assert rc == 0 and read_env(env)["THREADS_ENABLED"] == "1"           # untouched, not forced either way


def test_setup_exchanges_a_short_lived_token_with_one_shared_secret(tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    g = Graph()
    g.issued, g.lifetime = NOW - timedelta(minutes=1), timedelta(hours=1)
    asked: list[str] = []
    answers = iter([EN_TOK, UA_TOK, "app-secret-123"])

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return next(answers)
    from cyberalertx.tools import threads as tool
    env = tmp_path / ".env"
    env.write_text("X=1\nTHREADS_APP_ID=1000000000000001\n")
    env.chmod(0o600)
    reg = AccountStore(tmp_path / "threads_accounts.json", mapping={"en": "en", "ua": "ua"})
    rc = tool.cmd_setup(argparse.Namespace(env=str(env), allow_identity_change=False), ask=ask,
                        client=g.client(), store=reg)
    assert rc == 0 and sum("App Secret" in a for a in asked) == 1      # one shared secret, asked once
    vals = read_env(env)
    assert vals["THREADS_EN_ACCESS_TOKEN"] == EN_TOK + "LONG" and vals["THREADS_UA_ACCESS_TOKEN"] == UA_TOK + "LONG"
    assert vals["THREADS_APP_SECRET"] == "app-secret-123"


def test_setup_refuses_a_silent_identity_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    g = Graph()
    rc, env, reg = _setup(tmp_path, [EN_TOK, UA_TOK], g)
    assert rc == 0
    new = "THAAUaNewProfileCCCCCCCCCCCCCCCCCCCCCCCCCC3"
    g.users[new] = ("17841400000000077", "cyberalertx_ua")               # same username, different user id
    before = env.read_text()
    rc2, env, reg2 = _setup(tmp_path, ["", new], g)
    assert rc2 == 1 and env.read_text() == before


# ------------------------------------------------------------------ daily cap, no backlog, qualifiers

def test_daily_cap_and_no_backlog(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from cyberalertx.publish.destinations import INELIGIBLE, WAITING, DeliveryError
    from cyberalertx.threads.destination import ThreadsDestination
    s = store(tmp_path)
    register(s, check_token("en", EN_TOK, "cyberalertx", Graph().client()), EN_TOK, NOW)
    since = s.ensure_publishing_since("en", NOW)
    d = ThreadsDestination("en", settings=settings(daily_limit=2), accounts=s, public_base_url="https://x.test",
                           clock=lambda: NOW, image_check=lambda u: None)
    payload = {"id": "f" * 16, "published_at": (NOW - timedelta(days=1)).isoformat(), "threat_level": "High",
               "translations": {"en": {"title": "Old"}}}
    assert d.qualifies(payload) is False                                   # before Threads started: never planned
    job = SimpleNamespace(locale="en", publication_type="initial", external_state={},
                          article_published_at=payload["published_at"])
    with pytest.raises(DeliveryError) as e1:
        d.prepare(job, payload)
    assert e1.value.category == INELIGIBLE
    payload["published_at"] = job.article_published_at = (since + timedelta(minutes=5)).isoformat()
    s.record_publication("en", NOW)
    s.record_publication("en", NOW)
    with pytest.raises(DeliveryError) as e2:
        d.prepare(job, payload)
    assert e2.value.category == WAITING and "daily limit" in str(e2.value)


def test_image_must_be_public_png_of_a_usable_size() -> None:
    from cyberalertx.threads.destination import http_image_check
    from tests.test_media import png

    def serve(status: int, body: bytes) -> Any:
        return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, content=body)))
    http_image_check("https://x.test/media/a/telegram.png", client=serve(200, png(1200, 675)))
    with pytest.raises(ValueError):
        http_image_check("https://x.test/media/a/telegram.png", client=serve(404, b""))
    with pytest.raises(ValueError):
        http_image_check("https://x.test/media/a/telegram.png", client=serve(200, png(2000, 1125)))


def test_claims_and_suspicions_are_qualified_in_both_languages() -> None:
    from cyberalertx.threads.format import TEXT_LIMIT, render_post, threads_length
    claim = {"id": "a" * 16, "source": "dev.ua", "threat_level": "Medium",
             "evidence": {"exploitation": "not_reported"},
             "translations": {"ua": {"title": "NoName057(16) заявили про атаки на холодильники",
                                     "plain_summary": "Проросійські хакери заявили, що їхні атаки нагріли холодильники.",
                                     "what_to_do": ["Не купуйте охолоджені продукти з теплих вітрин."]}}}
    post = render_post(claim, locale="ua", url="https://cyberalertx.com/ua/threat/" + "a" * 16)
    assert "Не підтверджено: це заява самих зловмисників." in post.text and "Не купуйте" not in post.text
    sus = {"id": "b" * 16, "source": "BleepingComputer", "threat_level": "High",
           "evidence": {"exploitation": "suspected"},
           "translations": {"en": {"title": "Widget flaw", "plain_summary": "A Widget flaw may be used in attacks."}}}
    post = render_post(sus, locale="en", url="https://cyberalertx.com/en/threat/" + "b" * 16)
    assert "Exploitation is suspected, not confirmed." in post.text and threads_length(post.text) <= TEXT_LIMIT


def test_status_output_never_contains_a_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    import cyberalertx.threads.accounts as acc_mod
    from cyberalertx.tools import threads as tool
    monkeypatch.setattr(acc_mod, "ACCOUNTS_PATH", tmp_path / "threads_accounts.json")
    for k, v in {"THREADS_APP_ID": "1000000000000001", "THREADS_EN_ACCESS_TOKEN": EN_TOK,
                 "THREADS_UA_ACCESS_TOKEN": UA_TOK, "THREADS_APP_SECRET": "s3cr3t-value"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr("cyberalertx.publish.jobs.JOBS_PATH", tmp_path / "jobs.json", raising=False)
    tool.cmd_status(argparse.Namespace(live=False))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["app_id"] == "1000000000000001" and data["app_secret_configured"] is True
    for secret in (EN_TOK, UA_TOK, "s3cr3t-value"):
        assert secret not in out


def test_setup_needs_an_app_id_and_has_no_built_in_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cyberalertx.tools import threads as tool
    monkeypatch.setenv("HOME", str(tmp_path))
    env = tmp_path / ".env"
    env.write_text("X=1\n")
    env.chmod(0o600)
    answers = iter(["", EN_TOK, UA_TOK])
    rc = tool.cmd_setup(argparse.Namespace(env=str(env), allow_identity_change=False),
                        ask=lambda p: next(answers), client=Graph().client(),
                        store=AccountStore(tmp_path / "a.json", mapping={"en": "en", "ua": "ua"}))
    assert rc == 2 and env.read_text() == "X=1\n"
    assert not hasattr(tool, "DEFAULT_APP_ID")
