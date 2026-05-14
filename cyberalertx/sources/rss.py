"""Generic RSS / Atom source.

Uses `feedparser` because it handles every flavor of RSS, Atom, RDF, and
malformed-but-real-world feeds you'll encounter (Krebs, BleepingComputer,
CISA all serve slightly different shapes).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from time import mktime
from typing import List, Optional

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


class RssSource(Source):
    """Pull items from a single RSS / Atom feed URL."""

    def __init__(
        self,
        name: str,
        url: str,
        timeout: int = 15,
        user_agent: str = "CyberAlertX/0.1",
    ) -> None:
        super().__init__(name)
        self._url = url
        self._timeout = timeout
        self._user_agent = user_agent

    def fetch(self) -> List[NewsItem]:
        raw = self._download()
        if raw is None:
            return []
        return self._parse(raw)

    def _download(self) -> Optional[bytes]:
        """We download bytes ourselves (instead of letting feedparser do it)
        so we control timeout, retry, and request headers. Network errors
        are swallowed and logged — one bad source must not break the
        pipeline.

        Header set mimics a real browser/RSS-reader: Cloudflare-fronted
        feeds (ain.ua, dev.ua) and CISA reject minimal/bot-shaped requests
        with 403. Sending UA + Accept + Accept-Language gets us through.
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
            with httpx.Client(
                timeout=self._timeout,
                headers=headers,
                follow_redirects=True,
            ) as client:
                resp = client.get(self._url)
                resp.raise_for_status()
                return resp.content
        except httpx.HTTPError as exc:
            logger.warning("Source %s download failed: %s", self.name, exc)
            return None

    def _parse(self, payload: bytes) -> List[NewsItem]:
        parsed = feedparser.parse(payload)
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
            items.append(
                NewsItem(
                    title=title,
                    source=self.name,
                    url=url,
                    published_at=published,
                    raw_content=raw_content,
                )
            )
        return items


def _entry_datetime(entry) -> datetime:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        struct = getattr(entry, attr, None)
        if struct:
            return datetime.fromtimestamp(mktime(struct), tz=timezone.utc)
    return datetime.now(timezone.utc)
