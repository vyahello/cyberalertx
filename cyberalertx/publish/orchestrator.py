"""Publication orchestrator: plan jobs, then run due jobs through destinations.

    plan()  stories → eligible (story, locale, destination) jobs, idempotently
    run()   recover abandoned jobs → claim due jobs → prepare → deliver → record

It coordinates what already exists and recalculates nothing:

* eligibility — the post service's own gates (rendered, review-visible,
  language, half-translation), relevance (`effective_relevance`), and for
  Telegram the existing channel policy (`qualifies`, source tiers, language
  gate, `quality_problem`);
* priority — the Intelligence Core's Breaking decisions and Daily Top 10
  (computed with `write=False`, so the shadow state is not touched);
* delivery — `WebsiteDestination` / `TelegramDestination` (destinations.py);
* persistence — `JobStore` (jobs.py) plus the existing Telegram ledger.

Nothing is scheduled by this module: the existing timer calls it (see
docs/publish/PUBLICATION_ENGINE.md for the opt-in switch).
"""
from __future__ import annotations

import logging
import os
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..models import NewsItem
from .config import TelegramSettings
from .destinations import (INELIGIBLE, OPERATOR, RETRYABLE, UNKNOWN, WAITING, DeliveryError, before_activation,
                           edition_hash)
from .jobs import JobStore, PublicationJob, RetryPolicy, _iso, _parse as _parse_ts, job_id

logger = logging.getLogger(__name__)

KYIV = "Europe/Kyiv"
_LANGUAGE_GATE = {"en": frozenset({"en"}), "ua": frozenset({"en", "ua"})}   # = publish.service


# ---------------------------------------------------------------- policy

@dataclass(frozen=True)
class PublishPolicy:
    #: Only stories published within this window get NEW jobs — the archive
    #: is never (re)published by a first run.
    window_hours: float = 48.0
    #: Jobs per destination+locale per worker run. Telegram's default is the
    #: channel limit from TelegramSettings (the timer passes --limit 1 today).
    telegram_per_run: int = 5
    website_per_run: int = 500
    #: Per Threads account per run (CYBERALERTX_THREADS_LIMIT).
    threads_per_run: int = 1
    lease_seconds: float = 600.0
    max_attempts: int = 5
    #: Daily Top 10 delivery time, "HH:MM" in Kyiv. Unset (default) → Top 10
    #: stories only get a priority boost and go out at the next run.
    top10_at: str = ""
    #: Telegram follow-ups for Breaking stories whose evidence materially
    #: changed (intel evidence fingerprint). Off by default.
    breaking_updates: bool = False
    #: Record website revisions when an edition's visible content changes.
    website_updates: bool = True
    timezone: str = KYIV

    @classmethod
    def from_env(cls, settings: TelegramSettings | None = None) -> "PublishPolicy":
        def flag(name: str) -> bool:
            return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")
        return cls(
            window_hours=float(os.getenv("CYBERALERTX_PUBLISH_WINDOW_HOURS", "48")),
            telegram_per_run=settings.limit if settings else 5,
            threads_per_run=int(os.getenv("CYBERALERTX_THREADS_LIMIT", "1")),
            max_attempts=int(os.getenv("CYBERALERTX_PUBLISH_MAX_ATTEMPTS", "5")),
            top10_at=(os.getenv("CYBERALERTX_PUBLISH_TOP10_AT") or "").strip(),
            breaking_updates=flag("CYBERALERTX_PUBLISH_BREAKING_UPDATES"),
        )


PRIORITY_BREAKING = 100
PRIORITY_TOP = 50          # + (11 - rank)
PRIORITY_ORDINARY = 10


# ---------------------------------------------------------------- inputs

class EditionSource:
    """What the orchestrator needs from the post service (injectable)."""

    def __init__(self, service: Any) -> None:
        self.service = service

    def items(self) -> list[NewsItem]:
        return list(self.service.list_items())

    def payload(self, item: NewsItem, locale: str) -> dict[str, Any] | None:
        try:
            p = self.service.render_if_cached(item, required_locale=locale)
        except Exception as exc:          # one broken item never stops a run
            logger.warning("render failed for %s/%s: %s", item.fingerprint, locale, exc)
            return None
        if not isinstance(p, dict) or locale not in (p.get("translations") or {}):
            return None
        return dict(p)

    def review_status(self, fingerprint: str, locale: str) -> str:
        cache = getattr(getattr(self.service, "_generator", None), "_cache", None)
        post = cache.get(fingerprint, locale) if cache is not None else None
        return (getattr(post, "review_status", "") or "auto") if post is not None else "missing"


