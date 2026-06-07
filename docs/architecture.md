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
 │ The Hacker News  │────────▶│  │ cyberalertx-run    │  every 15 min         │
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
   │ (subscription   │ render │   │ .timer  every 6h      │ writes
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
   │ Telegram Bot API│◀───────│   │ cyberalertx-telegram  │ every 6h +15min
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

## 2. The five services (systemd units) — who owns what

| Service | Type / cadence | Responsibility | Calls Claude? |
|---|---|---|---|
| **cyberalertx-run** | always-on, APScheduler every **15 min** | The ingest pipeline: fetch RSS → clean → filter → enrich → rank → persist. Deterministic. | ❌ never |
| **cyberalertx-generate** | timer, every **6h** (00/06/12/18 UTC) | Turns raw NewsItems into polished, localized **ThreatPosts** via the Claude CLI, caches them. | ✅ **only one** |
| **cyberalertx-api** | always-on, FastAPI `:8000` | Read-only HTTP feed (`/posts`, `/healthz`, `/feedback`). Merges items + cached renders. | ❌ never |
| **cyberalertx-frontend** | always-on, Next.js `:3000` | Renders the website (SSR + 60s ISR), fetching from the API. | ❌ never |
| **cyberalertx-telegram** | timer, every **6h +15min** | Sends qualifying cached posts to the TG channels; dedup via ledger. | ❌ never |

**The key invariant:** AI costs money/time, so it runs in exactly **one**
place — `generate`. Everything else (ingest, API, frontend, telegram) only
*reads* what `generate` already produced. That's what keeps cost predictable
and the mental model simple.

### Operational cadence (UTC)

```
00:00  06:00  12:00  18:00   ── generate fires (Claude renders new items)
00:15  06:15  12:15  18:15   ── telegram fires (publishes what generate just rendered)
:00 :15 :30 :45  (every 15m) ── run fires (RSS ingest)
always-on                    ── api, frontend
```
The telegram timer is offset +15 min after generate so a freshly rendered
batch is publishable in the same cycle it was rendered.

---

## 3. The ingest pipeline (inside cyberalertx-run, every 15 min)

```
fetch RSS (parallel, httpx + feedparser)
   │   one bad feed can't break the run
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

---

## 4. The data stores (what lives where)

| Store | Holds | Written by | Read by |
|---|---|---|---|
| `data/items.json` | raw NewsItems (capped archive) | run | api, generate, telegram |
| `data/threat_posts.json` | AI renders, keyed `fingerprint:locale` | generate | api, telegram |
| **Postgres** (Supabase) | shadow copy of both tables | run, generate (dual-write) | parity checks / future read path |
| `data/telegram_published.jsonl` | "already posted" ledger | telegram | telegram (dedup) |
| `data/feedback.jsonl`, `*_metrics.json`, `source_health.json` | observability | api, run | you (`/admin/*`) |

**Storage backend** is selected by `CYBERALERTX_STORAGE_BACKEND`:
`json` (files only) or `dual` (files **and** Postgres; prod runs `dual`). In
`dual` mode every write fans out to both; if Postgres is down the write path
degrades to JSON-only and logs a warning — the pipeline never breaks because
the DB is unreachable.

**Why two models?** `NewsItem` (metadata) and `ThreatPost` (the readable
content) are deliberately separate: **one NewsItem → up to two ThreatPosts**
(en + ua). EN-source items render both locales; UA-source items render UA only
(never auto-translated to English — the asymmetric multilingual rule).

---

## 5. Lifecycle of one story (end to end)

```
T+0min   BleepingComputer publishes "Everest Forms Pro RCE"
T+≤15min run: fetches it → scores Critical/urgent → saved to items.json (raw, no prose)
         ↳ at this point it's on NO channel and NOT on the public feed yet
T+≤6h    generate: picks it (newest, uncached) → Claude CLI writes the UA+EN
         ThreatPost (title, summary, quick_facts, CVE refs) → threat_posts.json
         ↳ NOW it appears on the website feed (api serves cached renders only)
T+≤6h15m telegram: sees it's cached + Critical + trusted + not in ledger →
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

## 7. The Telegram publish path (cyberalertx-telegram)

```
list NewsItems (items.json)
   │  tier filter: trusted / verified only
   ▼
for each configured channel (en, ua), newest first:
   render_if_cached(item, locale)   ── cache hit? else skip (NEVER calls Claude)
      │
      ▼
   qualifies?  threat_level ≥ High  OR  actionability = urgent_action
      │
      ▼
   quality gate: non-empty title, right script for the locale
      │
      ▼
   already in ledger?  → skip
      │
      ▼
   format HTML (level emoji, bold title, summary, quick facts,
                CVE→NVD links, "Read more" → our site)
      │
      ▼
   Bot API sendMessage → channel   → record fingerprint:locale in the ledger
```

- **Idempotent:** the JSONL ledger means re-runs / reboots never double-post.
- **Channel-fatal errors** (bad chat id, bot-not-admin, bad token) abort that
  channel after one attempt instead of retrying every item.
- **Cost-safe:** it reuses the API's provider-less `_PostService`, so an
  un-rendered item just yields `None` and is skipped — no AI call ever fires
  from publishing. Code: `cyberalertx/publish/`.

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
