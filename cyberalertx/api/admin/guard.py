"""Who may see /admin/*, and what happens to everyone else.

Authentication is HTTP Basic against `CYBERALERTX_ADMIN_TOKEN`. Basic rather
than a `?token=` query parameter because nginx writes the full request URI
into a log it keeps for 365 days; a token in a URL would be on disk forever.
Any username is accepted — there is no admin *account* to discover or take
over, only the one secret.

WHAT BRUTE FORCE CAN AND CANNOT DO HERE

The token is meant to be `openssl rand -hex 32`: 256 bits. Guessing it is not
a slow attack, it is an impossible one — at a billion guesses a second the
expected time is around 10^60 years. Tokens under 24 characters are refused
outright, so a weak one can't be configured by accident.

The lockout below is therefore not what keeps the password safe. It exists
because a public login endpoint attracts scanners, and every wrong attempt
costs a constant-time compare and a log line. After `MAX_FAILURES` wrong
passwords from one address inside `WINDOW`, that address gets 429 for
`LOCKOUT` without the password being looked at. Every failure is also kept
for 24 hours so the overview page can show who is knocking.

WHY THE CLIENT ADDRESS CAN BE TRUSTED

The address comes from `X-Real-IP`, which nginx sets to `$remote_addr` and
overwrites whatever the client sent. nginx resolves `$remote_addr` with
`real_ip_header CF-Connecting-IP`, trusted only from Cloudflare's ranges
(`set_real_ip_from`). A client connecting directly gets its real socket
address. The API listens on 127.0.0.1 only, so nothing reaches it except
through that nginx. If that ever changes, this header becomes spoofable and
the lockout must move to nginx.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import HTTPException, Request
from fastapi.security import HTTPBasicCredentials

logger = logging.getLogger(__name__)

TOKEN_ENV = "CYBERALERTX_ADMIN_TOKEN"
MIN_TOKEN_LEN = 24

MAX_FAILURES = 5
WINDOW = 15 * 60.0
LOCKOUT = 15 * 60.0
_REPORT_WINDOW = timedelta(hours=24)
#: Stop remembering addresses past this many, oldest first. Bounds memory if
#: the endpoint is sprayed from a large botnet.
_MAX_TRACKED_ADDRESSES = 5000

REALM = 'Basic realm="CyberAlertX admin", charset="UTF-8"'


@dataclass(frozen=True)
class GuardStats:
    """Failed logins over the last 24 hours, for the overview page."""

    failed_24h: int
    addresses_24h: int
    top_addresses: list[tuple[str, int]]
    last_failure_at: datetime | None
    locked_now: int
    tracking_since: datetime


class AdminGuard:
    """FastAPI dependency guarding every /admin/* route."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._clock = clock
        self._now = now
        self._lock = threading.Lock()
        self._recent: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._log: deque[tuple[datetime, str]] = deque()
        self._started = now()
        self._warned_unconfigured = False

    # -- the dependency -----------------------------------------------------

    def check(self, request: Request, credentials: HTTPBasicCredentials | None) -> None:
        expected = os.getenv(TOKEN_ENV, "").strip()
        if len(expected) < MIN_TOKEN_LEN:
            # The hint goes to the server log, not the response. The public
            # body names no variable and no framework.
            if not self._warned_unconfigured:
                logger.warning(
                    "/admin is disabled: set %s to a random value of at least "
                    "%d characters (e.g. `openssl rand -hex 32`)", TOKEN_ENV, MIN_TOKEN_LEN,
                )
                self._warned_unconfigured = True
            raise HTTPException(status_code=503, detail="Not available.")

        address = client_address(request)
        with self._lock:
            retry = self._retry_after(address)
        if retry is not None:
            raise HTTPException(
                status_code=429,
                detail="Too many failed attempts. Try again later.",
                headers={"Retry-After": str(retry)},
            )

        if credentials is None:
            # The browser's first request never carries credentials; that is
            # how it learns to show the login box. Not a failed attempt.
            raise _challenge()

        supplied = credentials.password.encode("utf-8")
        if secrets.compare_digest(supplied, expected.encode("utf-8")):
            with self._lock:
                self._recent.pop(address, None)
            return

        with self._lock:
            self._record_failure(address)
        logger.warning("failed /admin login from %s", address)
        raise _challenge()

    # -- reporting ----------------------------------------------------------

    def stats(self) -> GuardStats:
        with self._lock:
            cutoff = self._now() - _REPORT_WINDOW
            while self._log and self._log[0][0] < cutoff:
                self._log.popleft()
            counts = Counter(addr for _, addr in self._log)
            now = self._clock()
            locked = sum(1 for until in self._locked_until.values() if until > now)
            return GuardStats(
                failed_24h=len(self._log),
                addresses_24h=len(counts),
                top_addresses=counts.most_common(5),
                last_failure_at=self._log[-1][0] if self._log else None,
                locked_now=locked,
                tracking_since=self._started,
            )

    # -- internals (call with the lock held) --------------------------------

    def _retry_after(self, address: str) -> int | None:
        until = self._locked_until.get(address)
        if until is None:
            return None
        remaining = until - self._clock()
        if remaining <= 0:
            del self._locked_until[address]
            return None
        return max(1, int(remaining))

    def _record_failure(self, address: str) -> None:
        now = self._clock()
        self._log.append((self._now(), address))
        recent = self._recent.setdefault(address, deque())
        recent.append(now)
        while recent and now - recent[0] > WINDOW:
            recent.popleft()
        if len(recent) >= MAX_FAILURES:
            self._locked_until[address] = now + LOCKOUT
            self._recent.pop(address, None)
            logger.warning("locking /admin for %s after %d failures", address, MAX_FAILURES)
        if len(self._recent) > _MAX_TRACKED_ADDRESSES:
            oldest = min(self._recent, key=lambda a: self._recent[a][-1] if self._recent[a] else 0.0)
            self._recent.pop(oldest, None)


def client_address(request: Request) -> str:
    """The visitor's address as nginx resolved it. See the module docstring
    for why this header is trustworthy in this deployment."""
    forwarded = request.headers.get("x-real-ip", "").strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _challenge() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Authentication required.",
        headers={"WWW-Authenticate": REALM},
    )


__all__ = ["AdminGuard", "GuardStats", "MIN_TOKEN_LEN", "TOKEN_ENV", "client_address"]
