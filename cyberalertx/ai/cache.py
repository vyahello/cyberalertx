"""File-backed cache of generated ThreatPosts.

Keyed by `(NewsItem.fingerprint, locale)` — the same NewsItem can be rendered
in multiple locales (en, uk) and each render is cached independently.

Why a separate file:
  * The pipeline cycle can rewrite `items.json` (rescoring, dedup); we don't
    want to lose AI outputs to those rewrites.
  * Generated posts can be inspected, hand-edited, or rolled back without
    touching the source-of-truth news store.

Cost-saving role: identical to the data layer's dedup — the LLM is the
expensive call, so we never make it twice for the same (fingerprint, locale).

On-disk shape (intentionally backward-tolerant — see `_load`):

    {
      "posts": {
        "<fingerprint>:<locale>": { <ThreatPost.to_storage_dict()> },
        ...
      }
    }
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable

from .models import ThreatPost

logger = logging.getLogger(__name__)


def _key(fingerprint: str, locale: str) -> str:
    return f"{fingerprint}:{locale}"


class ThreatPostCache:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._store: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            raw = payload.get("posts", {})
            # Legacy entries (pre-locale-aware cache) used bare fingerprints
            # as keys. Promote them to `:en` so old caches don't go cold.
            normalized: dict[str, dict] = {}
            for k, v in raw.items():
                if not isinstance(v, dict):
                    continue
                normalized[k if ":" in k else f"{k}:en"] = v
            self._store = normalized
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Corrupt threat-post cache at %s (%s) — starting empty.", self._path, exc)
            self._store = {}

    def _flush(self) -> None:
        payload = {"posts": self._store}
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".threat-posts-", suffix=".json", dir=str(self._path.parent)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def get(self, fingerprint: str, locale: str = "en") -> ThreatPost | None:
        raw = self._store.get(_key(fingerprint, locale))
        if raw is None:
            return None
        try:
            return ThreatPost.from_dict(raw)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning(
                "Cached post for %s/%s is malformed (%s) — discarding.",
                fingerprint, locale, exc,
            )
            return None

    def set(self, fingerprint: str, locale: str, post: ThreatPost) -> None:
        self._store[_key(fingerprint, locale)] = post.to_dict()
        self._flush()

    def all(self) -> Iterable[ThreatPost]:
        for raw in self._store.values():
            try:
                yield ThreatPost.from_dict(raw)
            except (KeyError, ValueError, TypeError):
                continue

    def __len__(self) -> int:
        return len(self._store)


__all__ = ["ThreatPostCache"]
