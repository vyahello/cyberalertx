# Production readiness — Phase 7

**Date:** 4 Nov 2026
**Worktree:** `/home/cax/cax-redesign`, branch `redesign/cti-platform`, HEAD
`73257f0` plus uncommitted Phase 1–7 work (preserved).
**Production:** `/home/cax/cax`, branch `main`, HEAD `73257f0`, clean, untouched.

Nothing was deployed, committed, pushed, published or sent. No production
data, service, timer, environment variable or database was changed. No paid AI
or image call was made.

**Evidence labels used below:**

| Label | Meaning |
|---|---|
| **[verified]** | Ran here: a test, measurement or read-only inspection |
| **[mocked]** | Tested against a fake external API |
| **[assumption]** | Reasoned, not run |
| **[recommendation]** | Proposed, not done |

## Verdict: **READY WITH CONDITIONS** for a staged rollout

The code passes everything that can be tested without real external accounts.
That includes three defects found in this phase and fixed (OPEN_ISSUES F1–F3).
The platform may go to **Stage B** (release candidate in a separate directory)
now, and to **Stage C** (controlled manual operation) after the conditions below.

New automated publishing (Stage D) and Threads (Stage E) each still need
real-world verification that only the administrator can authorize.

**Conditions:**
1. Upgrade the frontend dependencies (O1) in the release candidate.
2. Build the release venv from `requirements.lock` (O2, O3).
3. Back up `data/` and Supabase before switching.
4. Accept that audit attribution is unverified while there is a single shared
   admin password (O11).
5. Get explicit authorization for every stage.

| Dimension | State | Why |
|---|---|---|
| 1. Code | Ready | All six phases integrate. The end-to-end suite over 12 synthetic scenarios passes. F1–F3 fixed. |
| 2. Tests | Ready | 1383 passed, 1 skipped (environment locale) in both the production-venv and release-venv configurations against an isolated PG 16. mypy strict and tsc are clean. Next build is OK. Playwright: 39 passed, 2 failed (environmental `/healthz`), 1 skipped. |
| 3. Infrastructure | Conditions | The release-directory procedure is written but not executed. Units are root-owned, so switching them is an admin step. |
| 4. Database | Conditions | Migrations 001–005 are tested on an isolated PG 16 (fresh, upgrade, failure, restart). 005 is not yet applied to Supabase. Review persistence has not been run against a Supabase test project. |
| 5. External integrations | Not verified | Telegram legacy text delivery is proven in production. Every new delivery path (sendPhoto, job worker, reconciliation, all of Threads) is **[mocked]** only. Meta app and accounts do not exist yet. |
| 6. Operations | Conditions | `/admin/system` and `/admin/publishing` give visibility, but there is no alerting. The job store needs periodic pruning. The scheduler switch is planned, not done. |
| 7. Security | Conditions | Admin gate, CSRF, CSP, encryption and redaction are tested. There are pre-existing dependency advisories (O1, O2), a shared admin identity (O11), and no nginx rate limit (O12). |

The missing image provider does **not** reduce readiness: branded cards cover
publication by design [verified].

---

## 1. Architecture validation (actual implementation)

Identifiers through the pipeline:

| Identifier | What it is |
|---|---|
| **Article id** | `NewsItem.fingerprint`, a hash of the URL. Used by the API, website URLs `/{locale}/threat/{fingerprint}`, the post cache key `{fingerprint}:{locale}`, the Telegram ledger, cards, and a job's `fingerprint`. |
| **Story id** | `story_key`, assigned at ingest by `dedup.assign_incremental`, first-seen-wins and never moved. Since F1, the Intelligence Core uses that same key (`intel/story.py: stable_key`), so publication jobs, score history, Breaking state and illustrations stay attached to one identity. |
| **Locale** | Every edition is keyed by (fingerprint, locale) with locale `en` or `ua`. Threads slots map one-to-one to a locale; a mismatch is rejected [verified]. |
| **Attribution** | `item.source` and `item.url` → API payload `source` / `source_url` → website article and JSON-LD → Telegram "Source:" line → Threads "Source:" / "Джерело:" line (added in Phase 7) [verified]. |