@dataclass
class IntelView:
    """The slice of an Intelligence Core run the orchestrator uses."""
    story_of: dict[str, str] = field(default_factory=dict)        # fingerprint -> story key
    members: dict[str, list[str]] = field(default_factory=dict)   # story key -> fingerprints
    top_rank: dict[str, int] = field(default_factory=dict)        # story key -> 1..10
    breaking: dict[str, str] = field(default_factory=dict)        # story key -> evidence fingerprint
    relevance: dict[str, str] = field(default_factory=dict)       # story key -> relevance

    @classmethod
    def from_run(cls, res: Any) -> "IntelView":
        v = cls()
        for s in res.stories:
            fps = [m.fingerprint for m in s.members]
            v.members[s.key] = fps
            v.relevance[s.key] = s.relevance
            for fp in fps:
                v.story_of[fp] = s.key
        v.top_rank = {p["story_key"]: int(p["rank"]) for p in res.picks}
        v.breaking = {b["story_key"]: str(b.get("evidence_fingerprint", "")) for b in res.breaking}
        return v


def intel_view(items: Sequence[NewsItem], now: datetime) -> IntelView:
    """Run the Intelligence Core read-only over the current stores."""
    from ..ai.cache import ThreatPostCache
    from ..ai.fact_sheet import FactSheetCache
    from ..config import DATA_DIR
    from ..intel.engine import run as intel_run

    sheets_path = DATA_DIR / "fact_sheets.json"
    sheets = FactSheetCache(sheets_path) if sheets_path.exists() else None
    posts = ThreatPostCache(DATA_DIR / "threat_posts.json")
    return IntelView.from_run(intel_run(list(items), now=now, sheets=sheets, posts=posts, write=False))


# ---------------------------------------------------------------- planning

@dataclass
class PlanResult:
    created: list[PublicationJob] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    existing: int = 0

    def summary(self) -> dict[str, Any]:
        by: dict[str, int] = {}
        for s in self.skipped:
            by[s["reason"]] = by.get(s["reason"], 0) + 1
        return {"created": len(self.created), "existing": self.existing, "skipped": by}


def _kyiv_slot(now: datetime, hhmm: str, tz: str) -> datetime | None:
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return None
    local = now.astimezone(ZoneInfo(tz))
    slot = datetime.combine(local.date(), dtime(hh, mm), tzinfo=ZoneInfo(tz))
    return slot.astimezone(timezone.utc)


def _schedule(story: str, view: IntelView, policy: PublishPolicy, now: datetime) -> tuple[int, datetime, list[str]]:
    if story in view.breaking:
        return PRIORITY_BREAKING, now, ["breaking"]
    rank = view.top_rank.get(story)
    if rank is not None:
        at = now
        why = [f"daily top {rank}"]
        slot = _kyiv_slot(now, policy.top10_at, policy.timezone) if policy.top10_at else None
        if slot is not None and slot > now:
            at = slot
            why.append(f"held for the {policy.top10_at} Kyiv edition")
        return PRIORITY_TOP + (11 - rank), at, why
    return PRIORITY_ORDINARY, now, ["ordinary"]


