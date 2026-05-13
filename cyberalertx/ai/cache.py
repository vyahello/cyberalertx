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
        # `_mtime_seen` enables auto-reload when another process (the CLI
        # `generate` command, an editor, a deploy script) updates the cache
        # file while the API server is running. Without this, the server
        # holds a stale in-memory dict and every request pays the LLM cost
        # again. See `_maybe_reload()`.
        self._mtime_seen: float = 0.0
        self._load()

    def _current_mtime(self) -> float:
        """Return file mtime, or 0.0 if the file is absent / unreadable.
        Stat is cheap (one syscall) and runs once per `get()` — far cheaper
        than the LLM round-trip we'd otherwise pay on a stale cache."""
        try:
            return self._path.stat().st_mtime
        except OSError:
            return 0.0

    def _maybe_reload(self) -> None:
        """Reload the in-memory dict if the on-disk file has been updated
        since the last load. Idempotent — same mtime = no reload."""
        mtime = self._current_mtime()
        if mtime > self._mtime_seen:
            self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._store = {}
            self._mtime_seen = 0.0
            return
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            raw = payload.get("posts", {})
            # Legacy normalization:
            #   * Pre-locale-aware caches used bare fingerprints as keys —
            #     promote them to `:en` so old entries don't go cold.
            #   * Pre-rename caches used the BCP-47 code `:uk` for
            #     Ukrainian. We now use `:ua`. Rewrite the suffix on load
            #     so legacy entries stay live without a re-warm.
            normalized: dict[str, dict] = {}
            for k, v in raw.items():
                if not isinstance(v, dict):
                    continue
                if ":" not in k:
                    key = f"{k}:en"
                elif k.endswith(":uk"):
                    key = f"{k[:-3]}:ua"
                else:
                    key = k
                normalized[key] = v
            self._store = normalized
            self._mtime_seen = self._current_mtime()
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Corrupt threat-post cache at %s (%s) — starting empty.", self._path, exc)
            self._store = {}
            self._mtime_seen = 0.0

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
        # Pick up any out-of-process writes (the CLI `generate` command
        # running in another shell, a sysop hand-editing the file) before
        # serving a result. Without this, a freshly-warmed cache wouldn't
        # be visible to an already-running serve, and every API request
        # would re-trigger an LLM call — exactly the bug this guards.
        self._maybe_reload()
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
        # Reload before merging — picks up entries another process wrote
        # since our last `get()`, so we don't accidentally drop them when
        # we flush our local view.
        self._maybe_reload()
        self._store[_key(fingerprint, locale)] = post.to_dict()
        self._flush()
        self._mtime_seen = self._current_mtime()

    def all(self) -> Iterable[ThreatPost]:
        for raw in self._store.values():
            try:
                yield ThreatPost.from_dict(raw)
            except (KeyError, ValueError, TypeError):
                continue

    def __len__(self) -> int:
        return len(self._store)


__all__ = ["ThreatPostCache"]
