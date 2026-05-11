"""Factory that turns `SourceConfig` entries into live `Source` objects.

Centralizing this here means the orchestrator never imports concrete source
classes — it only knows the abstract `Source` interface.
"""
from __future__ import annotations

from typing import Iterable, List

from ..config import SETTINGS, SourceConfig
from .base import Source
from .rss import RssSource


def build_sources(configs: Iterable[SourceConfig] | None = None) -> List[Source]:
    configs = list(configs) if configs is not None else SETTINGS.sources
    sources: List[Source] = []
    for cfg in configs:
        if cfg.kind == "rss":
            sources.append(
                RssSource(
                    name=cfg.name,
                    url=cfg.url,
                    timeout=SETTINGS.request_timeout_seconds,
                    user_agent=SETTINGS.user_agent,
                )
            )
        else:
            raise ValueError(f"Unknown source kind: {cfg.kind!r}")
    return sources
