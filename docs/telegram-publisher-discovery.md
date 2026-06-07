# Telegram Publisher — Discovery Report

**Status:** discovery only. No implementation code written. This documents
the codebase as it exists today so we can plan a Telegram publishing module
that fits the existing architecture instead of fighting it.

**Date:** 2026-06-07
**Scope explored:** `cyberalertx/` (Python package), `frontend/` (Next.js),
`server/` (deploy), `tests/`, `data/` (live state).

> ⚠️ **The single most important finding up front:** this project is **not** a
> FastAPI + SQLAlchemy-ORM + Alembic CRUD app. It's a **batch pipeline**:
> RSS → enrich → JSON file store (Postgres is an *optional shadow*). The
> FastAPI app is **read-only** over that store. AI rework is a **separate CLI
> command** (`generate`) fired by a **systemd timer**, not Celery/background
> tasks. A Telegram publisher should be modeled as either (a) a pipeline
> **post-processor** or (b) a **new CLI subcommand fired by its own systemd
> timer** — mirroring how `generate` already works. See Open Questions.

---

## 1. Project structure

### Top-level layout

```
cyberalertx/                  ← Python package (the backend + pipeline + AI + CLI)
├── main.py                   ← argparse CLI entry point: once | run | top | generate | serve
├── config.py                 ← Settings dataclass (env-overridable), RSS source list
├── models.py                 ← NewsItem dataclass (the core domain object)
├── api/app.py                ← FastAPI app factory (READ-ONLY feed + 1 write endpoint /feedback)
├── ai/                       ← content generation layer (the "Claude rework" step)
│   ├── generator.py          ← ContentGenerator + build_default_generator()
│   ├── cache.py              ← ThreatPostCache (file-backed, (fingerprint,locale)-keyed)
│   ├── models.py             ← ThreatPost (output) + ThreatPostResponse (LLM schema)
│   ├── config.py             ← AISettings (provider selection, model, timeouts)
│   ├── providers/            ← claude_cli_provider.py (default), anthropic_provider.py, openai_stub.py
│   ├── rule_based.py         ← deterministic offline generator (fallback, $0)
│   └── templates.py, validation.py, references.py, editorial.py, ...
├── pipeline/                 ← the ingest stages (pure functions over NewsItem lists)
│   ├── orchestrator.py       ← Pipeline.run_once() — wires all stages in order
│   ├── normalize / filter / category / platforms / audience / actionability /
│   │   credibility / ranker / signals / relevance / keywords
├── sources/                  ← RSS fetching
│   ├── base.py (Source ABC), rss.py (RssSource), registry.py (build_sources)
├── storage/                  ← persistence
│   ├── base.py               ← NewsRepository Protocol
│   ├── json_store.py         ← JsonNewsStore (DEFAULT backend)
│   ├── factory.py            ← build_news_repository() / build_threat_post_cache()
│   ├── dual_write.py         ← DualWrite wrappers (JSON + PG)
│   └── pg/                   ← Postgres backend (SQLAlchemy Core 2.0 + psycopg3)
│       ├── engine.py, schema.py, news_store.py, threat_cache.py, serializers.py
│       └── migrations/*.sql  ← raw SQL migrations (NOT Alembic)
├── observability/            ← metrics.py (JSON counters), source_health.py
└── tools/                    ← one-off ops scripts (delete_post, pg_migrate, import_*, compare_storage)

frontend/                     ← Next.js 15 App Router (TS + Tailwind). Read-only feed UI.
server/                       ← systemd units, nginx conf, deploy/backup/setup scripts
tests/                        ← pytest (31 test files)
data/                         ← RUNTIME STATE (gitignored): items.json, threat_posts.json, *.jsonl
```

### How the "FastAPI app" is organized

There are **no routers, services-with-DI, ORM models, or a db session
dependency** in the conventional sense. `cyberalertx/api/app.py` (751 lines)
is a single `build_app()` factory that registers all routes inline as closures.
The only "service" is `_PostService` — a plain class that reads `NewsItem`s
from the JSON store and merges them with cached `ThreatPost`s.

All routes are **GET except one POST** (`/feedback`):

