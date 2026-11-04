"""System health from real checks and records.

States: healthy · warning · critical · unknown · not_configured.

* `not_configured` is not a failure — an optional provider (image
  generation, Threads, Postgres while JSON is authoritative) simply is not
  set up. It never raises the overall state.
* A stage with no record is `unknown`, never `healthy`.
* External probes (frontend HTTP, Postgres `SELECT 1`, `systemctl show`) are
  bounded by short timeouts and cached for `PROBE_TTL` seconds, so opening
  the page repeatedly costs nothing. Probes are injectable for tests.

Output never contains environment values, credentials, connection strings
or filesystem paths — only states, counts and timestamps.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from .readmodel import OpsSources, file_mtime, parse_ts, read_json, read_jsonl_tail

PROBE_TTL = 60.0
STARTED = datetime.now(timezone.utc)
UNITS = ("cyberalertx-api.service", "cyberalertx-frontend.service", "cyberalertx-run.service",
         "cyberalertx-generate.service", "cyberalertx-generate.timer",
         "cyberalertx-telegram.service", "cyberalertx-telegram.timer")
_RANK = {"healthy": 0, "unknown": 1, "warning": 2, "critical": 3}


@dataclass
class Check:
    group: str
    name: str
    status: str
    detail: str
    last: datetime | None = None
    href: str = ""


@dataclass
class Report:
    checks: list[Check]
    failures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def overall(self) -> str:
        ranked = [c.status for c in self.checks if c.status in _RANK]
        return max(ranked, key=lambda s: _RANK[s]) if ranked else "unknown"


_memo: dict[str, tuple[float, Any]] = {}
_memo_lock = threading.Lock()


def _cached(key: str, fn: Callable[[], Any]) -> Any:
    with _memo_lock:
        hit = _memo.get(key)
        if hit and time.monotonic() - hit[0] < PROBE_TTL:
            return hit[1]
    value = fn()
    with _memo_lock:
        _memo[key] = (time.monotonic(), value)
    return value


def clear_probe_cache() -> None:
    with _memo_lock:
        _memo.clear()


# ---------------------------------------------------------------- probes (injectable)

def probe_frontend() -> tuple[str, str]:
    url = os.getenv("CYBERALERTX_FRONTEND_PROBE_URL", "http://127.0.0.1:3000/en")
    if url.strip().lower() in ("", "off", "none"):
        return "not_configured", "probe disabled"
    import httpx
    try:
        r = httpx.get(url, timeout=2.5, follow_redirects=False)
    except httpx.HTTPError as exc:
        return "critical", f"no answer ({type(exc).__name__})"
    return ("healthy" if r.status_code == 200 else "critical"), f"HTTP {r.status_code}"


def probe_database() -> tuple[str, str]:
    backend = os.getenv("CYBERALERTX_STORAGE_BACKEND", "json").strip().lower()
    if backend != "dual":
        return "not_configured", "JSON storage is authoritative; Postgres mirror not enabled"
    try:
        from sqlalchemy import text

        from ..storage.pg.engine import get_engine
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:                              # noqa: BLE001 - never leak the URL
        return "critical", f"Postgres mirror unreachable ({type(exc).__name__})"
    return "healthy", "Postgres mirror answers"


def probe_units() -> dict[str, dict[str, str]]:
    """`systemctl show` for our units; {} when systemd is not reachable."""
    try:
        out = subprocess.run(
            ["systemctl", "show", *UNITS, "-p",
             "Id,ActiveState,SubState,Result,ExecMainExitTimestamp,LastTriggerUSec,NextElapseUSecRealtime"],
            capture_output=True, text=True, timeout=3, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    units: dict[str, dict[str, str]] = {}
    for block in out.strip().split("\n\n"):
        props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if props.get("Id"):
            units[props["Id"]] = props
    return units


# ---------------------------------------------------------------- report

def system_report(src: OpsSources, jobs: Sequence[Any], *, now: datetime, health: Mapping[str, Any],
                  metrics: Mapping[str, Any], threads_settings: Any, threads_accounts: Mapping[str, Any],
                  telegram: Any, intel_ok: bool,
                  frontend: Callable[[], tuple[str, str]] | None = None,
                  database: Callable[[], tuple[str, str]] | None = None,
                  units: Callable[[], dict[str, dict[str, str]]] | None = None) -> Report:
    checks: list[Check] = []
    add = checks.append

    # -- platform --------------------------------------------------------------
    up = now - STARTED
    add(Check("Platform", "API backend", "healthy", f"serving this page · up {int(up.total_seconds() // 3600)} h"))
    fs, fd = _cached("frontend", frontend or probe_frontend)
    add(Check("Platform", "Website (Next.js)", fs, fd))
    ds, dd = _cached("database", database or probe_database)
    add(Check("Platform", "Database", ds, dd))
    try:
        usage = shutil.disk_usage(src.data_dir)
        free = usage.free / usage.total
        writable = os.access(src.data_dir, os.W_OK)
        st = "critical" if not writable or free < 0.05 else "warning" if free < 0.15 else "healthy"
        add(Check("Platform", "Data storage", st,
                  f"{'writable' if writable else 'NOT writable'} · {free:.0%} disk free"))
    except OSError as exc:
        add(Check("Platform", "Data storage", "critical", f"unavailable ({type(exc).__name__})"))

    # -- scheduled work (systemd) ------------------------------------------------
    u = _cached("units", units or probe_units)
    if not u:
        add(Check("Schedules", "systemd units", "unknown", "systemd state not readable from the API process"))
    for unit in UNITS:
        props = u.get(unit)
        if not u:
            break
        if props is None or props.get("LoadState") == "not-found":
            continue
        active, result = props.get("ActiveState", ""), props.get("Result", "")
        if unit.endswith(".timer"):
            st = "healthy" if active == "active" else "critical"
            detail = f"{active} · next {props.get('NextElapseUSecRealtime', '') or '—'}"
        elif unit in ("cyberalertx-generate.service", "cyberalertx-telegram.service"):
            st = "healthy" if result in ("success", "") else "warning"
            detail = (f"last run {result or 'n/a'} · finished {props.get('ExecMainExitTimestamp', '') or '—'}")
        else:
            st = "healthy" if active == "active" else "critical"
            detail = f"{active}/{props.get('SubState', '')}"
        add(Check("Schedules", unit, st, detail))

    # -- pipeline records --------------------------------------------------------
    from ..api.admin.pages import classify_sources
    rows, stopped = classify_sources(health, now)
    failing = [r.name for r in rows if r.status == "failing"]
    last_cycle = parse_ts(health.get("last_cycle_utc"))
    add(Check("Pipeline", "Ingestion", "unknown" if last_cycle is None else "critical" if stopped else
              "warning" if failing else "healthy",
              (f"{len(failing)} source(s) failing: {', '.join(failing[:3])}" if failing else
               f"{len(rows)} sources fetching") + (" · ingest stopped" if stopped else ""), last_cycle, "/admin/sources"))
    gen_last = file_mtime(src.data_dir / "threat_posts.json")
    errs = int((metrics.get("counters") or {}).get("ai_provider_errors") or 0)
    gen_status = ("unknown" if gen_last is None else "critical" if now - gen_last > timedelta(hours=12)
                  else "warning" if now - gen_last > timedelta(hours=3) else "healthy")
    add(Check("Pipeline", "Editorial generation", gen_status,
              f"last brief cache write · {errs} provider errors since metrics start", gen_last, "/admin/review"))
    add(Check("Pipeline", "Intelligence Core", "healthy" if intel_ok else "critical",
              "live view computed" if intel_ok else "could not compute the story view", None, "/admin/intel"))

    # -- publication -------------------------------------------------------------
    abandoned = [j for j in jobs if j.status == "processing" and (t := parse_ts(j.lease_until)) and t < now]
    unknown = [j for j in jobs if j.status == "outcome_unknown"]
    failed = [j for j in jobs if j.status == "failed"]
    if not jobs:
        add(Check("Publication", "Publication worker", "not_configured",
                  "job worker not switched on; the legacy Telegram publisher runs from its timer"))
    else:
        st = "critical" if unknown or abandoned else "warning" if failed else "healthy"
        add(Check("Publication", "Publication worker", st,
                  f"{len(unknown)} unknown outcome · {len(abandoned)} abandoned · {len(failed)} failed",
                  max((t for j in jobs if (t := parse_ts(j.updated_at))), default=None), "/admin/publishing"))
    ledger = read_jsonl_tail(src.ledger_path, 1)
    add(Check("Publication", "Telegram", "healthy" if telegram and telegram.enabled else "not_configured",
              ("bot token and channel(s) configured" if telegram and telegram.enabled else "not configured")
              + (f" · photos {'on' if telegram and telegram.attach_images else 'off'}"),
              parse_ts(ledger[-1].get("timestamp")) if ledger else None))
    for slot, acc in sorted(threads_accounts.items()):
        enabled = bool(threads_settings and threads_settings.publish_enabled)
        status = getattr(acc, "status", "disconnected")
        st = ("healthy" if status == "connected" else
              ("critical" if enabled else "warning") if status == "needs_reconnect" else "not_configured")
        exp = parse_ts(getattr(acc, "expires_at", ""))
        if st == "healthy" and exp and exp - now < timedelta(days=7):
            st = "warning"
        add(Check("Publication", f"Threads {slot.upper()}", st,
                  f"{status}{' @' + acc.username if getattr(acc, 'username', '') else ''} · publishing "
                  f"{'enabled' if enabled else 'off'}" + (f" · token expires {exp:%Y-%m-%d}" if exp else ""),
                  parse_ts(getattr(acc, "last_verified_at", "")), "/admin/threads"))

    # -- media -------------------------------------------------------------------
    provider = (os.getenv("CYBERALERTX_IMAGE_PROVIDER") or "none").strip().lower()
    assets = read_json(src.media_dir / "assets.json", {})
    mfail = sum(1 for a in (assets.values() if isinstance(assets, dict) else []) if a.get("status") == "failed")
    add(Check("Media", "Branded cards", "healthy" if assets else "unknown",
              f"{sum(1 for a in assets.values() if a.get('asset_type') == 'branded_card')} recorded"
              if isinstance(assets, dict) and assets else "no media run recorded", None, "/admin/media"))
    add(Check("Media", "Image provider", "not_configured" if provider == "none" else "warning" if mfail else "healthy",
              "not configured — branded cards only (by design)" if provider == "none"
              else f"{provider} · {mfail} failed", None, "/admin/media"))

    # -- recorded failures ----------------------------------------------------------
    failures: list[dict[str, Any]] = []
    for j in failed + unknown:
        failures.append({"at": j.updated_at, "where": f"publication {j.destination}", "what": j.job_id,
                         "error": f"{j.error_category}: {j.last_error}", "persistent": j.status == "failed"})
    for a in (assets.values() if isinstance(assets, dict) else []):
        if a.get("status") == "failed":
            failures.append({"at": a.get("updated_at"), "where": "media", "what": a.get("story_key"),
                             "error": a.get("last_error", ""), "persistent": int(a.get("attempts") or 0) >= 3})
    for f in read_json(src.data_dir / "intel" / "latest.json", {}).get("failures", []) or []:
        failures.append({"at": read_json(src.data_dir / "intel" / "latest.json", {}).get("evaluated_at"),
                         "where": f"intel {f.get('stage')}", "what": f.get("story_key"), "error": f.get("error"),
                         "persistent": False})
    for slot, acc in threads_accounts.items():
        if getattr(acc, "last_error", ""):
            failures.append({"at": getattr(acc, "last_verified_at", "") or getattr(acc, "connected_at", ""),
                             "where": f"threads {slot}", "what": slot, "error": acc.last_error,
                             "persistent": getattr(acc, "status", "") == "needs_reconnect"})
    failures.sort(key=lambda f: str(f.get("at") or ""), reverse=True)
    return Report(checks, failures[:50])


__all__ = ["Check", "PROBE_TTL", "Report", "UNITS", "clear_probe_cache", "probe_database", "probe_frontend",
           "probe_units", "system_report"]
