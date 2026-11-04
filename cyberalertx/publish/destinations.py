"""Destination adapters: the small contract every publication target meets.

    prepare(job, payload) -> Prepared     build the destination's own content
                                          and media from the post payload;
                                          raises DeliveryError on bad content
    deliver(prepared, on_sending) -> Delivery
                                          execute; call `on_sending()` right
                                          before anything leaves the process
                                          (so a crash after it is treated as
                                          "may have been delivered")

Errors are `DeliveryError(category, retry_after)` with the categories the
orchestrator understands (see `RETRYABLE` / `OPERATOR`). Threads (Phase 5)
adds one more class here; nothing else needs to change.

Two destinations exist now:

* `WebsiteDestination` — the site is a read model over the API: an edition is
  live the moment it is rendered and passes review. "Publishing" it therefore
  means validating the edition, fixing its canonical URL and social card, and
  recording that delivery (content hash for update detection). No external
  call; fully idempotent.
* `TelegramDestination` — wraps the existing `TelegramPublisher`, message and
  caption renderers and Media Engine card URL. It also reads and writes the
  existing publish ledger, so the legacy `publish-telegram` command and the
  job worker can never send the same story twice to a channel.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .config import TelegramSettings
from .format import deep_link, notify, quality_problem, render_caption, render_message
from .ledger import PublishLedger
from .telegram import TelegramError

logger = logging.getLogger(__name__)

#: Worth trying again later, automatically.
RETRYABLE = frozenset({"network", "rate_limit", "temporary"})
#: Needs a person: retrying cannot succeed (and auth loops get accounts banned).
OPERATOR = frozenset({"auth", "permission"})
#: Never resend automatically — reconcile first.
UNKNOWN = "unknown_outcome"


class DeliveryError(RuntimeError):
    def __init__(self, message: str, *, category: str, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.category = category
        self.retry_after = retry_after


@dataclass
class Prepared:
    destination: str
    locale: str
    target: str                     # chat id, or "site"
    url: str                        # canonical article URL
    text: str = ""
    media_url: str = ""
    content_hash: str = ""
    members: list[str] = field(default_factory=list)   # fingerprints of the story
    extra: dict[str, Any] = field(default_factory=dict)

    def preview(self) -> dict[str, Any]:
        return {"destination": self.destination, "locale": self.locale, "target": self.target,
                "url": self.url, "media_url": self.media_url, "content_hash": self.content_hash,
                "text": self.text, **self.extra}


@dataclass
class Delivery:
    external_id: str
    url: str
    media_url: str = ""
    content_hash: str = ""
    note: str = ""


class Destination(Protocol):
    name: str

    def enabled(self, locale: str) -> bool: ...
    def prepare(self, job: Any, payload: dict[str, Any]) -> Prepared: ...
    def deliver(self, prepared: Prepared, on_sending: Callable[[], None]) -> Delivery: ...


# ---------------------------------------------------------------- shared

def edition_hash(payload: dict[str, Any], locale: str) -> str:
    """Hash of what a reader sees in one edition (text + severity + card art)."""
    content = (payload.get("translations") or {}).get(locale) or {}
    blob = {"content": content, "level": payload.get("threat_level"),
            "art": ((payload.get("media") or {}).get("illustration") or {}).get("asset_id", "")}
    return hashlib.sha256(json.dumps(blob, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def card_for(payload: dict[str, Any], locale: str, variant: str) -> str:
    """The edition's Media Engine card URL (versioned), or "" without one."""
    from ..media.cards import card_inputs, card_url, content_hash

    inputs = card_inputs(payload, locale)
    return card_url(locale, str(payload["id"]), variant, "png", content_hash(inputs)) if inputs else ""


