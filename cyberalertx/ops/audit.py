"""Append-only audit log of administrative actions.

There was no audit log before Phase 6 — review decisions were only stamped
on the post (`reviewed_by`/`reviewed_at`) and written to the process log.
This file is the one place every state-changing admin action is recorded:

    {"at", "actor", "address", "action", "target", "result", "meta"}

`actor` is the Basic-auth username the admin typed (any name is accepted by
the gate; there is one shared secret), `address` the client address nginx
reports. `meta` is filtered: keys that look like credentials are dropped and
every string passes through the same redaction as the HTTP logs, so a token,
secret, code or password can never be written here.

JSON Lines under `data/`, appended under an `fcntl` lock with `fsync`, never
rewritten. Reading is bounded to the tail of the file.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..config import DATA_DIR
from ..logsafe import redact

AUDIT_PATH = DATA_DIR / "admin_audit.jsonl"
_SECRET_KEY = re.compile(
    r"^(?:.*_)?(?:token|secret|password|passwd|authorization|cookie|code|csrf|api_?key|access_token)$", re.I)
_MAX_TAIL_BYTES = 2 * 1024 * 1024


def _clean(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "…"
    if isinstance(value, str):
        return redact(value)[:300]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(k)[:40]: _clean(v, depth + 1) for k, v in list(value.items())[:20]
                if not _SECRET_KEY.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [_clean(v, depth + 1) for v in list(value)[:20]]
    return redact(str(value))[:300]


class AuditLog:
    def __init__(self, path: Path = AUDIT_PATH) -> None:
        self.path = Path(path)

    def record(self, *, actor: str, action: str, target: str, result: str, address: str = "",
               now: datetime | None = None, **meta: Any) -> dict[str, Any]:
        entry = {
            "at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0).isoformat(),
            "actor": redact(actor or "admin")[:60], "address": (address or "")[:64],
            "action": action[:60], "target": redact(target)[:200], "result": result[:40],
            "meta": _clean(meta),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        return entry

    def recent(self, limit: int = 100, *, action_prefix: str = "") -> list[dict[str, Any]]:
        """Newest first, from the tail of the file only."""
        try:
            size = self.path.stat().st_size
            with open(self.path, "rb") as fh:
                fh.seek(max(0, size - _MAX_TAIL_BYTES))
                lines = fh.read().decode("utf-8", "replace").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and str(rec.get("action", "")).startswith(action_prefix):
                out.append(rec)
                if len(out) >= limit:
                    break
        return out


__all__ = ["AUDIT_PATH", "AuditLog"]
