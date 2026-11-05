# CyberAlertX — Architecture

How a story travels from an RSS feed to the website and the Telegram channels,
and what every component owns. This is the map; the per-file detail lives in
the module docstrings and `server/README.md` (ops).

---

## 1. The big picture (component map)

```
                              ┌─────────────────────────────────────────────┐
   EXTERNAL SOURCES           │                 YOUR VPS  (user: cax)        │
                              │                                              │
 ┌──────────────────┐  RSS    │  ┌────────────────────┐                       │
 │ The Hacker News  │────────▶│  │ cyberalertx-run    │  every 30 min         │
 │ BleepingComputer │  fetch  │  │ (APScheduler)      │  INGEST PIPELINE      │
 │ Krebs, Securelist│         │  │ deterministic, $0  │                       │
 │ CISA / itc/ain.. │         │  └─────────┬──────────┘                       │
 └──────────────────┘         │            │ writes                          │
                              │            ▼                                 │
                              │   ┌───────────────────────┐  dual-write  ┌───┴────────┐
                              │   │ data/items.json       │─────────────▶│  Postgres   │
                              │   │ (raw NewsItems)       │              │ (Supabase)  │
                              │   └───────────┬───────────┘              │ news_items  │
                              │               │ reads                    │ threat_posts│
   ┌─────────────────┐        │   ┌───────────┴───────────┐  dual-write  └───┬────────┘
   │  Claude CLI     │◀───────│   │ cyberalertx-generate  │──────────────────┘
   │ (subscription   │ render │   │ .timer  hourly        │ writes
   │  OAuth, no key) │───────▶│   │ THE ONLY THING THAT   │   ┌──────────────────────────┐
   └─────────────────┘        │   │ CALLS CLAUDE          │──▶│ data/threat_posts.json   │
                              │   └───────────────────────┘   │ (AI renders, per locale) │
                              │                                └───────────┬──────────────┘
                              │   ┌───────────────────────┐  reads cache   │
                              │   │ cyberalertx-api        │◀───────────────┤
                              │   │ FastAPI :8000 (local)  │  reads items   │
                              │   │ read-only, never AI    │◀───────────────┘
                              │   └───────────┬───────────┘
                              │               │ /posts /healthz
                              │   ┌───────────┴───────────┐
                              │   │ cyberalertx-frontend   │  SSR + ISR(60s)
                              │   │ Next.js :3000 (local)  │
                              │   └───────────┬───────────┘
                              │               │
                              │   ┌───────────┴───────────┐
   ┌─────────────────┐        │   │ nginx :443 (TLS)      │
   │ Telegram Bot API│◀───────│   │ cyberalertx-telegram  │ timer 10×/day, hold marker
   │   ↓             │  send  │   │ .timer → publish      │ reads threat_posts cache
   │ @cyberalertx_en │        │   └───────────────────────┘ writes telegram_published.jsonl
   │ @cyberalertx_ua │        │                                                            │
   └─────────────────┘        └────────────────────────────────────────────────────────────┘
            ▲                                    ▲
            │ link preview (OG)                  │ HTTPS
       ┌────┴─────┐                         ┌────┴─────┐
       │ Readers  │                         │ Visitors │  via Cloudflare (CDN+TLS) → nginx
       └──────────┘                         └──────────┘
```

---

## 2. The services (systemd units) — who owns what

