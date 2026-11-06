"""Threads integration: OAuth, encrypted tokens, account isolation, Threads-native
formatting, two-step publishing, uncertain outcomes, reconciliation, admin.

Every Threads call goes to `FakeThreads`, a stateful mock of the Graph API on
httpx.MockTransport (containers, publishing, posts) — no network, no real
account, no real token. Synthetic tokens only.
"""
from __future__ import annotations

import base64
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

pytest.importorskip("cryptography")
from cryptography.fernet import Fernet  # noqa: E402

from cyberalertx.publish.jobs import JobStore  # noqa: E402
from cyberalertx.publish.orchestrator import PublishPolicy, plan, run  # noqa: E402
from cyberalertx.threads.accounts import (  # noqa: E402
    AccountStore, SlotConflict, StateStore, TokenCipher, TokenStorageError,
)
from cyberalertx.threads.client import ThreadsClient, scrub  # noqa: E402
from cyberalertx.threads.config import ThreadsSettings, parse_accounts  # noqa: E402
from cyberalertx.threads.destination import ThreadsDestination, auto_reconcile  # noqa: E402
from cyberalertx.threads.format import render_post, threads_length  # noqa: E402
from cyberalertx.threads.oauth import OAuthError, complete_callback, refresh_due, start_connect, verify  # noqa: E402
from tests.test_publication import BASE, FakeSource, item, payload, settings, view  # noqa: E402
from tests.test_publication import source_for as _source_for  # noqa: E402

ASSET = "0123456789abcdef"


def source_for(*items_: Any, **kw: Any) -> FakeSource:
    """Every story has its canonical illustration (Threads waits without one)."""
    src = _source_for(*items_, **kw)
    for p in src.payloads.values():
        p["media"] = {"illustration": {"asset_id": ASSET, "alt": {"en": "Illustration: a server rack.",
                                                                  "ua": "Ілюстрація: серверна стійка."}}}
    return src

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
KEY = Fernet.generate_key().decode()
SECRET = "app-secret-SYNTHETIC-123"
USERS = {"code-en": ("111", "cax_en", "CyberAlertX EN"), "code-ua": ("222", "cax_ua", "CyberAlertX UA"),
         "code-other": ("333", "someone", "Someone Else")}


# ---------------------------------------------------------------- fake Threads API

class FakeThreads:
    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}            # token -> user id
        self.revoked: set[str] = set()
        self.containers: dict[str, dict[str, Any]] = {}
        self.posts: list[dict[str, Any]] = []
        self.script: dict[str, list[Any]] = {}      # endpoint -> queued responses/exceptions/"publish_then_timeout"
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.in_progress_polls = 0                  # IN_PROGRESS answers before FINISHED
        self.quota = (0, 250)
        self.n = 0
        self.lock = threading.Lock()

    def _id(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{1000 + self.n}"

    def _err(self, status: int, code: int, msg: str) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": msg, "type": "OAuthException", "code": code,
                                                      "fbtrace_id": "x"}})

    def _user(self, token: str) -> str | None:
        return None if token in self.revoked else self.tokens.get(token)

    def handler(self, req: httpx.Request) -> httpx.Response:
        with self.lock:
            return self._handle(req)

    def _handle(self, req: httpx.Request) -> httpx.Response:
        q = {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()} if req.content else {}
        args = {**q, **form}
        path = req.url.path
        key = self._key(req.method, path, args)
        self.calls.append((req.method, key, args))
        queued = self.script.get(key) or []
        if queued:
            out = queued.pop(0)
            if out == "publish_then_timeout":
                self._publish(args)
                raise httpx.ReadTimeout("read timed out")
            if isinstance(out, BaseException):
                raise out
            return out
        if key == "oauth":
            if form.get("client_secret") != SECRET or form.get("code") not in USERS:
                return self._err(400, 100, "Invalid verification code format.")
            uid = USERS[form["code"]][0]
            tok = f"SHORT-{uid}-{self._id('')}"
            self.tokens[tok] = uid
            return httpx.Response(200, json={"access_token": tok, "user_id": uid, "token_type": "bearer"})
        if key == "exchange":
            uid = self._user(q.get("access_token", ""))
            if not uid or q.get("client_secret") != SECRET or q.get("grant_type") != "th_exchange_token":
                return self._err(400, 190, "Invalid OAuth access token.")
            tok = f"THLONG{uid}x{self._id('')}abcdefghijklmnopqrstuvwxyz"
            self.tokens[tok] = uid
            return httpx.Response(200, json={"access_token": tok, "token_type": "bearer", "expires_in": 5184000})
        if key == "refresh":
            uid = self._user(q.get("access_token", ""))
            if not uid or q.get("grant_type") != "th_refresh_token":
                return self._err(400, 190, "Error validating access token: session has been invalidated")
            tok = f"THLONG{uid}r{self._id('')}abcdefghijklmnopqrstuvwxyz"
            self.tokens[tok] = uid
            return httpx.Response(200, json={"access_token": tok, "token_type": "bearer", "expires_in": 5184000})
        uid = self._user(args.get("access_token", ""))
        if uid is None:
            return self._err(400, 190, "Error validating access token")
        if key == "me":
            u = next(v for v in USERS.values() if v[0] == uid)
            return httpx.Response(200, json={"id": u[0], "username": u[1], "name": u[2]})
        if key == "create":
            if path.split("/")[2] != uid:
                return self._err(403, 10, "Application does not have permission for this action")
            if "image_url" in form and not form["image_url"].startswith("https://"):
                return self._err(400, 100, "The image_url is not a valid URL")
            cid = self._id("c")
            self.containers[cid] = {"user": uid, "status": "IN_PROGRESS" if self.in_progress_polls else "FINISHED",
                                    "polls": self.in_progress_polls, **form}
            return httpx.Response(200, json={"id": cid})
        if key == "status":
            c = self.containers.get(path.split("/")[2])
            if not c:
                return self._err(400, 100, "Unsupported get request")
            if c["status"] == "IN_PROGRESS":
                c["polls"] -= 1
                if c["polls"] < 0:
                    c["status"] = "FINISHED"
            return httpx.Response(200, json={"id": path.split("/")[2], "status": c["status"],
                                             "error_message": c.get("error_message", "")})
        if key == "publish":
            return self._publish(args)
        if key == "permalink":
            post = next((p for p in self.posts if p["id"] == path.split("/")[2]), None)
            return httpx.Response(200, json={"id": post["id"], "permalink": post["permalink"]}) if post else \
                self._err(400, 100, "not found")
        if key == "list":
            mine = [p for p in self.posts if p["user"] == uid]
            return httpx.Response(200, json={"data": [{k: p[k] for k in ("id", "permalink", "text", "timestamp")}
                                                      for p in mine]})
        if key == "limit":
            return httpx.Response(200, json={"data": [{"quota_usage": self.quota[0],
                                                       "config": {"quota_total": self.quota[1], "quota_duration": 86400}}]})
        return self._err(400, 100, f"unhandled {key}")

    def _publish(self, args: dict[str, Any]) -> httpx.Response:
        c = self.containers.get(args.get("creation_id", ""))
        if not c or c["status"] != "FINISHED":
            return self._err(400, 24, "The media is not ready / already published")
        c["status"] = "PUBLISHED"
        pid = self._id("p")
        self.posts.append({"id": pid, "user": c["user"], "text": c["text"], "container": args["creation_id"],
                           "permalink": f"https://www.threads.com/@x/post/{pid}", "timestamp": NOW.isoformat()})
        return httpx.Response(200, json={"id": pid})

    @staticmethod
    def _key(method: str, path: str, args: dict[str, Any]) -> str:
        if path == "/oauth/access_token":
            return "oauth"
        if path == "/access_token":
            return "exchange"
        if path == "/refresh_access_token":
            return "refresh"
        if path == "/v1.0/me":
            return "me"
        if path.endswith("/threads_publish"):
            return "publish"
        if path.endswith("/threads_publishing_limit"):
            return "limit"
        if path.endswith("/threads"):
            return "create" if method == "POST" else "list"
        if args.get("fields", "").startswith("status"):
            return "status"
        return "permalink"

    def client(self) -> ThreadsClient:
        return ThreadsClient(client=httpx.Client(transport=httpx.MockTransport(self.handler)))

    def created(self) -> list[str]:
        return [c for m, c, _ in self.calls if c == "create"]


