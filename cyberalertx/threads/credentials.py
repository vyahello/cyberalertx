"""Env-token accounts: validation, identity mapping, refresh.

Each account (EN, UA) has its own Threads user access token in the server's
.env. The Threads user id is never configured: `/me` with that token is the
source of truth, cross-checked with `debug_token` (same user id, valid,
required scopes, expiry). Accounts are handled independently: one invalid,
expired or mis-mapped token stops only its own account.

Token lifecycle (official docs, checked Nov 2026): long-lived tokens last
60 days and can be refreshed (`th_refresh_token`) once they are at least
24 h old and not expired; each refresh restarts the 60 days. A short-lived
token is exchanged (`th_exchange_token`, needs the shared app secret). The
actual expiry is read from `debug_token`, never assumed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .accounts import AccountStore, SlotConflict, TokenStorageError, _parse
from .client import ThreadsClient, ThreadsError
from .config import SCOPES, ThreadsSettings

logger = logging.getLogger(__name__)

#: Refresh when less than this is left (and the token is at least 24 h old).
REFRESH_WHEN_LEFT = timedelta(days=30)
MIN_REFRESH_AGE = timedelta(hours=24)
#: A token living less than this is short-lived (they last about an hour).
SHORT_LIVED = timedelta(days=2)
DEFAULT_USERNAMES = {"en": "cyberalertx", "ua": "cyberalertx_ua"}
ENV_TOKEN_VAR = {"en": "THREADS_EN_ACCESS_TOKEN", "ua": "THREADS_UA_ACCESS_TOKEN"}


def _ts(value: Any) -> datetime | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(n, tz=timezone.utc) if n > 0 else None


@dataclass
class TokenCheck:
    slot: str
    ok: bool = False
    user_id: str = ""
    username: str = ""
    expires_at: datetime | None = None
    issued_at: datetime | None = None
    data_access_expires_at: datetime | None = None
    scopes: list[str] = field(default_factory=list)
    token_type: str = ""
    problems: list[str] = field(default_factory=list)

    def short_lived(self) -> bool:
        if self.expires_at is None:
            return False
        start = self.issued_at or datetime.now(timezone.utc)
        return self.expires_at - start < SHORT_LIVED


def check_token(slot: str, token: str, expected_username: str, client: ThreadsClient) -> TokenCheck:
    """Validate one account's token. Never raises for API problems: they are listed."""
    res = TokenCheck(slot=slot)
    if not token:
        res.problems.append("no token")
        return res
    try:
        me = client.me(token)
    except ThreadsError as exc:
        res.problems.append(f"/me failed ({exc.category}): {exc}")
        return res
    res.user_id, res.username = str(me.get("id", "")), str(me.get("username", ""))
    if not res.user_id:
        res.problems.append("/me returned no id")
    if res.username != expected_username:
        res.problems.append(f"token belongs to @{res.username or '?'}, expected @{expected_username}")
    try:
        info = client.debug_token(token, token)
    except ThreadsError as exc:
        res.problems.append(f"debug_token failed ({exc.category}): {exc}")
        return res
    res.expires_at, res.issued_at = _ts(info.get("expires_at")), _ts(info.get("issued_at"))
    res.data_access_expires_at = _ts(info.get("data_access_expires_at"))
    res.scopes = [str(x) for x in info.get("scopes") or []]
    res.token_type = str(info.get("type", ""))
    if info.get("is_valid") is not True:
        res.problems.append("token is not valid")
    if str(info.get("user_id", "")) and str(info.get("user_id")) != res.user_id:
        res.problems.append("debug_token and /me disagree on the user id")
    missing = [s for s in SCOPES if s not in res.scopes]
    if missing:
        res.problems.append(f"missing permissions: {', '.join(missing)}")
    if res.expires_at and res.expires_at <= datetime.now(timezone.utc):
        res.problems.append("token has expired")
    res.ok = not res.problems
    return res


def check_pair(checks: list[TokenCheck]) -> list[str]:
    """Problems that involve both accounts (each one may be fine on its own)."""
    ids = [c.user_id for c in checks if c.user_id]
    return ["both tokens belong to the same Threads user"] if len(ids) != len(set(ids)) else []


def register(store: AccountStore, check: TokenCheck, token: str, now: datetime, *,
             allow_identity_change: bool = False) -> None:
    store.register(check.slot, user_id=check.user_id, username=check.username, token=token, now=now,
                   expires_at=check.expires_at, issued_at=check.issued_at, scopes=check.scopes,
                   token_type=check.token_type, data_access_expires_at=check.data_access_expires_at,
                   allow_identity_change=allow_identity_change)


@dataclass
class SlotResult:
    slot: str
    outcome: str        # ok | refreshed | not_due | too_new | mismatch | invalid | failed | skipped
    detail: str = ""


