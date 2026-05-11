"""Source plugin contract.

A `Source` is anything that can produce a list of `NewsItem`s when asked.
RSS feeds, JSON APIs, scraped HTML — all conform to the same interface.

Adding a new source is a matter of subclassing `Source` and registering it
in `cyberalertx.config.SETTINGS.sources` (or pushing one in code).
"""
from __future__ import annotations

import abc
from typing import List

from ..models import NewsItem


class Source(abc.ABC):
    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    @abc.abstractmethod
    def fetch(self) -> List[NewsItem]:
        """Return zero or more items. Must NOT raise on transient network errors."""
