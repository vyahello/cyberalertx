"""Generic RSS / Atom source.

Uses `feedparser` because it handles every flavor of RSS, Atom, RDF, and
malformed-but-real-world feeds you'll encounter (Krebs, BleepingComputer,
CISA all serve slightly different shapes).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from time import mktime
from typing import Any, Callable, List, Optional

import feedparser
import httpx

from ..models import NewsItem
from .base import Source

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", _HTML_TAG_RE.sub(" ", text)).strip()


# Per-source backoff after a failed fetch (O-CISA). The ingest loop runs
# every 30 min; a feed whose origin refuses us would otherwise log the same
# failure 48 times a day. Delay doubles per consecutive failure from
# _BACKOFF_BASE, capped by the failure class; a Retry-After header (429/503)
# is honoured when it asks for longer. In-memory: a restart retries once.
_BACKOFF_BASE = timedelta(minutes=30)
_BACKOFF_CAP_REFUSED = timedelta(hours=24)    # 401/403/404/410: the origin says no
_BACKOFF_CAP_TRANSIENT = timedelta(hours=6)   # 429, 5xx, timeouts, network, bad XML
_REFUSED = frozenset({401, 403, 404, 410})


@dataclass(frozen=True)
class FetchOutcome:
    """What the last `fetch()` did, for source health and the admin page.

    status: "ok" (items or a valid empty feed), "error" (this attempt failed),
    "skipped" (backing off after earlier failures; no request was made).
    """
    status: str
    error: str = ""                 # e.g. "http_403", "timeout", "invalid_feed"
    detail: str = ""
    consecutive_failures: int = 0
    next_attempt_utc: Optional[datetime] = None


class _FetchError(Exception):
    def __init__(self, kind: str, detail: str, retry_after: Optional[timedelta] = None,
                 refused: bool = False) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail, self.retry_after, self.refused = kind, detail, retry_after, refused


def _retry_after(value: Optional[str], now: datetime) -> Optional[timedelta]:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return timedelta(seconds=int(value))
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(when - now, timedelta(0))


class RssSource(Source):
    """Pull items from a single RSS / Atom feed URL."""

    def __init__(
        self,
        name: str,
        url: str,
        timeout: int = 15,
        user_agent: str = "CyberAlertX/1.0 (+https://cyberalertx.com)",
        *,
        clock: Callable[[], datetime] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(name)
        self._url = url
        self._timeout = timeout
        self._user_agent = user_agent
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._transport = transport          # tests inject httpx.MockTransport
        self._failures = 0
        self._last_error = ""
        self._next_attempt: Optional[datetime] = None
        self.last_outcome = FetchOutcome("ok")

    def fetch(self) -> List[NewsItem]:
        now = self._clock()
        if self._next_attempt is not None and now < self._next_attempt:
            self.last_outcome = FetchOutcome("skipped", self._last_error, "backing off",
                                             self._failures, self._next_attempt)
            logger.debug("Source %s skipped until %s (%s)", self.name, self._next_attempt, self._last_error)
            return []
        try:
            items = self._parse_checked(self._download(now))
        except _FetchError as exc:
            return self._failed(exc, now)
        if self._failures:
            logger.info("Source %s recovered after %d failed attempt(s)", self.name, self._failures)
        self._failures, self._last_error, self._next_attempt = 0, "", None
        self.last_outcome = FetchOutcome("ok")
        return items

    def _failed(self, exc: _FetchError, now: datetime) -> List[NewsItem]:
        self._failures += 1
        cap = _BACKOFF_CAP_REFUSED if exc.refused else _BACKOFF_CAP_TRANSIENT
        delay = min(cap, _BACKOFF_BASE * (2 ** (self._failures - 1)))
        if exc.retry_after is not None:
            delay = min(_BACKOFF_CAP_REFUSED, max(delay, exc.retry_after))
        self._next_attempt = now + delay
        changed = exc.kind != self._last_error
        self._last_error = exc.kind
        self.last_outcome = FetchOutcome("error", exc.kind, exc.detail, self._failures, self._next_attempt)
        # Warn when a source starts failing or fails differently; repeats are info.
        (logger.warning if self._failures == 1 or changed else logger.info)(
            "Source %s fetch failed (%s: %s); %d consecutive, next attempt in %s",
            self.name, exc.kind, exc.detail, self._failures, _human(delay))
        return []

    def _download(self, now: datetime) -> bytes:
        """We download bytes ourselves (instead of letting feedparser do it)
        so we control timeout, redirects and request headers.

        The User-Agent identifies CyberAlertX (no browser impersonation).
        Origins that refuse automated readers (CISA's edge answers 403 to
        data-centre networks, including Cloudflare Workers) are reported as
        failing and backed off, never worked around.
        """
        headers = {
            "User-Agent": self._user_agent,
            "Accept": (
                "application/rss+xml, application/atom+xml, "
                "application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"
            ),
            "Accept-Language": "en-US,en;q=0.9,uk;q=0.6",
        }
        try:
            with httpx.Client(timeout=self._timeout, headers=headers, follow_redirects=True,
                              max_redirects=5, transport=self._transport) as client:
                resp = client.get(self._url)
        except httpx.TimeoutException as exc:
            raise _FetchError("timeout", f"no response within {self._timeout}s") from exc
        except httpx.TooManyRedirects as exc:
            raise _FetchError("redirect_loop", "more than 5 redirects") from exc
        except httpx.HTTPError as exc:
            raise _FetchError("network", type(exc).__name__) from exc
        if resp.status_code >= 400:
            code = resp.status_code
            raise _FetchError(f"http_{code}", resp.reason_phrase or "error",
                              retry_after=_retry_after(resp.headers.get("Retry-After"), now)
                              if code in (429, 503) else None,
                              refused=code in _REFUSED)
        return resp.content

    def _parse_checked(self, payload: bytes) -> List[NewsItem]:
        parsed = feedparser.parse(payload)
        if parsed.bozo and not parsed.entries:
            raise _FetchError("invalid_feed", type(parsed.bozo_exception).__name__)
        return self._parse(payload, parsed)

    def _parse(self, payload: bytes, parsed: Any = None) -> List[NewsItem]:
        parsed = parsed if parsed is not None else feedparser.parse(payload)
        if parsed.bozo and not parsed.entries:
            logger.warning("Source %s returned unparseable feed: %s", self.name, parsed.bozo_exception)
            return []

        items: List[NewsItem] = []
        for entry in parsed.entries:
            published = _entry_datetime(entry)
            title = (getattr(entry, "title", "") or "").strip()
            url = (getattr(entry, "link", "") or "").strip()
            if not title or not url:
                continue
            raw_content = _strip_html(
                getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
            )
            byline = _strip_html(str(getattr(entry, "author", "") or ""))[:120].strip()
            items.append(
                NewsItem(
                    title=title,
                    source=self.name,
                    url=url,
                    published_at=published,
                    raw_content=raw_content,
                    byline=byline,
                )
            )
        return items


def _entry_datetime(entry: Any) -> datetime:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        struct = getattr(entry, attr, None)
        if struct:
            return datetime.fromtimestamp(mktime(struct), tz=timezone.utc)
    return datetime.now(timezone.utc)


def _human(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"
