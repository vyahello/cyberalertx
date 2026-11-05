# Phase 6 — Admin control room: final report

> **Status: historical record.** Paths such as `/home/cax/cax-redesign` and the deployment steps described here predate the release layout; see [docs/README.md](../README.md) for current documents.

All work was done in `/home/cax/cax-redesign` (branch `redesign/cti-platform`).

Nothing was deployed, committed or pushed. No real publishing was activated
and no messages were sent. Production is unchanged: its git status is clean,
and `data/` has no new files. Details of the dashboard are in
`docs/admin/ADMIN_DASHBOARD.md`.

## 1. Existing admin architecture

- **Where it runs.** Server-rendered HTML on the FastAPI app under `/admin`.
  The browser runs no JavaScript.
- **Access.** One gate covers every `/admin/*` path:
  - HTTP Basic against `CYBERALERTX_ADMIN_TOKEN`, minimum 24 characters;
  - lockout per address;
  - strict CSP;
  - `no-store` and `noindex`.

  The review queue's POST is protected by `same_origin()` plus a stateless
  HMAC CSRF token.
- **Pages before this phase:** overview, review, feedback, metrics (quality),
  sources, intel, media, publishing, threads (with OAuth routes), each with
  JSON.
- **Data sources:**

  | Source | What it holds |
  |---|---|
  | JSON stores | items, posts, intel `latest`/`scores`, cluster and relevance reports, media `assets`, publication jobs, Threads accounts, Telegram ledger |
  | `quality_metrics.json` | Cumulative counters, no dates |
  | `source_health.json` | Aggregates per source |
  | Postgres | Mirror only when `dual` |

- **Missing:** an audit log, dated AI usage, run records beyond file times,
  and an exception store.

## 2. Components reused

All existing pages and JSON endpoints kept their URLs. The rest of what was
reused:

| Area | Reused component |
|---|---|
| Admin access | `AdminGuard`, `same_origin`, `csrf_token` / `csrf_ok` |
| Page rendering | `ui.page`, `tile`, `panel`, `pill` |
| Overview and sources | The existing overview alerts and tiles; `classify_sources` |
| Intelligence | `intel.engine.run(write=False)`; `SourceTable` for reliability |
| Feeds | `sources.registry.build_sources` |
| Publishing | Publication Engine actions `retry_job`, `cancel_job`, `reconcile_job`; `PublishLedger` |
| Media | `MediaStore` |
| Threads | `AccountStore` and the OAuth routes |
| Telegram | `build_telegram_settings` |
| Storage | The Postgres engine |
| Fonts | Media Engine fonts (Fira Sans Condensed) |
| Logging | `logsafe.redact` |

## 3. New navigation and structure

- **Grouped sidebar.** Overview, then four groups:
  - Intelligence: Stories, Daily selection.
  - Editorial: Review, Feedback, Quality.
  - Media: Media studio.
  - Distribution: Publications, Social accounts.
  - Operations: Sources, AI usage, System health.
- **Header:** global search.
- **Other:** breadcrumbs, the Aperture glyph, and the site's interface font.
- **New pages:** `/admin/stories`, `/admin/stories/{key}`, `/admin/usage`,
  `/admin/system` (+ `.json`), `/admin/search`.
- **Unchanged:** all old URLs.

## 4. Overview

The existing health view is kept, and four sections are added below it.

- **Tiles.** Labelled by type (stories vs articles) and by Kyiv day:
  - stories today (in scope, from N articles);
  - stories and editions awaiting review;
  - deliveries today (Telegram ledger plus jobs);
  - delivery problems;
  - live Daily Top 10 with breaking/trending counts.
- **Pipeline.** Nine stages, each with its last recorded execution, counts,
  status and a link.
- **Destinations.** Six destinations with job counts per status and last
  delivery. Threads shows *publishing on/off* separately from *account
  state*.
- **Intelligence.** Top 10, breaking, trending, and low-confidence in-scope
  stories.
- **Recent activity.** Recorded events only.

## 5. Intelligence

**Stories list.** Every Core story with:
- title, articles and sources;
- relevance, score, confidence, verification, exploitation, category;
- Top 10 / trending / breaking flags and fact-sheet availability;
- review state per edition.

It supports filters for every field listed in the spec plus dates and
selection, sorting, and server-side pagination.

**Story detail.** Shows:
- dimensions with the reasons behind each;
- score components with their explanations;
- source articles;
- evidence, kept in separate sections: confirmed (two independent origins or
  a primary source), reported, attributed claims, contradictions, unknowns,
  identifiers and products;
- editions, publication jobs, media;
- clustering decisions (rule, confidence, reason).

With no fact sheet, the page says so and infers nothing. Corrections point to
the existing `tools.stories` overrides; no new merge system was added.

## 6. Editorial

