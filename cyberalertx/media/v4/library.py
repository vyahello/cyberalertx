"""Tier A: a small library of verified real-world photographs.

A photograph is used for a story only when the story names its subject (the
entry's `match` patterns) AND the entry passes `validate`: an allowed licence,
commercial use, modification and redistribution explicitly permitted, an
attribution recorded, and a file whose SHA-256 matches the manifest. Anything
short of that is not used — the story falls back to an original illustration.

Files live in the repository next to this module (never hotlinked) and are
embedded in the rendered SVG as data URIs, so the published image does not
depend on any external host.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

LIB_DIR = Path(__file__).with_name("library")

#: Licences a photograph may carry: public-domain dedications only, for now.
#: The same image is attached to Telegram and Threads posts, which carry no
#: credit line yet, so attribution licences (CC BY) would not be honoured
#: there. Share-alike licences stay excluded: our composites (photo +
#: annotation) would have to be released under them.
ALLOWED_LICENSES = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "PDM-1.0": "https://creativecommons.org/publicdomain/mark/1.0/",
}
_REQUIRED = ("id", "file", "sha256", "width", "height", "subject", "subject_ua", "match", "source_url", "author",
             "license", "license_url", "attribution_required", "commercial_use", "modification_allowed",
             "redistribution_allowed", "credit", "credit_ua", "retrieved", "processing", "focus")


@dataclass(frozen=True)
class LibraryAsset:
    id: str
    file: str
    sha256: str
    subject: str
    subject_ua: str
    match: tuple[str, ...]
    source_url: str
    author: str
    license: str
    license_url: str
    attribution_required: bool
    credit: str
    credit_ua: str
    focus: tuple[float, float]
    width: int
    height: int
    #: Box (x0, y0, x1, y1) on the plate around the subject, for annotation.
    marker: tuple[float, float, float, float] = (0, 0, 0, 0)

    @property
    def path(self) -> Path:
        return LIB_DIR / self.file

    def data_uri(self) -> str:
        mime = "image/jpeg" if self.file.endswith((".jpg", ".jpeg")) else "image/webp" \
            if self.file.endswith(".webp") else "image/png"
        return f"data:{mime};base64," + base64.b64encode(self.path.read_bytes()).decode("ascii")

    def provenance(self) -> dict[str, str]:
        return {"library_id": self.id, "source_url": self.source_url, "author": self.author,
                "license": self.license, "license_url": self.license_url, "credit": self.credit}


def validate(entry: dict[str, Any], *, check_file: bool = True) -> list[str]:
    """Problems that disqualify an entry (empty list = usable)."""
    problems = [f"missing {k}" for k in _REQUIRED if k not in entry or entry[k] in ("", None)]
    if problems:
        return problems
    lic = entry["license"]
    if lic not in ALLOWED_LICENSES:
        problems.append(f"licence {lic} not allowed")
    elif entry["license_url"].rstrip("/") != ALLOWED_LICENSES[lic].rstrip("/"):
        problems.append("licence URL does not match the licence")
    for flag in ("commercial_use", "modification_allowed", "redistribution_allowed"):
        if entry.get(flag) is not True:
            problems.append(f"{flag} not established")
    if not str(entry["source_url"]).startswith("https://"):
        problems.append("source URL must be https")
    for pat in entry["match"]:
        try:
            re.compile(pat)
        except re.error:
            problems.append(f"bad match pattern {pat!r}")
    if check_file:
        p = LIB_DIR / entry["file"]
        if not p.is_file():
            problems.append("file missing")
        elif hashlib.sha256(p.read_bytes()).hexdigest() != entry["sha256"]:
            problems.append("file hash does not match the manifest")
    if (entry["width"], entry["height"]) != (1600, 900):
        problems.append("plate must be 1600x900")
    return problems


@lru_cache(maxsize=1)
def load() -> tuple[LibraryAsset, ...]:
    raw = json.loads((LIB_DIR / "library.json").read_text(encoding="utf-8"))
    out = []
    for e in raw["assets"]:
        if validate(e):
            continue                     # never used; tests report it
        out.append(LibraryAsset(
            id=e["id"], file=e["file"], sha256=e["sha256"], subject=e["subject"], subject_ua=e["subject_ua"],
            match=tuple(e["match"]), source_url=e["source_url"], author=e["author"], license=e["license"],
            license_url=e["license_url"], attribution_required=bool(e["attribution_required"]),
            credit=e["credit"], credit_ua=e["credit_ua"], focus=(float(e["focus"][0]), float(e["focus"][1])),
            width=int(e["width"]), height=int(e["height"]),
            marker=tuple(float(v) for v in e.get("marker", (0, 0, 0, 0)))))  # type: ignore[arg-type]
    return tuple(out)


def find(text: str) -> LibraryAsset | None:
    """The library photograph whose subject the text names, if any."""
    for a in load():
        if any(re.search(p, text) for p in a.match):
            return a
    return None


def get(asset_id: str) -> LibraryAsset | None:
    return next((a for a in load() if a.id == asset_id), None)