def plan(
    source: EditionSource,
    store: JobStore,
    *,
    now: datetime,
    settings: TelegramSettings,
    destinations: Mapping[str, Any],
    view: IntelView | None = None,
    policy: PublishPolicy | None = None,
    ledger_has: Callable[[str, str], bool] | None = None,
    dry_run: bool = False,
) -> PlanResult:
    """Create the jobs that should exist and do not yet. Idempotent."""
    from ..pipeline.relevance import effective_relevance
    from .service import qualifies

    policy = policy or PublishPolicy.from_env(settings)
    items = source.items()
    view = view if view is not None else intel_view(items, now)
    existing = {j.job_id: j for j in store.all()}
    res = PlanResult(existing=len(existing))
    proposed: dict[str, PublicationJob] = {}
    cutoff = now - timedelta(hours=policy.window_hours)

    def skip(item: NewsItem, locale: str, dest: str, reason: str) -> None:
        res.skipped.append({"fingerprint": item.fingerprint, "locale": locale, "destination": dest,
                            "reason": reason})

    def latest(story: str, locale: str, dest: str) -> PublicationJob | None:
        """The most recent PUBLISHED job of this story/locale/destination."""
        done = [j for j in list(existing.values()) + list(proposed.values())
                if j.story_key == story and j.locale == locale and j.destination == dest
                and j.status == "published"]
        return max(done, key=lambda j: j.completed_at or j.created_at) if done else None

    # Safety net under the story identity: one initial delivery per article,
    # edition and destination, whatever story key it arrives under (a story
    # re-keyed upstream must never be posted a second time).
    initial_for = {(j.fingerprint, j.locale, j.destination) for j in existing.values()
                   if j.publication_type == "initial" and j.status != "cancelled"}

    def already(fp: str, locale: str, dest: str) -> bool:
        return (fp, locale, dest) in initial_for or any(
            (j.fingerprint, j.locale, j.destination) == (fp, locale, dest) and j.publication_type == "initial"
            for j in proposed.values())

    def has_open(story: str, locale: str, dest: str, ptype: str) -> bool:
        return any(j.story_key == story and j.locale == locale and j.destination == dest
                   and j.publication_type == ptype and j.status not in ("published", "cancelled", "failed")
                   for j in list(existing.values()) + list(proposed.values()))

    for item in sorted(items, key=lambda i: i.published_at, reverse=True):
        if getattr(item, "duplicate_of", ""):
            continue                                   # later coverage: its story already has an article
        story = view.story_of.get(item.fingerprint) or getattr(item, "story_key", "") or item.fingerprint
        relevance = view.relevance.get(story) or effective_relevance(item)
        if relevance == "out_of_scope":
            skip(item, "*", "*", "out of scope")
            continue
        recent = item.published_at >= cutoff
        prio, at, why = _schedule(story, view, policy, now)
        members = view.members.get(story, [item.fingerprint])
        for locale in ("en", "ua"):
            payload = source.payload(item, locale)
            if payload is None:
                skip(item, locale, "*", "edition not rendered or withheld by review")
                continue
            payload = {**payload, "_story_members": members}

            def make(dest: str, ptype: str = "initial", revision: str = "", p: int = prio,
                     when: datetime = at, reasons: list[str] = why, ev: str = "") -> PublicationJob:
                return PublicationJob(
                    job_id=job_id(story, locale, dest, ptype, revision), story_key=story,
                    fingerprint=item.fingerprint, members=list(members), locale=locale, destination=dest,
                    publication_type=ptype,
                    priority=p, reasons=list(reasons), scheduled_at=_iso(when),
                    article_published_at=_iso(item.published_at),
                    max_attempts=policy.max_attempts, evidence_fingerprint=ev)

            # ---- website ------------------------------------------------
            web_id = job_id(story, locale, "website")
            if web_id not in existing and web_id not in proposed and not already(item.fingerprint, locale, "website"):
                if recent:
                    proposed[web_id] = make("website", reasons=why)
                else:
                    skip(item, locale, "website", "outside the publication window")
            elif policy.website_updates:
                last = latest(story, locale, "website")
                h = edition_hash(payload, locale)
                if last is not None and last.content_hash and last.content_hash != h \
                        and last.fingerprint == item.fingerprint and not has_open(story, locale, "website", "update"):
                    upd = make("website", "update", h[:10], reasons=["edition content changed"])
                    proposed[upd.job_id] = upd

            # ---- threads (one destination per connected account) ---------
            for dname, tdest in destinations.items():
                if not dname.startswith("threads@") or not tdest.plans_for(locale):
                    continue
                if (getattr(item, "language", "en") or "en") not in _LANGUAGE_GATE[locale]:
                    skip(item, locale, dname, "language gate")
                    continue
                if getattr(item, "source_tier", "unverified") not in settings.require_tiers:
                    skip(item, locale, dname, "source tier")
                    continue
                th_id = job_id(story, locale, dname)
                if th_id in existing or th_id in proposed or any(already(fp, locale, dname) for fp in members):
                    continue
                if not recent:
                    skip(item, locale, dname, "outside the publication window")
                elif not tdest.qualifies(payload):
                    skip(item, locale, dname, "below the Threads severity bar")
                else:
                    proposed[th_id] = make(dname, ev=view.breaking.get(story, ""))

            # ---- telegram -----------------------------------------------
            tg = destinations.get("telegram")
            if tg is None or not tg.enabled(locale):
                continue
            if (getattr(item, "language", "en") or "en") not in _LANGUAGE_GATE[locale]:
                skip(item, locale, "telegram", "language gate")
                continue
            if getattr(item, "source_tier", "unverified") not in settings.require_tiers:
                skip(item, locale, "telegram", "source tier")
                continue
            tg_id = job_id(story, locale, "telegram")
            known = tg_id in existing or tg_id in proposed or any(already(fp, locale, "telegram") for fp in members)
            if not known:
                if ledger_has is not None and any(ledger_has(fp, locale) for fp in members):
                    # Sent by the legacy publisher: record it, never resend.
                    j = make("telegram", reasons=["already in the publish ledger"])
                    j.status, j.completed_at = "published", _iso(now)
                    j.note(now, "imported from ledger")
                    proposed[tg_id] = j
                    continue
                if not recent:
                    skip(item, locale, "telegram", "outside the publication window")
                    continue
                if not qualifies(payload, settings):
                    skip(item, locale, "telegram", "below the channel severity bar")
                    continue
                j = make("telegram", ev=view.breaking.get(story, ""))
                if before_activation(settings, item.published_at):
                    # Recorded, never sent: the job id stays taken, so the
                    # story is not planned again when its edition changes.
                    j.status, j.completed_at = "cancelled", _iso(now)
                    j.last_error = "article published before Telegram activation"
                    j.note(now, "cancelled", reason=j.last_error)
                proposed[tg_id] = j
            elif policy.breaking_updates and story in view.breaking:
                ev = view.breaking[story]
                last = latest(story, locale, "telegram")
                if last is not None and last.evidence_fingerprint and last.evidence_fingerprint != ev \
                        and not has_open(story, locale, "telegram", "breaking_update"):
                    upd = make("telegram", "breaking_update", ev[:10], p=PRIORITY_BREAKING, when=now,
                               reasons=["breaking: evidence materially changed"], ev=ev)
                    proposed[upd.job_id] = upd

    if dry_run:
        res.created = list(proposed.values())
    else:
        res.created = store.add_missing(proposed.values(), now)
    return res


