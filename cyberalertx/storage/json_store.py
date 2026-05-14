"""File-backed JSON store with fingerprint dedup.

Why JSON: the spec asks for "simple storage (JSON or DB-ready structure)".
The repository pattern (`NewsRepository`) is the abstraction the rest of the
codebase depends on, so swapping for SQLite / Postgres later is a one-file
change — no caller needs to be touched.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Protocol

from ..models import NewsItem

logger = logging.getLogger(__name__)


class NewsRepository(Protocol):
    def upsert_many(self, items: Iterable[NewsItem]) -> List[NewsItem]: ...
    def all(self) -> List[NewsItem]: ...
    def known_fingerprints(self) -> set[str]: ...


class JsonNewsStore:
    """Atomic, dedup-aware JSON store.

    Atomic = write to a temp file in the same directory, then `os.replace`.
    That guarantees readers never see a half-written file even if the
    process is killed mid-write.
    """

    def __init__(self, path: Path, max_items: int = 5000) -> None:
        self._path = Path(path)
        self._max_items = max_items
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, NewsItem] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._cache = {}
            return
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            self._cache = {
                item["fingerprint"]: NewsItem.from_storage_dict(item)
                for item in payload.get("items", [])
                if "fingerprint" in item
            }
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Corrupt store at %s (%s) — starting empty.", self._path, exc)
            self._cache = {}

    def _flush(self) -> None:
        # Reverse-chronological prune — keep the newest `max_items`. This
        # matches the product cap ("show the latest 15-20 stories"); the
        # feed and trending layers both work from this same recent pool.
        # (The earlier sort key — (threat_score, published_at) DESC — was
        # stickier for old criticals, which at max_items=5000 was fine but
        # at max_items=20 surfaces 2-month-old advisories above today's
        # news. With a small cap, "newest wins" is the right product.)
        items_sorted = sorted(
            self._cache.values(),
            key=lambda i: i.published_at,
            reverse=True,
        )[: self._max_items]
        self._cache = {i.fingerprint: i for i in items_sorted}

        serialized = {
            "items": [
                {"fingerprint": i.fingerprint, **i.to_storage_dict()}
                for i in items_sorted
            ]
        }
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".items-", suffix=".json", dir=str(self._path.parent)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(serialized, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def known_fingerprints(self) -> set[str]:
        return set(self._cache.keys())

    def upsert_many(self, items: Iterable[NewsItem]) -> List[NewsItem]:
        """Insert new items, refresh scores for existing ones.

        Returns the subset that was actually new (useful for notifications).
        """
        new_items: List[NewsItem] = []
        for item in items:
            fp = item.fingerprint
            if fp in self._cache:
                existing = self._cache[fp]
                # Re-score in case ranker has new signals (e.g. cross-source bump).
                existing.threat_score = max(existing.threat_score, item.threat_score)
                existing.tags = sorted(set(existing.tags) | set(item.tags))
            else:
                self._cache[fp] = item
                new_items.append(item)
        self._flush()
        return new_items

    def all(self) -> List[NewsItem]:
        return list(self._cache.values())
