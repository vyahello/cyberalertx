"""Central configuration for CyberAlertX data layer."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class SourceConfig:
    name: str
    url: str
    kind: str = "rss"


@dataclass(frozen=True)
class Settings:
    fetch_interval_minutes: int = int(os.getenv("CYBERALERTX_INTERVAL_MIN", "15"))
    request_timeout_seconds: int = int(os.getenv("CYBERALERTX_TIMEOUT", "15"))
    user_agent: str = os.getenv(
        "CYBERALERTX_UA",
        "CyberAlertX/0.1 (+https://example.invalid/cyberalertx)",
    )
    storage_path: Path = DATA_DIR / "items.json"
    max_items_retained: int = int(os.getenv("CYBERALERTX_MAX_ITEMS", "5000"))
    recency_half_life_hours: float = float(os.getenv("CYBERALERTX_HALF_LIFE_H", "12"))
    sources: List[SourceConfig] = field(default_factory=lambda: [
        # --- English (primary intelligence) ---
        SourceConfig("The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
        SourceConfig("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
        SourceConfig("Krebs on Security", "https://krebsonsecurity.com/feed/"),
        SourceConfig("Securelist (Kaspersky)", "https://securelist.com/feed/"),
        SourceConfig("CISA Alerts", "https://www.cisa.gov/cybersecurity-advisories/all.xml"),
        # --- Ukrainian (secondary, for the UK locale) ---
        SourceConfig("itc.ua", "https://itc.ua/ua/feed/"),
        SourceConfig("ain.ua", "https://ain.ua/feed/"),
        SourceConfig("dev.ua", "https://dev.ua/rss"),
        SourceConfig("dou.ua", "https://dou.ua/feed/"),
    ])


SETTINGS = Settings()