- `/admin/review` is kept as it is: tabs, per-edition cards, scorecard
  findings, the active-mode banner, and flag/hold semantics unchanged.
- Decisions are now audited, recording the actor, the target
  `fingerprint:locale`, and the *previous* status.
- Stories link to the review queue, and the overview counts pending items.

## 7. Media

- **Additions:** search by story id, asset id or headline (alt text), and
  the provider's last success.
- **Honest provider state:** "not configured — branded cards only, by
  design" is shown neutrally, not as a failure.
- **Regeneration:** "queue regeneration" (confirmed, audited) appears only
  when a provider is configured. It does what `tools.media regenerate` does
  and never calls a provider from the page.

## 8. Publications

- **Overview:** six destination tiles; each links to its filtered view.
- **Filters:** destination, language, status, story/job/post id, minimum
  priority, date range. Pagination is 50 per page, server-side.
- **Columns:** story, job, destination and type, status, priority,
  scheduled/next attempt, attempts, last error, result link or external id,
  update time.
- **Actions** (confirmed, CSRF-protected, audited, via the engine):
  - retry (failed/cancelled);
  - cancel;
  - reconcile delivered (id validated) or not delivered.

  `outcome_unknown` is never offered a retry, and a forced POST is refused by
  the engine (and audited). The `back` parameter is restricted to
  `/admin/publishing`, so there is no open redirect.

## 9. Social accounts

- `/admin/threads`, now titled "Social accounts".
- **Per Threads slot:** status, profile, token expiry (never the token),
  verification, error, and publishing state. A connected slot whose
  publishing flag is off is labelled as such.
- **Existing connect / verify / disconnect**, now audited.
- **Telegram panel (safe view):**
  - token present yes/no;
  - channels shown as public `@handle` or just "configured" (numeric chat ids
    are hidden);
  - photo flag, severity bar, per-run limit.

## 10. Sources

Feed health (existing) is shown next to columns that answer different
questions; they are never merged into one score:
- connector type and host;
- the Intelligence Core reliability profile (kind · 0–1 · note);
- articles in store;
- share of thin articles (< 300 characters of text, as an extraction-health
  signal).

"Test fetch" makes one confirmed, audited request through the existing RSS
connector and stores nothing.

There is no enable/disable switch, because sources are configured in code.
The page says this rather than inventing a second source model.

## 11. AI usage

**New per-call ledger** (`ops/usage.py`), written next to the existing counter
bumps in both providers. Stage labels come from a context variable: `brief` in
the generator, `fact_sheet` in extraction.

The page shows:
- **Cumulative counters** as-is, with no cost.
- **Ledger by day (Kyiv) or month.** Grouped by provider, model and stage,
  with tokens and cost labelled *estimated* (Claude CLI figure, or operator
  rates), *partial estimate*, or *unavailable*.
- **Image calls**, and the current cost-control settings.

The page makes no AI call. **Limitation:** there are no dated records before
this phase.

## 12. System health

Covers API, website probe, database, storage, the systemd units and timers,
ingestion, generation, Intelligence Core, the publication worker, Telegram,
each Threads slot, media and the image provider.

- **States:** healthy / warning / critical / unknown / not configured.
- **Recorded failures:** each marked persistent or temporary.
- **Audit log:** the latest 50 entries.
- **Caching:** probes cached 60 s.
- **Never shown:** environment values, connection strings, paths or tokens.

## 13. Security

**New:**
- `font-src 'self'`, for the admin font.
- `form-action 'self'` on every admin page (it was `'none'` except on review),
  needed for the GET search and filter forms. Forms can still only target
  this origin, and every state change requires POST + same-origin + CSRF +
  confirm.
- Input validation: query parameters and enums are whitelisted, lengths
  capped, ids pattern-checked.
- No open redirect.
- The Telegram view does not reveal chat ids.
- The database probe never echoes the URL.

**Tested:**
- 401 on every new GET and POST without credentials;
- 403 without a CSRF token, and 403 cross-origin;
- 400 without confirmation;
- secrets never appear on any page or in JSON.

## 14. Audit logging

New: `ops/audit.py`, writing to `data/admin_audit.jsonl` (append-only,
`fsync`, 0600). Covers:
- review approve/reject;
- publication retry/cancel/reconcile (including refusals);
- media regeneration;
- source test fetch;
- Threads connect-start, connect, verify, disconnect.

Credential-like meta keys are dropped and values redacted (tested).

## 15. Performance findings

Measured locally against worktree data (170 stories, 200 articles):

| Page | Time |
|---|---|
| Overview, first after a data change | ≈ 1.3 s |
| Overview, warm | ≈ 0.25 s |
| Stories, publications, usage, warm | < 10 ms |
| System, cold (probes) | 0.36 s |
| System, warm | 6 ms |
| Public `/posts` (unchanged path) | ≈ 0.06 s |

- **Heaviest work:** the Intelligence Core view, which is cached and keyed on
  the stores.