```python
# cyberalertx/api/app.py
@app.get("/healthz")            # liveness + feed-freshness telemetry
@app.get("/posts")              # main feed, reverse-chronological, cached_only by default
@app.get("/posts/trending")    # severity-ranked
@app.get("/posts/latest")
@app.get("/posts/{post_id}")    # single post by fingerprint
@app.get("/admin/metrics")      # observability JSON
@app.get("/admin/sources")      # per-source health JSON
@app.post("/feedback")          # the ONLY write endpoint (appends JSONL)
```

**Cost-safety invariant (important for Telegram):** the API server *never*
calls Anthropic. `_PostService.__init__` force-nulls the provider
(`generator._provider = None`). Live AI generation happens *only* from the
`generate --use-llm` CLI path. (api/app.py:88-118)

### Where RSS parsing lives

`cyberalertx/sources/rss.py` — `RssSource` uses `httpx` to download bytes
(custom headers/timeout) then `feedparser` to parse. One `RssSource` per feed
URL; `sources/registry.py:build_sources()` instantiates them from
`SETTINGS.sources`. The feed list (5 EN + 4 UA sources) is in `config.py:78-93`.

### Where the Claude rework step is invoked from

**Not cron, not Celery, not FastAPI background tasks.** It's a **systemd timer
firing a oneshot CLI command**:

- `server/systemd/cyberalertx-generate.timer` → every 6h (00,06,12,18 UTC)
- fires `server/systemd/cyberalertx-generate.service` (Type=oneshot) which runs:
  ```
  /home/cax/cax/venv/bin/python -m cyberalertx.main generate --limit 4 --use-llm
  ```
- `cmd_generate()` (main.py:131-276) walks the store, finds uncached
  `(fingerprint, locale)` pairs, and renders only the missing ones via
  `_PostService.render()` → `ContentGenerator.generate()` → the configured
  provider (default: **local `claude` CLI**, not the API).

The ingest loop is **separate**: `cyberalertx-run.service` runs
`main run --interval 15`, which uses **APScheduler** (`BlockingScheduler`,
in-process) to call `pipeline.run_once()` every 15 min. This path is
deterministic-only and never touches AI. (main.py:71-101)

> **This is the template for the Telegram publisher.** A new
> `cyberalertx-telegram.timer` + oneshot service running e.g.
> `python -m cyberalertx.main publish-telegram` would be the most consistent
> integration. See §5 and Open Questions.

### Where config/env loading happens

Two config modules, both plain `os.getenv` over frozen dataclasses (no
pydantic-settings):

- `cyberalertx/config.py` — `Settings` (fetch interval, timeout, UA, storage
  path, retention cap, source list). Singleton `SETTINGS = Settings()`.
- `cyberalertx/ai/config.py` — `AISettings` (provider, model, timeouts, CLI
  binary/token paths). Env vars prefixed `CYBERALERTX_AI_*` / `CYBERALERTX_CLAUDE_CLI_*`.

`.env` is loaded via `python-dotenv` (optional dep; falls back to plain
`os.getenv`). In prod it's injected by systemd `EnvironmentFile=/home/cax/cax/.env`.
Convention: **all app env vars are prefixed `CYBERALERTX_`** (except the raw
vendor keys `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`).

---

## 2. Database

### Which DB

**Primary = JSON files on disk.** `data/items.json` (news) and
`data/threat_posts.json` (AI renders). **Postgres is optional and
shadow-only**, selected by `CYBERALERTX_STORAGE_BACKEND`:

- `json` (default) — JSON only.
- `dual` — writes fan out to JSON **and** Postgres; reads still come from
  JSON for news (PG-preferred for threat posts). PG init failure silently
  degrades to JSON-only — *the pipeline must never break because PG is down*.
  (storage/factory.py)

The live `.env` has `CYBERALERTX_STORAGE_BACKEND` and `CYBERALERTX_PG_URL`
set (Supabase, per server/README.md), so **prod runs in `dual` mode**.

### ORM

**SQLAlchemy Core 2.0** (Table/select/insert constructs) + **psycopg3**
(`postgresql+psycopg` dialect). **Not** the ORM (no declarative models, no
`Session`/`sessionmaker`). No SQLModel, no Tortoise. (storage/pg/schema.py,
engine.py)

