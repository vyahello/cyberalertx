"""One shadow evaluation run: stories → scores → Top 10 / Trending / Breaking.

Reads the existing stores; writes ONLY under `data/intel/`:

    scores.json            story_key -> {current evaluation, history[]}
    editions/YYYY-MM-DD.json   one Daily Top 10 edition (kept; re-written only
                               while that edition is open and its picks change)
    breaking_state.json    story_key -> last alert's evidence fingerprint
    latest.json            the last run: picks, trending, breaking, failures,
                           relevance counts, comparison with current behaviour

Nothing here is wired to the public API, the feed or Telegram.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config import DATA_DIR
from ..models import NewsItem
from .config import IntelConfig, load_config
from .scoring import Evaluation, evaluate
from .selection import breaking, daily_top, trending
from .sources import SourceTable
from .story import StoryView, build_stories

logger = logging.getLogger(__name__)

INTEL_DIR = DATA_DIR / "intel"


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@dataclass
class RunResult:
    now: datetime
    stories: list[StoryView]
    evals: dict[str, Evaluation]
    recalculated: int
    edition: str
    picks: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    trending: list[dict[str, Any]]
    breaking: list[dict[str, Any]]
    failures: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        rel: dict[str, int] = {}
        for s in self.stories:
            rel[s.relevance] = rel.get(s.relevance, 0) + 1
        return {
            "evaluated_at": self.now.isoformat(), "stories": len(self.stories),
            "recalculated": self.recalculated, "relevance": rel, "edition": self.edition,
            "top": self.picks, "rejected": self.rejected[:50],
            "trending": [t for t in self.trending if t["trending"]],
            "breaking": self.breaking, "failures": self.failures,
        }


def _featured(intel_dir: Path) -> dict[str, set[str]]:
    """story_key -> member fingerprints at the time it was last featured."""
    out: dict[str, set[str]] = {}
    for f in sorted((intel_dir / "editions").glob("*.json")):
        for pick in _read(f, {}).get("picks", []):
            out[pick["story_key"]] = set(pick.get("members", []))
    return out


def run(
    items: Sequence[NewsItem],
    *,
    now: datetime | None = None,
    sheets: Any = None,
    posts: Any = None,
    intel_dir: Path = INTEL_DIR,
    cfg: IntelConfig | None = None,
    table: SourceTable | None = None,
    write: bool = True,
) -> RunResult:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cfg = cfg or load_config(intel_dir / "config.json")
    table = table or SourceTable.load(intel_dir / "sources.json")
    stories = build_stories(items, sheets=sheets, posts=posts)
    store: dict[str, Any] = _read(intel_dir / "scores.json", {})
    featured = _featured(intel_dir)
    evals: dict[str, Evaluation] = {}
    previous: dict[str, Evaluation] = {}
    failures: list[dict[str, Any]] = []
    recalculated = 0
    for s in stories:
        rec = store.get(s.key, {})
        prev = Evaluation.from_dict(rec["current"]) if rec.get("current") else None
        if prev is not None:
            previous[s.key] = prev
        was = s.key in featured
        new_ev = was and bool({m.fingerprint for m in s.members} - featured.get(s.key, set()))
        try:
            ev = evaluate(s, cfg, table, now, previous=prev, featured_before=was,
                          new_evidence_since_featured=new_ev)
        except Exception as exc:  # one bad story must not stop the run
            logger.exception("intel: evaluation failed for %s", s.key)
            failures.append({"story_key": s.key, "stage": "score", "error": f"{type(exc).__name__}: {exc}"})
            continue
        evals[s.key] = ev
        if ev is not prev:
            recalculated += 1
            history = ([prev.to_dict()] if prev else []) + rec.get("history", [])
            store[s.key] = {"current": ev.to_dict(), "history": history[: cfg.scoring.history_limit]}

    day, picks, rejected = daily_top(stories, evals, now, cfg)
    by_key = {s.key: s for s in stories}
    pick_dicts = [{**p.to_dict(), "members": sorted(m.fingerprint for m in by_key[p.story_key].members)}
                  for p in picks]
    trend = [t.to_dict() for t in trending(stories, evals, now, cfg, previous)]
    state: dict[str, Any] = _read(intel_dir / "breaking_state.json", {})
    brk = [b.to_dict() for b in breaking(stories, evals, table, cfg, now, state)]

    result = RunResult(now, stories, evals, recalculated, day.isoformat(), pick_dicts, rejected,
                       trend, brk, failures)
    if write:
        _write(intel_dir / "scores.json", store)
        _write(intel_dir / "breaking_state.json", state)
        edition_path = intel_dir / "editions" / f"{day.isoformat()}.json"
        old = _read(edition_path, {})
        if old.get("picks") != pick_dicts:
            # Recalculated while the edition is open (new evidence changed it);
            # earlier versions of this edition are kept in `revisions`.
            revisions = old.get("revisions", [])
            if old.get("picks"):
                revisions.append({"generated_at": old.get("generated_at"), "picks": old["picks"]})
            _write(edition_path, {"edition": day.isoformat(), "timezone": cfg.selection.timezone,
                                  "cutoff": cfg.selection.cutoff, "generated_at": now.isoformat(),
                                  "picks": pick_dicts, "revisions": revisions[-10:]})
        _write(intel_dir / "latest.json", result.summary())
    return result


def load_latest(intel_dir: Path = INTEL_DIR) -> Mapping[str, Any]:
    data = _read(intel_dir / "latest.json", {})
    return data if isinstance(data, dict) else {}


def load_scores(intel_dir: Path = INTEL_DIR) -> Mapping[str, Any]:
    data = _read(intel_dir / "scores.json", {})
    return data if isinstance(data, dict) else {}


__all__ = ["INTEL_DIR", "RunResult", "load_latest", "load_scores", "run"]
