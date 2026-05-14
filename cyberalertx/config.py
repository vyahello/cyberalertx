"""Central configuration for CyberAlertX data layer."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from urllib.parse import quote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class SourceConfig:
    name: str
    url: str
    kind: str = "rss"


# Optional Cloudflare Worker that fronts RSS feeds whose origins reject
# direct fetches from cloud IPs (Cloudflare WAF / bot gates). Set to the
# worker URL with the target-URL query param appended, e.g.
#   CYBERALERTX_RSS_PROXY_URL=https://my-worker.workers.dev/?u=
# The full target URL is appended (URL-encoded) after this prefix. When
# set, the hosts in _PROXIED_HOSTS get wrapped automatically. Empty
# (default) = direct fetches everywhere.
_RSS_PROXY_URL: str = os.getenv("CYBERALERTX_RSS_PROXY_URL", "").strip()

# Hosts that historically return 403 to direct fetches. Routed through the
# proxy when one is configured; otherwise fetched directly (browser UA in
# Settings.user_agent still helps in most cases).
_PROXIED_HOSTS = frozenset({
    "www.cisa.gov",
    "ain.ua",
    "dev.ua",
})


def _maybe_proxy(url: str) -> str:
    """Wrap `url` through the configured RSS proxy iff its host is in
    `_PROXIED_HOSTS` and a proxy URL is configured. Pass-through otherwise."""
    if not _RSS_PROXY_URL:
        return url
    host = (urlparse(url).hostname or "").lower()
    if host not in _PROXIED_HOSTS:
        return url
    return _RSS_PROXY_URL + quote(url, safe="")


@dataclass(frozen=True)
class Settings:
    fetch_interval_minutes: int = int(os.getenv("CYBERALERTX_INTERVAL_MIN", "15"))
    request_timeout_seconds: int = int(os.getenv("CYBERALERTX_TIMEOUT", "15"))
    # Realistic browser UA. Cloudflare-fronted sources (ain.ua, dev.ua) and
    # CISA reject bot-shaped UAs with 403. A vanilla Firefox ESR string
    # sails through. Override via CYBERALERTX_UA if your feeds rotate
    # against this signature.
    user_agent: str = os.getenv(
        "CYBERALERTX_UA",
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    )
    storage_path: Path = DATA_DIR / "items.json"
    # Storage cap. Auto-prunes oldest items beyond this count on each ingest.
    # 20 is the current product cap: feed shows 15 newest, trending highlights
    # 5 by danger from the same pool. Bump via CYBERALERTX_MAX_ITEMS if you
    # need a larger archive.
    max_items_retained: int = int(os.getenv("CYBERALERTX_MAX_ITEMS", "20"))
    recency_half_life_hours: float = float(os.getenv("CYBERALERTX_HALF_LIFE_H", "12"))
    sources: List[SourceConfig] = field(default_factory=lambda: [
        # --- English (primary intelligence) ---
        SourceConfig("The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
        SourceConfig("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
        SourceConfig("Krebs on Security", "https://krebsonsecurity.com/feed/"),
        SourceConfig("Securelist (Kaspersky)", "https://securelist.com/feed/"),
        SourceConfig(
            "CISA Alerts",
            _maybe_proxy("https://www.cisa.gov/cybersecurity-advisories/all.xml"),
        ),
        # --- Ukrainian (secondary, for the UK locale) ---
        SourceConfig("itc.ua", "https://itc.ua/ua/feed/"),
        SourceConfig("ain.ua", _maybe_proxy("https://ain.ua/feed/")),
        SourceConfig("dev.ua", _maybe_proxy("https://dev.ua/rss")),
        SourceConfig("dou.ua", "https://dou.ua/feed/"),
    ])


SETTINGS = Settings()