def tsettings(**kw: Any) -> ThreadsSettings:
    base: dict[str, Any] = dict(app_id="999000111", app_secret=SECRET,
                                redirect_uri="https://cyberalertx.com/admin/threads/callback",
                                token_key=KEY, publish_enabled=True)
    base.update(kw)
    return ThreadsSettings(**base)


def connect(tmp_path: Path, api: FakeThreads, slot: str, code: str, *, now: datetime = NOW,
            ts: ThreadsSettings | None = None) -> AccountStore:
    ts = ts or tsettings()
    accounts = AccountStore(tmp_path / "accounts.json", key=KEY, mapping=ts.accounts)
    states = StateStore(tmp_path / "states.json")
    url = start_connect(slot, settings=ts, states=states, now=now)
    state = parse_qs(urlparse(url).query)["state"][0]
    complete_callback({"code": code, "state": state}, settings=ts, states=states, accounts=accounts,
                      client=api.client(), now=now)
    return accounts


def both(tmp_path: Path, api: FakeThreads) -> AccountStore:
    connect(tmp_path, api, "en", "code-en")
    return connect(tmp_path, api, "ua", "code-ua")


def tdest(slot: str, accounts: AccountStore, api: FakeThreads, **kw: Any) -> ThreadsDestination:
    opts: dict[str, Any] = dict(settings=tsettings(), accounts=accounts, public_base_url=BASE,
                                client_factory=api.client, sleep=lambda s: None, clock=lambda: NOW,
                                initial_wait_s=0, poll_interval_s=60, poll_budget_s=120)
    opts.update(kw)
    return ThreadsDestination(slot, **opts)


def world(tmp_path: Path, api: FakeThreads, *items_: Any, src: FakeSource | None = None,
          accounts: AccountStore | None = None, **dkw: Any) -> tuple[JobStore, FakeSource, dict[str, Any]]:
    accounts = accounts or both(tmp_path, api)
    d = {"threads@en": tdest("en", accounts, api, **dkw), "threads@ua": tdest("ua", accounts, api, **dkw)}
    store = JobStore(tmp_path / "jobs.json")
    src = src or source_for(*items_)
    plan(src, store, now=NOW, settings=settings(channels={}), destinations=d, view=view(*items_),
         policy=PublishPolicy())
    return store, src, d


def go(store: JobStore, src: FakeSource, d: dict[str, Any], now: datetime = NOW) -> Any:
    return run(src, store, d, now=now, clock=lambda: now, rng=lambda: 0.5)