- **No new background jobs.** Polling is the user's own page loads, with no
  auto-refresh.

## 16. Files

**Created:**
- `cyberalertx/ops/{__init__,audit,usage,readmodel,health}.py`
- `cyberalertx/api/admin/ops_pages.py`
- `tests/test_admin_control_room.py`
- `docs/admin/ADMIN_DASHBOARD.md`
- `docs/admin/PHASE6_REPORT.md`

**Modified:**

| File | Change |
|---|---|
| `cyberalertx/api/admin/ui.py` | Grouped navigation, glyph, font, search, breadcrumbs, components, CSP |
| `cyberalertx/api/admin/pages.py` | Overview sections hook; sources columns and actions |
| `cyberalertx/api/admin/publishing_page.py` | Rewritten: filters, pagination, actions |
| `cyberalertx/api/admin/media_page.py` | Search, regeneration, provider state |
| `cyberalertx/api/admin/threads_page.py` | Social accounts, Telegram panel, publishing state |
| `cyberalertx/api/app.py` | New routes, actions, audit hooks, font route |
| `cyberalertx/ai/providers/{anthropic,claude_cli}_provider.py` | Usage ledger |
| `cyberalertx/ai/generator.py`, `cyberalertx/ai/fact_sheet.py` | Stage labels |
| `tests/conftest.py` | Isolation of the new ledgers |
| `tests/test_review.py`, `tests/test_media.py`, `tests/test_publication.py` | Assertions updated for the intended changes (CSP and UI wording) |

## 17. Dependencies added

None.

## 18. Automated tests

| Run | Result |
|---|---|
| With `cryptography` on the path | **1343 passed, 4 skipped** |
| Project venv as-is | 1300 passed, 5 skipped (the Threads suite skips without `cryptography`) |
| mypy strict | Clean, 119 files |
| tsc | Clean (no frontend change this phase) |

`tests/test_admin_control_room.py` (25 tests) covers:
- **Navigation and access:** every route resolves, is locked, and has an
  active nav item.
- **Data correctness:** articles vs stories counts, the Kyiv day (including
  summer time), destination counts against jobs.
- **Security:** secret redaction (bot token, app secret, private chat id); CSRF,
  origin and confirm on every new POST; engine-backed actions with audit
  (including `outcome_unknown` refusal and input validation); no open
  redirect; review audit; audit meta redaction.
- **Operations:** media regeneration only queues; source test fetch stores
  nothing; usage aggregation (estimated, operator rates, unavailable, Kyiv
  bucketing, invalid rates); the providers write the ledger.
- **Health:** optional parts are not failures and no record means unknown;
  frontend, database, unit and storage outages are reported; the database
  probe never leaks its URL.
- **Reliability:** empty world, Intelligence Core failure, large datasets with
  pagination and hostile parameters.

**A real bug the visual check caught.** The first screenshots showed
test-suite admin actions in the worktree's audit log. The new ledgers weren't
yet isolated in tests. They now are (`tests/conftest.py`), and the polluted
worktree-only files were removed. Production data was never touched, and the
post cache was verified unchanged.

## 19. Browser QA

Chromium, dark scheme, logged in, against the worktree API and real worktree
data.

- **Pages:** overview, stories, story detail, publications, social accounts,
  sources, usage, system, review, media, intel.
- **Widths:** 375, 390, 768, 1440, 1920 as relevant.
- **Result:** every page 200, no horizontal overflow, the Fira font loaded.

Fixes made from what the screenshots showed:
- clustering decisions rendered as raw dicts (now a table);
- an asset id clipped;
- the story key upper-cased in the breadcrumb.

## 20. Remaining limitations

- **Data mix in this test setup.** The worktree data is a 2 Nov snapshot, so
  ingest and generation correctly show *critical/stale*, while the systemd
  checks read the live host. In production both describe the same system.
- **AI usage history** has dates only from this release on. Cost is
  *estimated* or *unavailable*; nothing is measured, because no provider
  returns a billed amount.
- **No enable/disable for sources** (they are configured in code), and no UI
  merge/split (the CLI overrides are referenced).
- **No exception store:** "recorded failures" covers jobs, media, the intel
  run and Threads only. Process exceptions remain in the journal.
- **Overview speed:** about 0.25 s warm, because it rebuilds story rows for
  several sections. Acceptable, but cacheable if it grows.
- **One admin secret.** The actor is the typed Basic username, not a verified
  identity. Per-user accounts would be a separate decision.

## 21. Recommended next phase

Operations hardening:
- alert delivery for critical checks and `OPERATOR ACTION NEEDED` (today they
  appear on the page and in the journal only);
- an optional per-user admin identity for the audit;
- a small exception recorder in the generate/ingest timers.

Then the supervised production rollout of Phases 1–6.

**Phase 7 not started.**