| Stage | Implementation | Input → output | Persistence | Errors and retries | Recovery | Limits |
|---|---|---|---|---|---|---|
| Sources | `sources/registry.py`, `rss.py` (`SETTINGS.sources` in code) | feeds → `NewsItem`s | — | A crashing source is logged and skipped; the others continue [verified] | Next cycle (`run --interval 30`) | Configured in code (O15) |
| Ingest and normalize | `pipeline/orchestrator.py: Pipeline.run_once`, `normalize_all` | items → cleaned items, language | `data/items.json` (atomic rename) + PG `news_items` (dual) | Known fingerprints skipped (no duplicates) [verified] | Atomic write keeps the previous file on crash [verified] | 200 items retained in JSON |
| Relevance | `filter.py` (drop non-security), `relevance.py: stamp_relevance`, overrides | → in_scope / needs_review / out_of_scope | JSON fields; PG after 005 | Out-of-scope items are stored but not rendered [verified] | `effective_relevance` re-derives when the field is empty | Non-security items are dropped at ingest, counted in source health |
| Clustering | `dedup.assign_incremental` (ingest), `cluster_items` (audit and Core) | → `story_key`, `duplicate_of`, decisions with confidence | JSON + PG (004) | Overrides `data/stories/overrides.json` [verified] | Split/merge CLI | 5-day window (O18) |
| Fact sheets | `ai/fact_sheet.py: get_or_create_fact_sheet` | article → FactSheet (sanitized against the source text) | `data/fact_sheets.json` | A failure is recorded as `failed` and the brief renders without it [verified] | Never retried automatically for that article | One extra AI call per article (O7) |
| Evidence | `fact_sheet.cluster_evidence` | sheets → confirmed / reported facts, contradictions | in memory | Unverified never becomes confirmed [verified] | — | — |
| Intelligence | `intel/engine.py: run` (scoring, dimensions, selection) | stories → evaluations, Top 10, trending, Breaking | `data/intel/` (shadow) | One failing story is skipped and listed in failures | Deterministic recompute [verified] | Shadow only; selection affects job priority only |
| Editorial EN/UA | `ai/generator.py: ContentGenerator.generate` + validators | article + sheet → `ThreatPost` per locale | `data/threat_posts.json` + PG `threat_posts.payload` | Provider error or validation failure → rule-based, **not cached**, so the next run retries [verified] | Timer, hourly | — |
| Review | `ai/review.py`, `/admin/review` | → auto / pending / approved / rejected | Post cache; strict dual-write for decisions | PG down → reported, not silent (Phase 2 tests) | Retry syncs | `flag` default; `hold` needs O5 |
| Media | `media/` (cards on request in Next; illustrations via provider) | payload → cards; story → illustration | `data/media/` | Provider or storage failure recorded, never blocks [verified] | Retry limit 3; `regenerate` | No provider (O13) |
| Publication planning | `publish/orchestrator.py: plan` | stories × editions × destinations → jobs | `data/publish_jobs.json` | Idempotent ids; per-article safety net (F1) [verified] | — | — |
| Worker | `orchestrator.run` + destinations | jobs → deliveries | job store + Telegram ledger | Classified errors, backoff, `outcome_unknown`, expiry (F2) [verified, mocked] | Lease recovery [verified] | Not yet scheduled (§15) |
| Monitoring | `ops/` + `/admin/*` | records → views, audit | `admin_audit.jsonl`, `ai_usage.jsonl` | — | — | No alerting (O17) |

Data transformed or lost between stages, by design:
- non-security items are dropped at ingest;
- later coverage of a story becomes `duplicate_of` and is not rendered separately;
- identifiers not present in the source text are removed from fact sheets
  (sanitizer) [verified].

