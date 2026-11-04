"""Publication jobs: one record per (story, locale, destination, type).

Persistence follows the project's convention for operational state — one JSON
file under `data/` (`publish_jobs.json`), rewritten atomically (temp file +
rename) under an exclusive `fcntl` lock, like the AI cache and the media store.
The lock is what makes claiming safe: two workers (two timer fires, a timer
and a manual CLI run) read-modify-write the file one at a time, so a job can
be moved to `processing` by exactly one of them. A crashed worker leaves a
`processing` job with an expired lease, which the next run recovers.

The job id IS the publication identity — `{story}:{locale}:{destination}:{type}`
— so planning the same story twice can never create a second job, and a
published job is never re-executed by a later run.

Statuses
    scheduled        waiting for `scheduled_at` (the planner's default state;
                     a job due now is simply scheduled in the past)
    processing       claimed by one worker (`claimed_by`, `lease_until`)
    published        delivered; `external_id` / `published_url` recorded
    retrying         a recoverable failure; runs again at `next_attempt_at`
    failed           permanent failure, auth/permission problem, or retries
                     exhausted — needs `retry` from an operator
    cancelled        withdrawn by an operator or by policy (e.g. rejected)
    outcome_unknown  the destination may have accepted it; never resent
                     automatically — `reconcile` decides (see orchestrator)

There is no separate `pending` state: the prompt's pending/scheduled pair
collapses into `scheduled` because every job has a time it becomes due.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import random
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from ..config import DATA_DIR

JOBS_PATH = DATA_DIR / "publish_jobs.json"

STATUSES = ("scheduled", "processing", "published", "retrying", "failed", "cancelled", "outcome_unknown")
OPEN = ("scheduled", "retrying")                 # may be claimed when due
DONE = ("published", "cancelled")
DESTINATIONS = ("website", "telegram")
TYPES = ("initial", "update", "breaking_update")


def _iso(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat() if dt else ""


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def job_id(story: str, locale: str, destination: str, pub_type: str = "initial", revision: str = "") -> str:
    base = f"{story}:{locale}:{destination}:{pub_type}"
    return f"{base}:{revision}" if revision else base


@dataclass
class PublicationJob:
    job_id: str
    story_key: str                  # story identity (NewsItem.story_key, or the fingerprint)
    fingerprint: str                # the article (detail page) being published
    locale: str
    destination: str                # website | telegram
    publication_type: str = "initial"
    members: list[str] = field(default_factory=list)   # every article of the story (dedup)
    status: str = "scheduled"
    priority: int = 0               # higher runs first
    reasons: list[str] = field(default_factory=list)   # why this priority / schedule
    scheduled_at: str = ""
    article_published_at: str = ""  # the article's own time: newest goes first, stale expires
    attempts: int = 0
    max_attempts: int = 5
    last_attempt_at: str = ""
    next_attempt_at: str = ""
    claimed_by: str = ""
    lease_until: str = ""
    phase: str = ""                 # "" | "sending": set just before the external call
                                    # (Threads also: "container_created")
    external_state: dict[str, Any] = field(default_factory=dict)   # e.g. Threads container id
    external_id: str = ""           # Telegram message_id, website fingerprint
    published_url: str = ""
    media_url: str = ""             # the card/photo actually used
    content_hash: str = ""          # hash of the delivered content (update detection)
    evidence_fingerprint: str = ""  # Breaking evidence the delivery reflected
    last_error: str = ""
    error_category: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PublicationJob":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def due(self, now: datetime) -> bool:
        if self.status == "scheduled":
            at = _parse(self.scheduled_at)
        elif self.status == "retrying":
            at = _parse(self.next_attempt_at)
        else:
            return False
        return at is None or at <= now

    def note(self, now: datetime, event: str, **extra: Any) -> None:
        """Append to the job's own history (kept short)."""
        self.history.append({"at": _iso(now), "event": event, **extra})
        self.history = self.history[-20:]


# ---------------------------------------------------------------- retry policy

@dataclass(frozen=True)
class RetryPolicy:
    base_seconds: float = 120.0
    factor: float = 2.0
    cap_seconds: float = 6 * 3600.0
    jitter: float = 0.2             # ±20 %

    @classmethod
    def from_env(cls) -> "RetryPolicy":
        return cls(base_seconds=float(os.getenv("CYBERALERTX_PUBLISH_RETRY_BASE_S", "120")),
                   cap_seconds=float(os.getenv("CYBERALERTX_PUBLISH_RETRY_CAP_S", str(6 * 3600))))

    def delay(self, attempt: int, *, retry_after: float = 0.0, rng: Callable[[], float] = random.random) -> float:
        """Seconds before attempt `attempt + 1`. A server's `retry_after` is a floor."""
        raw = min(self.cap_seconds, self.base_seconds * self.factor ** max(0, attempt - 1))
        jittered = raw * (1 - self.jitter + 2 * self.jitter * rng())
        return max(jittered, float(retry_after))


# ---------------------------------------------------------------- store

