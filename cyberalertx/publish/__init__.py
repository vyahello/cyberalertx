"""Outbound publishing layer.

Takes already-AI-rendered ThreatPosts from the store/cache and pushes the
high-signal ones to external channels. The only channel today is Telegram.

Design invariants (mirrors the rest of the codebase):
  * Synchronous. One short HTTP call per message via the existing `httpx`.
  * Cost-safe. Reuses the API's `_PostService`, which NEVER calls Anthropic —
    we only publish posts that were already rendered by `generate --use-llm`.
  * Degrade-and-log. One bad post (format error, Telegram 4xx) is logged and
    skipped; the run continues and the post is retried next fire.
  * Idempotent. A JSONL ledger records every successful send keyed by
    (fingerprint, locale); re-runs never double-post.

Entry point: `cyberalertx.publish.service.publish_once`, driven by the
`publish-telegram` CLI subcommand and the `cyberalertx-telegram.timer`.
"""
from __future__ import annotations

from .config import TelegramSettings, build_telegram_settings
from .ledger import PublishLedger
from .service import PublishResult, publish_once
from .telegram import TelegramError, TelegramPublisher

__all__ = [
    "TelegramSettings",
    "build_telegram_settings",
    "PublishLedger",
    "PublishResult",
    "publish_once",
    "TelegramError",
    "TelegramPublisher",
]
