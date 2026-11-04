"""MediaAsset records and the file store for generated media.

Storage follows the project's existing convention — JSON for metadata
(`data/media/assets.json`, atomic writes, a cross-process file lock like the
threat-post cache) and plain files for bytes (`data/media/files/`). There is no
object store or CDN client in this project: public URLs are served by the
website (Next.js, behind Cloudflare), which reads validated files from the API's
internal `/media/{asset_id}` endpoint.

Two kinds of asset exist:

  branded_card            deterministic, rendered on request by the website
                          (`/{locale}/threat/{id}/card/{variant}.{fmt}`); the
                          record holds its URLs, content hash and alt text —
                          no bytes are stored, so nothing can go stale.
  editorial_illustration  bytes from an image provider, validated and stored
                          once per story under their SHA-256; platform variants
                          are cut from that one source by the website
                          (`/media/{asset_id}/{variant}.{fmt}`).

Asset ids are content-derived (no user input reaches a path), so filenames are
always `[0-9a-f]{64}.{png|jpg|webp}` — no traversal is possible.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import struct
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..config import DATA_DIR

MEDIA_DIR = DATA_DIR / "media"

ASSET_TYPES = ("branded_card", "editorial_illustration")
STATUSES = ("pending", "generating", "generated", "validated", "published", "failed", "skipped")

#: Accepted source formats for illustrations, by magic bytes.
ALLOWED_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
MAX_BYTES = 8 * 1024 * 1024
MIN_SIDE = 768
MAX_SIDE = 4096

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class MediaValidationError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class MediaAsset:
    asset_id: str
    story_key: str
    asset_type: str
    locale: str = ""                    # "" = shared across editions
    storage_key: str = ""               # file name under files/ (illustrations)
    public_url: str = ""                # primary public URL (og variant)
    variants: dict[str, str] = field(default_factory=dict)   # variant -> public URL
    mime_type: str = ""
    width: int = 0
    height: int = 0
    file_size: int = 0
    alt_text: dict[str, str] = field(default_factory=dict)   # locale -> alt
    source: str = "cyberalertx"
    license: str = "CyberAlertX original"
    generation_method: str = ""         # deterministic-svg | ai-image
    generation_model: str = ""
    prompt_version: str = ""
    prompt: str = ""
    content_hash: str = ""              # hash of the INPUTS that define the asset
    members: list[str] = field(default_factory=list)          # article fingerprints
    status: str = "pending"
    attempts: int = 0
    last_error: str = ""
    cost_usd: float = 0.0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @property
    def aspect_ratio(self) -> str:
        if not self.width or not self.height:
            return ""
        from math import gcd
        g = gcd(self.width, self.height)
        return f"{self.width // g}:{self.height // g}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["aspect_ratio"] = self.aspect_ratio
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MediaAsset":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------- validation

def sniff(data: bytes) -> tuple[str, int, int]:
    """(mime, width, height) from the file's own bytes. Raises on anything else."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return "image/png", w, h
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "image/jpeg", w, h
            seg = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + seg
        raise MediaValidationError("JPEG without a frame header")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X":
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return "image/webp", w, h
        if chunk == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return "image/webp", w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L":
            b = data[21:25]
            w = 1 + (((b[1] & 0x3F) << 8) | b[0])
            h = 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
            return "image/webp", w, h
    raise MediaValidationError("not a PNG, JPEG or WebP file")


def validate_image(data: bytes, *, declared_mime: str = "") -> tuple[str, int, int]:
    if not data:
        raise MediaValidationError("empty file")
    if len(data) > MAX_BYTES:
        raise MediaValidationError(f"file too large ({len(data)} bytes > {MAX_BYTES})")
    mime, w, h = sniff(data)
    if declared_mime and declared_mime.split(";")[0].strip() != mime:
        raise MediaValidationError(f"declared {declared_mime!r} but the bytes are {mime}")
    if mime not in ALLOWED_MIME:
        raise MediaValidationError(f"type {mime} not allowed")
    if min(w, h) < MIN_SIDE or max(w, h) > MAX_SIDE:
        raise MediaValidationError(f"dimensions {w}x{h} outside {MIN_SIDE}..{MAX_SIDE}")
    return mime, w, h