# ---------------------------------------------------------------- execution

@dataclass
class RunReport:
    recovered: list[str] = field(default_factory=list)
    published: list[dict[str, str]] = field(default_factory=list)
    retrying: list[dict[str, str]] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    unknown: list[dict[str, str]] = field(default_factory=list)
    cancelled: list[dict[str, str]] = field(default_factory=list)
    deferred: list[dict[str, str]] = field(default_factory=list)
    previews: list[dict[str, Any]] = field(default_factory=list)
    paused: list[str] = field(default_factory=list)
    dry_run: bool = False

    def summary(self) -> dict[str, Any]:
        return {k: (len(v) if isinstance(v, list) and k != "paused" else v) for k, v in self.__dict__.items()
                if k != "previews"}


def _selector(destinations: Mapping[str, Any], policy: PublishPolicy,
              limit: int | None) -> Callable[[list[PublicationJob]], list[PublicationJob]]:
    def select(due: list[PublicationJob]) -> list[PublicationJob]:
        # Highest priority first; within a priority the NEWEST article first,
        # as the legacy publisher does — with more qualifying stories than
        # slots, oldest-first would post an ever-staler backlog.
        def newest(j: PublicationJob) -> float:
            t = _parse_ts(j.article_published_at or j.scheduled_at)
            return -t.timestamp() if t else 0.0
        due = sorted(due, key=lambda j: (-j.priority, newest(j), j.created_at))
        caps: dict[tuple[str, str], int] = {}
        out = []
        for j in due:
            dest = destinations.get(j.destination)
            if dest is None or not dest.enabled(j.locale):
                continue
            if j.destination == "website":
                cap = policy.website_per_run
            elif j.destination.startswith("threads@"):
                cap = policy.threads_per_run
            else:
                cap = limit if limit is not None else policy.telegram_per_run
            k = (j.destination, j.locale)
            if caps.get(k, 0) >= cap:
                continue
            caps[k] = caps.get(k, 0) + 1
            out.append(j)
        return out
    return select