def tj(store: JobStore) -> list[Any]:
    """Threads jobs only (world() has no website destination; its jobs just wait)."""
    return [j for j in store.all() if j.destination.startswith("threads@")]


def st(store: JobStore) -> dict[str, str]:
    return {j.job_id: j.status for j in tj(store)}


# ---------------------------------------------------------------- config

def test_account_mapping_is_explicit_and_one_to_one() -> None:
    assert parse_accounts("en:en,ua:uk") == {"en": "en", "ua": "ua"}
    assert parse_accounts("main:en") == {"main": "en"}
    for bad in ("en:en,ua:en", "en:en,en:ua", "en", "en:fr", "a b:en"):
        with pytest.raises(ValueError):
            parse_accounts(bad)
    assert ThreadsSettings().publish_enabled is False                        # off by default


# ---------------------------------------------------------------- OAuth

def test_authorize_url_is_the_official_one_and_carries_no_secret(tmp_path: Path) -> None:
    url = start_connect("en", settings=tsettings(), states=StateStore(tmp_path / "s.json"), now=NOW)
    u = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert f"{u.scheme}://{u.netloc}{u.path}" == "https://threads.com/oauth/authorize"
    assert q["client_id"] == "999000111" and q["response_type"] == "code"
    assert q["redirect_uri"] == "https://cyberalertx.com/admin/threads/callback"
    assert q["scope"] == "threads_basic,threads_content_publish" and len(q["state"]) >= 40
    assert SECRET not in url and KEY not in url


def test_valid_callback_stores_an_encrypted_long_lived_token(tmp_path: Path) -> None:
    api = FakeThreads()
    accounts = connect(tmp_path, api, "en", "code-en")
    a = accounts.get("en")
    assert a.status == "connected" and a.threads_user_id == "111" and a.username == "cax_en"
    assert a.expires_at == (NOW + timedelta(seconds=5184000)).isoformat()
    raw = (tmp_path / "accounts.json").read_text()
    token = accounts.token("en")
    assert token.startswith("THLONG111") and token not in raw and "SHORT-" not in raw
    assert oct((tmp_path / "accounts.json").stat().st_mode & 0o777) == "0o600"
    assert "token_ciphertext" not in a.to_public(NOW) and a.to_public(NOW)["expires_in_days"] == 60.0
    assert accounts.get("ua").status == "disconnected"                       # other slot untouched


@pytest.mark.parametrize("case", ["invalid", "reused", "expired", "denied", "bad_code"])
def test_callback_rejections_store_nothing(tmp_path: Path, case: str) -> None:
    api, ts = FakeThreads(), tsettings()
    accounts = AccountStore(tmp_path / "accounts.json", key=KEY, mapping=ts.accounts)
    states = StateStore(tmp_path / "states.json")
    state = parse_qs(urlparse(start_connect("en", settings=ts, states=states, now=NOW)).query)["state"][0]
    params = {"code": "code-en", "state": state}
    when = NOW
    if case == "invalid":
        params["state"] = "forged-" + state
    elif case == "reused":
        complete_callback(dict(params), settings=ts, states=states, accounts=accounts, client=api.client(), now=NOW)
        accounts.disconnect("en", NOW)
    elif case == "expired":
        when = NOW + timedelta(minutes=11)
    elif case == "denied":
        params = {"error": "access_denied", "error_reason": "user_denied", "state": state}
    elif case == "bad_code":
        params["code"] = "stolen-code-XYZ"
    with pytest.raises(OAuthError) as exc:
        complete_callback(params, settings=ts, states=states, accounts=accounts, client=api.client(), now=when)
    assert accounts.get("en").status == "disconnected" and not accounts.get("en").token_ciphertext
    assert "stolen-code-XYZ" not in str(exc.value)
    if case == "invalid":
        return                                                               # the real state was never used
    with pytest.raises(OAuthError):                                          # a state is never usable twice
        complete_callback({"code": "code-en", "state": state}, settings=ts, states=states, accounts=accounts,
                          client=api.client(), now=NOW)


def test_state_is_bound_to_its_slot(tmp_path: Path) -> None:
    api, ts = FakeThreads(), tsettings()
    accounts = AccountStore(tmp_path / "accounts.json", key=KEY, mapping=ts.accounts)
    states = StateStore(tmp_path / "states.json")
    start_connect("en", settings=ts, states=states, now=NOW)
    ua_state = parse_qs(urlparse(start_connect("ua", settings=ts, states=states, now=NOW)).query)["state"][0]
    acc = complete_callback({"code": "code-ua", "state": ua_state, "slot": "en"}, settings=ts, states=states,
                            accounts=accounts, client=api.client(), now=NOW)
    assert acc.slot == "ua" and accounts.get("en").status == "disconnected"  # the request cannot pick the slot


def test_a_connected_slot_is_not_silently_switched_to_another_profile(tmp_path: Path) -> None:
    api = FakeThreads()
    connect(tmp_path, api, "en", "code-en")
    with pytest.raises(OAuthError, match="disconnect it first"):
        connect(tmp_path, api, "en", "code-other")
    accounts = AccountStore(tmp_path / "accounts.json", key=KEY)
    assert accounts.get("en").username == "cax_en"
    accounts.disconnect("en", NOW)
    assert connect(tmp_path, api, "en", "code-other").get("en").username == "someone"
    with pytest.raises(SlotConflict):
        accounts.save_connection("en", token="T", expires_in=10, user_id="111", username="x", name="", now=NOW)


