"""Safe reads and atomic updates of the server's .env (never `source`d).

Values are written unquoted, so both readers of the file agree on them: the
project loader (ops/release/loadenv.sh) and systemd's EnvironmentFile. Only
values without whitespace, quotes, `$`, backslashes or `#` are accepted —
Threads tokens and ids are plain alphanumeric strings.

An update:
  1. copies the current file to a protected backup (directory 0700, file 0600);
  2. rewrites only the given keys, keeping every other line, comment and order;
  3. writes a temporary file in the same directory (0600, same owner), fsyncs,
     and renames it over the original — readers never see a half-written file.
No value is ever printed or logged.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9._:/|@+=,-]*$")


class EnvFileError(ValueError):
    """Never contains a value."""


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE pairs exactly as ops/release/loadenv.sh reads them."""
    out: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def backup_env(path: Path, backup_dir: Path, *, label: str = "env") -> Path:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    dest = backup_dir / f"{label}-{stamp}"
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out, open(path, "rb") as src:
        shutil.copyfileobj(src, out)
        out.flush()
        os.fsync(out.fileno())
    return dest


def update_env(path: Path, updates: dict[str, str], *, backup_dir: Path, label: str = "env") -> Path:
    """Set `updates` in the file atomically; returns the backup path."""
    path = Path(path)
    for k, v in updates.items():
        if not _KEY.match(k):
            raise EnvFileError(f"invalid variable name {k!r}")
        if not _SAFE_VALUE.match(v):
            raise EnvFileError(f"value for {k} contains characters that are not safe unquoted")
    st = path.stat()
    backup = backup_env(path, backup_dir, label=label)
    lines = path.read_text(encoding="utf-8").splitlines()
    out, seen = [], set()
    for line in lines:
        s = line.strip()
        key = s.split("=", 1)[0].strip() if "=" in s and not s.startswith("#") else ""
        if key in updates:
            if key in seen:
                continue                       # drop later duplicates of a key we set
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        if hasattr(os, "fchown") and os.geteuid() == 0:
            os.fchown(fd, st.st_uid, st.st_gid)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    got = read_env(path)
    if any(got.get(k) != v for k, v in updates.items()):          # pragma: no cover - paranoia
        raise EnvFileError("update did not land; restore from the backup")
    return backup


__all__ = ["EnvFileError", "backup_env", "read_env", "update_env"]
