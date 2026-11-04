# Release-readiness register

Status as of Phase 7 (4 Nov 2026). This is the single list of what is still
open across Phases 1–7.

- **Severity:** Critical / High / Medium / Low.
- **Blocks:**
  - **Stage B**: blocks building a release candidate.
  - **Stage C**: blocks controlled manual operation.
  - **Stage D**: blocks automated new publishing.
  - **No**: does not block.
- **Owner:**
  - **Dev**: a code or documentation change.
  - **Admin**: the server or account owner.

"Verified" means a test or measurement ran. It never means a mocked API was
confirmed against the real service.

## Fixed in Phase 7

| # | Issue | How it was found | Fix and verification |
|---|---|---|---|
| F1 | **Story re-keying.** The Intelligence Core anchored each story on its *newest* article, so its key changed whenever newer coverage arrived. That reset score history and Breaking state, re-generated (paid) illustrations, and let the planner create a **second Threads post** for the same article. Threads has no ledger to stop that. | End-to-end test: score history was missing after new evidence arrived | `intel/story.py: stable_key()` adopts the first-seen ingest key, which is never moved. `publish/orchestrator.py: plan()` refuses a second initial job per article, edition and destination. Tests: `test_newer_coverage_does_not_rekey_a_story`, `test_planner_never_reposts_an_article_under_a_new_story_key`. Both fail when either fix is reverted (mutation-checked). |
| F2 | **Stale backlog.** The new worker sent the *oldest* article first, and its jobs never expired. With about 25 stories a day and 10 slots a day per channel, Telegram would have posted ever-older news after the scheduler switch. The legacy publisher sends newest first. | Comparing `service.py:170` with `orchestrator.py:368`, plus measured daily volume | Newest-first ordering within a priority. Social jobs outside the 48 h window are cancelled as "expired", never sent. Tests: `test_backlog_goes_newest_first_like_the_legacy_publisher` (mutation-checked) and `test_social_jobs_expire_outside_the_window`. |
| F3 | **Relevance not mirrored to Postgres.** Production runs `dual`, but `news_items` had no relevance columns, so every relevance decision and override existed only in JSON. | Persistence audit | Migration `005_news_items_relevance.sql`. `PgNewsStore` writes the columns only after seeing them in the live table, so migration and deploy can happen in either order. Tests: `test_pg_migrations_live.py`, 4 tests on an isolated PG 16. |

## Open