def test_token_refresh_lifecycle_and_isolation(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    api = FakeThreads()
    accounts = both(tmp_path, api)
    assert {r.outcome for r in refresh_due(accounts, api.client(), NOW + timedelta(hours=1))} == {"not_due"}
    later = NOW + timedelta(days=40)                                       # 20 days left: due
    old_en = accounts.token("en")
    api.revoked.add(accounts.token("ua"))
    caplog.set_level("ERROR")
    res = {r.slot: r.outcome for r in refresh_due(accounts, api.client(), later)}
    assert res == {"en": "refreshed", "ua": "failed"}
    en, ua = accounts.get("en"), accounts.get("ua")
    assert en.status == "connected" and accounts.token("en") != old_en
    assert en.expires_at == (later + timedelta(seconds=5184000)).isoformat() and en.last_refresh_at
    assert ua.status == "needs_reconnect" and "refresh refused" in ua.last_error
    assert "OPERATOR ACTION NEEDED" in caplog.text
    res2 = {r.slot: r.outcome for r in refresh_due(accounts, api.client(), later + timedelta(days=61))}
    assert res2["en"] == "expired" and accounts.get("en").status == "needs_reconnect"


def test_refresh_waits_until_the_token_is_a_day_old(tmp_path: Path) -> None:
    api = FakeThreads()
    accounts = connect(tmp_path, api, "en", "code-en")
    r = refresh_due(accounts, api.client(), NOW + timedelta(hours=2), when_left=timedelta(days=90))
    assert [x.outcome for x in r if x.slot == "en"] == ["too_new"]


def test_verify_detects_revoked_tokens(tmp_path: Path) -> None:
    api = FakeThreads()
    accounts = both(tmp_path, api)
    assert verify("en", accounts, api.client(), NOW).last_verified_at
    api.revoked.add(accounts.token("en"))
    assert verify("en", accounts, api.client(), NOW).status == "needs_reconnect"
    assert accounts.get("ua").status == "connected"


def test_tokens_fail_closed_without_a_valid_key(tmp_path: Path) -> None:
    with pytest.raises(TokenStorageError):
        TokenCipher("")
    with pytest.raises(TokenStorageError):
        TokenCipher("not-a-fernet-key")
    api = FakeThreads()
    connect(tmp_path, api, "en", "code-en")
    other = AccountStore(tmp_path / "accounts.json", key=Fernet.generate_key().decode())
    with pytest.raises(TokenStorageError, match="cannot be decrypted"):
        other.token("en")


def test_no_secret_ever_reaches_the_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    api = FakeThreads()
    accounts = both(tmp_path, api)
    store, src, d = world(tmp_path, api, item(1), accounts=accounts)
    api.script["publish"] = [httpx.ReadTimeout("timeout for access_token=THLONGsecretsecretsecretsecret")]
    go(store, src, d)
    blob = caplog.text + (tmp_path / "jobs.json").read_text()
    for secret in (SECRET, KEY, accounts.token("en"), accounts.token("ua"), "code-en", "THLONGsecret"):
        assert secret not in blob
    assert scrub("x?access_token=ABC&client_secret=DEF&code=GHI") == \
        "x?access_token=[redacted]&client_secret=[redacted]&code=[redacted]"


# ---------------------------------------------------------------- routing & isolation

def test_each_account_receives_only_its_own_edition(tmp_path: Path) -> None:
    api = FakeThreads()
    en_src, ua_src = item(1), item(2, language="ua")
    store, src, d = world(tmp_path, api, en_src, ua_src)
    assert sorted(st(store)) == ["s:0001:en:threads@en:initial", "s:0001:ua:threads@ua:initial",
                                 "s:0002:ua:threads@ua:initial"]           # UA source never on the EN profile
    go(store, src, d)
    by_user: dict[str, list[str]] = {}
    for p in api.posts:
        by_user.setdefault(p["user"], []).append(p["text"])
    assert all("/en/threat/" in t and "Widget flaw" in t for t in by_user["111"])
    assert all("/ua/threat/" in t and "Ваду у Widget" in t for t in by_user["222"])


def test_wrong_locale_for_an_account_is_rejected(tmp_path: Path) -> None:
    api = FakeThreads()
    accounts = both(tmp_path, api)
    it = item(1)
    job = type("J", (), {"locale": "ua", "external_state": {}})()
    from cyberalertx.publish.destinations import DeliveryError
    with pytest.raises(DeliveryError) as exc:
        tdest("en", accounts, api).prepare(job, payload(it))
    assert exc.value.category == "invalid_content"
    assert not tdest("en", accounts, api).enabled("ua")


def test_disconnecting_en_does_not_touch_ua(tmp_path: Path) -> None:
    api = FakeThreads()
    accounts = both(tmp_path, api)
    accounts.disconnect("en", NOW)
    store, src, d = world(tmp_path, api, item(1), accounts=accounts)
    assert list(st(store)) == ["s:0001:ua:threads@ua:initial"]              # no new EN jobs
    go(store, src, d)
    assert [p["user"] for p in api.posts] == ["222"]


def test_ua_auth_failure_pauses_only_ua(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    api = FakeThreads()
    accounts = both(tmp_path, api)
    store, src, d = world(tmp_path, api, item(1), item(2), accounts=accounts)
    api.revoked.add(accounts.token("ua"))
    caplog.set_level("ERROR")
    rep = go(store, src, d)
    s = st(store)
    assert s["s:0001:en:threads@en:initial"] == "published"
    assert "failed" in {s["s:0001:ua:threads@ua:initial"], s["s:0002:ua:threads@ua:initial"]}
    assert accounts.get("ua").status == "needs_reconnect" and accounts.get("en").status == "connected"
    assert any("threads@ua" in p for p in rep.paused) and "OPERATOR ACTION NEEDED" in caplog.text
    assert not d["threads@ua"].enabled("ua")                                 # no more UA claims until reconnect


def test_rate_limit_on_one_account_does_not_pause_the_other(tmp_path: Path) -> None:
    api = FakeThreads()
    store, src, d = world(tmp_path, api, item(1))
    api.script["create"] = [httpx.Response(429, headers={"retry-after": "600"},
                                           json={"error": {"message": "Application request limit reached", "code": 4}})]
    go(store, src, d)
    s = st(store)
    limited = [k for k, v in s.items() if v == "retrying"]
    assert len(limited) == 1 and len(api.posts) == 1
    j = store.get(limited[0])
    assert j and j.error_category == "rate_limit" and j.next_attempt_at == (NOW + timedelta(seconds=600)).isoformat()


def test_permission_error_needs_the_operator(tmp_path: Path) -> None:
    api = FakeThreads()
    store, src, d = world(tmp_path, api, item(1))
    api.script["create"] = [httpx.Response(403, json={"error": {"message": "Permissions error", "code": 10}})]
    go(store, src, d)
    failed = [j for j in tj(store) if j.status == "failed"]
    assert len(failed) == 1 and failed[0].error_category == "permission"


# ---------------------------------------------------------------- publishing

def test_image_post_uses_the_canonical_illustration(tmp_path: Path) -> None:
    api = FakeThreads()
    it = item(1)
    store, src, d = world(tmp_path, api, it)
    rep = go(store, src, d)
    assert len(rep.published) == 2 and len(api.posts) == 2
    creates = {a["access_token"][:9]: a for m, c, a in api.calls if c == "create"}
    ua = next(a for a in creates.values() if "/ua/" in a["text"])
    en = next(a for a in creates.values() if "/en/" in a["text"])
    # The same asset as the website and Telegram, its 1200x675 PNG derivative.
    assert ua["media_type"] == "IMAGE" and ua["image_url"] == en["image_url"] == f"{BASE}/media/{ASSET}/telegram.png"
    assert ua["alt_text"] == "Ілюстрація: серверна стійка." and en["alt_text"] == "Illustration: a server rack."
    assert ua["topic_tag"] == "Кібербезпека"
    j = store.get("s:0001:ua:threads@ua:initial")
    assert j and j.external_id.startswith("p") and j.published_url.startswith("https://www.threads.com/")
    assert j.external_state["container_id"].startswith("c") and j.external_state["media_type"] == "IMAGE"


def test_an_unreachable_illustration_means_waiting_not_a_text_post(tmp_path: Path) -> None:
    api = FakeThreads()

    def broken(url: str) -> None:
        raise ValueError("image URL answered HTTP 404")

    store, src, d = world(tmp_path, api, item(1), image_check=broken)
    go(store, src, d)
    assert api.created() == [] and api.posts == []
    assert all(j.status == "retrying" for j in tj(store))


def test_a_story_without_an_illustration_waits(tmp_path: Path) -> None:
    api = FakeThreads()
    it = item(1)
    src = source_for(it)
    for p in src.payloads.values():
        p.pop("media", None)
    store, src, d = world(tmp_path, api, it, src=src)
    rep = go(store, src, d)
    assert api.created() == [] and all("illustration" in r["reason"] for r in rep.deferred)


def test_a_refused_image_is_retried_never_posted_as_text(tmp_path: Path) -> None:
    api = FakeThreads()
    store, src, d = world(tmp_path, api, item(1))
    api.script["create"] = [httpx.Response(400, json={"error": {"message": "Image download failed", "code": 100}})]
    go(store, src, d)
    assert "TEXT" not in {a["media_type"] for m, c, a in api.calls if c == "create"}
    statuses = sorted(j.status for j in tj(store))
    assert "retrying" in statuses and len(api.posts) == statuses.count("published")


def test_slow_container_is_resumed_not_recreated(tmp_path: Path) -> None:
    api = FakeThreads()
    api.in_progress_polls = 5
    accounts = both(tmp_path, api)
    store, src, d = world(tmp_path, api, item(1), accounts=accounts)
    go(store, src, d)
    assert set(st(store).values()) == {"retrying"} and len(api.created()) == 2 and not api.posts
    go(store, src, d, now=NOW + timedelta(minutes=5))
    assert set(st(store).values()) == {"published"}
    assert len(api.created()) == 2 and len(api.posts) == 2                   # same two containers


def test_container_error_gets_a_new_image_container_never_text(tmp_path: Path) -> None:
    api = FakeThreads()
    store, src, d = world(tmp_path, api, item(1, language="ua"))
    orig = api._handle

    def errored(req: httpx.Request) -> httpx.Response:
        resp = orig(req)
        for c in api.containers.values():
            if c.get("media_type") == "IMAGE":
                c["status"], c["error_message"] = "ERROR", "UNKNOWN"
        return resp
    api._handle = errored                                                   # type: ignore[method-assign]
    go(store, src, d)
    assert {c["media_type"] for c in api.containers.values()} == {"IMAGE"} and api.posts == []
    assert st(store) == {"s:0001:ua:threads@ua:initial": "retrying"}
    api._handle = orig                                                      # type: ignore[method-assign]
    go(store, src, d, now=NOW + timedelta(hours=1))
    assert st(store) == {"s:0001:ua:threads@ua:initial": "published"}
    assert {c["media_type"] for c in api.containers.values()} == {"IMAGE"}


def test_expired_container_is_replaced(tmp_path: Path) -> None:
    api = FakeThreads()
    store, src, d = world(tmp_path, api, item(1, language="ua"))
    api.in_progress_polls = 5
    go(store, src, d)
    for c in api.containers.values():
        c["status"] = "EXPIRED"
    api.in_progress_polls = 0
    go(store, src, d, now=NOW + timedelta(minutes=5))
    assert len(api.created()) == 2 and len(api.posts) == 1


def test_publish_timeout_after_success_is_recognised(tmp_path: Path) -> None:
    api = FakeThreads()
    store, src, d = world(tmp_path, api, item(1, language="ua"))
    api.script["publish"] = ["publish_then_timeout"]
    go(store, src, d)
    j = store.get("s:0001:ua:threads@ua:initial")
    assert j and j.status == "published" and len(api.posts) == 1 and j.external_id == api.posts[0]["id"]
    assert any(h.get("note") == "published despite a failed response" for h in j.history)


def test_publish_5xx_with_unpublished_container_retries_the_same_container(tmp_path: Path) -> None:
    api = FakeThreads()
    store, src, d = world(tmp_path, api, item(1, language="ua"))
    api.script["publish"] = [httpx.Response(503, json={"error": {"message": "Service unavailable", "code": 2}})]
    go(store, src, d)
    assert st(store) == {"s:0001:ua:threads@ua:initial": "retrying"} and not api.posts
    go(store, src, d, now=NOW + timedelta(minutes=5))
    assert st(store) == {"s:0001:ua:threads@ua:initial": "published"}
    assert len(api.created()) == 1 and len(api.posts) == 1


def test_unknown_outcome_is_never_blindly_retried_and_reconciles(tmp_path: Path) -> None:
    api = FakeThreads()
    store, src, d = world(tmp_path, api, item(1, language="ua"))
    api.script["publish"] = ["publish_then_timeout"]
    calls = {"n": 0}
    real = api._handle

    def flaky(req: httpx.Request) -> httpx.Response:
        if FakeThreads._key(req.method, req.url.path, {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}) == "status":
            calls["n"] += 1
            if calls["n"] == 2:
                raise httpx.ConnectError("refused")
        return real(req)
    api._handle = flaky                                                     # 2nd status call = verification
    go(store, src, d)
    j = store.get("s:0001:ua:threads@ua:initial")
    assert j and j.status == "outcome_unknown" and len(api.posts) == 1
    for h in (1, 6, 24):
        go(store, src, d, now=NOW + timedelta(hours=h))
    assert len(api.posts) == 1 and len(api.created()) == 1                  # nothing resent automatically
    res = auto_reconcile(store, d, NOW + timedelta(days=1))
    assert res[0]["result"].startswith("published as p")
    j = store.get("s:0001:ua:threads@ua:initial")
    assert j and j.status == "published" and j.external_id == api.posts[0]["id"]


def test_auto_reconcile_requeues_an_unpublished_container(tmp_path: Path) -> None:
    api = FakeThreads()
    store, src, d = world(tmp_path, api, item(1, language="ua"))
    jid = "s:0001:ua:threads@ua:initial"
    store.claim(NOW, "dead", lease_s=10)
    cid = api.client().create_container("222", d["threads@ua"].accounts.token("ua"), text="t")
    store.update(jid, lambda j: (setattr(j, "phase", "sending"),
                                 j.external_state.update(container_id=cid, container_created_at=NOW.isoformat())), NOW)
    go(store, src, d, now=NOW + timedelta(minutes=1))                       # recovery → outcome_unknown
    assert st(store)[jid] == "outcome_unknown" and not api.posts
    assert auto_reconcile(store, d, NOW + timedelta(minutes=2))[0]["result"].startswith("not published")
    go(store, src, d, now=NOW + timedelta(minutes=3))
    assert st(store)[jid] == "published" and len(api.created()) == 1 and len(api.posts) == 1


def test_crash_after_container_creation_resumes_it(tmp_path: Path) -> None:
    api = FakeThreads()
    store, src, d = world(tmp_path, api, item(1, language="ua"))
    jid = "s:0001:ua:threads@ua:initial"
    store.claim(NOW, "dead", lease_s=10)
    cid = api.client().create_container("222", d["threads@ua"].accounts.token("ua"),
                                        text=render_post(payload(item(1, language="ua")), locale="ua",
                                                         url=f"{BASE}/ua/threat/x").text)
    store.update(jid, lambda j: (setattr(j, "phase", "container_created"),
                                 j.external_state.update(container_id=cid, container_created_at=NOW.isoformat())), NOW)
    rep = go(store, src, d, now=NOW + timedelta(minutes=1))
    assert jid in rep.recovered and st(store)[jid] == "published"
    assert len(api.created()) == 1 and api.posts[0]["container"] == cid


def test_quota_exhausted_is_a_rate_limit(tmp_path: Path) -> None:
    api = FakeThreads()
    api.quota = (250, 250)
    store, src, d = world(tmp_path, api, item(1, language="ua"))
    go(store, src, d)
    j = store.get("s:0001:ua:threads@ua:initial")
    assert j and j.status == "retrying" and j.error_category == "rate_limit" and not api.created()


def test_planning_and_running_twice_and_concurrently_post_once(tmp_path: Path) -> None:
    api = FakeThreads()
    items_ = [item(n) for n in range(1, 4)]
    accounts = both(tmp_path, api)
    store, src, d = world(tmp_path, api, *items_, accounts=accounts)
    plan(src, store, now=NOW, settings=settings(channels={}), destinations=d, view=view(*items_))
    assert len(tj(store)) == 6
    pol = PublishPolicy(threads_per_run=10)

    def worker() -> None:
        dd = {"threads@en": tdest("en", accounts, api), "threads@ua": tdest("ua", accounts, api)}
        run(src, JobStore(tmp_path / "jobs.json"), dd, now=NOW, clock=lambda: NOW, policy=pol, rng=lambda: 0.5)

    threads_ = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads_:
        t.start()
    for t in threads_:
        t.join()
    worker()
    assert len(api.posts) == 6 and len({p["text"] for p in api.posts}) == 6
    assert set(st(store).values()) == {"published"}


def test_per_run_cap_is_per_account(tmp_path: Path) -> None:
    api = FakeThreads()
    store, src, d = world(tmp_path, api, item(1), item(2), item(3))
    go(store, src, d)
    assert sorted(p["user"] for p in api.posts) == ["111", "222"]           # default 1 per account per run


# ---------------------------------------------------------------- formatting

def test_post_is_threads_native_not_the_telegram_message() -> None:
    it = item(1)
    p = payload(it)
    p["translations"]["en"]["why_it_matters"] = "Unpatched Widget servers give attackers a foothold."
    post = render_post(p, locale="en", url=f"{BASE}/en/threat/{it.fingerprint}")
    lines = post.text.split("\n\n")
    assert lines[0] == "Widget flaw Story 1" and lines[-1] == f"{BASE}/en/threat/{it.fingerprint}"
    assert "What to do: Patch Widget now" in post.text and "Unpatched Widget servers" in post.text
    assert "<" not in post.text and "#" not in post.text and "🔴" not in post.text
    assert post.topic_tag == "Cybersecurity" and threads_length(post.text) <= 500


def test_ua_post_comes_from_the_ua_edition() -> None:
    it = item(1)
    post = render_post(payload(it), locale="ua", url=f"{BASE}/ua/threat/{it.fingerprint}")
    assert post.text.startswith("Ваду у Widget") and "Що зробити: Оновіть Widget" in post.text
    assert "Джерело: BleepingComputer" in post.text                         # attribution survives
    assert not re.search(r"\bthe\b|What to do", post.text)


def test_long_post_is_shortened_deterministically_without_cutting_identifiers() -> None:
    it = item(1)
    p = payload(it)
    c = p["translations"]["en"]
    c["plain_summary"] = ("Attackers exploit CVE-2026-12345 in Widget Gateway 9.1 to run code. " * 9).strip()
    c["short_summary"] = "BleepingComputer reports 4,000 exposed Widget Gateway servers in 40 countries."
    c["why_it_matters"] = "Widget Gateway fronts corporate VPNs, so one bug opens the whole network. " * 2
    url = f"{BASE}/en/threat/{it.fingerprint}"
    a, b = render_post(p, locale="en", url=url), render_post(p, locale="en", url=url)
    assert a.text == b.text and threads_length(a.text) <= 500
    assert "Source: BleepingComputer" in a.text                             # kept even when shortening
    assert a.dropped[:3] == ["why", "action", "fact"] and a.dropped[-1] == "explain (shortened)"
    assert a.text.endswith(url) and a.text.startswith("Widget flaw Story 1")
    assert not re.search(r"CVE-\d{4}-\d{0,4}(?!\d)\b(?<!12345)", a.text.replace("CVE-2026-12345", ""))
    assert all(tok == "CVE-2026-12345" for tok in re.findall(r"CVE-[\d-]+", a.text))


def test_threads_length_counts_emoji_as_bytes() -> None:
    assert threads_length("abc") == 3 and threads_length("абв") == 3 and threads_length("🔴") == 4


# ---------------------------------------------------------------- compatibility & admin

def test_publishing_stays_off_without_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from cyberalertx.tools.publish import _threads_destinations
    monkeypatch.delenv("CYBERALERTX_THREADS_PUBLISH", raising=False)
    assert _threads_destinations(BASE) == {}
    monkeypatch.setenv("CYBERALERTX_THREADS_PUBLISH", "1")
    monkeypatch.setenv("CYBERALERTX_THREADS_TOKEN_KEY", KEY)
    assert set(_threads_destinations(BASE)) == {"threads@en", "threads@ua"}


def test_website_and_telegram_identities_are_unchanged(tmp_path: Path) -> None:
    from cyberalertx.publish.destinations import TelegramDestination, WebsiteDestination
    from tests.test_publication import Bot
    api = FakeThreads()
    accounts = both(tmp_path, api)
    bot = Bot()
    d = {"website": WebsiteDestination(BASE),
         "telegram": TelegramDestination(settings(), ledger_path=tmp_path / "l.jsonl", publisher_factory=bot.factory()),
         "threads@en": tdest("en", accounts, api), "threads@ua": tdest("ua", accounts, api)}
    it = item(1)
    store = JobStore(tmp_path / "jobs.json")
    src = source_for(it)
    plan(src, store, now=NOW, settings=settings(), destinations=d, view=view(it))
    every = {j.job_id: j.status for j in store.all()}
    assert sorted(every) == sorted(f"s:0001:{loc}:{dest}:initial" for loc in ("en", "ua")
                                       for dest in ("website", "telegram", f"threads@{loc}"))
    run(src, store, d, now=NOW, clock=lambda: NOW, rng=lambda: 0.5)
    assert {j.status for j in store.all()} == {"published"} and len(bot.sent()) == 2 and len(api.posts) == 2


def test_admin_threads_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    import cyberalertx.api.app as app_mod
    import cyberalertx.threads.accounts as acc_mod
    from cyberalertx.api.admin import AdminGuard

    api = FakeThreads()
    token = "t" * 48
    for k, v in {"CYBERALERTX_ADMIN_TOKEN": token, "CYBERALERTX_THREADS_APP_ID": "999000111",
                 "CYBERALERTX_THREADS_APP_SECRET": SECRET, "CYBERALERTX_THREADS_TOKEN_KEY": KEY,
                 "CYBERALERTX_THREADS_REDIRECT_URI": "https://cyberalertx.com/admin/threads/callback"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(acc_mod, "ACCOUNTS_PATH", tmp_path / "accounts.json")
    monkeypatch.setattr(acc_mod, "STATES_PATH", tmp_path / "states.json")
    monkeypatch.setattr(app_mod, "_threads_client_factory", api.client)
    guard = AdminGuard()
    client = TestClient(app_mod.build_app(feedback_path=tmp_path / "f.jsonl", admin_guard=guard))
    for path in ("/admin/threads", "/admin/threads.json", "/admin/threads/callback?code=x&state=y"):
        assert client.get(path).status_code == 401
    auth = {"Authorization": "Basic " + base64.b64encode(f"ed:{token}".encode()).decode(), "X-Real-IP": "203.0.113.9"}
    page = client.get("/admin/threads", headers=auth)
    assert page.status_code == 200 and "form-action 'self'" in page.headers["content-security-policy"]
    assert "Slot en" in page.text and "Slot ua" in page.text and SECRET not in page.text and KEY not in page.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)          # type: ignore[union-attr]
    assert client.post("/admin/threads/connect", data={"slot": "ua"}, headers=auth).status_code == 403
    assert client.post("/admin/threads/connect", data={"slot": "ua", "csrf": csrf},
                       headers={**auth, "Origin": "https://evil.example"}).status_code == 403
    r = client.post("/admin/threads/connect", data={"slot": "ua", "csrf": csrf}, headers=auth)
    assert r.status_code == 200 and "Continue to Threads" in r.text
    url = re.search(r'href="(https://threads\.com/oauth/authorize[^"]+)"', r.text).group(1).replace("&amp;", "&")  # type: ignore[union-attr]
    state = parse_qs(urlparse(url).query)["state"][0]
    cb = client.get(f"/admin/threads/callback?code=code-ua&state={state}", headers=auth, follow_redirects=False)
    assert cb.status_code == 303 and cb.headers["location"] == "/admin/threads?done=ua"
    again = client.get(f"/admin/threads/callback?code=code-ua&state={state}", headers=auth)
    assert again.status_code == 400 and "already used" in again.text
    data = client.get("/admin/threads.json", headers=auth).json()
    ua = next(a for a in data["accounts"] if a["slot"] == "ua")
    assert ua["status"] == "connected" and ua["username"] == "cax_ua" and ua["has_token"] is True
    assert "token_ciphertext" not in json.dumps(data) and "THLONG" not in json.dumps(data)
    assert next(a for a in data["accounts"] if a["slot"] == "en")["status"] == "disconnected"
    v = client.post("/admin/threads/verify", data={"slot": "ua", "csrf": csrf}, headers=auth, follow_redirects=False)
    assert v.status_code == 303
    dc = client.post("/admin/threads/disconnect", data={"slot": "ua", "csrf": csrf}, headers=auth,
                     follow_redirects=False)
    assert dc.status_code == 303
    assert client.get("/admin/threads.json", headers=auth).json()["accounts"][1]["status"] == "disconnected"
    assert client.post("/admin/threads/disconnect", data={"slot": "zz", "csrf": csrf}, headers=auth).status_code == 400


def test_attribution_alone_is_not_a_fact_and_actions_beat_soft_facts() -> None:
    it = item(1)
    p = payload(it)
    c = p["translations"]["en"]
    c["plain_summary"] = "Freezers at supermarket chains in several European countries were remotely set too warm."
    c["short_summary"] = ("BleepingComputer reports intruders reached refrigeration controls and altered "
                          "freezer temperatures at several supermarket chains.")
    post = render_post(p, locale="en", url=f"{BASE}/en/threat/{it.fingerprint}")
    assert "BleepingComputer reports" not in post.text and "intruders reached" not in post.text
    assert post.text.count("BleepingComputer") == 1 and "\n\nSource: BleepingComputer\n\n" in post.text
    assert "What to do: Patch Widget now" in post.text
    c["short_summary"] = "BleepingComputer reports that CVE-2026-4242 in Widget 7.2 is the entry point."
    post = render_post(p, locale="en", url=f"{BASE}/en/threat/{it.fingerprint}")
    assert "CVE-2026-4242 in Widget 7.2 is the entry point." in post.text and "BleepingComputer reports" not in post.text
