"""Threads account slots, encrypted tokens and one-time OAuth states.

Storage follows the project's convention for operational state: JSON files
under `data/` written atomically under an `fcntl` lock (as the publication
job store). What is different here is the secret:

* The access token is stored ONLY as a Fernet ciphertext (AES-128-CBC +
  HMAC-SHA256, from the `cryptography` package) under
  `CYBERALERTX_THREADS_TOKEN_KEY`. Without the key — or without the package —
  no token can be stored or read: connecting fails closed, the rest of the
  platform is unaffected.
* `to_public()` is the only view that leaves this module for the admin UI and
  JSON; it never contains the token or its ciphertext.
* The file is created with mode 0600.

OAuth `state` values are 32 random bytes (`secrets.token_urlsafe`). Only their
SHA-256 is stored, bound to one slot, valid for `STATE_TTL`, and deleted when
used — so a state can be consumed once, only for the slot it was issued for.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from ..config import DATA_DIR

ACCOUNTS_PATH = DATA_DIR / "threads_accounts.json"
STATES_PATH = DATA_DIR / "threads_oauth_states.json"
STATE_TTL = timedelta(minutes=10)

#: connected        token valid, last API check succeeded (or not yet failed)
#: needs_reconnect  token expired / revoked / refresh refused: an admin must reconnect
#: disconnected     never connected, or disconnected by an admin
STATUSES = ("disconnected", "connected", "needs_reconnect")


class TokenStorageError(RuntimeError):
    """Tokens cannot be encrypted/decrypted (no key, bad key, no package)."""


def _iso(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat() if dt else ""


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


class TokenCipher:
    def __init__(self, key: str) -> None:
        if not key:
            raise TokenStorageError("CYBERALERTX_THREADS_TOKEN_KEY is not set")
        try:
            from cryptography.fernet import Fernet  # type: ignore[import-not-found,unused-ignore]
        except ImportError as exc:                     # pragma: no cover - environment
            raise TokenStorageError("the 'cryptography' package is not installed") from exc
        try:
            self._f = Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise TokenStorageError("CYBERALERTX_THREADS_TOKEN_KEY is not a valid Fernet key") from exc

    def encrypt(self, token: str) -> str:
        return str(self._f.encrypt(token.encode()).decode())

    def decrypt(self, blob: str) -> str:
        from cryptography.fernet import InvalidToken  # type: ignore[import-not-found,unused-ignore]
        try:
            return str(self._f.decrypt(blob.encode()).decode())
        except InvalidToken as exc:
            raise TokenStorageError("stored token cannot be decrypted with the current key") from exc


@dataclass
class Account:
    slot: str
    locale: str
    status: str = "disconnected"
    threads_user_id: str = ""
    username: str = ""
    name: str = ""
    token_ciphertext: str = field(default="", repr=False)
    token_obtained_at: str = ""         # when the current long-lived token was issued/refreshed
    expires_at: str = ""
    last_refresh_at: str = ""
    last_verified_at: str = ""
    last_error: str = ""
    rate_limited_until: str = ""
    connected_at: str = ""
    disconnected_at: str = ""
    scopes: list[str] = field(default_factory=list)
    # -- env-token mode (THREADS_*_ACCESS_TOKEN); no secret is stored here ---------
    token_source: str = ""              # "env" | "oauth"
    token_fingerprint: str = ""         # sha256 prefix of the token: detects a changed token, reveals nothing
    token_type: str = ""                # from debug_token (e.g. USER)
    data_access_expires_at: str = ""
    last_published_at: str = ""
    publications: list[str] = field(default_factory=list)   # recent publication times (daily cap)
    publishing_since: str = ""          # first enabled run: nothing older is ever posted (no backlog)

    def to_public(self, now: datetime | None = None) -> dict[str, Any]:
        d = asdict(self)
        d.pop("token_ciphertext")
        d["has_token"] = bool(self.token_ciphertext) or self.token_source == "env"
        exp = _parse(self.expires_at)
        if exp and now:
            d["expires_in_days"] = round((exp - now).total_seconds() / 86400, 1)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Account":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class _JsonFile:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        with open(self.path.with_suffix(".lock"), "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except ValueError as exc:
            raise RuntimeError(f"{self.path} is unreadable: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def write(self, data: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=f".{self.path.stem}.")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


class AccountStore:
    """Account slots. Each mutation touches exactly one slot."""

    def __init__(self, path: Path = ACCOUNTS_PATH, *, key: str = "", mapping: dict[str, str] | None = None,
                 env_tokens: dict[str, str] | None = None) -> None:
        self._file = _JsonFile(path)
        self._key = key
        self.mapping = dict(mapping or {"en": "en", "ua": "ua"})
        #: Tokens from THREADS_*_ACCESS_TOKEN. When set, they are the only token
        #: source; nothing token-like is written to the registry.
        self._env = {k: v for k, v in (env_tokens or {}).items() if v}

    def _cipher(self) -> TokenCipher:
        return TokenCipher(self._key)

    def get(self, slot: str) -> Account:
        if slot not in self.mapping:
            raise KeyError(f"unknown Threads slot {slot!r}")
        raw = self._file.read().get(slot)
        acc = Account.from_dict(raw) if raw else Account(slot=slot, locale=self.mapping[slot])
        acc.locale = self.mapping[slot]               # configuration is the source of truth
        return acc

    def all(self) -> list[Account]:
        return [self.get(s) for s in self.mapping]

    def update(self, slot: str, fn: Callable[[Account], None]) -> Account:
        if slot not in self.mapping:
            raise KeyError(f"unknown Threads slot {slot!r}")
        with self._file.locked():
            data = self._file.read()
            raw = data.get(slot)
            acc = Account.from_dict(raw) if raw else Account(slot=slot, locale=self.mapping[slot])
            acc.locale = self.mapping[slot]
            fn(acc)
            data[slot] = asdict(acc)
            self._file.write(data)
            return acc

    # -- tokens ----------------------------------------------------------------

    @property
    def env_mode(self) -> bool:
        return bool(self._env)

    def has_token(self, slot: str) -> bool:
        if self._env:
            return bool(self._env.get(slot))
        return bool(self.get(slot).token_ciphertext)

    def set_env_token(self, slot: str, token: str) -> None:
        """After an atomic .env refresh: use the new token for the rest of this process."""
        self._env[slot] = token

    def token(self, slot: str) -> str:
        if self._env:
            tok = self._env.get(slot, "")
            if not tok:
                raise TokenStorageError(f"THREADS_{slot.upper()}_ACCESS_TOKEN is not set")
            return tok
        acc = self.get(slot)
        if not acc.token_ciphertext:
            raise TokenStorageError(f"no token stored for Threads slot {slot!r}")
        return self._cipher().decrypt(acc.token_ciphertext)

    def save_connection(self, slot: str, *, token: str, expires_in: int, user_id: str, username: str,
                        name: str, now: datetime, scopes: list[str] | None = None) -> Account:
        blob = self._cipher().encrypt(token)          # fails closed before anything is written

        def f(a: Account) -> None:
            if a.threads_user_id and a.threads_user_id != user_id and a.status == "connected":
                # Reconnecting a slot to a DIFFERENT profile must be deliberate:
                # disconnect first. Stops an EN connect landing on the UA slot's profile.
                raise SlotConflict(f"slot {slot!r} is connected to another Threads profile "
                                   f"(@{a.username}); disconnect it first")
            a.status, a.token_ciphertext = "connected", blob
            a.threads_user_id, a.username, a.name = user_id, username, name
            a.token_obtained_at = a.connected_at = _iso(now)
            a.expires_at = _iso(now + timedelta(seconds=int(expires_in)))
            a.last_verified_at, a.last_error, a.disconnected_at = _iso(now), "", ""
            a.scopes = list(scopes or [])
        return self.update(slot, f)

    def save_refresh(self, slot: str, *, token: str, expires_in: int, now: datetime) -> Account:
        blob = self._cipher().encrypt(token)

        def f(a: Account) -> None:
            a.token_ciphertext, a.token_obtained_at = blob, _iso(now)
            a.expires_at = _iso(now + timedelta(seconds=int(expires_in)))
            a.last_refresh_at, a.last_error = _iso(now), ""
            if a.status == "needs_reconnect":
                a.status = "connected"
        return self.update(slot, f)

    def register(self, slot: str, *, user_id: str, username: str, token: str, now: datetime,
                 expires_at: datetime | None, issued_at: datetime | None, scopes: list[str],
                 token_type: str = "", data_access_expires_at: datetime | None = None,
                 allow_identity_change: bool = False) -> Account:
        """Record a verified env-token account (from `/me` + `debug_token`).

        A slot never silently changes identity: if it already maps to another
        Threads user, this refuses unless the operator explicitly allows it."""
        fp = token_fingerprint(token)

        def f(a: Account) -> None:
            if a.threads_user_id and a.threads_user_id != user_id and not allow_identity_change:
                raise SlotConflict(f"slot {slot!r} is registered to another Threads user "
                                   f"(@{a.username}); refusing to swap identities")
            if a.token_fingerprint != fp:
                a.token_obtained_at = _iso(issued_at or now)
            a.status, a.token_source, a.token_fingerprint, a.token_ciphertext = "connected", "env", fp, ""
            a.threads_user_id, a.username = user_id, username
            a.expires_at = _iso(expires_at) if expires_at else ""
            a.data_access_expires_at = _iso(data_access_expires_at) if data_access_expires_at else ""
            a.token_type, a.scopes = token_type, list(scopes)
            a.connected_at = a.connected_at or _iso(now)
            a.last_verified_at, a.last_error, a.disconnected_at = _iso(now), "", ""
        return self.update(slot, f)

    def record_publication(self, slot: str, now: datetime) -> Account:
        def f(a: Account) -> None:
            keep = [t for t in a.publications if (_parse(t) or now) > now - timedelta(days=1)]
            a.publications = keep + [_iso(now)]
            a.last_published_at = _iso(now)
        return self.update(slot, f)

    def published_last_24h(self, slot: str, now: datetime) -> int:
        return sum(1 for t in self.get(slot).publications if (_parse(t) or now) > now - timedelta(days=1))

    def ensure_publishing_since(self, slot: str, now: datetime) -> datetime:
        acc = self.get(slot)
        since = _parse(acc.publishing_since)
        if since is None:
            def f(a: Account) -> None:
                a.publishing_since = a.publishing_since or _iso(now)
            acc = self.update(slot, f)
            since = _parse(acc.publishing_since) or now
        return since

    def disconnect(self, slot: str, now: datetime, reason: str = "disconnected by admin") -> Account:
        def f(a: Account) -> None:
            a.status, a.token_ciphertext, a.expires_at = "disconnected", "", ""
            a.disconnected_at, a.last_error = _iso(now), reason if reason != "disconnected by admin" else ""
        return self.update(slot, f)

    def mark(self, slot: str, now: datetime, *, status: str | None = None, error: str | None = None,
             verified: bool = False, rate_limited_until: datetime | None = None) -> Account:
        def f(a: Account) -> None:
            if status is not None:
                a.status = status
            if error is not None:
                a.last_error = error[:300]
            if verified:
                a.last_verified_at, a.last_error = _iso(now), ""
            if rate_limited_until is not None:
                a.rate_limited_until = _iso(rate_limited_until)
        return self.update(slot, f)


class SlotConflict(RuntimeError):
    pass


def token_fingerprint(token: str) -> str:
    """12 hex chars of SHA-256: enough to notice a changed token, useless to an attacker."""
    return hashlib.sha256(token.encode()).hexdigest()[:12] if token else ""


class StateStore:
    """One-time OAuth `state` values bound to a slot."""

    def __init__(self, path: Path = STATES_PATH) -> None:
        self._file = _JsonFile(path)

    @staticmethod
    def _h(state: str) -> str:
        return hashlib.sha256(state.encode()).hexdigest()

    def issue(self, slot: str, now: datetime) -> str:
        state = secrets.token_urlsafe(32)
        with self._file.locked():
            data = {k: v for k, v in self._file.read().items()
                    if (_parse(v.get("expires_at", "")) or now) > now}      # drop expired ones
            data[self._h(state)] = {"slot": slot, "issued_at": _iso(now), "expires_at": _iso(now + STATE_TTL)}
            self._file.write(data)
        return state

    def consume(self, state: str, now: datetime) -> str:
        """The slot this state was issued for. Raises ValueError if the state
        is unknown, already used or expired. Always deletes it."""
        if not state or len(state) > 200:
            raise ValueError("missing or malformed state")
        key = self._h(state)
        with self._file.locked():
            data = self._file.read()
            rec = data.pop(key, None)
            if rec is not None:
                self._file.write(data)
        if rec is None:
            raise ValueError("unknown or already used state")
        exp = _parse(rec.get("expires_at", ""))
        if exp is None or exp <= now:
            raise ValueError("expired state")
        return str(rec["slot"])


__all__ = ["ACCOUNTS_PATH", "Account", "AccountStore", "STATES_PATH", "STATE_TTL", "STATUSES",
           "SlotConflict", "StateStore", "TokenCipher", "TokenStorageError", "token_fingerprint"]