Nothing else is dropped. Rollback is the exception (O19).

## 2. End-to-end results [verified, mocked externals]

`tests/test_e2e_pipeline.py` (20 tests) runs the real stages over
`tests/fixtures/e2e_dataset.py`. The dataset is 15 articles covering the 12
required scenarios, all marked `[SYNTHETIC TEST DATA]`.

| Scenario | Result |
|---|---|
| 1 Critical, confirmed exploitation (CISA) | Verified, confidence high, exploitation confirmed, Breaking, top priority on all six destinations |
| 2 New vulnerability, no exploitation | Exploitation not confirmed |
| 3–6 Ransomware / breach / phishing / malware | Ingested, in scope, own stories, categories set |
| 7 Two articles, same event | One story, one canonical, 2 independent sources |
| 8 Similar but unrelated | Separate stories |
| 9 Outdated + new development (6 days) | **Separate stories**: known window limit (O18) |
| 10 Non-security | Never stored |
| 11 Conflicting claims | One story; contradiction preserved |
| 12 Low-confidence, high-impact | Unverified, low confidence, not Breaking, not Top 10 |

Also verified:
- duplicate ingestion creates nothing;
- a failed source recovers on the next cycle;
- a crash mid-write leaves the previous file;
- split override;
- invented CVE and CVSS values dropped;
- one fact sheet per article, reused by both locales;
- EN and UA generated separately from the same facts;
- an unsupported identifier rejected;
- AI timeout falls back and is not cached;
- review rejection hides only that edition;
- distinct, stable card URLs per locale;
- `NoProvider` records no attempt;
- the mock illustration appears only for the eligible story;
- six destinations with one Telegram 502 isolated and retried once;
- locale routing for every message and post;
- a second plan/run sends nothing;
- the admin pages make no network or AI call.

### Test regression summary (actual runs, Phase 7)

| Configuration | Result |
|---|---|
| Production venv + `cryptography` + isolated PG 16 | **1383 passed, 1 skipped** (no non-C locale on this box) |
| Release-candidate venv (`requirements.lock`) + isolated PG 16 | **1383 passed, 1 skipped** |
| Production venv exactly as installed (no `cryptography`, no PG) | 1327 passed, 7 skipped (Threads, PG and crypto-dependent tests skip cleanly) |
| Live PG only (`test_pg_migrations_live.py` + `test_pg_review_live.py`) | 7 passed |
| mypy strict (both venvs) | clean, 119 files |
| tsc | clean |
| `next build` | compiled |
| Playwright (chromium + mobile) | 39 passed, 1 skipped, 2 failed: `/healthz` only, environmental (O23) |

**Versus Phase 6** (1343 passed, 4 skipped, without PG):
- the live PG tests now run instead of skipping;
- new tests were added: `test_e2e_pipeline.py` (20), `test_pg_migrations_live.py` (4), `test_release_readiness.py` (6), and 3 in `test_publication.py`;
- no earlier test was removed;
- the only assertions changed were the deliberate Threads attribution update (`test_threads.py`).

**Lint:** not configured for Python or JS, so recorded rather than added (O22).

## 3. Failure injection [verified, mocked]

