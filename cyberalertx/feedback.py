"""Reader feedback: validate a vote, store it, and add it up.

The detail page asks one question — was this helpful? — and offers 👍 / 👎.
A 👎 opens an optional follow-up asking what could be better. This module is
the server side of that widget: what a submission may contain, how it is
written, and how the append-only log is turned into numbers an editor can act
on. It has no I/O beyond reading and appending one JSONL file, and the
aggregation is a pure function so it is trivial to test.

WHY THE LOG RECORDS CHANGES, NOT STATE

A reader can change their mind: 👍 then 👎, or click 👍 again to take it back.
Storing only "the latest vote per reader" would need a stable reader id, which
is a persistent pseudonymous identifier — exactly what the rest of this
project refuses to keep (see `server/analytics`: salted hashes, rotated daily,
nothing persistent). So the browser remembers its own vote locally and every
submission says what it is replacing:

    {"vote": "down", "previous": "up"}   # switched
    {"vote": "none", "previous": "up"}   # took it back

Summing those deltas gives exact net counts with no identifier at all. The
trade-off is that a hand-crafted request can claim any `previous`; counts are
floored at zero, and the site is small enough that this is an acceptable
bound for now.

V1 RECORDS

The first version of the widget offered five buttons — helpful, too vague, too
technical, incorrect, not relevant — and wrote `{"signal": ...}`. Those records
are still in the file and still count: "helpful" is a 👍, the other four are a
👎 carrying that reason. Old cached copies of the page may also keep posting
the v1 shape for a while after a deploy, so the endpoint accepts it too.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

logger = logging.getLogger(__name__)

VOTES: frozenset[str] = frozenset({"up", "down", "none"})
#: The optional follow-up after a 👎. Kept to four so the choice is quick;
#: these are the same four the v1 widget offered, so old and new records
#: aggregate into one breakdown.
REASONS: frozenset[str] = frozenset({
    "too_vague", "too_technical", "incorrect", "not_relevant",
})
LOCALES: frozenset[str] = frozenset({"en", "ua"})

_LEGACY_SIGNALS: dict[str, tuple[str, str | None]] = {
    "helpful": ("up", None),
    "too_vague": ("down", "too_vague"),
    "too_technical": ("down", "too_technical"),
    "incorrect": ("down", "incorrect"),
    "not_relevant": ("down", "not_relevant"),
}

_MAX_ID_LEN = 64


class FeedbackError(ValueError):
    """A submission that fails validation. The message is safe to return."""


def parse_submission(payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Validate one POST body and return the record to append.

    Accepts the v2 shape — `{id, locale, kind: "vote", vote, previous}` or
    `{id, locale, kind: "reason", reason}` — and the v1 `{id, locale, signal}`.
    Raises `FeedbackError` on anything else.
    """
    post_id = str(payload.get("id") or "").strip()
    locale = str(payload.get("locale") or "").strip()
    if not post_id or len(post_id) > _MAX_ID_LEN:
        raise FeedbackError("invalid id")
    if locale not in LOCALES:
        raise FeedbackError("invalid locale")

    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    base: dict[str, Any] = {"v": 2, "id": post_id, "locale": locale, "timestamp": stamp}

    signal = payload.get("signal")
    if signal is not None and "kind" not in payload:
        mapped = _LEGACY_SIGNALS.get(str(signal).strip())
        if mapped is None:
            raise FeedbackError("invalid signal")
        vote, reason = mapped
        record = {**base, "kind": "vote", "vote": vote, "previous": "none"}
        if reason:
            record["reason"] = reason
        return record

    kind = str(payload.get("kind") or "").strip()
    if kind == "vote":
        vote = str(payload.get("vote") or "").strip()
        previous = str(payload.get("previous") or "none").strip()
        if vote not in VOTES or previous not in VOTES:
            raise FeedbackError("invalid vote")
        if vote == previous:
            raise FeedbackError("vote unchanged")
        return {**base, "kind": "vote", "vote": vote, "previous": previous}
    if kind == "reason":
        reason = str(payload.get("reason") or "").strip()
        if reason not in REASONS:
            raise FeedbackError("invalid reason")
        return {**base, "kind": "reason", "reason": reason}
    raise FeedbackError("invalid kind")


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield every well-formed record. A bad line is skipped, not fatal —
    one torn write must not hide the rest of the file from the editor."""
    try:
        fh = path.open("r", encoding="utf-8")
    except FileNotFoundError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                yield _upgrade(raw)


def _upgrade(raw: dict[str, Any]) -> dict[str, Any]:
    """Present a v1 record in the v2 shape so aggregation has one path."""
    if raw.get("v") == 2:
        return raw
    mapped = _LEGACY_SIGNALS.get(str(raw.get("signal") or ""))
    if mapped is None:
        return {}
    vote, reason = mapped
    out = {
        "v": 2, "id": raw.get("id", ""), "locale": raw.get("locale", ""),
        "timestamp": raw.get("timestamp", ""), "kind": "vote",
        "vote": vote, "previous": "none",
    }
    if reason:
        out["reason"] = reason
    return out


@dataclass
class PostFeedback:
    """Net feedback for one post in one locale."""

    id: str
    locale: str
    up: int = 0
    down: int = 0
    reasons: Counter[str] = field(default_factory=Counter)
    last_at: str = ""

    @property
    def total(self) -> int:
        return self.up + self.down

    @property
    def helpful_rate(self) -> float | None:
        return self.up / self.total if self.total else None


@dataclass
class FeedbackSummary:
    posts: list[PostFeedback]
    up: int
    down: int
    reasons: Counter[str]
    by_locale: dict[str, tuple[int, int]]
    recent_down: list[dict[str, Any]]
    votes_last_7d: int
    records: int

    @property
    def helpful_rate(self) -> float | None:
        total = self.up + self.down
        return self.up / total if total else None


def summarize(
    records: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    recent_limit: int = 20,
) -> FeedbackSummary:
    """Fold the change log into net counts per post.

    Each vote record subtracts its `previous` and adds its `vote`; counts are
    floored at zero so a forged `previous` cannot drive a post negative.
    """
    now = now or datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    posts: dict[tuple[str, str], PostFeedback] = {}
    reasons_total: Counter[str] = Counter()
    down_votes: list[dict[str, Any]] = []
    reason_recs: list[dict[str, Any]] = []
    votes_7d = 0
    n = 0

    def slot(rec: dict[str, Any]) -> PostFeedback:
        key = (str(rec.get("id", "")), str(rec.get("locale", "")))
        if key not in posts:
            posts[key] = PostFeedback(id=key[0], locale=key[1])
        return posts[key]

    for rec in records:
        if not rec or not rec.get("id"):
            continue
        n += 1
        entry = slot(rec)
        stamp = str(rec.get("timestamp") or "")
        entry.last_at = max(entry.last_at, stamp)
        kind = rec.get("kind")
        if kind == "vote":
            previous, vote = rec.get("previous"), rec.get("vote")
            if previous == "up":
                entry.up = max(0, entry.up - 1)
            elif previous == "down":
                entry.down = max(0, entry.down - 1)
            if vote == "up":
                entry.up += 1
            elif vote == "down":
                entry.down += 1
                down_votes.append(dict(rec))
            if _parse_ts(stamp) >= week_ago:
                votes_7d += 1
        reason = rec.get("reason")
        if reason in REASONS:
            entry.reasons[str(reason)] += 1
            reasons_total[str(reason)] += 1
            if kind == "reason":
                reason_recs.append(rec)

    rows = [p for p in posts.values() if p.total or p.reasons]
    # Worst first, because the editor opens this page to find what needs
    # fixing; ties broken by most recent activity. Two stable sorts, since
    # an ISO timestamp cannot be negated inside one key.
    rows.sort(key=lambda p: p.last_at, reverse=True)
    rows.sort(key=lambda p: (-p.down, p.up))

    # A 👎 and the reason that follows it arrive as two records — the vote is
    # sent the moment it is clicked so it counts even if the reader never
    # picks a reason. Pair them back up for the recent list, so the editor
    # sees "👎 too vague" once rather than a bare 👎 and a stray reason.
    _attach_reasons(down_votes, reason_recs)
    recent_down = down_votes
    by_locale: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    for p in rows:
        u, d = by_locale[p.locale]
        by_locale[p.locale] = (u + p.up, d + p.down)
    recent_down.sort(key=lambda r: str(r.get("timestamp", "")), reverse=True)
    return FeedbackSummary(
        posts=rows,
        up=sum(p.up for p in rows),
        down=sum(p.down for p in rows),
        reasons=reasons_total,
        by_locale=dict(by_locale),
        recent_down=recent_down[:recent_limit],
        votes_last_7d=votes_7d,
        records=n,
    )


_REASON_WINDOW = timedelta(minutes=30)


def _attach_reasons(
    down_votes: list[dict[str, Any]], reason_recs: list[dict[str, Any]],
) -> None:
    """Give each 👎 the first unclaimed reason for the same post and locale
    that arrived within `_REASON_WINDOW` after it. A v1 record already
    carries its reason and is left alone."""
    unclaimed = sorted(reason_recs, key=lambda r: str(r.get("timestamp", "")))
    for vote in sorted(down_votes, key=lambda r: str(r.get("timestamp", ""))):
        if vote.get("reason"):
            continue
        cast_at = _parse_ts(str(vote.get("timestamp", "")))
        for i, rec in enumerate(unclaimed):
            if (rec.get("id"), rec.get("locale")) != (vote.get("id"), vote.get("locale")):
                continue
            given_at = _parse_ts(str(rec.get("timestamp", "")))
            if cast_at <= given_at <= cast_at + _REASON_WINDOW:
                vote["reason"] = rec.get("reason")
                unclaimed.pop(i)
                break


def _parse_ts(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


__all__ = [
    "FeedbackError",
    "FeedbackSummary",
    "PostFeedback",
    "REASONS",
    "VOTES",
    "append_record",
    "parse_submission",
    "read_records",
    "summarize",
]
