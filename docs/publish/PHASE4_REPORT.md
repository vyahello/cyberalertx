# Phase 4 — Publication Engine: final report

Built and tested in `/home/cax/cax-redesign` (branch `redesign/cti-platform`)
only. Nothing was deployed, committed or pushed. **No Telegram message was
sent**; every Bot API call ran against `httpx.MockTransport` with fake channel
ids. Production systemd units, environment, data and database are unchanged.
Production's `data/` contains no job store.

**Labels used below:**
- **implemented & tested:** real code exercised by automated tests.
- **mocked:** the external side was simulated.
- **unverified:** never run against the real service.

## 1. Existing publication architecture (audit)

- **Website — a pull model.** `generate --use-llm` (hourly timer) caches a
  rendered edition per (fingerprint, locale). `_PostService.render_if_cached`
  serves only editions that pass the review gate, the half-translation gate
  and the script check. Next.js renders `/{locale}/threat/{id}` with ISR.
  There is no "publish" step and no record of it. `generate` never overwrites
  a cached edition.
- **Telegram:** `publish_once` (`cyberalertx-telegram.timer`, 10 fires a day,
  `--limit 1`). Gates: tier, `duplicate_of`, optional out-of-scope hiding, the
  language gate, the append-only ledger keyed by (fingerprint, locale) plus
  story-level dedupe, `qualifies()` and `quality_problem`. It sends
  `sendMessage`, or with `ATTACH_IMAGES=1` `sendPhoto` with text fallback.
- **Review** (`CYBERALERTX_REVIEW_MODE`):
  - `flag` (default): `pending` editions stay visible and keep publishing,
    including to Telegram; `rejected` editions are hidden.
  - `hold`: `pending` editions are hidden too.
  - `off`: nothing is hidden.
- **Missing:**
  - per-destination state;
  - claiming or leases (concurrent runs could double-send);
  - retry and backoff;
  - error classification;
  - any notion of an uncertain outcome. Before this phase a timeout led to a
    text fallback and a resend on the next run, which could post twice;
  - recovery tools and an operator view.

## 2. Components reused

- `_PostService` with its review, translation and script gates.
- `effective_relevance` and `duplicate_of`.
- The Intelligence Core `run(write=False)`: stories, Daily Top 10 and
  Breaking evidence rules.
- `TelegramSettings`, `qualifies()`, `quality_problem`, `render_message`,
  `render_caption` and `deep_link`.
- `TelegramPublisher`: extended, not duplicated.
- `PublishLedger`: shared by both paths.
- The Media Engine card URLs.
- The JSON + `fcntl` + atomic-rename storage pattern.
- The admin gate, `ui.page` and its CSP.
- The existing timer.

## 3. Components added or modified

**Added:**
- `publish/jobs.py`
- `publish/destinations.py`
- `publish/orchestrator.py`
- `tools/publish.py`
- `api/admin/publishing_page.py`
- `tests/test_publication.py`
- `docs/publish/`

**Modified:**
- `publish/telegram.py`: error `category`, `retry_after`, `accepted_possible`;
  unreadable 2xx responses are now treated as unknown.
- `publish/service.py`: the legacy path never falls back to text after an
  uncertain photo send.
- `api/app.py`: `/admin/publishing` (+ `.json`).
- `api/admin/ui.py`: navigation entry.

## 4. Job model

Detailed in `PUBLICATION_ENGINE.md`.

- **Identity:** `{story}:{locale}:{destination}:{type}[:{revision}]`.
- **Statuses:** `scheduled`, `processing`, `published`, `retrying`, `failed`,
  `cancelled`, `outcome_unknown`. The spec's `pending` is merged into
  `scheduled`, because every job has a due time.
- **Extra fields beyond the spec:**
  - `members`: ledger dedupe across the whole story;
  - `phase`: marks a crash during the send;
  - `content_hash` and `evidence_fingerprint`: decide when an update is
    warranted;
  - `history`: the last 20 events.

## 5. Idempotency strategy and limits

**Implemented & tested:**
- The deterministic job id plus `add_missing` mean planning twice changes
  nothing.
- Claims are a locked read-modify-write. With 4 concurrent workers each job is
  sent exactly once; with the lock removed the test sends duplicates.
- Published jobs are never re-executed.
- Leases recover dead workers, and a crash mid-send becomes `outcome_unknown`.
- The ledger is re-read before every Telegram send.
- Stories already sent by the legacy publisher are imported as `published`.
- A corrupt store stops the worker; it is never read as empty.

**Limit:** Telegram has no idempotency key, so exactly-once delivery cannot be
guaranteed. A send that may have been accepted is held as `outcome_unknown`
and resolved by a person with `reconcile`, because bots cannot read channel
history. The remaining risk is "possibly sent, needs a look". It is never a
silent duplicate.