| Failure | Test | Result |
|---|---|---|
| Crash during ingestion write | `test_crash_during_store_write_leaves_previous_data_intact` | Old file intact; next run completes |
| Worker crash after claim / mid-send | `test_crash_mid_run_recovers_without_resending` | Retried, or `outcome_unknown` if mid-send |
| DB unavailable during a review decision | `test_unreachable_postgres_is_reported_and_retry_syncs`, `test_dual_write_failed_postgres_is_reported_not_silent` | Reported, not silent; sync on retry |
| Storage unavailable during media | `test_storage_failure_is_recorded_not_raised` | Recorded as failed |
| AI provider timeout | `test_unsupported_identifier_is_rejected_and_fallback_is_not_cached` | Rule-based fallback, not cached, recovers |
| Telegram 429 / 502 / dropped connection | `test_rate_limit_respects_retry_after…`, the e2e six-destination test, `test_unknown_outcome_is_not_retried_and_reconciles` | Backoff ≥ retry_after; isolated; never resent blindly |
| Threads container created, response lost | `test_crash_after_container_creation_resumes_it` | Same container resumed |
| Threads published, response lost | `test_publish_timeout_after_success_is_recognised`, `test_unknown_outcome_is_never_blindly_retried_and_reconciles` | Detected via the container, or held for reconciliation |
| Two workers on the same jobs | `test_two_concurrent_workers_never_send_the_same_job` (4 threads; fails without the lock), `test_planning_and_running_twice_and_concurrently_post_once` | Each job once |
| Restart with unfinished jobs | lease recovery tests | No loss, no blind resend |

Not found anywhere: silent data loss, infinite retry (bounded attempts;
`auth` / `permission` fail immediately), cross-locale publication, or orphaned
media corrupting the pipeline.

**Delivery guarantees.** Internally, each job is processed exactly once.
Externally, neither Telegram nor Threads offers idempotency keys, so a lost
response becomes `outcome_unknown`, which is never resent automatically. It
is reconciled by a person (Telegram) or from the container state (Threads).

## 4. Concurrency [verified]

| Test | Result |
|---|---|
| Job claims | `fcntl` lock with atomic rename; the 4-worker test fails with the lock removed |
| Review cache writers | Phase 2 concurrency test passes |
| Job-store lock contention | 80 contended updates: 3.3 s at 1k jobs, 14.5 s at 5k, 42 s at 15k. Linear in file size, hence the weekly prune (O20). |

## 5–6. PostgreSQL and migrations

| Check | Result |
|---|---|
| Environment | Isolated `postgres:16-alpine` (tmpfs, localhost, removed afterwards). Never Supabase; the test refuses a Supabase URL. |
| `test_pg_migrations_live.py` (new, 4 tests) | Pass: fresh init + idempotent re-run; upgrade 001–004 → 005 with data preserved; new code on the old schema (writes still work), then restart → columns used; broken migration rolled back and earlier versions kept, then the fixed file applied |
| `test_pg_review_live.py` (Phase 2, 3 tests) | Pass |
| Runner | `tools/pg_migrate.py`: one transaction per file, `schema_migrations` bookkeeping, forward-only (README) |

**Data that stays JSON-only:** fact sheets, intel scores, media assets, publication jobs, Threads accounts, admin audit, AI usage.

**Why that's acceptable:** JSON is the authoritative store; Postgres is a write mirror (reads stay on JSON). These records are operational state of a single host, written by one process type, with the file locks tested. Moving them to Postgres would add failure modes without a reader that needs it.

**Recommendation:** revisit this only when a second host or a Postgres read-path is planned.

**Supabase:** apply 005 after a backup (DEPLOYMENT_RUNBOOK §5). It is safe before or after the code deploy.

## 7. AI editorial benchmark: plan (not run; needs authorization)

- **Command:** `python -m cyberalertx.tools.benchmark --fp 5ff3e4930a9500af --fp 0f81648bf5c6b707 --fp c741ac626ea63cce --fp 9406dd2ee53324ce`
- **Dry run [verified]:** all four exist and nothing was written.

| Story | Why it was chosen | Calls |
|---|---|---|
| Ivanti Connect Secure zero-days (EN source, BleepingComputer) | Exploited vulnerability with identifiers; tests the fact sheet and the UA vulnerability vocabulary | 3 (sheet + EN + UA) |
| Synology / C3RB3R ransomware (EN source) | Earlier output asserted unsupported background (BENCHMARK_EXAMPLES §1) | 3 |
| «Повітряна тривога» breach (UA source, ain.ua) | UA-only, multi-source cluster, attribution | 2 (sheet + UA) |
| DOU News roundup (UA source) | Low-signal roundup; tests relevance and restraint | 2 |
| **Total** | | **10** |