# ---------------------------------------------------------------- store

class MediaStore:
    def __init__(self, root: Path = MEDIA_DIR) -> None:
        self.root = Path(root)
        self.files = self.root / "files"
        self.index = self.root / "assets.json"
        self.files.mkdir(parents=True, exist_ok=True)
        self._cache: tuple[tuple[int, int, int], dict[str, dict[str, Any]]] = ((0, 0, -1), {})

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        with open(self.root / "assets.json.lock", "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _read(self) -> dict[str, dict[str, Any]]:
        # Re-parsed only when the file changes: the API consults the store once
        # per rendered post. mtime alone is not enough (two writes inside one
        # kernel tick share it); every write is a rename, so the inode changes.
        try:
            st = self.index.stat()
        except OSError:
            return {}
        key = (st.st_ino, st.st_mtime_ns, st.st_size)
        if key == self._cache[0]:
            return self._cache[1]
        try:
            data = json.loads(self.index.read_text(encoding="utf-8"))
            data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}
        self._cache = (key, data)
        return data

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self.root), prefix=".assets.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.index)
            st = self.index.stat()
            self._cache = ((st.st_ino, st.st_mtime_ns, st.st_size), data)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def all(self) -> list[MediaAsset]:
        return [MediaAsset.from_dict(v) for v in self._read().values()]

    def get(self, asset_id: str) -> MediaAsset | None:
        raw = self._read().get(asset_id)
        return MediaAsset.from_dict(raw) if raw else None

    def put(self, asset: MediaAsset) -> None:
        with self._locked():
            data = dict(self._read())
            asset.updated_at = _now()
            data[asset.asset_id] = asset.to_dict()
            self._write(data)

    def put_many(self, assets: Iterable[MediaAsset]) -> None:
        with self._locked():
            data = dict(self._read())
            for a in assets:
                a.updated_at = _now()
                data[a.asset_id] = a.to_dict()
            self._write(data)

    def for_story(self, story_key: str) -> list[MediaAsset]:
        return [a for a in self.all() if a.story_key == story_key]

    def illustration_for_member(self, fingerprint: str) -> MediaAsset | None:
        """The validated illustration of the story this article belongs to."""
        found = [a for a in self.all() if a.asset_type == "editorial_illustration"
                 and a.status in ("validated", "published") and fingerprint in a.members]
        return max(found, key=lambda a: a.updated_at) if found else None

    # -- bytes ---------------------------------------------------------------

    def save_bytes(self, data: bytes, *, declared_mime: str = "") -> tuple[str, str, int, int]:
        """Validate and store. Returns (sha256, mime, width, height). Idempotent."""
        mime, w, h = validate_image(data, declared_mime=declared_mime)
        digest = hashlib.sha256(data).hexdigest()
        path = self.files / f"{digest}.{ALLOWED_MIME[mime]}"
        if not path.exists():
            fd, tmp = tempfile.mkstemp(dir=str(self.files), prefix=".img.")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        return digest, mime, w, h

    def open_file(self, asset_id: str) -> tuple[bytes, str] | None:
        """Bytes + MIME of a validated illustration, or None. `asset_id` is the
        first 16+ hex chars of the stored SHA-256 (as used in public URLs)."""
        if not re.fullmatch(r"[0-9a-f]{16,64}", asset_id or ""):
            return None
        asset = next((a for a in self.all() if a.asset_type == "editorial_illustration"
                      and a.storage_key.startswith(asset_id)
                      and a.status in ("validated", "published")), None)
        if asset is None or not _HEX64.match(asset.storage_key.split(".")[0]):
            return None
        path = (self.files / asset.storage_key).resolve()
        if path.parent != self.files.resolve() or not path.is_file():
            return None
        data = path.read_bytes()
        mime, _, _ = sniff(data)
        return data, mime


__all__ = ["ALLOWED_MIME", "ASSET_TYPES", "MAX_BYTES", "MEDIA_DIR", "MIN_SIDE", "MediaAsset",
           "MediaStore", "MediaValidationError", "STATUSES", "sniff", "validate_image"]
