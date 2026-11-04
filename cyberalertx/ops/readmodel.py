"""Read-only views for the admin control room, over the stores that exist.

Rules this module keeps:

* **Articles are not stories.** A NewsItem is one source article; a story is
  the Intelligence Core cluster (`StoryView`). Every count says which it is.
* **Days are Kyiv editorial days** (Europe/Kyiv, the edition timezone),
  stated on screen; stored timestamps stay UTC.
* **No synthetic data.** A stage with no execution record is `unknown`, not
  healthy; an event is listed only if something recorded it with a time.
* **Bounded and cached.** The Intelligence Core view is computed with
  `write=False` (the shadow state is untouched) and memoised for
  `INTEL_TTL` seconds or until the stores change; nothing here calls an AI
  provider or the network.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..config import DATA_DIR

KYIV = ZoneInfo("Europe/Kyiv")
INTEL_TTL = 600.0
PAGE_SIZE = 50
DESTINATIONS = (("website", "en"), ("website", "ua"), ("telegram", "en"), ("telegram", "ua"),
                ("threads@en", "en"), ("threads@ua", "ua"))
DEST_LABEL = {"website": "Website", "telegram": "Telegram", "threads@en": "Threads", "threads@ua": "Threads"}


def kyiv_day(now: datetime, day: date | None = None) -> tuple[datetime, datetime, date]:
    d = day or now.astimezone(KYIV).date()
    start = datetime.combine(d, dtime(0, 0), tzinfo=KYIV)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc), d


def parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def file_sig(path: Path) -> tuple[int, int, int]:
    try:
        st = path.stat()
        return (st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0, -1)


def file_mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def read_jsonl_tail(path: Path, limit: int = 5000) -> list[dict[str, Any]]:
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            fh.seek(max(0, size - 4 * 1024 * 1024))
            lines = fh.read().decode("utf-8", "replace").splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


# ---------------------------------------------------------------- context

@dataclass
class OpsSources:
    """Where the read models look. The app builds one per request from the
    live services; tests build one over a tmp directory."""
    items: Callable[[], list[Any]]
    posts: Callable[[], list[Any]]                 # every cached ThreatPost
    post_cache: Any = None                         # ThreatPostCache-like (for the intel view)
    data_dir: Path = DATA_DIR

    @property
    def jobs_path(self) -> Path:
        return self.data_dir / "publish_jobs.json"

    @property
    def ledger_path(self) -> Path:
        return self.data_dir / "telegram_published.jsonl"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def intel_dir(self) -> Path:
        return self.data_dir / "intel"


_intel_lock = threading.Lock()
_intel_memo: dict[str, Any] = {}


def intel_view(src: OpsSources, now: datetime) -> Any:
    """Intelligence Core RunResult (write=False), memoised.

    Recomputed when the article store, post cache or fact sheets change, or
    after INTEL_TTL seconds. Returns None if the Core cannot run."""
    items = src.items()
    sig = (len(items), max((i.fetched_at.isoformat() for i in items), default=""),
           file_sig(src.data_dir / "threat_posts.json"), file_sig(src.data_dir / "fact_sheets.json"),
           str(src.data_dir))
    with _intel_lock:
        hit = _intel_memo.get("v")
        if hit and hit[0] == sig and time.monotonic() - hit[1] < INTEL_TTL:
            return hit[2]
    try:
        from ..ai.fact_sheet import FactSheetCache
        from ..intel.engine import run as intel_run
        sp = src.data_dir / "fact_sheets.json"
        res = intel_run(items, now=now, sheets=FactSheetCache(sp) if sp.exists() else None,
                        posts=src.post_cache, write=False, intel_dir=src.intel_dir)
    except Exception:                                  # noqa: BLE001 - the page shows "unavailable"
        res = None
    with _intel_lock:
        _intel_memo["v"] = (sig, time.monotonic(), res)
    return res


def clear_cache() -> None:
    with _intel_lock:
        _intel_memo.clear()


def load_jobs(src: OpsSources) -> list[Any]:
    from ..publish.jobs import JobStore
    if not src.jobs_path.exists():
        return []
    try:
        return JobStore(src.jobs_path).all()
    except RuntimeError:
        return []


# ---------------------------------------------------------------- stories

@dataclass
class StoryRow:
    key: str
    title: str
    anchor: str
    articles: int
    sources: list[str]
    relevance: str
    score: float | None
    confidence: str
    verification: str
    exploitation: str
    category: str
    top_rank: int | None
    trending: bool
    breaking: bool
    fact_sheet: bool
    editions: dict[str, str]          # locale -> review status / "missing"
    first_seen: datetime | None
    latest: datetime | None


def story_rows(res: Any) -> list[StoryRow]:
    if res is None:
        return []
    top = {p["story_key"]: int(p["rank"]) for p in res.picks}
    trend = {t["story_key"] for t in res.trending if t.get("trending")}
    brk = {b["story_key"] for b in res.breaking}
    rows = []
    for s in res.stories:
        ev = res.evals.get(s.key)
        en = s.posts.get("en")
        title = (getattr(en, "title", "") or getattr(s.posts.get("ua"), "title", "") or s.anchor.title)
        evidence = getattr(s, "evidence", None)
        category = str(getattr(evidence, "event_type", "") or "") if evidence is not None else ""
        if not category or category == "other":
            category = str(s.anchor.category or "other")
        rows.append(StoryRow(
            key=s.key, title=title, anchor=s.anchor.fingerprint, articles=len(s.members),
            sources=list(s.independent_sources), relevance=s.relevance,
            score=round(ev.score, 1) if ev else None,
            confidence=ev.dim("confidence") if ev else "", verification=ev.dim("verification_status") if ev else "",
            exploitation=ev.dim("exploitation_status") if ev else "", category=category,
            top_rank=top.get(s.key), trending=s.key in trend, breaking=s.key in brk, fact_sheet=bool(s.sheets),
            editions={loc: (getattr(s.posts.get(loc), "review_status", "") or "auto") if s.posts.get(loc) else "missing"
                      for loc in ("en", "ua")},
            first_seen=min((m.fetched_at for m in s.members), default=None),
            latest=max((m.published_at for m in s.members), default=None),
        ))
    return rows


@dataclass
class StoryQuery:
    q: str = ""
    min_score: float | None = None
    confidence: str = ""
    verification: str = ""
    exploitation: str = ""
    category: str = ""
    relevance: str = ""
    editorial: str = ""            # pending | approved | rejected | auto | missing
    flag: str = ""                 # top | trending | breaking | low_confidence
    since: date | None = None
    until: date | None = None
    sort: str = "score"            # score | latest | articles
    page: int = 1

    @classmethod
    def from_params(cls, p: Mapping[str, str]) -> "StoryQuery":
        def num(v: str) -> float | None:
            try:
                return float(v) if v.strip() else None
            except ValueError:
                return None

        def day(v: str) -> date | None:
            try:
                return date.fromisoformat(v) if v.strip() else None
            except ValueError:
                return None

        def word(v: str, allowed: Iterable[str]) -> str:
            v = (v or "").strip().lower()
            return v if v in allowed else ""
        try:
            page = max(1, min(10_000, int(p.get("page", "1") or 1)))
        except ValueError:
            page = 1
        return cls(
            q=(p.get("q") or "").strip()[:120], min_score=num(p.get("min_score", "")),
            confidence=word(p.get("confidence", ""), ("high", "medium", "low")),
            verification=word(p.get("verification", ""), ("verified", "partially_verified", "unverified")),
            exploitation=word(p.get("exploitation", ""), ("confirmed", "reported", "poc_available", "unknown")),
            category=(p.get("category") or "").strip()[:40],
            relevance=word(p.get("relevance", ""), ("in_scope", "borderline", "out_of_scope")),
            editorial=word(p.get("editorial", ""), ("pending", "approved", "rejected", "auto", "missing")),
            flag=word(p.get("flag", ""), ("top", "trending", "breaking", "low_confidence")),
            since=day(p.get("since", "")), until=day(p.get("until", "")),
            sort=word(p.get("sort", ""), ("score", "latest", "articles")) or "score", page=page,
        )


def filter_stories(rows: Sequence[StoryRow], q: StoryQuery) -> tuple[list[StoryRow], int]:
    """(this page, total matching). Server-side filtering and pagination."""
    needle = q.q.lower()
    out = []
    for r in rows:
        if needle and needle not in r.title.lower() and needle not in r.key.lower() and needle != r.anchor:
            continue
        if q.min_score is not None and (r.score is None or r.score < q.min_score):
            continue
        if q.confidence and r.confidence != q.confidence:
            continue
        if q.verification and r.verification != q.verification:
            continue
        if q.exploitation and r.exploitation != q.exploitation:
            continue
        if q.category and r.category != q.category:
            continue
        if q.relevance and r.relevance != q.relevance:
            continue
        if q.editorial and q.editorial not in r.editions.values():
            continue
        if q.flag == "top" and r.top_rank is None or q.flag == "trending" and not r.trending \
                or q.flag == "breaking" and not r.breaking or q.flag == "low_confidence" and r.confidence != "low":
            continue
        local = r.latest.astimezone(KYIV).date() if r.latest else None
        if q.since and (local is None or local < q.since) or q.until and (local is None or local > q.until):
            continue
        out.append(r)
    key: Callable[[StoryRow], Any] = {
        "score": lambda r: (r.score if r.score is not None else -1, r.latest or datetime.min.replace(tzinfo=timezone.utc)),
        "latest": lambda r: r.latest or datetime.min.replace(tzinfo=timezone.utc),
        "articles": lambda r: (r.articles, r.score or 0),
    }[q.sort]
    out.sort(key=key, reverse=True)
    start = (q.page - 1) * PAGE_SIZE
    return out[start:start + PAGE_SIZE], len(out)


def story_detail(res: Any, key: str) -> dict[str, Any] | None:
    """Everything the Core knows about one story, keeping confirmed facts,
    reported claims, contradictions and open questions apart."""
    if res is None:
        return None
    s = next((x for x in res.stories if x.key == key), None)
    if s is None:
        return None
    ev = res.evals.get(s.key)
    evidence = getattr(s, "evidence", None)
    facts = list(getattr(evidence, "facts", []) or [])
    sheets = list(s.sheets or [])
    identifiers: dict[str, set[str]] = {"cve": set(), "product": set(), "actor": set(), "malware": set()}
    claims: list[dict[str, str]] = []
    unknowns: list[str] = []
    for sh in sheets:
        identifiers["cve"].update(sh.cve_ids)
        identifiers["product"].update(f"{p.vendor} {p.product}".strip() for p in sh.affected_products)
        identifiers["actor"].update(sh.threat_actors)
        identifiers["malware"].update(sh.malware_families)
        claims.extend({"statement": c.statement, "attribution": c.attribution, "status": c.status} for c in sh.claims)
        unknowns.extend(sh.open_questions)
    return {
        "story": s, "evaluation": ev,
        "top": next((p for p in res.picks if p["story_key"] == key), None),
        "trending": next((t for t in res.trending if t["story_key"] == key and t.get("trending")), None),
        "breaking": next((b for b in res.breaking if b["story_key"] == key), None),
        "confirmed": [f for f in facts if getattr(f, "status", "") == "confirmed"],
        "reported": [f for f in facts if getattr(f, "status", "") != "confirmed"],
        "claims": claims,
        "contradictions": list(getattr(evidence, "contradictions", []) or []),
        "unknowns": sorted(set(unknowns)),
        "identifiers": {k: sorted(v) for k, v in identifiers.items() if v},
        "has_evidence": evidence is not None, "sheets": len(sheets),
    }


# ---------------------------------------------------------------- overview

def overview_metrics(src: OpsSources, res: Any, jobs: Sequence[Any], now: datetime) -> dict[str, Any]:
    start, end, day = kyiv_day(now)
    items = src.items()
    today = [i for i in items if start <= i.fetched_at < end]
    rows = story_rows(res)
    stories_today = [r for r in rows if r.first_seen and start <= r.first_seen < end]
    posts = src.posts()
    pending = [p for p in posts if (p.review_status or "auto") == "pending"]
    ledger = [r for r in read_jsonl_tail(src.ledger_path) if (t := parse_ts(r.get("timestamp"))) and start <= t < end]
    pub_today = [j for j in jobs if j.status == "published" and (t := parse_ts(j.completed_at)) and start <= t < end
                 and "imported" not in " ".join(h.get("event", "") for h in j.history)]
    latest = read_json(src.intel_dir / "latest.json", {})
    return {
        "day": day, "articles_today": len(today), "stories_today": len(stories_today),
        "in_scope_today": sum(1 for r in stories_today if r.relevance != "out_of_scope"),
        "stories_total": len(rows),
        "pending_editions": len(pending), "pending_stories": len({p.source_fingerprint for p in pending}),
        "telegram_sent_today": len(ledger), "jobs_published_today": len(pub_today),
        "jobs": {s: sum(1 for j in jobs if j.status == s) for s in
                 ("scheduled", "retrying", "processing", "failed", "outcome_unknown", "published", "cancelled")},
        "jobs_active": bool(jobs),
        "top10": len(res.picks) if res else None, "breaking": len(res.breaking) if res else None,
        "trending": sum(1 for t in res.trending if t.get("trending")) if res else None,
        "edition": getattr(res, "edition", "") if res else "",
        "shadow_evaluated_at": latest.get("evaluated_at", ""),
    }


# ---------------------------------------------------------------- pipeline

@dataclass
class Stage:
    name: str
    status: str                       # healthy | warning | critical | unknown | not_configured | manual
    last: datetime | None
    last_label: str
    counts: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""
    href: str = ""


def _age_status(last: datetime | None, now: datetime, warn: timedelta, crit: timedelta) -> str:
    if last is None:
        return "unknown"
    age = now - last
    return "healthy" if age <= warn else "warning" if age <= crit else "critical"


def pipeline(src: OpsSources, res: Any, jobs: Sequence[Any], now: datetime, *,
             health: Mapping[str, Any], metrics: Mapping[str, Any]) -> list[Stage]:
    from ..pipeline.relevance import effective_relevance
    counters = metrics.get("counters") or {}
    items = src.items()
    stages: list[Stage] = []

    last_cycle = parse_ts(health.get("last_cycle_utc"))
    srcs = health.get("sources") or {}
    stale = [n for n, h in srcs.items() if (t := parse_ts(h.get("last_successful_ingest_utc"))) is None
             or now - t > timedelta(hours=6)]
    st = _age_status(last_cycle, now, timedelta(minutes=45), timedelta(hours=3))
    if st == "healthy" and stale:
        st = "warning"
    stages.append(Stage("Incoming sources", st, last_cycle, "last fetch cycle",
                        [("sources", str(len(srcs))), ("no items > 6 h", str(len(stale)))],
                        href="/admin/sources"))

    newest = max((i.fetched_at for i in items), default=None)
    dups = sum(1 for i in items if getattr(i, "duplicate_of", ""))
    stages.append(Stage("Normalization & dedup", _age_status(newest, now, timedelta(hours=2), timedelta(hours=12)),
                        newest, "newest article stored",
                        [("articles stored", str(len(items))), ("later coverage", str(dups))]))

    cl = read_json(src.data_dir / "stories" / "cluster_report.json", {})
    rows = story_rows(res)
    multi = sum(1 for r in rows if r.articles > 1)
    low = len(cl.get("low_confidence_links") or [])
    stages.append(Stage("Story clustering", "healthy" if res is not None else "unknown",
                        parse_ts(cl.get("generated_at")), "last cluster audit",
                        [("stories", str(len(rows))), ("multi-article", str(multi)),
                         ("low-confidence links (audit)", str(low))],
                        note="clustering runs at ingest; the audit is manual", href="/admin/stories"))

    rel: dict[str, int] = {}
    for i in items:
        r = effective_relevance(i)
        rel[r] = rel.get(r, 0) + 1
    rr = read_json(src.data_dir / "stories" / "relevance_report.json", {})
    stages.append(Stage("Relevance", "warning" if int(counters.get("relevance_ai_errors") or 0) else "healthy",
                        parse_ts(rr.get("generated_at")), "last relevance audit",
                        [(k.replace("_", " "), str(v)) for k, v in sorted(rel.items())],
                        note="rules at ingest; counters since metrics start"))

    sheets_path = src.data_dir / "fact_sheets.json"
    extracted, failed = int(counters.get("fact_sheet_extracted") or 0), int(counters.get("fact_sheet_failures") or 0)
    if not sheets_path.exists():
        stages.append(Stage("Fact sheets", "not_configured", None, "no fact sheet store",
                            [("extracted (counter)", str(extracted)), ("failed", str(failed))],
                            note="no data/fact_sheets.json on this host"))
    else:
        rate_bad = failed and failed > extracted
        stages.append(Stage("Fact sheets", "warning" if rate_bad else "healthy", file_mtime(sheets_path),
                            "last fact sheet write", [("extracted", str(extracted)), ("failed", str(failed))]))

    latest = read_json(src.intel_dir / "latest.json", {})
    ev_at = parse_ts(latest.get("evaluated_at"))
    fails = len(latest.get("failures") or [])
    stages.append(Stage("Intelligence scoring", "critical" if res is None else "warning" if fails else "healthy",
                        ev_at, "last shadow evaluation (manual)",
                        [("stories scored now", str(len(res.evals)) if res else "—"),
                         ("failures (last shadow run)", str(fails))],
                        note="live view recomputed here; shadow run is `tools.intel evaluate`", href="/admin/intel"))

    posts_path = src.data_dir / "threat_posts.json"
    att, ok = int(counters.get("ai_renders_attempted") or 0), int(counters.get("ai_renders_success") or 0)
    errs = int(counters.get("ai_provider_errors") or 0)
    gen_last = file_mtime(posts_path)
    stages.append(Stage("Editorial generation", _age_status(gen_last, now, timedelta(hours=3), timedelta(hours=12)),
                        gen_last, "last brief cache write",
                        [("editions cached", str(len(src.posts()))),
                         ("AI accepted", f"{ok}/{att}" if att else "—"), ("provider errors", str(errs))],
                        note="counters since " + str(metrics.get("first_seen_utc") or "—")[:10], href="/admin/review"))

    assets = read_json(src.media_dir / "assets.json", {})
    statuses: dict[str, int] = {}
    for a in assets.values() if isinstance(assets, dict) else []:
        k = f"{a.get('asset_type', '')}:{a.get('status', '')}"
        statuses[k] = statuses.get(k, 0) + 1
    mfail = sum(v for k, v in statuses.items() if k.endswith(":failed"))
    stages.append(Stage("Media", "unknown" if not assets else "warning" if mfail else "healthy",
                        file_mtime(src.media_dir / "assets.json"), "last media run",
                        [("cards", str(statuses.get("branded_card:generated", 0))),
                         ("illustrations", str(sum(v for k, v in statuses.items()
                                                   if k.startswith("editorial_illustration") and k.endswith(("validated", "published"))))),
                         ("failed", str(mfail))],
                        note="cards render on request; run = `tools.media run`", href="/admin/media"))

    ledger = read_jsonl_tail(src.ledger_path, 1)
    tg_last = parse_ts(ledger[-1].get("timestamp")) if ledger else None
    bad = sum(1 for j in jobs if j.status in ("failed", "outcome_unknown"))
    job_last = max((t for j in jobs if (t := parse_ts(j.updated_at))), default=None)
    last = max((t for t in (tg_last, job_last) if t), default=None)
    status = ("critical" if any(j.status == "outcome_unknown" for j in jobs) else "warning" if bad
              else "healthy" if last else "unknown")
    stages.append(Stage("Publication", status, last, "last delivery record",
                        [("jobs", str(len(jobs)) if jobs else "worker not active"), ("failed / unknown", str(bad)),
                         ("Telegram ledger", "present" if ledger else "none")], href="/admin/publishing"))
    return stages


# ---------------------------------------------------------------- destinations

@dataclass
class Destination:
    key: str
    locale: str
    label: str
    counts: dict[str, int]
    configured: str                   # human-readable configuration state
    configured_tone: str
    connected: str = ""               # Threads: account state, separate from publishing
    last_published: datetime | None = None
    extra: str = ""


def destinations(src: OpsSources, jobs: Sequence[Any], *, telegram: Any, threads_settings: Any,
                 threads_accounts: Mapping[str, Any]) -> list[Destination]:
    ledger = read_jsonl_tail(src.ledger_path)
    out = []
    for dest, loc in DESTINATIONS:
        mine = [j for j in jobs if j.destination == dest and j.locale == loc]
        counts: dict[str, int] = {}
        for j in mine:
            counts[j.status] = counts.get(j.status, 0) + 1
        last = max((t for j in mine if j.status == "published" and (t := parse_ts(j.completed_at))), default=None)
        label = f"{DEST_LABEL[dest]} {loc.upper()}"
        if dest == "website":
            d = Destination(dest, loc, label, counts, "always on (read model)", "ok", last_published=last)
        elif dest == "telegram":
            chat = telegram.chat_id_for(loc) if telegram else None
            sent = [r for r in ledger if r.get("locale") == loc]
            tl = parse_ts(sent[-1].get("timestamp")) if sent else None
            d = Destination(dest, loc, label, counts,
                            ("channel configured" if chat else "no channel configured"), "ok" if chat else "neutral",
                            last_published=max((t for t in (last, tl) if t), default=None),
                            extra=f"{len(sent)} sends in the legacy ledger tail"
                            + (" · photos on" if telegram and telegram.attach_images else " · photos off"))
        else:
            slot = dest.split("@", 1)[1]
            acc = threads_accounts.get(slot)
            enabled = bool(threads_settings and threads_settings.publish_enabled)
            status = getattr(acc, "status", "disconnected") if acc else "not mapped"
            d = Destination(dest, loc, label, counts,
                            "publishing enabled" if enabled else "publishing off", "warn" if enabled else "neutral",
                            connected=(f"{status}" + (f" @{acc.username}" if acc and acc.username else "")),
                            last_published=last)
        out.append(d)
    return out


# ---------------------------------------------------------------- activity

@dataclass
class Event:
    at: datetime
    kind: str
    tone: str
    text: str
    href: str = ""


def activity(src: OpsSources, jobs: Sequence[Any], *, audit: Sequence[Mapping[str, Any]], res: Any,
             now: datetime, limit: int = 40) -> list[Event]:
    """Only events that were recorded with their own timestamp."""
    ev: list[Event] = []
    for a in audit[:200]:
        if (t := parse_ts(a.get("at"))):
            ev.append(Event(t, "admin", "bad" if a.get("result") not in ("ok", "success") else "accent",
                            f"{a.get('actor', 'admin')} · {a.get('action')} {a.get('target')} → {a.get('result')}"))
    for j in jobs:
        for h in j.history[-5:]:
            e = str(h.get("event", ""))
            if e in ("published", "failed", "outcome_unknown", "retrying", "cancelled", "recovered") and (t := parse_ts(h.get("at"))):
                tone = {"published": "ok", "failed": "bad", "outcome_unknown": "bad", "retrying": "warn"}.get(e, "neutral")
                ev.append(Event(t, "publication", tone, f"{j.destination} {j.locale.upper()} {e}: {j.story_key}",
                                f"/admin/publishing?q={j.job_id}"))
    for rec in read_jsonl_tail(src.ledger_path, 200):
        if (t := parse_ts(rec.get("timestamp"))):
            ev.append(Event(t, "telegram", "ok", f"Telegram {str(rec.get('locale', '')).upper()} message sent "
                                                f"({rec.get('fingerprint', '')})",
                            f"/admin/stories?q={rec.get('fingerprint', '')}"))
    for p in src.posts():
        if p.reviewed_at and (t := parse_ts(p.reviewed_at)):
            ev.append(Event(t, "review", "ok" if p.review_status == "approved" else "bad",
                            f"{p.review_status} {p.source_fingerprint}:{p.language} by {p.reviewed_by or 'editor'}",
                            "/admin/review?status=" + (p.review_status or "pending")))
    assets = read_json(src.media_dir / "assets.json", {})
    for a in (assets.values() if isinstance(assets, dict) else []):
        if a.get("asset_type") == "editorial_illustration" and (t := parse_ts(a.get("updated_at"))):
            ev.append(Event(t, "media", "bad" if a.get("status") == "failed" else "ok",
                            f"illustration {a.get('status')} for {a.get('story_key')}", "/admin/media"))
    for row in story_rows(res):
        if row.first_seen and now - row.first_seen < timedelta(days=2):
            ev.append(Event(row.first_seen, "story", "neutral", f"new story: {row.title}",
                            f"/admin/stories/{row.key}"))
    ev.sort(key=lambda e: e.at, reverse=True)
    return ev[:limit]


# ---------------------------------------------------------------- search

def search(q: str, res: Any, jobs: Sequence[Any]) -> dict[str, list[Any]]:
    q = (q or "").strip()
    if not q:
        return {"stories": [], "jobs": []}
    rows = story_rows(res)
    ql = q.lower()
    stories = [r for r in rows if ql in r.key.lower() or ql == r.anchor or ql in r.title.lower()
               or (res and any(m.fingerprint == q for s in res.stories if s.key == r.key for m in s.members))][:25]
    found_jobs = [j for j in jobs if ql in j.job_id.lower() or q == j.fingerprint or q in j.members
                  or ql == j.external_id.lower()][:25]
    return {"stories": stories, "jobs": found_jobs}


__all__ = ["DESTINATIONS", "Destination", "Event", "OpsSources", "PAGE_SIZE", "Stage", "StoryQuery", "StoryRow",
           "activity", "clear_cache", "destinations", "filter_stories", "intel_view", "kyiv_day", "load_jobs",
           "overview_metrics", "parse_ts", "pipeline", "read_json", "read_jsonl_tail", "search", "story_detail",
           "story_rows"]
