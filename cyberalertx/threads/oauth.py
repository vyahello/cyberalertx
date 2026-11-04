"""Connect, callback, refresh and verify — per account slot.

Flow (official Threads authorization, see docs/threads/THREADS_SETUP.md):

  1. An admin presses Connect for a slot → `start_connect` issues a one-time
     state bound to that slot and returns the authorization URL.
  2. Threads redirects to CYBERALERTX_THREADS_REDIRECT_URI with `code` and
     `state` (or `error=access_denied`).
  3. `complete_callback` consumes the state (→ the slot it was issued for; the
     callback cannot choose a slot), exchanges the code for a short-lived
     token, exchanges that for a 60-day long-lived token, reads the profile,
     checks it is the same user the token was issued to, and stores the token
     encrypted in THAT slot only.

Refresh: long-lived tokens can be refreshed once they are 24 h old and not
yet expired; each refresh gives 60 days. `refresh_due` refreshes any token
with fewer than `REFRESH_WHEN_LEFT` days left. An expired token cannot be
refreshed — the slot goes to `needs_reconnect` and only that slot stops.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .accounts import Account, AccountStore, StateStore, TokenStorageError, _parse
from .client import ThreadsClient, ThreadsError
from .config import SCOPES, ThreadsSettings

logger = logging.getLogger(__name__)

MIN_REFRESH_AGE = timedelta(hours=24)
REFRESH_WHEN_LEFT = timedelta(days=30)


class OAuthError(RuntimeError):
    """A connection attempt failed; the message is safe to show to an admin."""


def start_connect(slot: str, *, settings: ThreadsSettings, states: StateStore, now: datetime) -> str:
    if slot not in settings.accounts:
        raise OAuthError(f"unknown Threads slot {slot!r}")
    if not settings.oauth_configured:
        raise OAuthError("Threads OAuth is not configured (app id, secret, https redirect URI and token key)")
    state = states.issue(slot, now)
    return ThreadsClient.authorize_url(settings.authorize_url, app_id=settings.app_id,
                                       redirect_uri=settings.redirect_uri, state=state, scopes=SCOPES)


def complete_callback(params: dict[str, str], *, settings: ThreadsSettings, states: StateStore,
                      accounts: AccountStore, client: ThreadsClient, now: datetime) -> Account:
    state = params.get("state", "")
    try:
        slot = states.consume(state, now)            # one-time; bound slot; expiry
    except ValueError as exc:
        raise OAuthError(f"Connection refused: {exc}. Start again from /admin/threads.") from exc
    if params.get("error"):
        reason = params.get("error_reason") or params.get("error", "")
        raise OAuthError(f"Threads authorization for '{slot}' was not granted ({reason[:60]}).")
    code = params.get("code", "").removesuffix("#_")
    if not code:
        raise OAuthError("Threads returned no authorization code.")
    if not settings.oauth_configured:
        raise OAuthError("Threads OAuth is not configured.")
    try:
        short, user_id = client.exchange_code(app_id=settings.app_id, app_secret=settings.app_secret,
                                              redirect_uri=settings.redirect_uri, code=code)
        token, expires_in = client.long_lived(app_secret=settings.app_secret, short_token=short)
        me = client.me(token)
    except ThreadsError as exc:
        logger.warning("threads connect failed for slot %s: %s", slot, exc)   # scrubbed
        raise OAuthError(f"Threads rejected the connection for '{slot}' ({exc.category}).") from exc
    if str(me.get("id", "")) != user_id:
        raise OAuthError("The token and the profile do not match; nothing was saved.")
    try:
        acc = accounts.save_connection(slot, token=token, expires_in=expires_in, user_id=user_id,
                                       username=str(me.get("username", "")), name=str(me.get("name", "")),
                                       now=now, scopes=list(SCOPES))
    except TokenStorageError as exc:
        raise OAuthError(f"Token storage unavailable: {exc}") from exc
    except RuntimeError as exc:                       # SlotConflict
        raise OAuthError(str(exc)) from exc
    logger.info("threads slot %s connected to @%s", slot, acc.username)
    return acc


@dataclass
class RefreshResult:
    slot: str
    outcome: str        # refreshed | not_due | too_new | expired | failed | skipped
    detail: str = ""


def refresh_due(accounts: AccountStore, client: ThreadsClient, now: datetime, *,
                when_left: timedelta = REFRESH_WHEN_LEFT) -> list[RefreshResult]:
    out: list[RefreshResult] = []
    for acc in accounts.all():
        if acc.status == "disconnected" or not acc.token_ciphertext:
            out.append(RefreshResult(acc.slot, "skipped", acc.status))
            continue
        expires, obtained = _parse(acc.expires_at), _parse(acc.token_obtained_at)
        if expires is None or expires <= now:
            accounts.mark(acc.slot, now, status="needs_reconnect",
                          error="token expired; reconnect from /admin/threads")
            logger.error("OPERATOR ACTION NEEDED: Threads slot %s token expired", acc.slot)
            out.append(RefreshResult(acc.slot, "expired"))
            continue
        if expires - now > when_left:
            out.append(RefreshResult(acc.slot, "not_due"))
            continue
        if obtained is not None and now - obtained < MIN_REFRESH_AGE:
            out.append(RefreshResult(acc.slot, "too_new"))
            continue
        try:
            token, expires_in = client.refresh(accounts.token(acc.slot))
            accounts.save_refresh(acc.slot, token=token, expires_in=expires_in, now=now)
            out.append(RefreshResult(acc.slot, "refreshed"))
        except ThreadsError as exc:
            if exc.category in ("auth", "permission"):
                accounts.mark(acc.slot, now, status="needs_reconnect", error=f"refresh refused: {exc}")
                logger.error("OPERATOR ACTION NEEDED: Threads slot %s refresh refused: %s", acc.slot, exc)
            else:
                accounts.mark(acc.slot, now, error=f"refresh failed (will retry): {exc}")
            out.append(RefreshResult(acc.slot, "failed", exc.category))
        except TokenStorageError as exc:
            accounts.mark(acc.slot, now, error=str(exc))
            out.append(RefreshResult(acc.slot, "failed", "storage"))
    return out


def verify(slot: str, accounts: AccountStore, client: ThreadsClient, now: datetime) -> Account:
    """One authenticated call (`/me`); updates health without touching other slots."""
    acc = accounts.get(slot)
    try:
        me: dict[str, Any] = client.me(accounts.token(slot))
    except TokenStorageError as exc:
        return accounts.mark(slot, now, error=str(exc))
    except ThreadsError as exc:
        status = "needs_reconnect" if exc.category in ("auth", "permission") else None
        return accounts.mark(slot, now, status=status, error=f"verify failed: {exc}")
    if str(me.get("id", "")) != acc.threads_user_id:
        return accounts.mark(slot, now, status="needs_reconnect", error="token now belongs to another profile")
    return accounts.mark(slot, now, verified=True,
                         status="connected" if acc.status == "needs_reconnect" else None)


__all__ = ["MIN_REFRESH_AGE", "OAuthError", "REFRESH_WHEN_LEFT", "RefreshResult", "complete_callback",
           "refresh_due", "start_connect", "verify"]
