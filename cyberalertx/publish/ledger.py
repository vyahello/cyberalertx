"""Append-only ledger of what has been published, keyed by (fingerprint, locale).

Follows the `feedback.jsonl` pattern in api/app.py: one JSON object per line,
no schema migration, no admin UI. JSON-first so it works under the default
storage backend; nothing here touches Postgres.

A line is written ONLY after Telegram confirms the send (we store the returned
`message_id`). That ordering is what makes re-runs idempotent: on the next
fire we load every recorded (fingerprint, locale) into a set and skip them.

Worst case — a send succeeds but the append fails (disk full mid-write) — the
post is sent again on the next run. A rare single duplicate is an acceptable
trade for never silently dropping a post.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _key(fingerprint: str, locale: str) -> str:
    return f"{fingerprint}:{locale}"


class PublishLedger:
    """File-backed record of successful publishes.

    Thread-safe appends (a single lock), tolerant reads (a corrupt line is
    skipped, not fatal). Construct once per run.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._published: set[str] = self._load()

    def _load(self) -> set[str]:
        if not self._path.exists():
            return set()
        seen: set[str] = set()
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        # One bad line must not blind us to the rest of the
                        # ledger — skip it and keep reading.
                        continue
                    fp = rec.get("fingerprint")
                    loc = rec.get("locale")
                    if fp and loc:
                        seen.add(_key(fp, loc))
        except OSError as exc:
            logger.warning("could not read publish ledger %s (%s)", self._path, exc)
        return seen

    def is_published(self, fingerprint: str, locale: str) -> bool:
        return _key(fingerprint, locale) in self._published

    def published_keys(self) -> set[str]:
        return set(self._published)

    def record(
        self, *, fingerprint: str, locale: str, channel: str, message_id: int,
    ) -> None:
        """Append one success record and mark it in the in-memory set.

        Called only after a confirmed send. Best-effort on disk: a failed
        append is logged (the in-memory set is still updated so we don't
        double-send within the same run)."""
        record = {
            "fingerprint": fingerprint,
            "locale": locale,
            "channel": channel,
            "message_id": message_id,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            self._published.add(_key(fingerprint, locale))
            try:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                logger.warning(
                    "publish ledger append failed for %s/%s (%s)",
                    fingerprint, locale, exc,
                )

    def __len__(self) -> int:
        return len(self._published)


__all__ = ["PublishLedger"]