**Expected tokens** (from 2,049 recorded production calls), per call:

| Input | Cache write | Cache read | Output |
|---|---|---|---|
| ≈ 657 | ≈ 10.9k | ≈ 17k | ≈ 1.9k |

For 10 calls that is about 6.6k input, 109k cache-write, 170k cache-read and
19k output tokens. This is **[assumption]**: fact-sheet calls are smaller than
renders.

**Cost:**
- Production uses `claude_cli` on the subscription, so there is no per-call
  billed amount. The calls count against the subscription's usage limits.
- From this release on, the usage ledger records the CLI's notional
  `total_cost_usd` per call.
- No dollar figure is estimated here, because no verified rates are on record.
- If run via the API instead, cost = the token counts above × the then-current
  published rates for the configured model.

**Expected outputs:** `data/editorial/benchmark/REPORT.md` (before/after per
field, plus scorecards), with a separate cache that is never served.

**Evaluation criteria:**
- every factual claim traces to the source;
- identifiers intact;
- no unsupported background;
- UA reads as native editorial (editor judgement);
- scorecard ≥ the review threshold;
- the fact check passes.

`BENCHMARK_EXAMPLES.md` "after" texts were **hand-edited by Claude**, not model
output, and must not be compared as if they were.

## 8. Media readiness [verified]

- **Branded-card-only mode works:**
  - `NoProvider` records no attempts;
  - `/admin/media` and `/admin/system` show "not configured — by design";
  - publication proceeds without illustrations.
- **Card routes:** 200 for all variants. Cold render 0.09–0.15 s.
- **To enable illustrations later [recommendation]:** choose a provider,
  implement `ImageProvider`, set `CYBERALERTX_IMAGE_PROVIDER`, test with
  `tools.media run --max-calls 1` (MEDIA_ENGINE.md).

## 9. Telegram readiness

| Aspect | State |
|---|---|
| Current production path | `publish-telegram --limit 1` from `cyberalertx-telegram.service`, 10 fires a day. Proven: 3,046 ledger entries [verified, read-only]. |
| Request implementation | `TelegramPublisher._post`, sendMessage / sendPhoto; error categories; no inline sleep in the worker [verified, mocked] |
| Photos | `CYBERALERTX_TELEGRAM_ATTACH_IMAGES`, default **off** [verified]. Text fallback only on a definite refusal; never after an unknown outcome. |
| Rate limit | 429 → `retry_after` floor; channel paused for the run [mocked] |
| Unknown outcomes | `outcome_unknown` → `/admin/publishing` reconcile (needs the message id from the channel) [mocked] |
| Per-channel status | `/admin/publishing` and `/admin/threads` (Telegram panel) [verified] |
| Live validation (Stage C) | A private test channel, a test bot added as admin, test `CHANNEL_EN/UA` values in a *separate* env file. Run `tools.publish cycle --send --limit 1` against it, confirm locale, photo and fallback, then restore. |

## 10. Threads readiness

- **[mocked] only:** OAuth (state, CSRF, slot binding), encryption, refresh,
  `graph.threads.com/v1.0`, container create / status / publish,
  reconciliation, per-account errors.
- **Disabled by default:** `CYBERALERTX_THREADS_PUBLISH` is off by default
  [verified], and `_threads_destinations` returns nothing.
- **Dependency:** `cryptography>=42.0` is declared in `requirements.txt` and
  pinned to 50.0.2 in `requirements.lock`. Without it the API still serves,
  and Threads fails closed with "cryptography package: missing". There is
  **no plaintext fallback**: no key or no package means nothing is written
  [verified, `test_release_readiness.py`].