def _required_text(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    c = (payload.get("translations") or {}).get(locale) or {}
    if not str(c.get("title") or "").strip():
        raise DeliveryError(f"no {locale} title", category="invalid_content")
    if not (str(c.get("plain_summary") or "").strip() or str(c.get("short_summary") or "").strip()):
        raise DeliveryError(f"no {locale} summary", category="invalid_content")
    return c


# ---------------------------------------------------------------- website

class WebsiteDestination:
    name = "website"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def enabled(self, locale: str) -> bool:
        return locale in ("en", "ua")

    def prepare(self, job: Any, payload: dict[str, Any]) -> Prepared:
        _required_text(payload, job.locale)
        if job.locale not in (payload.get("available_locales") or [job.locale]):
            raise DeliveryError(f"edition {job.locale} not available", category="invalid_content")
        return Prepared(
            destination="website", locale=job.locale, target="site",
            url=deep_link(self.base_url, job.locale, str(payload["id"])),
            media_url=card_for(payload, job.locale, "og"),
            content_hash=edition_hash(payload, job.locale),
            extra={"source": payload.get("source", ""), "source_url": payload.get("source_url", "")},
        )

    def deliver(self, prepared: Prepared, on_sending: Callable[[], None]) -> Delivery:
        # Nothing leaves the process: the API already serves this edition.
        fingerprint = prepared.url.rsplit("/", 1)[-1]
        return Delivery(external_id=fingerprint, url=prepared.url, media_url=prepared.media_url,
                        content_hash=prepared.content_hash)


# ---------------------------------------------------------------- telegram

_UPDATE_PREFIX = {"en": "🔄 <b>Update</b>", "ua": "🔄 <b>Оновлення</b>"}


class TelegramDestination:
    name = "telegram"

    def __init__(self, settings: TelegramSettings, *, ledger_path: Path,
                 publisher_factory: Callable[[], Any] | None = None) -> None:
        self.settings = settings
        self.ledger_path = Path(ledger_path)
        self._factory = publisher_factory
        self._publisher: Any = None

    def enabled(self, locale: str) -> bool:
        return bool(self.settings.chat_id_for(locale))

    def _client(self) -> Any:
        if self._publisher is None:
            if self._factory is not None:
                self._publisher = self._factory()
            else:
                from .telegram import TelegramPublisher
                if not self.settings.bot_token:
                    raise DeliveryError("no bot token configured", category="auth")
                # No inline sleeping on 429: the job is rescheduled instead.
                self._publisher = TelegramPublisher(self.settings.bot_token, api_base=self.settings.api_base,
                                                    timeout_seconds=self.settings.request_timeout_seconds,
                                                    max_retry_after_seconds=0)
        return self._publisher

    def close(self) -> None:
        if self._publisher is not None and hasattr(self._publisher, "close"):
            self._publisher.close()
        self._publisher = None

    def prepare(self, job: Any, payload: dict[str, Any]) -> Prepared:
        chat = self.settings.chat_id_for(job.locale)
        if not chat:
            raise DeliveryError(f"no Telegram channel for {job.locale}", category="permission")
        _required_text(payload, job.locale)
        problem = quality_problem(payload, locale=job.locale)
        if problem:
            raise DeliveryError(f"quality gate: {problem}", category="invalid_content")
        base = self.settings.public_base_url
        try:
            text = render_message(payload, locale=job.locale, base_url=base)
            photo = card_for(payload, job.locale, "telegram") if self.settings.attach_images else ""
            caption = render_caption(payload, locale=job.locale, base_url=base) if photo else ""
        except (KeyError, ValueError) as exc:
            raise DeliveryError(f"format failed: {exc}", category="invalid_content") from exc
        if job.publication_type == "breaking_update":
            prefix = _UPDATE_PREFIX.get(job.locale, _UPDATE_PREFIX["en"])
            text = f"{prefix}\n\n{text}"
            caption = f"{prefix}\n\n{caption}" if caption else ""
        return Prepared(
            destination="telegram", locale=job.locale, target=chat,
            url=deep_link(base, job.locale, str(payload["id"])), text=text, media_url=photo,
            content_hash=edition_hash(payload, job.locale),
            members=list(payload.get("_story_members") or [payload["id"]]),
            extra={"caption": caption, "silent": not notify(payload),
                   "publication_type": job.publication_type},
        )

    def _already_sent(self, prepared: Prepared) -> bool:
        ledger = PublishLedger(self.ledger_path)          # fresh read: another process may have sent it
        return any(ledger.is_published(fp, prepared.locale) for fp in prepared.members)

    def deliver(self, prepared: Prepared, on_sending: Callable[[], None]) -> Delivery:
        initial = prepared.extra.get("publication_type", "initial") == "initial"
        if initial and self._already_sent(prepared):
            return Delivery(external_id="", url=prepared.url, note="already in the publish ledger; not resent")
        client = self._client()
        silent = bool(prepared.extra.get("silent"))
        message_id: int | None = None
        media_used = ""
        if prepared.media_url and prepared.extra.get("caption"):
            on_sending()
            try:
                message_id = client.send_photo(prepared.target, prepared.media_url,
                                               prepared.extra["caption"], disable_notification=silent)
                media_used = prepared.media_url
            except TelegramError as exc:
                cat = exc.category
                if cat not in ("missing_media", "invalid_content"):
                    raise DeliveryError(str(exc), category=cat, retry_after=exc.retry_after) from exc
                # Telegram refused the photo itself — nothing was posted, so the
                # text post is a safe fallback (never after an unknown outcome).
                logger.warning("sendPhoto refused (%s) — falling back to text", exc)
        if message_id is None:
            on_sending()
            try:
                message_id = client.send_message(prepared.target, prepared.text, preview_url=prepared.url,
                                                 disable_notification=silent)
            except TelegramError as exc:
                raise DeliveryError(str(exc), category=exc.category, retry_after=exc.retry_after) from exc
        PublishLedger(self.ledger_path).record(fingerprint=prepared.url.rsplit("/", 1)[-1],
                                               locale=prepared.locale, channel=prepared.target,
                                               message_id=message_id)
        return Delivery(external_id=str(message_id), url=prepared.url, media_url=media_used,
                        content_hash=prepared.content_hash)


__all__ = ["DeliveryError", "Delivery", "Destination", "OPERATOR", "Prepared", "RETRYABLE",
           "TelegramDestination", "UNKNOWN", "WebsiteDestination", "card_for", "edition_hash"]
