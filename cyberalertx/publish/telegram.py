"""Minimal synchronous Telegram Bot API client.

Two methods — `sendMessage`, and `sendPhoto` for posts that carry the story's
Media Engine card (off unless CYBERALERTX_TELEGRAM_ATTACH_IMAGES=1) — over the
existing `httpx`. No `aiogram` /
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

from ..logsafe import install as _install_log_redaction

_install_log_redaction()   # httpx logs request URLs; ours carry credentials


#: Bot API 400 descriptions that mean "the photo", not "the message".
_MEDIA_ERRORS = ("wrong file identifier", "failed to get http url content",
                 "wrong type of the web page content", "image_process_failed",
                 "photo_invalid_dimensions", "wrong remote file", "photo_save_file_invalid")

#: Transport failures raised before the request left this machine.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout,
             httpx.UnsupportedProtocol, httpx.InvalidURL)


def _transport_error(method: str, exc: Exception, stage: str = "") -> "TelegramError":
    not_sent = isinstance(exc, _NOT_SENT)
    return TelegramError(f"{method} {stage}transport error: {exc}",
                         category="network" if not_sent else "unknown_outcome")


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
        category: str | None = None,
        retry_after: int = 0,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.description = description
        self._category = category
        self.retry_after = retry_after

    @property
    def category(self) -> str:
        """What kind of failure this is — drives retry and fallback decisions.

        network        the request never reached Telegram: safe to resend
        rate_limit     429; `retry_after` says when (not accepted)
        temporary      502/503/504 gateway errors (not accepted)
        auth           401: bad token — operator action, no retry
        permission     403 / chat not found — operator action, no retry
        missing_media  Telegram could not fetch or use the photo URL
        invalid_content other 400s: this payload will never be accepted
        unknown_outcome the request may have been accepted (read timeout,
                       dropped connection, 500, an unparsable 200): resending
                       could duplicate the post, so it must be reconciled
        """
        if self._category:
            return self._category
        code, desc = self.status_code, self.description.lower()
        if code is None:
            return "unknown_outcome"
        if code == 429:
            return "rate_limit"
        if code == 401:
            return "auth"
        if code == 403 or (code == 400 and ("chat not found" in desc or "chat_id is empty" in desc)):
            return "permission"
        if code == 400 and any(k in desc for k in _MEDIA_ERRORS):
            return "missing_media"
        if 400 <= code < 500:
            return "invalid_content"
        if code in (502, 503, 504):
            return "temporary"
        return "unknown_outcome"

    @property
    def accepted_possible(self) -> bool:
        """True when Telegram may have published the message anyway."""
        return self.category == "unknown_outcome"

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
        reply_markup: dict[str, Any] | None = None,
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
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._post("sendMessage", payload)

    def send_photo(
        self,
        chat_id: str,
        photo_url: str,
        caption: str,
        *,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
        reply_markup: dict[str, Any] | None = None,
    ) -> int:
        """POST sendPhoto with a public HTTPS image URL. Returns the message_id.

        Telegram fetches the URL itself, so it must be publicly reachable —
        the Media Engine's card URL on the site domain. `caption` must already
        fit Telegram's 1024-character caption limit (format.render_caption).
        Same failure contract as `send_message`.
        """
        if not photo_url.startswith("https://"):
            raise TelegramError("sendPhoto needs a public https:// image URL",
                                category="missing_media")
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }
        if reply_markup:
            # The inline keyboard: one URL button to the full article.
            payload["reply_markup"] = reply_markup
        return self._post("sendPhoto", payload)

    def _post(self, method: str, payload: dict[str, Any]) -> int:
        try:
            resp = self._client.post(self._url(method), json=payload)
        except httpx.HTTPError as exc:
            raise _transport_error(method, exc) from exc

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
        retry_after = 0
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
                    resp = self._client.post(self._url(method), json=payload)
                except httpx.HTTPError as exc:
                    raise _transport_error(method, exc, "retry after 429 ") from exc
                try:
                    body = resp.json()
                except ValueError:
                    body = {}
                retry_after = int((body.get("parameters") or {}).get("retry_after", 0) or 0)

        if resp.status_code < 400 and not body.get("ok"):
            # A 2xx we cannot read: Telegram may well have posted it.
            raise TelegramError(f"{method} returned HTTP {resp.status_code} without a readable result",
                                status_code=resp.status_code, category="unknown_outcome")
        if resp.status_code >= 400 or not body.get("ok"):
            desc = body.get("description") or resp.text[:200]
            raise TelegramError(
                f"{method} failed (HTTP {resp.status_code}): {desc}",
                status_code=resp.status_code,
                description=str(desc),
                retry_after=retry_after,
            )

        message_id = (body.get("result") or {}).get("message_id")
        if not isinstance(message_id, int):
            raise TelegramError(f"{method} ok but no message_id in result",
                                status_code=resp.status_code, category="unknown_outcome")
        return message_id

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TelegramPublisher":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["TelegramPublisher", "TelegramError"]
