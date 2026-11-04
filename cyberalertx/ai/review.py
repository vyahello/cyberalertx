"""Editorial review state: modes, visibility, and the editor's decisions.

`ThreatPost.review_status` is one of:

    auto      published without review (every post cached before this
              feature existed loads as auto)
    pending   the scorecard asked for a human look
    approved  the editor signed it off
    rejected  the editor turned it down

`CYBERALERTX_REVIEW_MODE` decides what those mean for readers:

    off   no review at all: nothing is queued at generation time and nothing
          is hidden. The escape hatch — behaves exactly as before.
    flag  (default) posts the scorecard flags are marked `pending` and keep
          publishing; the editor works the queue after the fact. A post the
          editor explicitly REJECTS is taken down — otherwise the Reject
          button would change nothing a reader sees.
    hold  as flag, and `pending` posts are also withheld from the feed, RSS,
          trending, latest, the detail endpoint (404) and Telegram until
          approved.

The mode is read from the environment on every call (cheap), so a test or an
operator can flip it without rebuilding the app.
"""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

from .models import REVIEW_STATUSES, ThreatPost

MODE_ENV = "CYBERALERTX_REVIEW_MODE"
REVIEW_MODES: tuple[str, ...] = ("off", "flag", "hold")
DEFAULT_MODE = "flag"

#: Decision verb → stored status.
DECISIONS: dict[str, str] = {"approve": "approved", "reject": "rejected"}


class _PostStore(Protocol):
    def get(self, fingerprint: str, locale: str = "en") -> ThreatPost | None: ...
    def set(self, fingerprint: str, locale: str, post: ThreatPost) -> None: ...
    def all(self) -> Iterable[ThreatPost]: ...


def review_mode() -> str:
    raw = os.getenv(MODE_ENV, "").strip().lower()
    return raw if raw in REVIEW_MODES else DEFAULT_MODE


def initial_status(needs_review: bool, mode: str | None = None) -> str:
    """Status a freshly generated post is cached with."""
    mode = mode or review_mode()
    return "pending" if needs_review and mode in ("flag", "hold") else "auto"


def hidden_statuses(mode: str | None = None) -> frozenset[str]:
    mode = mode or review_mode()
    if mode == "hold":
        return frozenset({"pending", "rejected"})
    if mode == "flag":
        return frozenset({"rejected"})
    return frozenset()


def is_publicly_visible(post: Any, mode: str | None = None) -> bool:
    """May readers (site, RSS, Telegram) see this post under `mode`?"""
    status = getattr(post, "review_status", "auto") or "auto"
    return status not in hidden_statuses(mode)


def parse_key(key: str) -> tuple[str, str]:
    """"<fingerprint>:<locale>" → (fingerprint, locale). Raises ValueError."""
    fingerprint, sep, locale = (key or "").strip().rpartition(":")
    locale = "ua" if locale == "uk" else locale
    if not sep or not fingerprint or locale not in ("en", "ua") or not fingerprint.isalnum():
        raise ValueError(f"expected FINGERPRINT:LOCALE (locale en|ua), got {key!r}")
    return fingerprint, locale


def post_key(post: ThreatPost) -> str:
    locale = "ua" if post.language in ("ua", "uk") else (post.language or "en")
    return f"{post.source_fingerprint}:{locale}"


def apply_decision(
    cache: _PostStore,
    fingerprint: str,
    locale: str,
    decision: str,
    reviewer: str,
    *,
    now: datetime | None = None,
) -> ThreatPost:
    """Persist an approve/reject through the cache backend (JSON, and PG when
    dual-write is on). Raises KeyError if no such post, ValueError on a bad
    decision. The post text is never touched — only the review fields."""
    status = DECISIONS.get(decision)
    if status is None:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}, got {decision!r}")
    post = cache.get(fingerprint, locale)
    if post is None:
        raise KeyError(f"{fingerprint}:{locale}")
    when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    updated = replace(
        post,
        review_status=status,
        reviewed_by=(reviewer or "editor").strip()[:80],
        reviewed_at=when.replace(microsecond=0).isoformat(),
    )
    # A human decision must not be lost quietly: under dual-write, use the
    # strict path, which still writes JSON first but raises
    # `SecondaryWriteError` when Postgres did not take the change.
    strict = getattr(cache, "set_strict", None)
    if callable(strict):
        strict(fingerprint, locale, updated)
    else:
        cache.set(fingerprint, locale, updated)
    return updated


def posts_with_status(cache: _PostStore, statuses: Iterable[str]) -> list[ThreatPost]:
    wanted = set(statuses) & set(REVIEW_STATUSES)
    return [p for p in cache.all() if (p.review_status or "auto") in wanted]


__all__ = [
    "DECISIONS",
    "DEFAULT_MODE",
    "MODE_ENV",
    "REVIEW_MODES",
    "apply_decision",
    "hidden_statuses",
    "initial_status",
    "is_publicly_visible",
    "parse_key",
    "post_key",
    "posts_with_status",
    "review_mode",
]