| # | Issue | Sev. | Production impact | Blocks | Required action | Owner | Verification criteria | Status |
|---|---|---|---|---|---|---|---|---|
| O1 | Frontend dependencies: `next` 15.5.18 (1 critical advisory, Server Actions DoS/SSRF), `sharp` 0.34.5 (libvips/libheif advisories), `postcss`, `nanoid`, `source-map-js` (high). **The same versions run in production today.** | High | sharp processes images in the Media Engine routes; Next's critical advisories concern Server Actions, which this app does not use (0 files). | Stage C | Upgrade within the release candidate (`npm audit fix`, then Next patch release), rebuild, re-run tsc, build, Playwright and visual checks | Dev | `npm audit --omit=dev` shows 0 critical/high; e2e and visual QA pass | Open |
| O2 | Python: the production venv has `starlette` 1.0.0 and `anyio` 4.13.0, with 12 known advisories. **Pre-existing.** | High | API framework | No: the release venv fixes it | Build the release venv from `requirements.lock` (starlette 1.10.0, anyio 4.16.0) | Admin (during deploy) | `pip-audit` in the release venv: no known vulnerabilities (**verified in the Phase 7 rehearsal venv**) | Ready |
| O3 | `cryptography` is missing from the production venv | Medium | Threads cannot store tokens; it fails closed. Nothing else is affected (tested). | Stage C, for Threads only | Installed automatically by `pip install -r requirements.lock` in the release venv | Admin | `/admin/threads` Configuration panel shows "cryptography package: set" | Ready |
| O4 | Migration 005 is not applied to Supabase | Medium | Relevance stays JSON-only until applied. Safe in either deploy order. | No | `python -m cyberalertx.tools.pg_migrate` with the production env, after a Supabase backup | Admin | `pg_migrate --status` shows 005 applied; after a restart the warning "news_items lacks relevance_*" is gone | Open |
| O5 | Review persistence was never exercised against a Supabase *test project* (only a local PG 16) | Medium | `hold` mode depends on strict dual-write | Before any `hold` | Run `tests/test_pg_review_live.py` with `CYBERALERTX_TEST_DB_URL` pointing at a Supabase test project (never production) | Admin | 3/3 pass on the pooler URL | Open |
| O6 | The four-story editorial benchmark (10 Claude CLI calls) has not been run | Medium | Real AI output quality and real fact sheets are unproven; all Phase 7 editorial tests use mocked synthetic answers | Stage D (quality gate) | Authorize; run `python -m cyberalertx.tools.benchmark --fp …` (plan in PRODUCTION_READINESS §8) | Admin authorizes, Dev runs | `data/editorial/benchmark/REPORT.md` reviewed by the editor, especially the UA text | Awaiting authorization |
| O7 | **Fact sheets add one AI call per article in production** (`CYBERALERTX_FACT_SHEET` defaults to on) | Medium | The hourly `generate --limit 1` makes about 1 extra Claude CLI call per new article (about 25 a day), on the subscription | No; approved in Phase 1 ("+1 call") | Confirm the budget, or set `CYBERALERTX_FACT_SHEET=0` for the first days | Admin | Usage ledger `/admin/usage` shows `fact_sheet` calls at the expected rate | Open (decision) |
| O8 | Real Telegram delivery through the **new** paths (sendPhoto, job worker, reconciliation) is unverified; all mocked | Medium | The legacy text path is proven in production (3,046 ledger sends) | Stage D | Private test channel + test bot token; run Stage C checks | Admin | Messages in the private channel with the correct locale; ledger + jobs agree | Open |
| O9 | Meta app, OAuth and the Threads API are unverified (no app or accounts) | Medium | None while `CYBERALERTX_THREADS_PUBLISH=0` (default, tested) | Stage E (Threads) | THREADS_SETUP.md steps 1–15 | Admin | Both slots verify; one supervised post per profile | Blocked on admin |
| O10 | App Review / development-mode status for Threads is unclear | Low | Same as O9 | Stage E | Check the App Dashboard | Admin | Dashboard shows publishing allowed for both testers | Blocked on admin |
| O11 | **Shared admin password**: the audit "actor" is the typed Basic-auth username, not a verified identity | Medium | Attribution is advisory; anyone holding the token can type any name | No for a single administrator; **yes before adding a second administrator** | See PRODUCTION_READINESS §11: per-user tokens in the same gate (small change), or SSO at the edge | Dev + Admin | Audit entries carry a verified user id | Open |
| O12 | No rate limiting in nginx (`limit_req` absent). The app has the admin lockout and the feedback cap. | Low | Cloudflare sits in front; the API is localhost-only | No | Optional `limit_req` for `/admin` and `/feedback` | Admin | Load test returns 429 above the limit | Open |
| O13 | No image-generation provider | Low (by design) | Branded cards only; publication not blocked (tested) | No | Choose a provider, then MEDIA_ENGINE.md "Provider: the blocker" | Admin decides | One validated illustration in `/admin/media` | Open (decision) |
| O14 | AI usage history starts with this release; earlier usage is cumulative counters only | Low | `/admin/usage` daily/monthly views begin at deploy | No | None (documented on the page) | — | — | Accepted |
| O15 | Sources are configured in code; no enable/disable from the admin | Low | Changes need a release | No | Accept, or move the list to config later | Dev | — | Accepted |
| O16 | Story merge/split only via the CLI (`tools.stories`) | Low | The editor needs shell access | No | Accept, or add an admin form later (with CSRF and audit) | Dev | — | Accepted |
| O17 | Errors outside publishing, media, intel and Threads are visible only in the journal | Low | Process crashes are not on `/admin/system` | No | Optional exception recorder in the timers | Dev | — | Accepted |
| O18 | **Clustering window**: a development more than 5 days after the original (`_WINDOW_DAYS = 5`) becomes a *new* story (test `test_outdated_story_beyond_window_is_a_new_story`) | Low | The follow-up is posted as a new story, not as an update of the old one | No | Accept (deliberate), or add a "follow-up of" link later | Dev | — | Accepted, documented |
| O19 | Rollback to the old code drops relevance fields from `items.json` on its first ingest cycle (old serializer), and the old code has no review gate (rejected editions reappear) | Medium | Only if a rollback happens after editors used overrides or rejected posts | No | ROLLBACK_RUNBOOK §4: back up `items.json` before rollback and restore on roll-forward | Admin | — | Documented |
| O20 | Job store is a single JSON file. Measured update latency: 36 ms at 1k jobs, 0.5 s at 15k jobs. About 100 jobs a day expected. | Low | Fine at a 30-day retention | No | `python -m cyberalertx.tools.publish prune --older-than-days 30` weekly (cron or manually) | Admin | Job file < 5 MB | Open |
| O21 | `tools.publish cycle` exits 0 even when jobs fail; failures surface on `/admin/publishing` and `/admin/system` and in the journal (`OPERATOR ACTION NEEDED`) | Low | systemd shows "success" for a run with failed jobs | No | Watch the admin pages after the switch; optional non-zero exit on operator errors later | Dev | — | Accepted |
| O22 | No Python/JS lint is configured (mypy strict and tsc are) | Low | — | No | Optional | Dev | — | Accepted |
| O23 | `/healthz` Playwright test fails locally only (no nginx in the test environment); production `/healthz` returns 200 JSON | — | None | No | None | — | Verified: API :8300 `/healthz` 200, Next :3300 404, production 200 | Environmental |
| O24 | The repo's `server/systemd/*.service` copies differ from the installed units (for example `run --interval 30` live vs `15` in git) | Low | Copying the repo units would silently change ingest frequency | Stage B | Use the installed units as the base (DEPLOYMENT_RUNBOOK §3); update the repo copies in a later commit | Dev | Unit diff reviewed before install | Open |
