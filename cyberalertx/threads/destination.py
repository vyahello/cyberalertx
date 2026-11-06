"""Threads destination for the Publication Engine — one instance per account slot.

Registered as `threads@{slot}` (e.g. `threads@en`, `threads@ua`), so the job
identity `{story}:{locale}:threads@{slot}:{type}` keeps the two profiles apart
and Website/Telegram identities are untouched. A slot serves exactly the
locale it is mapped to; any other combination is rejected in `prepare`.

Two-step publishing (official flow): create a media container → wait until
its status is FINISHED → `threads_publish`. The job's `external_state` holds
the container id from the moment it exists, and `phase` records where we are:

    (none) ──create──▶ container_created ──FINISHED──▶ sending ──▶ published
                         │ IN_PROGRESS too long → retrying (same container)
                         │ ERROR → a new container with the same image (never text-only)
                         │ EXPIRED (24 h) → a new container
                         ▼
    publish timed out / 5xx / unreadable → check the container:
        PUBLISHED → find the post (recent posts, exact text) → published
        FINISHED  → not published: retrying, the SAME container next time
        anything else / check failed → outcome_unknown (never blindly re-sent)

A new container is never created while an older one might still be
published: an attempt always starts by checking the stored container.
Exactly-once delivery is still impossible (Threads has no idempotency key);
what remains is surfaced as `outcome_unknown`, see `auto_reconcile`.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..publish.config import LEVEL_WEIGHT
from ..publish.destinations import INELIGIBLE, WAITING, Delivery, DeliveryError, Prepared, edition_hash
from ..publish.format import deep_link
from .accounts import AccountStore, TokenStorageError, _iso, _parse
from .client import ThreadsClient, ThreadsError
from .config import ThreadsSettings
from .format import ThreadsContentError, render_post

logger = logging.getLogger(__name__)

CONTAINER_TTL = timedelta(hours=24)          # official: unpublished containers expire after 24 h
#: The story's canonical illustration — the same asset as the website and
#: Telegram — as its 1200×675 PNG derivative (width within Threads' 320–1440).
IMAGE_VARIANT = "telegram.png"


def _norm(text: str) -> str:
    return " ".join((text or "").split())


class ThreadsDestination:
    def __init__(self, slot: str, *, settings: ThreadsSettings, accounts: AccountStore, public_base_url: str,
                 client_factory: Callable[[], ThreadsClient] | None = None,
                 image_check: Callable[[str], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 initial_wait_s: float = 30.0, poll_interval_s: float = 60.0, poll_budget_s: float = 120.0) -> None:
        if slot not in settings.accounts:
            raise ValueError(f"unknown Threads slot {slot!r}")
        self.slot, self.locale = slot, settings.accounts[slot]
        self.name = f"threads@{slot}"
        self.settings, self.accounts = settings, accounts
        self.base = public_base_url.rstrip("/")
        self._factory = client_factory or ThreadsClient
        self._client: ThreadsClient | None = None
        self._image_check = image_check
        self._sleep, self._clock = sleep, clock
        self.initial_wait_s, self.poll_interval_s, self.poll_budget_s = initial_wait_s, poll_interval_s, poll_budget_s

    # -- contract -------------------------------------------------------------

    def enabled(self, locale: str) -> bool:
        if locale != self.locale or not self.settings.publish_enabled:
            return False
        acc = self.accounts.get(self.slot)
        return acc.status == "connected" and self.accounts.has_token(self.slot)

    def plans_for(self, locale: str) -> bool:
        return self.enabled(locale)

    def _before_start(self, published: Any) -> bool:
        """No backlog: only articles published after Threads publishing began for this account."""
        since = _parse(self.accounts.get(self.slot).publishing_since)
        when = _parse(str(published or ""))
        return since is not None and (when is None or when < since)

    def qualifies(self, payload: dict[str, Any]) -> bool:
        if self._before_start(payload.get("published_at")):
            return False
        level_ok = LEVEL_WEIGHT.get(payload.get("threat_level", "Low"), 0) >= LEVEL_WEIGHT[self.settings.min_level]
        return level_ok or payload.get("actionability_level") == "urgent_action"

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None

    def _api(self) -> ThreadsClient:
        if self._client is None:
            self._client = self._factory()
        return self._client

    def prepare(self, job: Any, payload: dict[str, Any]) -> Prepared:
        if job.locale != self.locale:
            raise DeliveryError(f"{self.name} serves {self.locale}, not {job.locale}", category="invalid_content")
        acc = self.accounts.get(self.slot)
        if acc.status != "connected" or not self.accounts.has_token(self.slot):
            # Disconnected after planning: wait for a reconnect, do not burn the job.
            raise DeliveryError(f"{self.name} is {acc.status}", category="temporary", retry_after=3600)
        if job.publication_type == "initial" and self._before_start(
                getattr(job, "article_published_at", "") or payload.get("published_at")):
            raise DeliveryError("article published before Threads publishing began", category=INELIGIBLE)
        if self.settings.daily_limit and \
                self.accounts.published_last_24h(self.slot, self._clock()) >= self.settings.daily_limit:
            raise DeliveryError(f"{self.name}: daily limit of {self.settings.daily_limit} reached", category=WAITING)
        url = deep_link(self.base, job.locale, str(payload["id"]))
        try:
            post = render_post(payload, locale=job.locale, url=url)
        except ThreadsContentError as exc:
            raise DeliveryError(str(exc), category="invalid_content") from exc
        ill = (payload.get("media") or {}).get("illustration") or {}
        if not ill.get("asset_id"):
            # Same rule as Telegram: the story's own image or nothing yet; never another picture.
            raise DeliveryError("waiting for the story's illustration", category=WAITING)
        image = f"{self.base}/media/{ill['asset_id']}/{IMAGE_VARIANT}"
        alt = str((ill.get("alt") or {}).get(job.locale) or "")
        problem = self._check_image(image)
        if problem:
            raise DeliveryError(f"illustration not usable yet: {problem}", category=WAITING)
        state = dict(getattr(job, "external_state", {}) or {})
        created = _parse(str(state.get("container_created_at", "")))
        if not state.get("container_id") or (created and self._clock() - created >= CONTAINER_TTL):
            state = {}
        return Prepared(
            destination=self.name, locale=job.locale, target=f"@{acc.username or self.slot}", url=url,
            text=post.text, media_url=image, content_hash=edition_hash(payload, job.locale),
            extra={"topic_tag": post.topic_tag, "alt_text": alt, "dropped": post.dropped,
                   "container_id": state.get("container_id", ""),
                   "container_created_at": state.get("container_created_at", ""),
                   "user_id": acc.threads_user_id},
        )

    def _check_image(self, url: str) -> str:
        if not url.startswith(self.base + "/media/") or not url.endswith("/" + IMAGE_VARIANT):
            return "not the canonical illustration URL on the public site"
        if self._image_check is not None:
            try:
                self._image_check(url)
            except Exception as exc:                       # noqa: BLE001 - report and fall back
                return str(exc)[:200]
        return ""

    # -- delivery ---------------------------------------------------------------

    def deliver(self, prepared: Prepared, on_sending: Callable[..., None]) -> Delivery:
        try:
            token = self.accounts.token(self.slot)
        except TokenStorageError as exc:
            self._account_error("auth", str(exc))
            raise DeliveryError(str(exc), category="auth") from exc
        try:
            return self._deliver(prepared, on_sending, token)
        except ThreadsError as exc:
            self._account_error(exc.category, str(exc), exc.retry_after)
            raise DeliveryError(str(exc), category=exc.category, retry_after=exc.retry_after) from exc

    def _deliver(self, p: Prepared, on_sending: Callable[..., None], token: str) -> Delivery:
        api, user = self._api(), str(p.extra["user_id"])
        image = p.media_url
        container = str(p.extra.get("container_id") or "")
        created_at = str(p.extra.get("container_created_at") or "")

        ready = False
        if container:                                    # resume: never a second post
            status, err = api.container_status(container, token)
            ready = status == "FINISHED"
            if status == "PUBLISHED":
                return self._found(p, token, created_at, note="container was already published")
            if status == "EXPIRED":
                container = ""
            elif status == "ERROR":
                # A fresh container with the same image; never a text-only fallback.
                logger.warning("%s: container failed (%s) — new container", self.name, err)
                container = ""
        if not container:
            self._check_quota(user, token)
            container, image = self._create(p, on_sending, user, token, image)
            created_at = _iso(self._clock())

        if not ready:
            try:
                container, image, created_at = self._await_ready(p, on_sending, user, token, container,
                                                                 image, created_at)
            except _AlreadyPublished:
                return self._found(p, token, created_at, note="container was published while waiting")

        on_sending(phase="sending")
        try:
            media_id = api.publish(user, token, container)
        except ThreadsError as exc:
            if exc.category not in ("unknown_outcome", "temporary", "network"):
                raise                                     # a definite refusal: nothing was posted
            return self._verify_after_publish(p, token, container, created_at, exc)
        return self._done(p, token, media_id, image)

    def _create(self, p: Prepared, on_sending: Callable[..., None], user: str, token: str,
                image: str) -> tuple[str, str]:
        api = self._api()
        try:
            cid = api.create_container(user, token, text=p.text, image_url=image,
                                       alt_text=str(p.extra.get("alt_text", "")),
                                       topic_tag=str(p.extra.get("topic_tag", "")))
        except ThreadsError as exc:
            if image and exc.category == "missing_media":
                # Threads could not fetch the image: retry later, never post without it.
                raise ThreadsError(f"image refused: {exc}", category="temporary", retry_after=1800) from exc
            if exc.category == "unknown_outcome":
                # An orphan container is never published and expires in 24 h:
                # retrying creation is safe, unlike retrying a publish.
                raise ThreadsError(f"container creation outcome unknown: {exc}", category="temporary") from exc
            else:
                raise
        on_sending(phase="container_created", container_id=cid, container_created_at=_iso(self._clock()),
                   media_type="IMAGE" if image else "TEXT")
        return cid, image

    def _await_ready(self, p: Prepared, on_sending: Callable[..., None], user: str, token: str,
                     container: str, image: str, created_at: str) -> tuple[str, str, str]:
        api = self._api()
        waited = 0.0
        if self.initial_wait_s:
            self._sleep(self.initial_wait_s)             # docs: wait ~30 s on average
            waited += self.initial_wait_s
        while True:
            status, err = api.container_status(container, token)
            if status == "FINISHED":
                return container, image, created_at
            if status == "PUBLISHED":
                raise _AlreadyPublished()
            if status == "ERROR":
                raise DeliveryError(f"container error: {err}", category="temporary", retry_after=1800)
            if status == "EXPIRED":
                container, image = self._create(p, on_sending, user, token, image)
                created_at = _iso(self._clock())
                continue
            if waited >= self.poll_budget_s:
                # Still processing: keep the container, come back next run.
                raise DeliveryError(f"container {status or 'unknown'} after {waited:.0f}s",
                                    category="temporary", retry_after=self.poll_interval_s)
            self._sleep(self.poll_interval_s)
            waited += self.poll_interval_s

    def _verify_after_publish(self, p: Prepared, token: str, container: str, created_at: str,
                              cause: ThreadsError) -> Delivery:
        try:
            status, _ = self._api().container_status(container, token)
        except ThreadsError as exc:
            raise DeliveryError(f"publish outcome unknown ({cause}); status check failed ({exc})",
                                category="unknown_outcome") from exc
        if status == "PUBLISHED":
            return self._found(p, token, created_at, note="published despite a failed response")
        if status == "FINISHED":
            raise DeliveryError(f"publish failed ({cause}); container still unpublished — retrying it",
                                category="temporary", retry_after=self.poll_interval_s)
        raise DeliveryError(f"publish outcome unknown ({cause}); container status {status!r}",
                            category="unknown_outcome")

    def _found(self, p: Prepared, token: str, created_at: str, *, note: str) -> Delivery:
        since = (_parse(created_at) or self._clock() - CONTAINER_TTL) - timedelta(minutes=10)
        try:
            posts = self._api().recent_posts(str(p.extra["user_id"]), token, since_unix=int(since.timestamp()))
        except ThreadsError as exc:
            raise DeliveryError(f"container published but the post could not be listed: {exc}",
                                category="unknown_outcome") from exc
        match = [x for x in posts if _norm(str(x.get("text", ""))) == _norm(p.text)]
        if len(match) != 1:
            raise DeliveryError(f"container published; {len(match)} matching posts found — reconcile by hand",
                                category="unknown_outcome")
        self.accounts.mark(self.slot, self._clock(), verified=True)
        self.accounts.record_publication(self.slot, self._clock())
        return Delivery(external_id=str(match[0]["id"]), url=str(match[0].get("permalink", "") or ""),
                        media_url=p.media_url, content_hash=p.content_hash, note=note)

    def _done(self, p: Prepared, token: str, media_id: str, image: str) -> Delivery:
        try:
            link = self._api().permalink(media_id, token)
        except ThreadsError:
            link = ""                                     # the post exists; the URL is a nicety
        self.accounts.mark(self.slot, self._clock(), verified=True)
        self.accounts.record_publication(self.slot, self._clock())
        return Delivery(external_id=media_id, url=link, media_url=image, content_hash=p.content_hash)

    def _check_quota(self, user: str, token: str) -> None:
        try:
            used, total, duration = self._api().publishing_limit(user, token)
        except ThreadsError as exc:
            if exc.category in ("auth", "permission"):
                raise
            return                                        # advisory only
        if total and used >= total:
            raise ThreadsError(f"publishing quota used: {used}/{total} per {duration}s", category="rate_limit",
                               retry_after=3600)

    def _account_error(self, category: str, message: str, retry_after: float = 0.0) -> None:
        now = self._clock()
        if category in ("auth", "permission"):
            self.accounts.mark(self.slot, now, status="needs_reconnect", error=message)
            logger.error("OPERATOR ACTION NEEDED: Threads %s: %s — run tools.threads setup", self.slot, message)
        elif category == "rate_limit":
            self.accounts.mark(self.slot, now, error=message,
                               rate_limited_until=now + timedelta(seconds=retry_after or 3600))


class _AlreadyPublished(Exception):
    pass


def http_image_check(url: str, *, client: Any = None) -> None:
    """Raise unless the image is publicly fetchable as Threads requires:
    HTTP 200 without credentials, PNG/JPEG, ≤ 8 MB, width 320–1440, ratio ≤ 10:1."""
    import httpx

    from ..media.assets import sniff

    c = client or httpx.Client(timeout=20, follow_redirects=False)
    try:
        r = c.get(url)
    finally:
        if client is None:
            c.close()
    if r.status_code != 200:
        raise ValueError(f"card URL answered HTTP {r.status_code}")
    if len(r.content) > 8 * 1024 * 1024:
        raise ValueError("card larger than 8 MB")
    mime, w, h = sniff(r.content)
    if mime not in ("image/png", "image/jpeg"):
        raise ValueError(f"card is {mime}; Threads takes JPEG or PNG")
    if not 320 <= w <= 1440 or max(w, h) / max(1, min(w, h)) > 10:
        raise ValueError(f"card is {w}x{h}; Threads wants width 320–1440 and ratio ≤ 10:1")


def auto_reconcile(store: Any, destinations: dict[str, Any], now: datetime) -> list[dict[str, str]]:
    """Resolve `outcome_unknown` Threads jobs from the API where possible.

    PUBLISHED container + exactly one matching post → published.
    FINISHED container (never published) → scheduled again (same container).
    Anything else stays `outcome_unknown` for a person."""
    from ..publish.jobs import PublicationJob

    out: list[dict[str, str]] = []
    for job in store.all():
        dest = destinations.get(job.destination)
        cid = (job.external_state or {}).get("container_id")
        if job.status != "outcome_unknown" or not isinstance(dest, ThreadsDestination) or not cid:
            continue
        try:
            token = dest.accounts.token(dest.slot)
            status, _ = dest._api().container_status(cid, token)
        except (ThreadsError, TokenStorageError) as exc:
            out.append({"job_id": job.job_id, "result": f"left unknown: {exc}"})
            continue
        if status == "FINISHED":
            def requeue(j: PublicationJob) -> None:
                j.status, j.scheduled_at, j.next_attempt_at = "scheduled", _iso(now), ""
                j.note(now, "auto-reconciled: container not published")
            store.update(job.job_id, requeue, now)
            out.append({"job_id": job.job_id, "result": "not published → rescheduled (same container)"})
        elif status == "PUBLISHED":
            acc = dest.accounts.get(dest.slot)
            created = _parse(str(job.external_state.get("container_created_at", ""))) or now - CONTAINER_TTL
            try:
                posts = dest._api().recent_posts(acc.threads_user_id, token,
                                                 since_unix=int((created - timedelta(minutes=10)).timestamp()))
            except ThreadsError as exc:
                out.append({"job_id": job.job_id, "result": f"left unknown: {exc}"})
                continue
            # The text we would send is not stored; match by time window and
            # article link, which every CyberAlertX post ends with.
            link = f"/{job.locale}/threat/{job.fingerprint}"
            match = [x for x in posts if link in str(x.get("text", ""))]
            if len(match) == 1:
                def found(j: PublicationJob, m: dict[str, Any] = match[0]) -> None:
                    j.status, j.external_id = "published", str(m["id"])
                    j.published_url, j.completed_at = str(m.get("permalink", "") or ""), _iso(now)
                    j.last_error = j.error_category = ""
                    j.note(now, "auto-reconciled: found on Threads", external_id=str(m["id"]))
                store.update(job.job_id, found, now)
                dest.accounts.record_publication(dest.slot, now)
                out.append({"job_id": job.job_id, "result": f"published as {match[0]['id']}"})
            else:
                out.append({"job_id": job.job_id, "result": f"left unknown: {len(match)} matching posts"})
        else:
            out.append({"job_id": job.job_id, "result": f"left unknown: container {status}"})
    return out


__all__ = ["CONTAINER_TTL", "IMAGE_VARIANT", "ThreadsDestination", "auto_reconcile"]