Sessions/connections: a process-wide lazy `Engine` with a connection pool
(`pool_size=2, max_overflow=8, pool_pre_ping=True, pool_recycle=1800`). Each
store method does `with get_engine().connect()/.begin() as conn:` — **no
long-lived sessions, no DI**. (storage/pg/engine.py, news_store.py:48-58)

### Migrations

**Raw `.sql` files**, applied by a hand-rolled runner — **not Alembic**:

- Files: `cyberalertx/storage/pg/migrations/001_init.sql`,
  `002_threat_posts.sql`, `003_threat_posts_denormalized.sql`.
- Runner: `python -m cyberalertx.tools.pg_migrate` (records applied versions
  in a `schema_migrations` table; idempotent, all `CREATE ... IF NOT EXISTS`).
- `storage/pg/schema.py` mirrors the DDL as SQLAlchemy `Table` objects so the
  Python layer builds typed statements. **Both must be edited together when
  adding a column** (the comment in schema.py and `tests/test_pg_live.py`
  enforce this).

### The core model — `NewsItem` (dataclass, not ORM)

`cyberalertx/models.py` — `@dataclass NewsItem`. There is **no `News` ORM
class**; this dataclass is the domain object, mirrored 1:1 by the
`news_items` Postgres table. All fields:

| Field | Type | Notes |
|---|---|---|
| `title` | `str` | required |
| `source` | `str` | feed name, e.g. "The Hacker News" |
| `url` | `str` | article URL (also the dedup basis) |
| `published_at` | `datetime` | tz-aware UTC |
| `raw_content` | `str` | HTML-stripped summary from the feed |
| `threat_score` | `float` | from ranker; `0.0` default |
| `tags` | `list[str]` | |
| `fetched_at` | `datetime` | defaults to now() |
| `language` | `str` | **`"en"` / `"ua"` / `"other"` / `"unknown"`** (single field, not separate tables) |
| `original_language` | `str` | what the feed served (preserved across translation) |
| `category` | `str` | `"other"` default; values: `vulnerability`, `scam`, `phishing`, `malware`, ... (see pipeline/category.py) |
| `category_confidence` | `float` | |
| `affected_platforms` | `list[str]` | e.g. `["Android"]`, `["Linux"]` |
| `audience_targets` | `list[str]` | e.g. `["sysadmins"]`, `["mobile_users","normal_users"]` |
| `audience_relevance_score` | `float` | |
| `actionability_level` | `str` | **`informational` / `recommended_action` / `urgent_action`** |
| `actionability_score` | `float` | `[0,1]` continuous backing the level |
| `source_tier` | `str` | **`trusted` / `verified` / `unverified`** (credibility) |
| `source_credibility_score` | `float` | `[0,1]` |
| `corroborating_sources` | `list[str]` | other trusted sources on same story |

Notes for the Telegram module:
- **`id` / `slug`:** there is no separate id or slug column. The identifier is
  a **derived `fingerprint`** — `sha256(url or title)[:16]` (a `@property`,
  models.py:69-73). The PG `news_items` table uses `fingerprint` as the PK.
- **`summary` / `body`:** `NewsItem` only has `raw_content` (the feed blurb).
  The polished, human-readable text lives in the **`ThreatPost`** (AI output),
  not in `NewsItem`. See below.
- **severity:** there is no single "severity" on `NewsItem`. The reader-facing
  severity is `ThreatPost.threat_level` (`Low/Medium/High/Critical`), assigned
  by the AI/rule-based layer. `NewsItem` carries `threat_score` (unbounded
  float, internal ranking) + `actionability_level` (urgency).
- **No existing telegram / social-post fields anywhere.** Confirmed by grep —
  nothing related to publishing, message ids, or channel posts exists.

### The `ThreatPost` model (AI output — what you'd actually publish)

`cyberalertx/ai/models.py` — `@dataclass ThreatPost`. This is the
human-friendly rendered content, cached per `(fingerprint, locale)`:

| Field | Type | Notes |
|---|---|---|
| `title` | `str` | localized headline |
| `short_summary` | `str` | **the feed/card text — 100-200 chars, one paragraph** |
| `threat_level` | `str` | `Low/Medium/High/Critical` |
| `why_it_matters` | `str` | |
| `affected_users` | `list[str]` | |
| `what_to_do` | `list[str]` | action items |
| `what_not_to_do` | `list[str]` | |
| `quick_facts` | `list[str]` | scan chips |
| `emotional_weight` | `float` | |
| `reading_time_seconds` | `int` | |
| `detail_body` | `str` | 2-5 paragraphs (`\n\n`-separated) for the detail page |
| `references` | `list[Reference]` | `{type, label, url}` — CVE/advisory/vendor links |
| `language` | `str` | `"en"` / `"ua"` |
| `source_fingerprint` | `str` | links back to the NewsItem |
| `generated_by` | `str` | `"rule_based"` / `"anthropic:..."` / `"claude-cli:..."` |

> **For a Telegram post, the natural source of text is the `ThreatPost`
> (`title` + `short_summary` + `threat_level` + a link), not the raw
> `NewsItem`.** Only items that have been through `generate` have a ThreatPost.

### threat_posts table / cache

- PG table `threat_posts`: composite PK `(fingerprint, locale)`, `payload`
  JSONB holding the full ThreatPost, plus mirrored columns (`threat_level`,
  `generated_by`, `language`) and denormalized `published_at`/`category`/
  `actionability_level` (populated by a migration-003 trigger).
- JSON form `data/threat_posts.json`: `{"posts": {"<fingerprint>:<locale>": {...}}}`.
  Keys look like `a6001f4e5eace5ba:en`, `a6001f4e5eace5ba:ua`.

### How sessions are created

There is no session factory or DI. For PG: `get_engine()` returns a
process-wide pooled `Engine`; callers use short `with ... connect()` blocks
(storage/pg/engine.py:53-77, news_store.py). For JSON: `JsonNewsStore(path,
max_items)` is constructed directly; reads are mtime-cached.

### Sample real rows (from live `data/items.json`)

```jsonc
// Row 1 — EN, vulnerability category
{
  "title": "DirtyDecrypt PoC Released for Linux Kernel CVE-2026-31635 LPE Vulnerability",
  "source": "The Hacker News",
  "url": "https://thehackernews.com/2026/05/dirtydecrypt-poc-released-for-linux.html",
  "published_at": "2026-05-19T12:56:26+00:00",
  "language": "en", "original_language": "en",
  "category": "vulnerability",
  "threat_score": 18.50,
  "actionability_level": "informational",
  "source_tier": "trusted",
  "affected_platforms": ["Linux"],
  "audience_targets": ["sysadmins"]
  // (fingerprint is derived from url at runtime, not stored in JSON)
}

// Row 2 — EN, scam category, multi-audience
{
  "title": "Trapdoor Android Ad Fraud Scheme Hit 659 Million Daily Bid Requests Using 455 Apps",
  "source": "The Hacker News",
  "url": "https://thehackernews.com/2026/05/trapdoor-android-ad-fraud-scheme-hit.html",
  "published_at": "2026-05-19T14:38:12+00:00",
  "language": "en", "original_language": "en",
  "category": "scam",
  "threat_score": 15.79,
  "actionability_level": "informational",
  "source_tier": "trusted",
  "affected_platforms": ["Android"],
  "audience_targets": ["mobile_users", "normal_users"]
}
```

(There are also UA-language rows, e.g. a test fixture title `"Звичайна новина"`;
real UA items come from itc.ua / ain.ua / dev.ua / dou.ua.)

Live store as of exploration: `data/items.json` ≈ 330 KB,
`data/threat_posts.json` ≈ 41 KB.

---

## 3. URL structure of the site

Single domain, **locale as the first path segment** (no subdomains, no
separate UA/EN domains):

```
https://cyberalertx.com/{locale}                       → feed homepage
https://cyberalertx.com/{locale}/threat/{fingerprint}  → article detail page
```

- `{locale}` ∈ `en` | `ua`. Legacy `uk` is accepted and normalized to `ua`.
- `{fingerprint}` = the 16-hex `NewsItem.fingerprint`.
- Root `/` 308-redirects to `/{DEFAULT_LOCALE}` via `frontend/middleware.ts`.

Confirmed by `frontend/app/[locale]/threat/[id]/page.tsx` and the example URL
in `server/README.md`:
`https://<your-domain>/ua/threat/<fingerprint>`.