class JobStore:
    """`{job_id: job}` in one JSON file; every mutation runs under the lock."""

    def __init__(self, path: Path = JOBS_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        with open(self.path.with_suffix(".lock"), "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except ValueError as exc:
            # A corrupt job file must stop the worker, not be silently treated
            # as "no jobs" — that would re-plan and could re-send everything.
            raise RuntimeError(f"publication job store {self.path} is unreadable: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".publish_jobs.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # -- reads ---------------------------------------------------------------

    def all(self) -> list[PublicationJob]:
        return [PublicationJob.from_dict(v) for v in self._read().values()]

    def get(self, jid: str) -> PublicationJob | None:
        raw = self._read().get(jid)
        return PublicationJob.from_dict(raw) if raw else None

    # -- writes --------------------------------------------------------------

    def add_missing(self, jobs: Iterable[PublicationJob], now: datetime) -> list[PublicationJob]:
        """Insert jobs whose id does not exist yet. Existing jobs — in any
        state — are left untouched. Returns the jobs actually added."""
        added: list[PublicationJob] = []
        with self._locked():
            data = self._read()
            for j in jobs:
                if j.job_id in data:
                    continue
                j.created_at = j.updated_at = _iso(now)
                data[j.job_id] = j.to_dict()
                added.append(j)
            if added:
                self._write(data)
        return added

    def update(self, jid: str, fn: Callable[[PublicationJob], None], now: datetime) -> PublicationJob | None:
        """Atomically load one job, apply `fn`, save it."""
        with self._locked():
            data = self._read()
            raw = data.get(jid)
            if raw is None:
                return None
            job = PublicationJob.from_dict(raw)
            fn(job)
            job.updated_at = _iso(now)
            data[jid] = job.to_dict()
            self._write(data)
            return job

    def claim(self, now: datetime, worker: str, *, lease_s: float = 600.0,
              select: Callable[[list[PublicationJob]], list[PublicationJob]] | None = None) -> list[PublicationJob]:
        """Move due jobs to `processing` for `worker`, in one locked step.

        `select` orders and caps the due jobs (priority, per-destination
        limits); the default takes all of them. Only what it returns is claimed.
        """
        with self._locked():
            data = self._read()
            due = [PublicationJob.from_dict(v) for v in data.values()]
            due = [j for j in due if j.due(now)]
            chosen = select(due) if select else due
            lease = _iso(now + timedelta(seconds=lease_s))
            for j in chosen:
                j.status, j.claimed_by, j.lease_until, j.phase = "processing", worker, lease, ""
                j.attempts += 1
                j.last_attempt_at = _iso(now)
                j.updated_at = _iso(now)
                j.note(now, "claimed", worker=worker, attempt=j.attempts)
                data[j.job_id] = j.to_dict()
            if chosen:
                self._write(data)
            return chosen

    def recover_abandoned(self, now: datetime) -> list[PublicationJob]:
        """`processing` jobs whose lease ran out: the worker died.

        If it died before the external call (`phase` empty) the job simply
        becomes retryable. If it died during the call (`phase == "sending"`)
        the destination may have accepted it, so an external destination goes
        to `outcome_unknown`; the website (idempotent, internal) is retried.
        """
        out: list[PublicationJob] = []
        with self._locked():
            data = self._read()
            for jid, raw in data.items():
                j = PublicationJob.from_dict(raw)
                lease = _parse(j.lease_until)
                if j.status != "processing" or (lease and lease > now):
                    continue
                if j.phase == "sending" and j.destination != "website":
                    j.status, j.error_category = "outcome_unknown", "unknown_outcome"
                    j.last_error = f"worker {j.claimed_by or '?'} stopped during delivery"
                else:
                    j.status, j.next_attempt_at = "retrying", _iso(now)
                    j.last_error = f"worker {j.claimed_by or '?'} stopped before delivery"
                j.note(now, "recovered", to=j.status)
                j.claimed_by = j.lease_until = j.phase = ""
                j.updated_at = _iso(now)
                data[jid] = j.to_dict()
                out.append(j)
            if out:
                self._write(data)
        return out

    def prune(self, now: datetime, *, older_than_days: float = 90.0) -> int:
        """Move published/cancelled jobs completed before the cutoff to
        `publish_jobs.archive.jsonl`. Safe: the planner never recreates them —
        their stories are outside the publication window, and a Telegram
        delivery is still found in the publish ledger."""
        cutoff = now - timedelta(days=older_than_days)
        with self._locked():
            data = self._read()
            old = {k: v for k, v in data.items() if v.get("status") in DONE
                   and (_parse(v.get("completed_at", "")) or now) < cutoff}
            if not old:
                return 0
            with open(self.path.with_name(self.path.stem + ".archive.jsonl"), "a", encoding="utf-8") as fh:
                for v in old.values():
                    fh.write(json.dumps(v, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._write({k: v for k, v in data.items() if k not in old})
            return len(old)


__all__ = ["DESTINATIONS", "DONE", "JOBS_PATH", "JobStore", "OPEN", "PublicationJob", "RetryPolicy",
           "STATUSES", "TYPES", "job_id"]