## 6. Website EN/UA

**Implemented & tested.** Each edition is validated: title, summary, locale
available. The job records:
- the canonical URL `/{locale}/threat/{fingerprint}` (unchanged);
- the localized versioned `og` card;
- source attribution;
- the content hash.

A rejected edition's job is cancelled. A held edition waits without spending
attempts. A changed edition creates a per-locale `update` job with the same
URL and keeps its history. No new article is created per source report. The
archive outside the 48 h window is never planned.

There is no external call, because the site already serves the edition. This
records the website delivery; it is not a push.

## 7. Telegram EN/UA

**Implemented & tested (mocked).**
- Each locale goes to its own channel with its own text and its own
  localized card.
- `sendPhoto` is used when `ATTACH_IMAGES=1`, which is still off by default.
- A refused photo falls back to text. An uncertain photo does not.
- 429 respects `retry_after` and pauses the channel for the run.
- 401 and 403 fail and log an operator alert, without retry loops.
- Connect errors back off; read timeouts, 500s and unreadable 200s become
  `outcome_unknown`.
- The message id is stored in the job and in the ledger.

**Unverified:** real Bot API behaviour. Telegram fetching the card URL
depends on the Phase 3 routes being deployed.

## 8. Scheduling

No new timer, cron job or worker. The existing `cyberalertx-telegram.timer`
would run `tools.publish cycle --send --limit 1` instead of
`publish-telegram`. That switch is documented but **not made**. The per-run
cap keeps today's spread of 10 a day per channel.

Times are stored in UTC. Kyiv time, with summer time, is used only for the
optional Top 10 slot `CYBERALERTX_PUBLISH_TOP10_AT`, which is unset by default
so no new schedule is active.

## 9. Retry and recovery

Exponential backoff with jitter: 120 s × 2ⁿ, capped at 6 h, ±20 %, with
`retry_after` as a floor. `max_attempts` defaults to 5.

Error categories:
- `network`
- `temporary`
- `rate_limit`
- `auth`
- `permission`
- `invalid_content`
- `missing_media`
- `unknown_outcome`

Retryable jobs that exhaust their attempts become `failed`. Operator actions
are `retry`, `reconcile --sent/--not-sent` and `cancel`. Expired leases are
recovered at the start of every run.

## 10. Review and relevance

`flag`, `hold` and `off` behave exactly as before. No mode was changed and no
new approval system was added. Out-of-scope stories get no jobs. The website's
own out-of-scope visibility is still governed by the unchanged
`CYBERALERTX_HIDE_OUT_OF_SCOPE` flag. The Phase 2 persistence safeguards are
untouched.

## 11. Breaking priority

- Uses the Intelligence Core's `breaking()` decisions, with its evidence rules
  and the never-unverified rule. Nothing is recalculated.
- Breaking jobs get priority 100 and are due immediately. Daily Top 10 jobs
  get 50 + (11 − rank).
- Follow-ups only happen when the evidence fingerprint changed, and only with
  `CYBERALERTX_PUBLISH_BREAKING_UPDATES=1` (off by default).
- Unchanged evidence produces nothing. The original post and job history are
  kept. Channel rate limits still apply.

## 12. Media Engine integration

- Telegram uses the edition's versioned `telegram` card, with the
  illustration embedded when one exists. Website jobs record the `og` card.
- No illustration is ever required, and no image generation is called. No
  image provider is configured.

## 13. Admin and CLI

- **`/admin/publishing` and `.json`:** behind the existing token gate and CSP.
  Shows per-destination tiles, unknown outcomes with the reconcile command,
  failed jobs with the retry command, due and retrying jobs, and recent
  publications. Read-only.
- **`python -m cyberalertx.tools.publish`:** `plan [--dry-run] [--story]`,
  `run`, `cycle`, `status`, `pending`, `failed`, `unknown`, `show`, `retry`,
  `cancel`, `reconcile`, `prune`.
- Only `run --send` and `cycle --send` can deliver.
- `--send` is refused when channels are set but no token is.

### Dry-run demonstration (worktree data, fake channels, no token)

`plan` on the worktree snapshot with a 72 h window created 31 jobs:

| Destination | Jobs |
|---|---|
| Website EN | 7 |
| Website UA | 12 |
| Telegram EN | 5 |
| Telegram UA | 7 |

Skipped:
- 58 editions not rendered or withheld by review;
- 9 out of scope;
- 7 below the channel severity bar;
- 506 outside the window.

`run --story s:0290a6f139027c` (preview) for one story:

```
s:0290a6f139027c:en:website:initial   deliver  https://cyberalertx.com/en/threat/53069937df157c21  card en/…/og.png?v=d7ac6e9d…
s:0290a6f139027c:en:telegram:initial  deliver  → @fake_cax_en  photo en/…/telegram.png?v=d7ac6e9d…  "🟠 Supermarket freezers in several European countries remotely set to wrong temperatures…"
s:0290a6f139027c:ua:website:initial   deliver  https://cyberalertx.com/ua/threat/53069937df157c21  card ua/…/og.png?v=a2fb5f52…
s:0290a6f139027c:ua:telegram:initial  deliver  → @fake_cax_ua  photo ua/…/telegram.png?v=a2fb5f52…  "🟠 Хакери віддалено змінили температуру морозильників у супермаркетах…"
```

A simulated run of that story on a scratch copy, with a mocked Bot API where
the EN channel returns 502, gave independent statuses per destination:

```
website  en  published  ext=53069937df157c21
website  ua  published  ext=53069937df157c21
telegram ua  published  ext=4242
telegram en  retrying   attempts=1  err=temporary   (next attempt in ~2 min)
```

## 14. Tests and actual results

- **pytest:** 1274 passed, 4 skipped. `tests/test_publication.py` adds 37
  tests covering:
  - job creation: eligible, out of scope, missing locale, plan twice, ledger
    import, window / severity / language / tier gates, held editions;
  - idempotency: run twice, 4 concurrent workers, crash mid-run, unknown
    outcome never resent, reconcile both ways;
  - website: localized URL and card, update only on change with the same URL,
    rejected cancelled, missing fields;
  - Telegram: channel per locale, photo success, refused-photo fallback,
    uncertain photo with no fallback, 429 with `retry_after`, 401 operator
    alert, connect-error backoff to exhaustion and operator retry,
    invalid content, error categories, unreadable 200, the legacy path's
    no-fallback fix;
  - scheduling: future jobs wait, Breaking first under a cap,
    Top 10 at 09:00 Kyiv, summer time, backoff and jitter, Breaking updates,
    hold deferral;
  - operations: dry run changes nothing, CLI preview, corrupt store, prune,
    admin lock and CSP.
- **Mutation check:** with the store lock removed, the concurrency test fails.
- **Existing suites:** ingestion, generation, review queue, feed, media and
  legacy Telegram all still pass.
- **mypy strict:** clean, 103 files. **tsc:** clean (no frontend change this
  phase).
- **Worktree test API:** boots with the new routes; `/healthz` and `/posts`
  answer 200.

## 15. Files changed

**Added:**
- `cyberalertx/publish/{jobs,destinations,orchestrator}.py`
- `cyberalertx/tools/publish.py`
- `cyberalertx/api/admin/publishing_page.py`
- `tests/test_publication.py`
- `docs/publish/PUBLICATION_ENGINE.md`
- `docs/publish/PHASE4_REPORT.md`

**Modified:**
- `cyberalertx/publish/telegram.py`
- `cyberalertx/publish/service.py`
- `cyberalertx/api/app.py`
- `cyberalertx/api/admin/ui.py`

## 16. Dependencies added

None.

## 17. Remaining risks

- Reconciling `outcome_unknown` takes a person (a Bot API limitation).
- The legacy `publish-telegram` path has no unknown state. It now avoids the
  photo-then-text double post, but a text timeout is still resent on the next
  run, as before.
- The job store is a single JSON file. Each mutation rewrites it; `prune`
  keeps it small, but it should be run, for example monthly. Postgres
  dual-write was not added; jobs are operational state, like the ledger.
- Running the legacy command and `cycle --send` at the same time could race,
  because the legacy command reads the ledger once per run. Switch from one to
  the other; don't run both.
- Breaking follow-up wording is a simple prefix. It needs editorial review
  before it is enabled.
- An untracked file `/home/cax/cax/.e` (53 bytes, 3 Nov 16:23) appeared in
  the production checkout during this session. It was not created by this
  work and was neither read nor touched. The owner should check it.

## 18. Deployment prerequisites

1. Deploy Phases 1–4 together. Telegram photos need the card routes.
2. On the server, run `tools.publish cycle` without `--send` and review the
   output.
3. Run `tools.publish plan` once. This imports ledger history.
4. Change `cyberalertx-telegram.service` ExecStart to
   `python -m cyberalertx.tools.publish cycle --send --limit 1` and reload
   systemd.
5. Optionally, later: `CYBERALERTX_TELEGRAM_ATTACH_IMAGES=1`,
   `CYBERALERTX_PUBLISH_TOP10_AT`, `CYBERALERTX_PUBLISH_BREAKING_UPDATES=1`.
6. Keep `CYBERALERTX_ADMIN_TOKEN` set so `/admin/publishing` is reachable.

## 19. Recommended next phase

Phase 5: a Threads destination adapter (OAuth, token storage, container
create and publish). It uses the existing `threads-*` cards and plugs into the
job engine unchanged. **Not started.**