**So a Telegram post's "Read more" link = `https://cyberalertx.com/{locale}/threat/{fingerprint}`.**

The Python backend API (`/posts`, `/healthz`) is internal (127.0.0.1:8000),
fronted by nginx; the public site only exposes the Next.js routes + the
proxied `/posts`, `/healthz`, `/feedback` API paths.

---

## 4. Existing dependencies

From `requirements.txt`:

| Concern | Library | Notes |
|---|---|---|
| HTTP client | **`httpx>=0.27`** | used in `sources/rss.py` (sync `httpx.Client`). **Use this for Telegram calls** — no aiohttp/requests present. |
| RSS parsing | `feedparser>=6.0.11` | |
| Validation/schema | `pydantic>=2.7` | used for `ThreatPostResponse` (LLM I/O) |
| Scheduler | `APScheduler>=3.10.4` | in-process loop for `run` |
| Dates | `python-dateutil>=2.9` | |
| API | `fastapi>=0.115`, `uvicorn[standard]>=0.32` | |
| AI | `anthropic>=0.45` | optional; CLI provider is default |
| Postgres | `SQLAlchemy>=2.0,<2.1`, `psycopg[binary]>=3.1` | only imported in `dual` mode |
| Env | `python-dotenv>=1.0` | optional |
| Tests | `pytest>=8.0` | |

- **Image processing: none.** No Pillow, no imaging lib. (If Telegram posts
  need rendered image cards, that's a new dependency + a decision — see Open
  Questions.)
- **Telegram lib: none.** No `aiogram`, no `python-telegram-bot`. Given the
  sync, short-lived, subprocess/CLI style of this codebase, the lightest fit
  is **direct Bot API calls over the existing `httpx`** (a single
  `POST https://api.telegram.org/bot<token>/sendMessage`) rather than pulling
  in a full async bot framework. Confirm in Open Questions.
- **Logging:** stdlib `logging`. Every module does
  `logger = logging.getLogger(__name__)`. Configured centrally in
  `main._setup_logging()` (`%(asctime)s %(levelname)s [%(name)s] %(message)s`).
  In prod, logs go to **journald** (systemd `StandardOutput=journal`).
- **Settings management:** plain `os.getenv` over frozen dataclasses (no
  pydantic-settings). Prefix `CYBERALERTX_`.

---

## 5. Deployment

From `server/README.md` + `server/systemd/*`:

- **Host:** single Ubuntu 24.04 VPS (~2 GB RAM), app user **`cax`**, app dir
  **`/home/cax/cax`**, venv at `/home/cax/cax/venv`.
- **Process manager: systemd** (no Docker, no supervisord). Units:

  | Unit | Type | Cadence | Role |
  |---|---|---|---|
  | `cyberalertx-api` | simple | always-on | FastAPI on 127.0.0.1:8000 |
  | `cyberalertx-run` | simple | always-on | APScheduler ingest every 15 min |
  | `cyberalertx-frontend` | simple | always-on | Next.js on 127.0.0.1:3000 |
  | `cyberalertx-generate.service` | **oneshot** | fired by timer | `generate --limit 4 --use-llm` (AI render) |
  | `cyberalertx-generate.timer` | timer | every 6h | activates the oneshot |

- **Cron jobs:** the only system cron is the **daily backup** (`backup.sh`).
  Recurring app work uses **systemd timers** (the `generate` timer), and the
  ingest cadence uses **APScheduler inside `cyberalertx-run`**. There is **no
  Celery, no Celery beat**.
- **Logs:** **journald** (`journalctl -u <unit>`). nginx logs to
  `/var/log/nginx/`. App-level metrics are JSON files in `data/`
  (`quality_metrics.json`, `source_health.json`) + `feedback.jsonl`.
- **`.env` in prod:** `/home/cax/cax/.env`, `chmod 600`, injected via systemd
  `EnvironmentFile=`. Current keys (values redacted):
  `CYBERALERTX_STORAGE_BACKEND`, `CYBERALERTX_PG_URL`, `ANTHROPIC_API_KEY`,
  `CYBERALERTX_AI_PROVIDER`, `CYBERALERTX_AI_MODEL`, `CYBERALERTX_AI_MAX_TOKENS`,
  `CYBERALERTX_AI_RETRIES`, `CYBERALERTX_AI_CACHE`, `OPENAI_API_KEY`,
  `CYBERALERTX_OPENAI_MODEL`. **A Telegram bot token + channel id would be new
  entries here.**
