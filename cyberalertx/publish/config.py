"""Telegram publishing configuration (environment-overridable).

Kept separate from `cyberalertx.config` for the same reason `ai/config.py` is
separate: the feature can be entirely disabled (no token → no publishing),
and its lifecycle (bot tokens, channel ids, signal thresholds) differs from
the feed/ingest settings.

All knobs read from the environment with the `CYBERALERTX_TELEGRAM_` prefix
(matching the project-wide `CYBERALERTX_` convention). Nothing here triggers
network I/O — `build_telegram_settings()` just snapshots env into a frozen
dataclass.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# Severity ordering — mirrors `_LEVEL_WEIGHT` in api/app.py and the frontend's
# LEVEL_WEIGHT so "minimum level" comparisons agree across every layer.
LEVEL_WEIGHT: dict[str, int] = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}

# Source tiers we trust enough to broadcast. `unverified` is excluded by
# default — we don't want an unprofiled blog repost going out to the channel.
_DEFAULT_TIERS = frozenset({"trusted", "verified"})

# Public site base — used to build the "Read more" deep link
# (`{base}/{locale}/threat/{fingerprint}`). Overridable for staging.
_DEFAULT_PUBLIC_BASE = "https://cyberalertx.com"

# Telegram Bot API root. Overridable so tests can point at a local stub.
_DEFAULT_API_BASE = "https://api.telegram.org"


@dataclass(frozen=True)
class TelegramSettings:
    """Snapshot of the publishing configuration.

    `channels` maps a locale (`"en"` / `"ua"`) to a Telegram chat id
    (`@channelusername` or a numeric id). A locale absent from the map is
    skipped entirely — that's how the UA channel stays optional.
    """

    bot_token: str | None = None
    channels: dict[str, str] = field(default_factory=dict)
    # Minimum threat level to publish. An item below this still publishes if
    # its actionability_level is urgent (see `min_level_weight` usage in the
    # selector) — severity OR urgency qualifies.
    min_level: str = "High"
    require_tiers: frozenset[str] = _DEFAULT_TIERS
    # Max messages to send per run (per locale). Caps blast radius on a
    # backfill and stays well under Telegram's ~20 msg/min-per-chat ceiling.
    limit: int = 5
    # Seconds to sleep between sends — gentle pacing for the rate limiter.
    send_delay_seconds: float = 1.0
    public_base_url: str = _DEFAULT_PUBLIC_BASE
    api_base: str = _DEFAULT_API_BASE
    request_timeout_seconds: int = 15

    @property
    def min_level_weight(self) -> int:
        return LEVEL_WEIGHT.get(self.min_level, LEVEL_WEIGHT["High"])

    @property
    def enabled(self) -> bool:
        """True iff we have a token and at least one channel to send to."""
        return bool(self.bot_token) and bool(self.channels)

    def chat_id_for(self, locale: str) -> str | None:
        return self.channels.get(locale)


def build_telegram_settings() -> TelegramSettings:
    """Construct settings from the environment.

    Recognized vars:
      CYBERALERTX_TELEGRAM_BOT_TOKEN     — BotFather token (required to send)
      CYBERALERTX_TELEGRAM_CHANNEL_EN    — chat id for the English channel
      CYBERALERTX_TELEGRAM_CHANNEL_UA    — chat id for the Ukrainian channel (optional)
      CYBERALERTX_TELEGRAM_MIN_LEVEL     — Low|Medium|High|Critical (default High)
      CYBERALERTX_TELEGRAM_LIMIT         — max sends per locale per run (default 5)
      CYBERALERTX_TELEGRAM_SEND_DELAY_S  — pacing between sends (default 1.0)
      CYBERALERTX_PUBLIC_BASE_URL        — site base for deep links (default prod)
      CYBERALERTX_TELEGRAM_API_BASE      — Bot API root (default api.telegram.org)
    """
    channels: dict[str, str] = {}
    for locale, var in (("en", "CYBERALERTX_TELEGRAM_CHANNEL_EN"),
                        ("ua", "CYBERALERTX_TELEGRAM_CHANNEL_UA")):
        value = (os.getenv(var) or "").strip()
        if value:
            channels[locale] = value

    min_level = (os.getenv("CYBERALERTX_TELEGRAM_MIN_LEVEL") or "High").strip().title()
    if min_level not in LEVEL_WEIGHT:
        min_level = "High"

    return TelegramSettings(
        bot_token=(os.getenv("CYBERALERTX_TELEGRAM_BOT_TOKEN") or "").strip() or None,
        channels=channels,
        min_level=min_level,
        limit=int(os.getenv("CYBERALERTX_TELEGRAM_LIMIT", "5")),
        send_delay_seconds=float(os.getenv("CYBERALERTX_TELEGRAM_SEND_DELAY_S", "1.0")),
        public_base_url=(
            os.getenv("CYBERALERTX_PUBLIC_BASE_URL") or _DEFAULT_PUBLIC_BASE
        ).rstrip("/"),
        api_base=(
            os.getenv("CYBERALERTX_TELEGRAM_API_BASE") or _DEFAULT_API_BASE
        ).rstrip("/"),
    )


__all__ = ["TelegramSettings", "build_telegram_settings", "LEVEL_WEIGHT"]