| Service | Type / cadence | Responsibility | Calls the AI? |
|---|---|---|---|
| **cyberalertx-run** | always-on, ingest every **30 min** | The ingest pipeline: fetch RSS → clean → filter → enrich → evidence → rank → persist. Deterministic. | ❌ never |
| **cyberalertx-generate** | timer, **hourly** (`--limit 1`) | Turns the newest raw NewsItem into localized **ThreatPosts** (EN + UA) via the Claude CLI, scores them, caches them. Then the media run draws missing story illustrations (SVG, no AI). | ✅ **only one** |
| **cyberalertx-api** | always-on, FastAPI `:8000` | HTTP feed (`/posts`, `/healthz`, `/feedback`) and `/admin`. Merges items + cached renders. | ❌ never |
| **cyberalertx-frontend** | always-on, Next.js `:3000` | Renders the website (SSR + ISR), fetching from the API. | ❌ never |
| **cyberalertx-analytics** | timer, daily 03:00 | Visitor statistics from the nginx log into `data/analytics.sqlite3`. | ❌ never |
| **cyberalertx-telegram** | timer, **10×/day** | Publication queue: one post per channel per run, with the story illustration. Runs only while the hold marker exists ([operations §7](operations/OPERATIONS.md#7-telegram)). Threads publishing is off. | ❌ never |

**The key invariant:** AI costs money/time, so it runs in exactly **one**
place — `generate`. Everything else only *reads* what `generate` produced.

All units except analytics load `/home/cax/cax/.env` and run the active
immutable release through `/home/cax/cyberalertx/current` (§10).

---

## 3. The ingest pipeline (inside cyberalertx-run, every 30 min)

```
fetch RSS (parallel, httpx + feedparser)
   │   one bad feed can't break the run; a failing feed backs off
   │   (30 min doubling, max 24 h for refusals / 6 h for transient errors)
   ▼
dedup ──▶ normalize ──▶ filter ──▶ categorize ──▶ platforms ──▶ audience
(fingerprint)  (lang,    (keyword   (vuln/scam/   (Linux,       (sysadmins,
 = sha256(url)  UTF-8)    scoring)   phishing…)    Android…)     devs…)
   │
   ▼
actionability ──▶ credibility ──▶ rank ──▶ persist (items.json + Postgres)
(urgent/         (trusted/       (threat   one NewsItem per story,
 recommended/     verified/       score)    keyed by fingerprint
 informational)   unverified)
```

Output: a `NewsItem` dataclass with ~20 enrichment fields. **No prose is
written here** — just metadata and scoring. Code: `cyberalertx/pipeline/
orchestrator.py` wires the stages; each stage is a pure function over a list
of `NewsItem`.

**Source health** (`data/source_health.json`, `/admin/sources`): per source,
cycles seen / empty / failed, items fetched and kept, the last successful
fetch, and the current failure (`last_error` such as `http_403`,
`consecutive_failures`, `next_attempt_utc`). Feeds are fetched with an
identifiable User-Agent; a feed whose origin refuses automated readers (CISA,
O37) shows as failing rather than being worked around.

**Evidence** (`pipeline/evidence.py`): from the source title, excerpt and
byline only, the separate questions exploitation / compromise / campaign /
sponsorship / unknowns, kept apart from severity. A label needs a stated
claim; hedged, negated, capability and statistical wording does not count.
The generator's scorecard compares each brief with these labels and flags
unsupported claims for review (mode `flag`: the post stays visible);
[EDITORIAL_REVIEW_PROCESS.md](editorial/EDITORIAL_REVIEW_PROCESS.md).

---

## 4. The data stores (what lives where)

| Store | Holds | Written by | Read by |
|---|---|---|---|
| `data/items.json` | raw NewsItems (capped archive) | run | api, generate, telegram |
| `data/threat_posts.json` | AI renders, keyed `fingerprint:locale` | generate | api, telegram |
| **Postgres** (Supabase) | shadow copy of both tables | run, generate (dual-write) | parity checks / future read path |
| `data/telegram_published.jsonl` | "already posted" ledger | telegram | telegram (dedup) |
| `data/publish_jobs.json` | publication jobs (state, attempts, schedule) | telegram | telegram, api (`/admin/publishing`) |
| `data/media/assets.json`, `data/media/files/` | illustration metadata and SVG files (content-addressed) | generate (media run) | api, frontend (`/media/…`), telegram |
| `data/feedback.jsonl`, `*_metrics.json`, `source_health.json` | observability | api, run | you (`/admin/*`) |

**Storage backend** is selected by `CYBERALERTX_STORAGE_BACKEND`:
`json` (files only) or `dual` (files **and** Postgres; prod runs `dual`). In
`dual` mode every write fans out to both; if Postgres is down the write path
degrades to JSON-only and logs a warning — the pipeline never breaks because
the DB is unreachable.

**Read path in `dual` mode** (`storage/dual_write.py`): JSON is read first and
is authoritative. A JSON miss never costs a per-item query (O27): the process
keeps an index of the `(fingerprint, locale)` keys Postgres holds (one
keys-only SELECT, refreshed at most every `CYBERALERTX_PG_INDEX_TTL_SECONDS`,
default 60) and, in the same refresh, loads the few posts Postgres has but
JSON lacks with one batch query. The index is warmed in the background when
the cache is built. Own writes and deletes update it immediately; rows another
process writes **only** to Postgres appear within one TTL. An unreadable JSON
file fails closed (no Postgres fallback, O28). Since Stage C the production
API runs with `CYBERALERTX_STORAGE_BACKEND=json` (drop-in
`stage-c-json-reads.conf`) until this read path is deployed.

**Why two models?** `NewsItem` (metadata) and `ThreatPost` (the readable
content) are deliberately separate: **one NewsItem → up to two ThreatPosts**
(en + ua). EN-source items render both locales; UA-source items render UA only
(never auto-translated to English — the asymmetric multilingual rule).

---

## 5. Lifecycle of one story (end to end)

```
T+0min   BleepingComputer publishes "Everest Forms Pro RCE"
T+≤30min run: fetches it → scores Critical/urgent → saved to items.json (raw, no prose)
         ↳ at this point it's on NO channel and NOT on the public feed yet
T+≤1h    generate: picks it (newest, uncached) → Claude CLI writes the UA+EN
         ThreatPost (title, summary, quick_facts, CVE refs) → threat_posts.json
         ↳ NOW it appears on the website feed (api serves cached renders only)
(Stage D) telegram: sees it's cached + Critical + trusted + not in ledger →
         formats HTML (CVE→NVD links) → Bot API sendMessage → @cyberalertx_ua/en
         → records fingerprint:locale in telegram_published.jsonl (never re-sent)
```

A story only reaches the public feed and the channels **after** `generate` has
rendered it. Raw-but-unrendered items wait in `items.json` until the next
generate fire — that's why the feed/channels fill in over hours, not instantly.

---

## 6. Two request flows (front of house)

**Website visitor:**
```
Browser ──HTTPS──▶ Cloudflare (CDN, TLS) ──▶ nginx :443 ──┬─ /        → Next.js :3000 ──▶ API :8000 /posts
                                                          └─ /posts,/healthz,/feedback → API :8000 directly
```
The browser never talks to the Python API directly in normal page loads — the
Next.js server fetches `/posts` server-side and ships rendered HTML, so the JS
bundle stays small. nginx routes the API paths for any client-side calls
(feedback widget, freshness poll).

**Telegram / social link preview (Open Graph):**
```
Someone shares  …/ua/threat/{id}
   → the messenger fetches that page's <meta og:*> tags
   → per-article, per-locale card (UA title + summary + UA brand image)
```
Per-locale OG is set in `app/[locale]/layout.tsx` (home) and
`app/[locale]/threat/[id]/page.tsx` (article). These are cached hard by
Telegram — see `server/README.md` → "Social previews" for the cache-busting
flow (rebuild → Cloudflare purge → @WebpageBot).

---

## 7. Illustrations and the Telegram publish path

**Illustrations** (`cyberalertx/media/`, after every `generate` run):

```
public stories (items.json, with a published brief), newest first
   │  visual brief from verified fields: event (evidence-gated) + scene (technology) + seed (story key)
   ▼
same brief hash as the stored asset?  → reuse
   │ no
   ▼
local ComfyUI (disabled) ─fail/absent─▶ SVG renderer (svg_art.py) ─▶ sanitize ─▶ data/media/files/<sha>.svg
                                                                                 data/media/assets.json
website  /media/{asset}/{article,og,preview,telegram}.{png,webp,avif}  ← rasterized from that one file
```

Details: [media/IMAGE_GENERATION.md](media/IMAGE_GENERATION.md).

**Telegram** (`cyberalertx/publish/`, `tools.publish cycle --send --limit 1`):

```
plan: one job per story × locale × destination (deterministic id), within 48 h;
      the publish ledger is imported, so anything already posted is "published"
   │
   ▼
due job → edition rendered and approved?  else wait (no attempt spent)
   │
   ▼
story illustration validated?  else wait (no attempt spent)
   │
   ▼
format caption (emoji headline, TL;DR, optional sections, severity, source) + article button
   │
   ▼
Bot API sendPhoto(https://cyberalertx.com/media/{asset}/telegram.png, caption)
   → job published + ledger line (never re-sent)
```

- **Idempotent:** job ids plus the ledger mean re-runs and reboots never
  double-post. A crash during a send leaves the job `outcome_unknown` for an
  operator rather than retrying blindly.
- **Channel-fatal errors** (bad chat id, bot not admin, bad token) pause that
  channel; transient errors retry with backoff.
- **Cost-safe:** publishing reads only cached renders; it never calls the AI.
- **Gate:** the unit's drop-in requires `/home/cax/cyberalertx/STAGE_D_AUTHORIZED`;
  removing it stops publishing. Details: [publish/PUBLICATION_ENGINE.md](publish/PUBLICATION_ENGINE.md).

---

## 8. The Claude CLI detail (why it's special)

`generate` shells out to the local `claude` CLI in headless mode (`claude -p`),
reusing your **subscription OAuth**, not a metered API key. It deliberately
strips `ANTHROPIC_API_KEY` from the subprocess environment so the call bills
the subscription instead of pay-per-token. It demands a single JSON object back
(a `ThreatPostResponse`), validates it, and on any failure — CLI missing, not
logged in, timeout, malformed JSON — falls back to deterministic **rule-based**
text. So even if Claude is unreachable, the pipeline keeps producing posts (in
the source language; translations are skipped rather than shipped half-done).
Code: `cyberalertx/ai/providers/claude_cli_provider.py`.

---

## 9. Tech stack at a glance

| Layer | Tech |
|---|---|
| Ingest / pipeline | Python, `httpx`, `feedparser`, APScheduler |
| Domain model | plain `@dataclass` (NewsItem, ThreatPost); Pydantic only at the LLM I/O boundary |
| Storage | JSON files (default) + SQLAlchemy Core 2.0 + psycopg3 → Postgres/Supabase (dual-write); raw `.sql` migrations (not Alembic) |
| AI | local `claude` CLI (subscription) → rule-based fallback |
| API | FastAPI + uvicorn, read-only |
| Frontend | Next.js 15 App Router, React 19, TypeScript, Tailwind; `/{locale}` routing (en/ua) |
| Publishing | Telegram Bot API over `httpx` (sync), JSONL ledger |
| Edge | nginx (TLS, reverse proxy) behind Cloudflare (CDN/DDoS) |
| Process mgmt | systemd (4 long-lived services + 2 timers); logs → journald |
| Observability | JSON counters + source-health + feedback JSONL, exposed at `/admin/*` |
```

---

## 10. Deployment model

```
/home/cax/cyberalertx/releases/<YYYYMMDD-HHMM-sha>/   immutable: one commit + venv + frontend build
        └── data -> /home/cax/cax/data               shared persistent data
/home/cax/cyberalertx/current -> releases/<active>   switched atomically; units run from here
/home/cax/cax/                                       git checkout (development) + .env + data/
```

A release is built once from a reviewed commit, verified file by file, and
never modified. Switching the active release (forward or back) changes only
the `current` symlink and restarts api, frontend and run. Migrations are a
separate, manual step. Details: [operations/OPERATIONS.md](operations/OPERATIONS.md).