- **Server user:** `cax` (memory note: do **not** SSH into the VPS from this
  environment; hand commands to the user).
- **TLS:** nginx terminates with a Cloudflare Origin Certificate; Cloudflare
  fronts the domain.

### Two natural integration shapes for the publisher

1. **Pipeline post-processor** (`orchestrator.py` already has the hook):
   `Pipeline(__init__)` accepts `post_processors: Iterable[PostProcessor]`,
   where `PostProcessor = Callable[[Sequence[NewsItem]], None]`, called via
   `_notify(new_items)` after each ingest cycle (orchestrator.py:49-50,
   198-206). **Currently no post-processors are wired** (`_build_pipeline()`
   in main.py passes none). *Caveat:* new items at ingest time do **not** yet
   have a `ThreatPost` (AI runs later, on the generate timer), so a
   post-processor here would publish raw/rule-based text or have to wait.

2. **New CLI subcommand + systemd timer** (mirrors `generate`): e.g.
   `cyberalertx.main publish-telegram`, fired by a
   `cyberalertx-telegram.timer`, that selects already-AI-rendered posts and
   pushes the unpublished ones. This decouples publishing from both ingest and
   render cadence and matches the established operational pattern. **Likely
   the better fit** — but it needs a "what's already been published?" record
   (new field/file/table). See Open Questions.

---

## 6. Code style

From `models.py`, `api/app.py`, `pipeline/orchestrator.py`,
`storage/pg/news_store.py`, `tests/test_api.py`, `tests/test_observability.py`:

- **Type hints:** `from __future__ import annotations` at the top of *every*
  module. **PEP 604 unions** (`str | None`, `list[str]`, `dict[str, Any]`) are
  the modern default; older modules still use `Optional[...]` / `List[...]`
  from `typing` (e.g. `sources/rss.py`, `storage/base.py`). Match the file
  you're editing — but new code leans PEP 604.
- **Domain modeling:** `@dataclass` for domain/value objects (`NewsItem`,
  `ThreatPost`, `Reference`, `CycleResult`, `Settings`, `AISettings`).
  **Pydantic only at the LLM I/O boundary** (`ThreatPostResponse`).
  `Settings`/`AISettings` are `@dataclass(frozen=True)`.
- **Async patterns:** the backend is **almost entirely synchronous.** RSS
  fetch, storage, AI provider (subprocess), and FastAPI routes are all sync
  (`def`, not `async def`). Concurrency where needed uses
  `concurrent.futures.ThreadPoolExecutor` (orchestrator fan-out) — **not
  asyncio.** A Telegram publisher should be **sync** to fit. (This is another
  reason to prefer raw `httpx` calls over an async bot framework.)
- **Logging:** module-level `logger = logging.getLogger(__name__)`;
  `logger.info/warning/exception`. `%`-style lazy args
  (`logger.warning("Source %s failed: %s", name, exc)`), never f-strings in log
  calls.
- **Error handling:** "one bad input must never break the batch." Pervasive
  pattern: wrap per-item work in `try/except Exception`, log, and continue/skip
  (rss.py `_download`, orchestrator `_safe_fetch`/`_notify`,
  api `_render_many`). External-dependency failures (PG, AI) **degrade
  gracefully to the cheaper path** rather than raising (storage/factory.py,
  the rule-based fallback). Defensive `except` blocks are marked
  `# pragma: no cover - defensive`.
- **Comments:** unusually thorough — module docstrings explain *why*, and
  inline comments capture past bugs and invariants. Match this density;
  document the *reasoning*, not just the *what*.
- **Tests:** **pytest**, in `tests/` at repo root, named `test_*.py`, one file
  per concern (31 files). Style: small module-level `_item(**overrides)`
  factories, fake in-memory stores/services (`_FakeStore`, `_FakeService`),
  `tmp_path` fixture for file-backed components, `TestClient` for the API. No
  classes required (plain `def test_...`); fixtures via `@pytest.fixture`. No
  external network in tests — everything injected. (test_api.py:19-72,
  test_observability.py:27-48)