- **Install:** with the release venv (`pip install -r requirements.lock`).
- **Live validation:** THREADS_SETUP.md §1–15 (blocked on the Meta app).

## 11. Admin security assessment

**Verified:**
- the gate covers every `/admin/*` path, including the new font route;
- 401 without credentials, on GET and POST;
- every POST requires same-origin, an HMAC CSRF token and a confirm box;
- `form-action 'self'` everywhere (GET filters), `script-src` absent
  (`default-src 'none'`), `frame-ancestors 'none'`, `no-store`, `noindex`;
- secrets never rendered (bot token, app secret, private chat ids, Fernet
  key, DB URL);
- `back=` restricted to `/admin/publishing` (no open redirect);
- audit metadata redacted;
- admin pages make no AI or network calls;
- files 0600 (`data/*`, `.env`).

**Shared admin password (O11).** There is one secret (`CYBERALERTX_ADMIN_TOKEN`),
and Basic auth accepts *any* username. Consequences:

| Concern | Consequence |
|---|---|
| Attribution | The audit "actor" is what the person typed. It is a label, not an identity. Pages and docs present it as "typed name", never as verified. |
| Accountability | Anyone with the token can act as anyone. |
| Audit reliability | Action, target, time, result and client address are reliable; the actor is not. |
| Multiple administrators | Not distinguishable. |
| Incident investigation | Limited to address and time. |

**Recommendation:**
- **Acceptable for one administrator.**
- **Before a second administrator:** add per-user tokens to the existing gate.
  For example, `CYBERALERTX_ADMIN_USERS` holds `user:sha256(token)` pairs; the
  Basic username must match its own token, and the audit records that verified
  name. This reuses the gate, lockout and CSRF (keyed per user).
- **Alternative:** put SSO at the edge (Cloudflare Access) and record the
  asserted email header.
- **Migration path:** keep `CYBERALERTX_ADMIN_TOKEN` as a break-glass account,
  add users, then retire the shared token.

**Other findings:**
- No nginx `limit_req` (O12).
- Outbound requests go only to configured or validated URLs (feeds, Telegram,
  Threads graph, our own card URLs with a prefix check, the frontend probe), so
  there is no user-controlled SSRF.
- Media is validated by magic bytes, size and dimensions; asset paths are
  hex-only (traversal tests).
- CORS rejects foreign origins.

**Dependencies:** see §13 and O1/O2.

## 12. Performance [verified, local]

| Path | Measured |
|---|---|
| Home `/en` (ISR) | 3–10 ms |
| Article | 0.26 s cold, 6 ms warm |
| Card render (og / telegram / portrait) | 0.09 / 0.09 / 0.15 s |
| API `/posts?limit=20` | ≈ 0.056 s steady (one cold outlier 0.78 s) |
| Admin overview | ≈ 1.3 s first after a data change; ≈ 0.25 s warm |
| Admin stories, publishing, usage | < 10 ms warm |
| Job store update | 36 ms at 1k jobs, 0.2 s at 5k, 0.5 s at 15k |
| Memory (RSS) | Production API ≈ 137–195 MB; worktree API ≈ 104 MB; Next ≈ 400 MB |
| Production volume [verified, read-only] | ≈ 25 canonical articles a day |

**Projected job volume:** about 100 jobs a day, so 3k at a 30-day prune
(update latency ≈ 0.1 s).

**Suggested monitoring thresholds** (from these measurements):

| Signal | Threshold |
|---|---|
| Admin `/admin/system` overall | critical |
| `outcome_unknown` | > 0 |
| `failed` jobs | > 0 for 24 h |
| Ingest last cycle | > 3 h |
| Brief cache write | > 12 h |
| Job file size | > 5 MB |
| Disk free | < 15 % |

No SLA is implied.

## 13. Dependencies and environment