def verify_accounts(settings: ThreadsSettings, store: AccountStore, client: ThreadsClient,
                    now: datetime) -> list[SlotResult]:
    """Each run: the token still maps to the registered user and expected username.
    A mismatch or invalid token stops only that account (status needs_reconnect)."""
    out: list[SlotResult] = []
    for slot in settings.accounts:
        if not store.has_token(slot):
            out.append(SlotResult(slot, "skipped", "no token"))
            continue
        acc = store.get(slot)
        expected = settings.usernames.get(slot) or DEFAULT_USERNAMES.get(slot, "")
        try:
            me = client.me(store.token(slot))
        except ThreadsError as exc:
            if exc.category in ("auth", "permission"):
                store.mark(slot, now, status="needs_reconnect", error=f"token rejected: {exc}")
                logger.error("OPERATOR ACTION NEEDED: Threads %s token rejected: %s", slot, exc)
                out.append(SlotResult(slot, "invalid", exc.category))
            else:
                store.mark(slot, now, error=f"verify failed (will retry): {exc}")
                out.append(SlotResult(slot, "failed", exc.category))
            continue
        uid, uname = str(me.get("id", "")), str(me.get("username", ""))
        if uname != expected or (acc.threads_user_id and uid != acc.threads_user_id):
            store.mark(slot, now, status="needs_reconnect",
                       error=f"token maps to @{uname} ({uid}); registered @{acc.username} ({acc.threads_user_id})")
            logger.error("OPERATOR ACTION NEEDED: Threads %s token maps to another account", slot)
            out.append(SlotResult(slot, "mismatch"))
            continue
        if not acc.threads_user_id:
            # Never registered by `setup`: refuse to guess; the operator runs setup.
            store.mark(slot, now, status="needs_reconnect", error="not registered; run tools.threads setup")
            out.append(SlotResult(slot, "mismatch", "unregistered"))
            continue
        store.mark(slot, now, verified=True, status="connected" if acc.status != "connected" else None)
        out.append(SlotResult(slot, "ok"))
    return out


def refresh_tokens(settings: ThreadsSettings, store: AccountStore, client: ThreadsClient, now: datetime, *,
                   env_path: Path, backup_dir: Path, when_left: timedelta = REFRESH_WHEN_LEFT) -> list[SlotResult]:
    """Refresh env tokens close to expiry; write each into .env atomically.

    The new token is validated (`/me`: same user) before the file changes; the
    previous file is kept in a protected backup until the update is confirmed,
    then that backup is removed (it holds a now-superseded secret)."""
    from .envfile import EnvFileError, update_env

    out: list[SlotResult] = []
    for slot in settings.accounts:
        acc = store.get(slot)
        if not store.has_token(slot) or acc.status == "needs_reconnect":
            out.append(SlotResult(slot, "skipped", acc.status))
            continue
        expires, obtained = _parse(acc.expires_at), _parse(acc.token_obtained_at)
        if expires is None:
            out.append(SlotResult(slot, "not_due", "no expiry reported"))
            continue
        if expires <= now:
            store.mark(slot, now, status="needs_reconnect", error="token expired; generate a new one and run setup")
            logger.error("OPERATOR ACTION NEEDED: Threads %s token expired", slot)
            out.append(SlotResult(slot, "invalid", "expired"))
            continue
        if expires - now > when_left:
            out.append(SlotResult(slot, "not_due"))
            continue
        if obtained is not None and now - obtained < MIN_REFRESH_AGE:
            out.append(SlotResult(slot, "too_new"))
            continue
        try:
            new, _expires_in = client.refresh(store.token(slot))
            check = check_token(slot, new, acc.username, client)
            if not check.ok or check.user_id != acc.threads_user_id:
                raise ThreadsError("refreshed token failed validation: " + "; ".join(check.problems),
                                   category="auth")
            backup = update_env(env_path, {ENV_TOKEN_VAR[slot]: new}, backup_dir=backup_dir,
                                label=f"env-before-threads-{slot}-refresh")
            register(store, check, new, now)
            store.update(slot, lambda a: setattr(a, "last_refresh_at", now.replace(microsecond=0).isoformat()))
            store.set_env_token(slot, new)
            backup.unlink(missing_ok=True)
            out.append(SlotResult(slot, "refreshed"))
        except ThreadsError as exc:
            if exc.category in ("auth", "permission"):
                store.mark(slot, now, error=f"refresh refused: {exc}")
                logger.error("OPERATOR ACTION NEEDED: Threads %s refresh refused: %s", slot, exc)
            else:
                store.mark(slot, now, error=f"refresh failed (will retry): {exc}")
            out.append(SlotResult(slot, "failed", exc.category))
        except (EnvFileError, OSError, TokenStorageError, SlotConflict) as exc:
            store.mark(slot, now, error=f"refresh not saved: {type(exc).__name__}")
            logger.error("OPERATOR ACTION NEEDED: Threads %s refresh could not be saved", slot)
            out.append(SlotResult(slot, "failed", "storage"))
    return out


__all__ = ["DEFAULT_USERNAMES", "ENV_TOKEN_VAR", "REFRESH_WHEN_LEFT", "SlotResult", "TokenCheck", "check_pair",
           "check_token", "refresh_tokens", "register", "verify_accounts"]
