"""Storage interface contracts.

`NewsRepository` is the duck-typed Protocol every storage backend must
satisfy. The JSON store has been the only implementation; this module
formalizes the contract so the Postgres backend and the dual-write
wrapper can swap in without touching callers.

Reads in this PR still come from JSON. Postgres is shadow-write only.
"""
from __future__ import annotations

from typing import Iterable, List, Protocol

from ..models import NewsItem


class NewsRepository(Protocol):
    """Minimum surface area every storage backend must expose.

    Identical to the Protocol historically declared in `json_store.py` —
    re-homed here so backends in `storage/pg/` can import without
    cycling through the JSON implementation.
    """

    def upsert_many(self, items: Iterable[NewsItem]) -> List[NewsItem]: ...
    def all(self) -> List[NewsItem]: ...
    def known_fingerprints(self) -> set[str]: ...


__all__ = ["NewsRepository"]