---

## Recommended design (decisions)

These are the chosen answers to the open questions, optimizing for: fits the
existing patterns, **zero new dependencies**, **no DB migration**, idempotent,
and cheap to run. Each links back to the evidence above.

| # | Decision | Why |
|---|---|---|
| **Content** | Publish **only AI-rendered posts** (those with a `ThreatPost` in the cache). | Telegram gets the polished `short_summary`, not the raw feed blurb. Raw `NewsItem`s at ingest time have no `ThreatPost` yet (§2, §5). |
| **Filter bar** | Publish iff **`threat_level ∈ {High, Critical}` OR `actionability_level == "urgent_action"`**, AND **`source_tier ∈ {trusted, verified}`**. All thresholds env-tunable. | Keeps the channel high-signal; matches the fields the data actually carries (§2). Defaults are conservative — easy to loosen later. |
| **Locale / channels** | **Two channels: EN + UA.** Each publishes its own locale render (`:en` / `:ua`). UA channel optional — if its id isn't configured, UA is skipped. | Respects the asymmetric multilingual rule (UA-source never auto-translated to EN). Mirrors the site's `/{en,ua}` split. |
| **Trigger** | **New CLI subcommand `publish-telegram` + its own systemd timer** (`cyberalertx-telegram.timer`), mirroring `generate`. **Not** a pipeline post-processor. | Post-processor fires at ingest when no `ThreatPost` exists yet. A timer-driven command publishes already-rendered posts and keeps publishing decoupled from ingest/render cadence (§5). |
| **"Already published" state** | **JSONL ledger** at `data/telegram_published.jsonl`, one line per `{fingerprint, locale, channel, message_id, timestamp}`. | Follows the existing `feedback.jsonl` pattern (api/app.py:706-745). JSON-first = no PG migration, no `schema.py` edit. Append-only, trivially idempotent. |
| **Idempotency** | Write the ledger line **only after** a successful `sendMessage` (capturing the returned `message_id`). On startup, load published `(fingerprint, locale)` keys into a set and skip them. | A send that succeeds but fails to record will, worst case, double-post once — acceptable and rare. Never silently drops. |
| **Dependency** | **Raw Telegram Bot API over the existing sync `httpx`** (`POST /bot<token>/sendMessage`). No `aiogram` / `python-telegram-bot` / Pillow. | The whole backend is synchronous (§6). One HTTP call per post; a bot framework is dead weight here. |
| **Message format** | **HTML parse mode**, text-only. Layout: threat-level emoji + **bold title**, blank line, `short_summary`, optional 1-2 `quick_facts`, then a "🔗 Read more" link to `https://cyberalertx.com/{locale}/threat/{fingerprint}`. | HTML escaping is far less error-prone than MarkdownV2. Text-only avoids a new imaging dependency (§4). |
| **Rate limiting** | Publish at most **N per run** (default 5, env-tunable) with a small sleep between sends. | Stays well under Telegram's ~20 msg/min-per-chat ceiling, and caps blast radius on a backfill (§4). |
| **Failure handling** | Per-post `try/except` → log + skip; unpublished posts are retried on the next timer fire. No alerting. | Matches the degrade-and-log invariant used everywhere (§6). |

### Proposed module shape (for the implementation PR — not built yet)

```
cyberalertx/
├── publish/
│   ├── __init__.py
│   ├── telegram.py        # TelegramPublisher: sync httpx Bot API client (sendMessage)
│   ├── ledger.py          # PublishLedger: JSONL read/append, (fingerprint,locale) dedup set
│   ├── selector.py        # choose_publishable(items, cache, cfg) -> ordered list
│   └── format.py          # render_message(threat_post, item, locale) -> HTML string
└── (main.py)              # new `publish-telegram` subcommand: --limit, --dry-run, --language

server/systemd/
├── cyberalertx-telegram.service   # oneshot: python -m cyberalertx.main publish-telegram --limit 5
└── cyberalertx-telegram.timer     # hourly (OnCalendar=*-*-* *:00:00)

tests/
└── test_telegram_publish.py       # selector bar, formatter escaping, ledger dedup, dry-run, httpx mocked
```

