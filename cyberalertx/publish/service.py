"""Publish orchestration — selects qualifying posts and pushes the new ones.

Flow (per configured locale channel, newest-first):

    list NewsItems  →  tier filter  →  language gate  →  render_if_cached
        →  severity/urgency bar  →  ledger dedup  →  format  →  send  →  record

Cost-safety: we reuse the API's `_PostService`, whose generator has its
provider force-nulled, so an un-rendered item yields `None` from
`render_if_cached` and is skipped — we never trigger an LLM call from here.
Only posts already rendered by `generate --use-llm` are eligible.

`--dry-run` runs the entire selection + formatting path and prints what would
be sent, without constructing a publisher or touching the network.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import DATA_DIR
from .config import LEVEL_WEIGHT, TelegramSettings, build_telegram_settings
from .format import quality_problem, render_message
from .ledger import PublishLedger
from .telegram import TelegramError, TelegramPublisher

logger = logging.getLogger(__name__)

# Default ledger location — alongside the other JSONL runtime state.
DEFAULT_LEDGER_PATH = DATA_DIR / "telegram_published.jsonl"

# Locales eligible to appear on each channel. The EN channel is strict
# (English-source only); the UA channel is inclusive (EN-source items render
# in UA too) — identical to the homepage feed gate in api/app.py:list_posts.
_LOCALE_LANGUAGE_GATE: dict[str, frozenset[str]] = {
    "en": frozenset({"en"}),
    "ua": frozenset({"en", "ua"}),
}


@dataclass
class PublishResult:
    sent: int = 0
    skipped_already: int = 0
    skipped_filtered: int = 0
    skipped_uncached: int = 0
    skipped_invalid: int = 0
    errors: int = 0
    dry_run: bool = False
    by_channel: dict[str, int] = field(default_factory=dict)

    def __str__(self) -> str:
        mode = "DRY-RUN " if self.dry_run else ""
        per = ", ".join(f"{k}={v}" for k, v in sorted(self.by_channel.items()))
        return (
            f"{mode}sent={self.sent} ({per}) "
            f"already={self.skipped_already} filtered={self.skipped_filtered} "
            f"uncached={self.skipped_uncached} invalid={self.skipped_invalid} "
            f"errors={self.errors}"
        )


def qualifies(payload: dict[str, Any], settings: TelegramSettings) -> bool:
    """Severity OR urgency bar. Tier is filtered earlier on the NewsItem.

    A post passes if its AI-assigned threat_level meets the configured
    minimum, OR its actionability is `urgent_action` regardless of level
    (an actively-exploited Medium still deserves the channel).
    """
    level_ok = (
        LEVEL_WEIGHT.get(payload.get("threat_level", "Low"), 0)
        >= settings.min_level_weight
    )
    urgent = payload.get("actionability_level") == "urgent_action"
    return level_ok or urgent


def publish_once(
    *,
    settings: TelegramSettings | None = None,
    service: Any | None = None,
    ledger: PublishLedger | None = None,
    publisher: TelegramPublisher | None = None,
    limit: int | None = None,
    language: str | None = None,
    dry_run: bool = False,
) -> PublishResult:
    """Run one publish pass.

    All collaborators are injectable for tests. In production the CLI passes
    nothing and we build the defaults: env-derived settings, a cost-safe
    `_PostService`, the on-disk ledger, and a real Telegram client.

    `language` restricts the run to a single channel locale (e.g. "en");
    `limit` overrides the per-channel cap from settings.
    """
    settings = settings or build_telegram_settings()
    result = PublishResult(dry_run=dry_run)

    # Resolve channel set — all configured, or just the requested locale.
    channels = dict(settings.channels)
    if language:
        chat = settings.channels.get(language)
        channels = {language: chat} if chat else {}

    if not channels:
        logger.warning(
            "telegram publish: no channels configured%s — nothing to do.",
            f" for locale {language!r}" if language else "",
        )
        return result

    # Live (non-dry-run) needs a token + publisher.
    if not dry_run and not settings.bot_token and publisher is None:
        logger.warning("telegram publish: no bot token set — nothing to do.")
        return result

    # Lazy-build collaborators only when needed.
    if service is None:
        from ..api.app import _PostService  # local import: avoids FastAPI on dry import
        service = _PostService()
    if ledger is None:
        ledger = PublishLedger(DEFAULT_LEDGER_PATH)

    owns_publisher = False
    if publisher is None and not dry_run:
        publisher = TelegramPublisher(
            settings.bot_token or "",
            api_base=settings.api_base,
            timeout_seconds=settings.request_timeout_seconds,
        )
        owns_publisher = True

    per_channel_limit = limit if limit is not None else settings.limit

    try:
        items = service.list_items()
        # Tier filter once (shared across channels).
        items = [
            i for i in items
            if (getattr(i, "source_tier", "unverified") in settings.require_tiers)
        ]
        # Newest first — channels should lead with the freshest threat.
        items.sort(key=lambda i: i.published_at, reverse=True)

        for locale, chat_id in channels.items():
            gate = _LOCALE_LANGUAGE_GATE.get(locale, frozenset({locale}))
            sent_here = 0
            for item in items:
                if sent_here >= per_channel_limit:
                    break
                if (getattr(item, "language", "en") or "en") not in gate:
                    continue
                if ledger.is_published(item.fingerprint, locale):
                    result.skipped_already += 1
                    continue
                try:
                    payload = service.render_if_cached(item, required_locale=locale)
                except Exception as exc:
                    logger.warning(
                        "render_if_cached failed for %s/%s: %s",
                        item.fingerprint, locale, exc,
                    )
                    result.errors += 1
                    continue
                if payload is None:
                    result.skipped_uncached += 1
                    continue
                if not qualifies(payload, settings):
                    result.skipped_filtered += 1
                    continue
                # Pre-send quality gate — never ship a half-translated or
                # empty card, even if it's cached and qualifies on severity.
                problem = quality_problem(payload, locale=locale)
                if problem:
                    logger.info(
                        "skipping %s/%s — %s", item.fingerprint, locale, problem,
                    )
                    result.skipped_invalid += 1
                    continue

                try:
                    message = render_message(
                        payload, locale=locale, base_url=settings.public_base_url,
                    )
                except (KeyError, ValueError) as exc:
                    logger.warning(
                        "format failed for %s/%s: %s", item.fingerprint, locale, exc,
                    )
                    result.errors += 1
                    continue

                if dry_run:
                    logger.info(
                        "[dry-run] would send to %s (%s):\n%s",
                        chat_id, locale, message,
                    )
                    result.sent += 1
                    result.by_channel[locale] = result.by_channel.get(locale, 0) + 1
                    sent_here += 1
                    continue

                try:
                    message_id = publisher.send_message(chat_id, message)
                except TelegramError as exc:
                    result.errors += 1
                    # A channel-level failure (bad chat id, bot not admin, bad
                    # token) is not item-specific — retrying every other post
                    # would just rack up identical errors and risk a flood-wait.
                    # Abort this channel with one actionable line.
                    if getattr(exc, "is_channel_fatal", False):
                        logger.error(
                            "channel %r (%s) is misconfigured: %s — skipping the "
                            "rest of this channel. Check the chat id is correct "
                            "and the bot is an admin with 'Post Messages'.",
                            chat_id, locale, exc,
                        )
                        break
                    logger.warning(
                        "telegram send failed for %s/%s: %s",
                        item.fingerprint, locale, exc,
                    )
                    continue

                ledger.record(
                    fingerprint=item.fingerprint,
                    locale=locale,
                    channel=chat_id,
                    message_id=message_id,
                )
                result.sent += 1
                result.by_channel[locale] = result.by_channel.get(locale, 0) + 1
                sent_here += 1
                if settings.send_delay_seconds > 0:
                    time.sleep(settings.send_delay_seconds)
    finally:
        if owns_publisher and publisher is not None:
            publisher.close()

    return result


__all__ = ["publish_once", "PublishResult", "qualifies", "DEFAULT_LEDGER_PATH"]