def run(
    source: EditionSource,
    store: JobStore,
    destinations: Mapping[str, Any],
    *,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    policy: PublishPolicy | None = None,
    retry: RetryPolicy | None = None,
    limit: int | None = None,
    worker: str | None = None,
    dry_run: bool = False,
    send_delay_s: float = 0.0,
    rng: Callable[[], float] | None = None,
) -> RunReport:
    """Execute due jobs. `dry_run` claims nothing, changes nothing, sends nothing."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = now or clock()
    policy = policy or PublishPolicy()
    retry = retry or RetryPolicy.from_env()
    worker = worker or f"{socket.gethostname()}:{os.getpid()}"
    report = RunReport(dry_run=dry_run)
    select = _selector(destinations, policy, limit)
    by_fp = {i.fingerprint: i for i in source.items()}
    stale_before = now - timedelta(hours=policy.window_hours)

    if dry_run:
        for j in select([j for j in store.all() if j.due(now)]):
            item = by_fp.get(j.fingerprint)
            payload = source.payload(item, j.locale) if item else None
            entry: dict[str, Any] = {"job_id": j.job_id, "fingerprint": j.fingerprint, "status": j.status,
                                     "priority": j.priority, "reasons": j.reasons, "scheduled_at": j.scheduled_at}
            if item is not None and j.destination != "website" and item.published_at < stale_before:
                entry["would"] = "expire: article older than the publication window"
            elif payload is None:
                entry["would"] = "cancel or defer: edition no longer available"
            else:
                try:
                    payload = {**payload, "_story_members": sorted(set(j.members) | {j.fingerprint})}
                    entry.update(destinations[j.destination].prepare(j, payload).preview())
                    entry["would"] = "deliver"
                except DeliveryError as exc:
                    entry["would"] = f"fail: {exc.category}: {exc}"
            report.previews.append(entry)
        return report

    report.recovered = [j.job_id for j in store.recover_abandoned(now)]
    # Social posts about articles that left the publication window are not
    # news any more: cancel them before claiming (website jobs only record a
    # live edition, so they never expire).
    for j in store.all():
        item = by_fp.get(j.fingerprint)
        if (j.status in ("scheduled", "retrying") and j.destination != "website" and item is not None
                and item.published_at < stale_before):
            def expire(x: PublicationJob) -> None:
                if x.status in ("scheduled", "retrying"):
                    x.status, x.completed_at = "cancelled", _iso(now)
                    x.last_error = "expired: article older than the publication window"
                    x.note(now, "expired")
            store.update(j.job_id, expire, now)
            report.cancelled.append({"job_id": j.job_id, "reason": "expired (outside publication window)"})
    # Queued Telegram posts about articles from before activation: cancel,
    # never send (they may have been planned before the cutoff existed).
    tg = destinations.get("telegram")
    tg_settings = getattr(tg, "settings", None)
    for j in store.all():
        if (j.status in ("scheduled", "retrying") and j.destination == "telegram"
                and j.publication_type == "initial" and before_activation(tg_settings, j.article_published_at)):
            def precut(x: PublicationJob) -> None:
                if x.status in ("scheduled", "retrying"):
                    x.status, x.completed_at = "cancelled", _iso(now)
                    x.last_error = "article published before Telegram activation"
                    x.note(now, "cancelled", reason=x.last_error)
            store.update(j.job_id, precut, now)
            report.cancelled.append({"job_id": j.job_id, "reason": "published before Telegram activation"})
    claimed = store.claim(now, worker, lease_s=policy.lease_seconds, select=select)
    paused: set[tuple[str, str]] = set()
    sent_telegram = 0

    for job in claimed:
        key = (job.destination, job.locale)
        jnow = clock()
        if key in paused:
            def release(j: PublicationJob) -> None:
                j.status, j.claimed_by, j.lease_until = "scheduled", "", ""
                j.attempts = max(0, j.attempts - 1)
                j.note(jnow, "released", reason="destination paused this run")
            store.update(job.job_id, release, jnow)
            report.deferred.append({"job_id": job.job_id, "reason": "destination paused"})
            continue

        item = by_fp.get(job.fingerprint)
        payload = source.payload(item, job.locale) if item else None
        if payload is None:
            status = source.review_status(job.fingerprint, job.locale) if item else "missing"
            stale = item is not None and item.published_at < jnow - timedelta(hours=policy.window_hours)
            if status == "rejected" or item is None or stale:
                reason = ("rejected by the editor" if status == "rejected" else
                          "article no longer exists" if item is None else
                          f"edition still unavailable ({status}) after the publication window")

                def cancel(j: PublicationJob, reason: str = reason) -> None:
                    j.status, j.claimed_by, j.lease_until, j.last_error = "cancelled", "", "", reason
                    j.completed_at = _iso(jnow)
                    j.note(jnow, "cancelled", reason=reason)
                store.update(job.job_id, cancel, jnow)
                report.cancelled.append({"job_id": job.job_id, "reason": reason})
            else:
                # Held for review (hold mode) or not rendered right now: wait,
                # without spending an attempt.
                def defer(j: PublicationJob, status: str = status) -> None:
                    j.status, j.claimed_by, j.lease_until = "retrying", "", ""
                    j.attempts = max(0, j.attempts - 1)
                    j.next_attempt_at = _iso(jnow + timedelta(hours=1))
                    j.note(jnow, "deferred", review_status=status)
                store.update(job.job_id, defer, jnow)
                report.deferred.append({"job_id": job.job_id, "reason": f"edition not available ({status})"})
            continue

        dest = destinations[job.destination]
        payload = {**payload, "_story_members": sorted(set(job.members) | {job.fingerprint})}
        if job.destination == "telegram" and sent_telegram and send_delay_s > 0:
            time.sleep(send_delay_s)

        def mark_sending(phase: str = "sending", jid: str = job.job_id, **state: Any) -> None:
            """Persist progress BEFORE the next external step: `phase` tells
            recovery what may have happened; `state` (e.g. a Threads
            container id) lets the next attempt resume instead of redoing."""
            def f(j: PublicationJob) -> None:
                j.phase = phase
                if state:
                    j.external_state = {**j.external_state, **state}
            store.update(jid, f, clock())

        try:
            prepared = dest.prepare(job, payload)
            delivery = dest.deliver(prepared, mark_sending)
        except DeliveryError as exc:
            if exc.category == INELIGIBLE:
                def drop(j: PublicationJob, reason: str = str(exc), t: datetime = clock()) -> None:
                    j.status, j.claimed_by, j.lease_until, j.phase = "cancelled", "", "", ""
                    j.completed_at, j.last_error = _iso(t), reason
                    j.note(t, "cancelled", reason=reason)
                store.update(job.job_id, drop, clock())
                report.cancelled.append({"job_id": job.job_id, "reason": str(exc)})
                continue
            if exc.category == WAITING:
                def wait(j: PublicationJob, reason: str = str(exc), t: datetime = clock()) -> None:
                    j.status, j.claimed_by, j.lease_until, j.phase = "retrying", "", "", ""
                    j.attempts = max(0, j.attempts - 1)
                    j.next_attempt_at = _iso(t + timedelta(minutes=20))
                    j.last_error = reason
                    j.note(t, "waiting", reason=reason)
                store.update(job.job_id, wait, clock())
                report.deferred.append({"job_id": job.job_id, "reason": str(exc)})
                continue
            _record_failure(store, job, exc.category, str(exc), exc.retry_after, clock(), retry, report, rng)
            if exc.category in OPERATOR or exc.category == "rate_limit":
                paused.add(key)
                report.paused.append(f"{job.destination}:{job.locale} ({exc.category})")
                if exc.category in OPERATOR:
                    logger.error("OPERATOR ACTION NEEDED: %s %s — %s", job.destination, job.locale, exc)
            continue
        except Exception as exc:                      # a bug, not a destination answer
            current = store.get(job.job_id)
            cat = UNKNOWN if (current and current.phase == "sending" and job.destination != "website") else "temporary"
            _record_failure(store, job, cat, f"{type(exc).__name__}: {exc}", 0, clock(), retry, report, rng)
            continue

        def done(j: PublicationJob, d: Any = delivery, t: datetime = clock()) -> None:
            j.status, j.claimed_by, j.lease_until, j.phase = "published", "", "", ""
            j.external_id, j.published_url, j.media_url = d.external_id, d.url, d.media_url
            j.content_hash = d.content_hash or j.content_hash
            j.last_error = j.error_category = ""
            j.completed_at = _iso(t)
            j.note(t, "published", external_id=d.external_id, **({"note": d.note} if d.note else {}))
        store.update(job.job_id, done, clock())
        report.published.append({"job_id": job.job_id, "external_id": delivery.external_id, "url": delivery.url})
        if job.destination == "telegram" and not delivery.note:
            sent_telegram += 1

    report.paused = sorted(set(report.paused))
    for dest in destinations.values():
        if hasattr(dest, "close"):
            dest.close()
    return report


def _record_failure(store: JobStore, job: PublicationJob, category: str, message: str, retry_after: float,
                    now: datetime, retry: RetryPolicy, report: RunReport,
                    rng: Callable[[], float] | None) -> None:
    entry = {"job_id": job.job_id, "category": category, "error": message[:300]}

    def f(j: PublicationJob) -> None:
        j.claimed_by = j.lease_until = j.phase = ""
        j.last_error, j.error_category = message[:500], category
        if category == UNKNOWN:
            j.status = "outcome_unknown"
        elif category in RETRYABLE and j.attempts < j.max_attempts:
            delay = retry.delay(j.attempts, retry_after=retry_after, **({"rng": rng} if rng else {}))
            j.status, j.next_attempt_at = "retrying", _iso(now + timedelta(seconds=delay))
            entry["next_attempt_at"] = j.next_attempt_at
        else:
            j.status = "failed"
            if category in RETRYABLE:
                j.last_error = f"retries exhausted ({j.attempts}): {message}"[:500]
        j.note(now, j.status, category=category)
    updated = store.update(job.job_id, f, now)
    status = updated.status if updated else "failed"
    {"outcome_unknown": report.unknown, "retrying": report.retrying}.get(status, report.failed).append(entry)


# ---------------------------------------------------------------- operator actions

class ActionError(ValueError):
    pass


def retry_job(store: JobStore, jid: str, now: datetime) -> PublicationJob:
    """failed / cancelled → scheduled now, attempts reset. Never for
    published or outcome_unknown (that needs `reconcile`)."""
    def f(j: PublicationJob) -> None:
        if j.status not in ("failed", "cancelled", "retrying"):
            raise ActionError(f"{j.job_id} is {j.status}; only failed, cancelled or retrying jobs can be retried")
        j.status, j.attempts, j.scheduled_at, j.next_attempt_at = "scheduled", 0, _iso(now), ""
        j.note(now, "operator retry")
    job = store.update(jid, f, now)
    if job is None:
        raise ActionError(f"no job {jid}")
    return job


def reconcile_job(store: JobStore, jid: str, now: datetime, *, sent_id: str = "", not_sent: bool = False,
                  ledger_record: Callable[[PublicationJob, str], None] | None = None) -> PublicationJob:
    """Resolve an `outcome_unknown` job after checking the destination.

    `sent_id` — it WAS delivered (e.g. the Telegram message id seen in the
    channel): mark published and record it in the ledger. `not_sent` — it was
    not: schedule it again."""
    if bool(sent_id) == bool(not_sent):
        raise ActionError("give exactly one of --sent MESSAGE_ID or --not-sent")

    def f(j: PublicationJob) -> None:
        if j.status != "outcome_unknown":
            raise ActionError(f"{j.job_id} is {j.status}, not outcome_unknown")
        if sent_id:
            j.status, j.external_id, j.completed_at = "published", sent_id, _iso(now)
            j.note(now, "reconciled: delivered", external_id=sent_id)
        else:
            j.status, j.scheduled_at, j.next_attempt_at = "scheduled", _iso(now), ""
            j.note(now, "reconciled: not delivered")
        j.last_error = j.error_category = ""
    job = store.update(jid, f, now)
    if job is None:
        raise ActionError(f"no job {jid}")
    if sent_id and ledger_record is not None:
        ledger_record(job, sent_id)
    return job


def cancel_job(store: JobStore, jid: str, now: datetime, reason: str = "operator") -> PublicationJob:
    def f(j: PublicationJob) -> None:
        if j.status in ("published", "processing"):
            raise ActionError(f"{j.job_id} is {j.status} and cannot be cancelled")
        j.status, j.completed_at, j.last_error = "cancelled", _iso(now), reason
        j.note(now, "cancelled", reason=reason)
    job = store.update(jid, f, now)
    if job is None:
        raise ActionError(f"no job {jid}")
    return job


def status_counts(jobs: Iterable[PublicationJob]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for j in jobs:
        k = f"{j.destination}:{j.locale}"
        out.setdefault(k, {})
        out[k][j.status] = out[k].get(j.status, 0) + 1
    return out


__all__ = ["ActionError", "EditionSource", "IntelView", "PlanResult", "PublishPolicy", "RunReport",
           "cancel_job", "intel_view", "plan", "reconcile_job", "retry_job", "run", "status_counts"]