New env vars (user adds to `/home/cax/cax/.env`; I won't SSH in):
`CYBERALERTX_TELEGRAM_BOT_TOKEN`, `CYBERALERTX_TELEGRAM_CHANNEL_EN`,
`CYBERALERTX_TELEGRAM_CHANNEL_UA` (optional), and optional tuning knobs
`CYBERALERTX_TELEGRAM_MIN_LEVEL`, `CYBERALERTX_TELEGRAM_LIMIT`.

`--dry-run` (mirroring `generate`) renders + prints the messages and the
would-publish list **without** calling Telegram — the safe preview before the
first real run.

### Confirmed by the user (2026-06-07)

1. **Cadence** — **align to the 6h `generate` timer.** The telegram timer
   fires at `00,06,12,18:15:00` UTC — 15 min after generate, so the freshly
   rendered posts from that fire are publishable in the same cycle.
2. **Channels** — **two channels, EN + UA.** Both
   `CYBERALERTX_TELEGRAM_CHANNEL_EN` and `CYBERALERTX_TELEGRAM_CHANNEL_UA`
   are expected; the UA channel is still skipped gracefully if its id is
   absent.

---

## Open questions for the user (original — now superseded by the decisions above)

**Product / behaviour**
- **Which content gets published?** Only AI-rendered posts (have a
  `ThreatPost`), or any ingested `NewsItem`? My recommendation: only
  AI-rendered ones, so Telegram gets polished `short_summary` text.
- **Filter threshold?** Publish everything, or only above a bar (e.g.
  `threat_level` ∈ {High, Critical}, or `actionability_level` =
  `urgent_action`, or `source_tier` = `trusted`)? The data supports any of
  these.
- **Which locale(s)?** One channel for EN + one for UA? A single bilingual
  channel? This decides whether we publish `:en`, `:ua`, or both renders.
  (Recall the asymmetric rule: UA-source items are never auto-translated to EN.)
- **Message format?** Plain text, Telegram **MarkdownV2**, or **HTML**? Include
  which fields — `title`, `short_summary`, `threat_level` badge, `quick_facts`,
  `references`, and the `…/threat/{fingerprint}` link?
- **Images?** Text-only messages (no new deps), or rendered image cards
  (requires Pillow/HTML-to-image + a design)? Text-only is far simpler and
  fits the current dependency set.
- **Volume / rate:** how many posts per run is acceptable? Telegram Bot API
  limits ~30 msg/s and ~20 msg/min to the same chat — relevant if backfilling.

**Architecture**
- **Trigger model:** (a) pipeline **post-processor** at ingest (raw items, no
  AI text yet), (b) **new CLI subcommand + systemd timer** (publishes
  AI-rendered posts; my recommendation), or (c) hook into the existing
  `generate` flow (publish right after a render)? Each has different freshness
  / cost / complexity tradeoffs.
- **Dedup / "already published" state:** there's no existing field for this.
  Options: a new JSONL ledger (`data/telegram_published.jsonl`, fits the
  `feedback.jsonl` pattern), a new boolean/timestamp column on
  `threat_posts` (needs a migration + schema.py edit), or a new small table.
  Which storage style do you want — JSON-first (default backend) or PG-aware
  (matches `dual` mode)?
- **Idempotency on retry:** if a send succeeds but recording it fails, we must
  not double-post. Acceptable to store the returned Telegram `message_id`?

**Ops / secrets**
- **Credentials:** new `.env` keys — proposed `CYBERALERTX_TELEGRAM_BOT_TOKEN`
  and `CYBERALERTX_TELEGRAM_CHANNEL_ID` (+ a UA channel id if two channels).
  Confirm naming. These need to be added to `/home/cax/cax/.env` on the VPS by
  you (I won't SSH in).
- **Cadence:** if timer-driven, what schedule? Align with the 6h generate
  timer, or more frequent (e.g. hourly) so news is timelier?
- **Dependency choice confirmation:** OK to implement with **raw `httpx` Bot
  API calls** (sync, zero new deps) rather than adding `aiogram` /
  `python-telegram-bot`? This matches the codebase's sync style.
- **Failure handling:** on Telegram API error, retry next run (degrade-and-log,
  consistent with the rest of the codebase) — confirm that's the desired
  behaviour rather than alerting.
```