| Area | Detail |
|---|---|
| Runtimes | Python 3.12.3; Node 20.20.2 [verified]. Disk 42 GB free on `/home`; `data/` is 233 MB. |
| Python | `requirements.txt` (ranges) and **`requirements.lock`** (exact set tested in Phase 7: fastapi 0.162.0, starlette 1.10.0, anyio 4.16.0, cryptography 50.0.2, SQLAlchemy 2.0.57, psycopg 3.3.7, pydantic 2.14.2, httpx 0.28.1). `pip-audit`: none. Full suite and mypy pass in that venv. |
| Node | `frontend/package-lock.json`; upgrade pending (O1) |
| Build-time env (`frontend/.env.production`) | `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_UMAMI_WEBSITE_ID`. API_URL defaults to `127.0.0.1:8000`. |
| Runtime env (`/home/cax/cax/.env`, names only) | Existing: `ANTHROPIC_API_KEY`, `CYBERALERTX_ADMIN_TOKEN`, `CYBERALERTX_AI_*`, `CYBERALERTX_CLAUDE_CLI_BIN`, `CYBERALERTX_INTERVAL_MIN`, `CYBERALERTX_OTHER_VHOSTS`, `CYBERALERTX_PG_URL`, `CYBERALERTX_RSS_PROXY_URL`, `CYBERALERTX_STORAGE_BACKEND=dual`, `CYBERALERTX_TELEGRAM_BOT_TOKEN`, `CYBERALERTX_TELEGRAM_CHANNEL_EN/UA`, `CYBERALERTX_TELEGRAM_MIN_LEVEL=Medium`, `CYBERALERTX_UA`. **No new variable is required for Stage B/C.** |

## 14. Feature flags and settings (defaults read from code)

| Setting | Code default | Purpose | Safe initial production value | Dependencies |
|---|---|---|---|---|
| `CYBERALERTX_REVIEW_MODE` | `flag` | off / flag / hold visibility of pending posts | `flag` (unset) | `hold` needs O5 + approval |
| `CYBERALERTX_REVIEW_THRESHOLD` | scorecard default | Score below which a post is queued | unset | — |
| `CYBERALERTX_HIDE_OUT_OF_SCOPE` | off | Also hide already published out-of-scope items | off | — |
| `CYBERALERTX_FACT_SHEET` | **on** | One fact-sheet call per article before rendering | on (approved +1 call) or `0` at first (O7) | AI provider |
| `CYBERALERTX_AI_PROVIDER` | `claude_cli` | Text provider | unchanged (`claude_cli`) | CLI login |
| `CYBERALERTX_AI_MODEL` / `_CLAUDE_CLI_MODEL` | haiku 4.5 / CLI default | Model | unchanged | — |
| `CYBERALERTX_AI_PRICES` | unset | Operator rates for cost estimates | unset | — |
| `CYBERALERTX_STORAGE_BACKEND` | `json` | json / dual | `dual` (as now) | `CYBERALERTX_PG_URL`, migrations |
| `CYBERALERTX_TELEGRAM_ATTACH_IMAGES` | off | sendPhoto with the card | **off** | Public card routes deployed |
| `CYBERALERTX_TELEGRAM_LIMIT` | 5 | Per channel per run (CLI `--limit` overrides) | units pass `--limit 1` | — |
| `CYBERALERTX_TELEGRAM_MIN_LEVEL` | High | Severity bar | `Medium` (as now) | — |
| `CYBERALERTX_TELEGRAM_SEND_DELAY_S` | 1.0 | Pacing | default | — |
| `CYBERALERTX_PUBLISH_WINDOW_HOURS` | 48 | New jobs only, plus social expiry | default | — |
| `CYBERALERTX_PUBLISH_MAX_ATTEMPTS` | 5 | Retries per job | default | — |
| `CYBERALERTX_PUBLISH_RETRY_BASE_S` / `_CAP_S` | 120 / 21600 | Backoff | default | — |
| `CYBERALERTX_PUBLISH_TOP10_AT` | unset | Hold Top 10 social posts until HH:MM Kyiv | **unset** | — |
| `CYBERALERTX_PUBLISH_BREAKING_UPDATES` | off | Telegram follow-ups | **off** | Editorial review |
| `CYBERALERTX_THREADS_PUBLISH` | off | Threads destinations exist | **off** | O9, O10, `cryptography`, key |
| `CYBERALERTX_THREADS_APP_ID` / `_SECRET` / `_REDIRECT_URI` / `_TOKEN_KEY` / `_ACCOUNTS` | unset / `en:en,ua:ua` | OAuth and encryption | unset until Stage E | Meta app |
| `CYBERALERTX_THREADS_LIMIT` / `_MIN_LEVEL` | 1 / High | Per account per run / bar | defaults | — |
| `CYBERALERTX_IMAGE_PROVIDER` | `none` | Illustration provider | `none` | O13 |
| `CYBERALERTX_ILLUSTRATION_MAX_PER_RUN` / `_MIN_SCORE` / `_TOP_N` | 3 / 55 / 3 | Cost caps / eligibility | defaults | provider |
| `CYBERALERTX_PUBLIC_BASE_URL` | `https://cyberalertx.com` | Links and card URLs | default | — |
| `CYBERALERTX_FRONTEND_PROBE_URL` | `http://127.0.0.1:3000/en` | Health probe | default | — |
| `CYBERALERTX_INTERVAL_MIN` | 15 (unit passes 30) | Ingest interval | as now (30) | — |
| Timezone | Europe/Kyiv (intel config) | Editions, admin days | unchanged | — |

