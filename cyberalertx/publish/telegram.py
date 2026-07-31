"""Minimal synchronous Telegram Bot API client.

One method we need — `sendMessage` — over the existing `httpx`. No `aiogram` /
`python-telegram-bot`: the backend is fully synchronous and a bot framework is
dead weight for a single fire-and-forget call per post.

Failure is a raised `TelegramError`; the caller logs and skips, consistent with
the degrade-and-log pattern used everywhere else.
"""
from __future__ import annotations

import logging
import time
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
        max_retry_after_seconds: int = 30,
    ) -> None:
        if not bot_token:
            raise ValueError("bot_token is required")
        self._token = bot_token
        self._api_base = api_base.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_seconds)
        # Ceiling on how long we'll block for a flood-wait. Telegram
        # occasionally answers with minutes; blocking a publish run that long
        # is worse than deferring to the next timer fire.
        self._max_retry_after = max_retry_after_seconds

    def _url(self, method: str) -> str:
        return f"{self._api_base}/bot{self._token}/{method}"

    def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        parse_mode: str = "HTML",
        preview_url: str | None = None,
        disable_notification: bool = False,
    ) -> int:
        """POST sendMessage. Returns the new message_id.

        `preview_url` pins which link Telegram builds the preview card from.
        This matters: the message body linkifies CVE ids, and those links
        appear before our own "Read more" link. Telegram previews the FIRST
        link it finds, so without pinning, every CVE post ships with an
        nvd.nist.gov card sitting under our text as if NIST published it.

        `disable_notification` sends silently. Reserved for routine posts —
        a channel that buzzes a phone for every advisory gets muted, and a
        muted channel can't deliver the one alert that matters.

        Raises TelegramError on any failure (so the caller can log + skip and
        the post is retried next run). We do NOT retry inline — the timer is
        the retry mechanism.
        """
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }
        if preview_url:
            payload["link_preview_options"] = {
                "url": preview_url,
                # Small media keeps the card from dominating the message —
                # the text is the product, the card is a hint.
                "prefer_small_media": True,
                "show_above_text": False,
            }
        else:
            payload["link_preview_options"] = {"is_disabled": True}
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

        # 429 means we hit the flood limit and Telegram is telling us exactly
        # how long to wait. Honouring it once is the difference between
        # finishing the run and losing every remaining post: the alternative
        # is that each subsequent send hits the same limit and the backlog
        # rolls to the next timer fire. We wait once and retry once — beyond
        # that the run genuinely should end and let the timer take over.
        if resp.status_code == 429:
            retry_after = int(
                (body.get("parameters") or {}).get("retry_after", 0) or 0
            )
            if 0 < retry_after <= self._max_retry_after:
                logger.warning(
                    "telegram rate limit hit, waiting %ss before one retry",
                    retry_after,
                )
                time.sleep(retry_after)
                try:
                    resp = self._client.post(self._url("sendMessage"), json=payload)
                    body = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    raise TelegramError(
                        f"sendMessage retry after 429 failed: {exc}"
                    ) from exc

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
