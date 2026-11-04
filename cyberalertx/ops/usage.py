"""AI usage: a per-call ledger, and honest aggregation of it.

Before Phase 6 the only usage record was a set of cumulative counters
(`quality_metrics.json`: `anthropic_*` / `claude_cli_*` calls and tokens) —
totals since the file was created, with no dates. They are still shown as-is.

From Phase 6 every provider call also appends one line to
`data/ai_usage.jsonl`, written at the same point the counters are bumped:

    {"at", "provider", "model", "stage", "input_tokens", "output_tokens",
     "cache_read_tokens", "cache_write_tokens", "cost_usd", "cost_source"}

`stage` comes from a context variable set by the caller (fact_sheet,
relevance, brief…); calls made outside a marked stage say "unspecified".

Cost is never invented:

    measured   — none of our providers returns a billed amount today
    estimated  — `cost_source = "claude-cli"`: the CLI's own `total_cost_usd`
                 (for subscription logins this is a notional figure), or
                 `"operator-rates"`: tokens × rates the operator configured in
                 CYBERALERTX_AI_PRICES (JSON, USD per million tokens per model)
    unavailable — everything else; shown as such, never as $0.
"""
from __future__ import annotations

import contextlib
import contextvars
import fcntl
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping
from zoneinfo import ZoneInfo

from ..config import DATA_DIR

USAGE_PATH = DATA_DIR / "ai_usage.jsonl"
_STAGE: contextvars.ContextVar[str] = contextvars.ContextVar("cyberalertx_ai_stage", default="")
_MAX_LINES = 200_000


@contextlib.contextmanager
def stage(name: str) -> Iterator[None]:
    """Label every provider call made inside this block with `name`."""
    token = _STAGE.set(name)
    try:
        yield
    finally:
        _STAGE.reset(token)


def record_call(*, provider: str, model: str, input_tokens: int = 0, output_tokens: int = 0,
                cache_read_tokens: int = 0, cache_write_tokens: int = 0, cost_usd: Any = None,
                cost_source: str = "", path: Path | None = None, now: datetime | None = None) -> None:
    """Append one call. Best effort: usage accounting must never break a render."""
    try:
        cost = float(cost_usd) if cost_usd not in (None, "") else None
    except (TypeError, ValueError):
        cost = None
    row = {
        "at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "provider": provider, "model": model or "", "stage": _STAGE.get() or "unspecified",
        "input_tokens": int(input_tokens), "output_tokens": int(output_tokens),
        "cache_read_tokens": int(cache_read_tokens), "cache_write_tokens": int(cache_write_tokens),
        "cost_usd": cost, "cost_source": cost_source if cost is not None else "",
    }
    target = Path(path or USAGE_PATH)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, (json.dumps(row) + "\n").encode())
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    except OSError:
        pass


def load(path: Path | None = None) -> list[dict[str, Any]]:
    try:
        lines = Path(path or USAGE_PATH).read_text(encoding="utf-8").splitlines()[-_MAX_LINES:]
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("at"):
            rows.append(r)
    return rows


def operator_rates() -> dict[str, dict[str, float]]:
    """CYBERALERTX_AI_PRICES, e.g. {"claude-x": {"input": 3, "output": 15, "cache_read": 0.3,
    "cache_write": 3.75}} in USD per million tokens. Empty when unset or invalid."""
    raw = os.getenv("CYBERALERTX_AI_PRICES", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    out: dict[str, dict[str, float]] = {}
    if isinstance(data, dict):
        for model, rates in data.items():
            if isinstance(rates, dict):
                try:
                    out[str(model)] = {k: float(v) for k, v in rates.items()
                                       if k in ("input", "output", "cache_read", "cache_write")}
                except (TypeError, ValueError):
                    continue
    return out


@dataclass
class Bucket:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    estimated_usd: float = 0.0
    estimated_calls: int = 0          # calls whose cost is known (estimated)
    sources: set[str] = field(default_factory=set)

    @property
    def unavailable_calls(self) -> int:
        return self.calls - self.estimated_calls

    def add(self, r: Mapping[str, Any], rates: Mapping[str, Mapping[str, float]]) -> None:
        self.calls += 1
        for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
            setattr(self, k, getattr(self, k) + int(r.get(k) or 0))
        cost, source = r.get("cost_usd"), str(r.get("cost_source") or "")
        if cost is None and str(r.get("model", "")) in rates:
            rate = rates[str(r["model"])]
            cost = sum(int(r.get(f"{k}_tokens") or 0) * rate.get(k, 0.0) / 1_000_000
                       for k in ("input", "output", "cache_read", "cache_write"))
            source = "operator-rates"
        if cost is not None:
            self.estimated_usd += float(cost)
            self.estimated_calls += 1
            self.sources.add(source)


def aggregate(rows: list[dict[str, Any]], *, period: str = "day", tz: str = "Europe/Kyiv",
              rates: Mapping[str, Mapping[str, float]] | None = None) -> dict[str, dict[tuple[str, str, str], Bucket]]:
    """{period label: {(provider, model, stage): Bucket}} — newest period first."""
    rates = rates if rates is not None else operator_rates()
    zone = ZoneInfo(tz)
    out: dict[str, dict[tuple[str, str, str], Bucket]] = defaultdict(dict)
    for r in rows:
        try:
            at = datetime.fromisoformat(str(r["at"])).astimezone(zone)
        except (ValueError, KeyError):
            continue
        label = at.strftime("%Y-%m-%d" if period == "day" else "%Y-%m")
        key = (str(r.get("provider", "")), str(r.get("model", "")), str(r.get("stage", "")))
        out[label].setdefault(key, Bucket()).add(r, rates)
    return dict(sorted(out.items(), reverse=True))


__all__ = ["Bucket", "USAGE_PATH", "aggregate", "load", "operator_rates", "record_call", "stage"]