## 15. Scheduler transition

See DEPLOYMENT_RUNBOOK §7. Verified findings:

- **`--limit` semantics:** `--limit 1` caps **Telegram per channel per run**,
  as the legacy command does. Website jobs use their own cap (500, internal
  recording only). Threads uses `CYBERALERTX_THREADS_LIMIT` (and is off)
  [verified, `test_limit_semantics_for_the_scheduler_plan`].
- **Timeout:** with Threads off, a run is plan (≈ 1–3 s Core view) plus up to
  2 sends (≤ 15 s timeout + 1 s pacing each) plus website recording (≈ 0.1 s per
  job). **300 s is enough.** Raise it to 600 s only when Threads is enabled
  (worst case ≈ 150 s container wait per account). This corrects the Phase 5
  advice to raise it unconditionally.
- **Ordering and expiry:** newest first, social jobs expire after 48 h (F2).
- **Concurrency:** one unit, so the old and new commands never run together.
  Manual `publish-telegram` must not be run after the switch. Both paths
  honour the shared ledger anyway.

## 16–17. Release and rollback

See DEPLOYMENT_RUNBOOK.md and ROLLBACK_RUNBOOK.md.

## 18. Open issues

See OPEN_ISSUES.md (F1–F3 fixed; O1–O24 open or accepted).

## 19. Manual actions required from the administrator

1. **Authorize Stage B** (release candidate build; no service change).
2. **Back up** `/home/cax/cax/data` and the `.env` file, and take a Supabase
   backup (DEPLOYMENT_RUNBOOK §2).
3. **Decide** on the fact-sheet call budget (O7) and confirm review mode
   `flag`.
4. **Authorize and apply migration 005** to Supabase (§5), or defer it.
5. **Authorize Stage C:** sudo to install the new unit files (§6), and switch
   services during a quiet hour.
6. **Optional before Stage D:**
   - create a private Telegram test channel and test bot;
   - authorize the 10-call benchmark (O6);
   - point `CYBERALERTX_TEST_DB_URL` at a Supabase **test** project and run the
     live review tests (O5).
7. **Before a second administrator:** decide on per-user admin credentials (O11).
8. **For Threads:** create the Meta app and add the testers
   (THREADS_SETUP.md); keep `CYBERALERTX_THREADS_PUBLISH=0` until both slots
   verify.
