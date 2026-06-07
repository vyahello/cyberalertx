"""Minimal synchronous Telegram Bot API client.

One method we need — `sendMessage` — over the existing `httpx`. No `aiogram` /
`python-telegram-bot`: the backend is fully synchronous and a bot framework is
dead weight for a single fire-and-forget call per post.

Failure is a raised `TelegramError`; the caller logs and skips, consistent with
the degrade-and-log pattern used everywhere else.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TelegramError(RuntimeError):
    """Raised when the Bot API call fails (transport error, non-2xx, ok:false).

    `status_code` / `description` carry the Bot API response so the caller can
    tell a *channel-level* misconfiguration (bad chat id, bot not admin) apart
    from a one-off / transient failure. The former should abort the whole
    channel; the latter only skips one post.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        description: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.description = description

    @property
    def is_channel_fatal(self) -> bool:
        """True when retrying other posts to this channel is pointless.

        401/403 → bad token or the bot isn't an admin of the channel.
        400 'chat not found' / empty chat_id → the configured chat id is wrong.
        All three are channel-wide, not item-specific.
        """
        desc = self.description.lower()
        if self.status_code in (401, 403):
            return True
        if self.status_code == 400 and (
            "chat not found" in desc or "chat_id is empty" in desc
        ):
            return True
        return False


class TelegramPublisher:
    """Sends messages to Telegram channels via the Bot API.

    Construct once and reuse — it holds a pooled `httpx.Client`. `client` is
    injectable so tests can pass a transport-mocked client without real I/O.
    """

    def __init__(
        self,
        bot_token: str,
        *,
        api_base: str = "https://api.telegram.org",
        timeout_seconds: int = 15,
        client: httpx.Client | None = None,
    ) -> None:
        if not bot_token:
            raise ValueError("bot_token is required")
        self._token = bot_token
        self._api_base = api_base.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def _url(self, method: str) -> str:
        return f"{self._api_base}/bot{self._token}/{method}"

    def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = False,
    ) -> int:
        """POST sendMessage. Returns the new message_id.

        Raises TelegramError on any failure (so the caller can log + skip and
        the post is retried next run). We do NOT retry inline — the timer is
        the retry mechanism.
        """
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        try:
            resp = self._client.post(self._url("sendMessage"), json=payload)
        except httpx.HTTPError as exc:
            raise TelegramError(f"sendMessage transport error: {exc}") from exc

        # Telegram returns 200 with {ok: true, result: {...}} on success, and
        # a non-2xx with {ok: false, description: "..."} on error. Surface the
        # human-readable description when present.
        try:
            body = resp.json()
        except ValueError:
            body = {}

        if resp.status_code >= 400 or not body.get("ok"):
            desc = body.get("description") or resp.text[:200]
            raise TelegramError(
                f"sendMessage failed (HTTP {resp.status_code}): {desc}",
                status_code=resp.status_code,
                description=str(desc),
            )

        message_id = (body.get("result") or {}).get("message_id")
        if not isinstance(message_id, int):
            raise TelegramError("sendMessage ok but no message_id in result")
        return message_id

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TelegramPublisher":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["TelegramPublisher", "TelegramError"]
