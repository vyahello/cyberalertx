# Publication Engine

One job per **story × edition × destination × publication type**. Four
destinations exist today: Website EN, Website UA, Telegram EN and Telegram UA.
A failure on one never holds back the others. The engine works through the
existing post service, review gate, Intelligence Core, Media Engine, Telegram
publisher and publish ledger. It has no scheduler of its own: the existing
timer runs it, once an operator switches that timer over (see below).

## Pieces

| File | Role |
|---|---|
| `cyberalertx/publish/jobs.py` | `PublicationJob`, `JobStore` (JSON + `fcntl` lock + atomic rename), `RetryPolicy` |
| `cyberalertx/publish/destinations.py` | Adapter contract (`prepare` / `deliver`), `WebsiteDestination`, `TelegramDestination`, `DeliveryError` |
| `cyberalertx/publish/orchestrator.py` | `plan()`, `run()`, recovery, operator actions (`retry`, `reconcile`, `cancel`) |
| `cyberalertx/publish/telegram.py` | Existing client. Every failure now carries a `category` and, for 429, `retry_after` |
| `cyberalertx/tools/publish.py` | CLI |
| `/admin/publishing`, `/admin/publishing.json` | Read-only operator view, behind the existing admin gate |

## Job model

`job_id` is `{story}:{locale}:{destination}:{type}[:{revision}]`. That id **is
the publication identity**: planning the same story again cannot create a
second job, and a job in any state is never overwritten by planning.

- **story:** the Intelligence Core story key. If there is none, the item's
  `story_key`; failing that, its fingerprint.
- **type:** `initial`, `update` (website revision) or `breaking_update`
  (Telegram follow-up).

Fields:

| Group | Fields |
|---|---|
| Identity | `story_key`, `fingerprint` (the article), `members` (every article of the story), `locale`, `destination`, `publication_type` |
| Scheduling | `status`, `priority`, `reasons`, `scheduled_at` |
| Attempts | `attempts` / `max_attempts`, `last_attempt_at`, `next_attempt_at` |
| Lease | `claimed_by`, `lease_until`, `phase` |
| Result | `external_id`, `published_url`, `media_url`, `content_hash`, `evidence_fingerprint` |
| Errors | `last_error`, `error_category` |
| History | `history` (last 20 events), `created_at`, `updated_at`, `completed_at` |

Statuses:

| Status | Meaning |
|---|---|
| `scheduled` | Waiting for `scheduled_at`. The spec's *pending* and *scheduled* are one state here, because every job has a due time. |
| `processing` | Claimed by one worker, under a lease. |
| `published` | Delivered. |
| `retrying` | Recoverable failure; due again at `next_attempt_at`. |
| `failed` | Permanent error, auth/permission error, or retries exhausted. Needs an operator `retry`. |
| `cancelled` | Rejected by the editor, the article is gone, or cancelled by an operator. |
| `outcome_unknown` | The destination may have accepted it. Never resent automatically. |

The store lives at `data/publish_jobs.json`. Every mutation is a locked
read-modify-write with `fsync` and rename, so the file survives restarts, and
two workers can never claim the same job. A test runs 4 concurrent workers;
with the lock removed that test fails. A corrupt store stops the worker
instead of being read as empty, because "no jobs" would mean re-planning.
`prune` moves finished jobs older than 90 days to
`publish_jobs.archive.jsonl`.

## Planning: who gets a job

Planning recalculates nothing. It reads what the existing code already
decides:

| Gate | Source |
|---|---|
| Not later coverage of a known story | `duplicate_of` (existing dedup) |
| In scope | Intelligence Core relevance, else `effective_relevance` |
| Edition exists, is review-visible, not half-translated, right script | `_PostService.render_if_cached(item, required_locale=…)`, the same gate the site, RSS and Telegram use |
| Recent | `CYBERALERTX_PUBLISH_WINDOW_HOURS` (default 48). The archive is never published. |
| Telegram only | Channel configured for the locale, language gate (EN channel takes EN sources; UA takes both), source tier, `qualifies()` severity/urgency bar |
| Telegram already sent | The publish ledger, checked across every article of the story. Such a job is created already `published` and is never sent. |

**Review mode is preserved exactly** (`cyberalertx/ai/review.py`):

- `flag` (default): `pending` editions stay visible, so they get jobs. This is
  the same as today's site and Telegram behaviour. `rejected` editions are
  hidden, and their open jobs are cancelled at run time.
- `hold`: `pending` editions are hidden. They get no job until approved, and
  an already-open job is deferred (no attempt spent).
- `off`: nothing is hidden.

The mode is not changed by this phase.

## Priority and timing

| Story | Priority | When |
|---|---|---|
| Breaking (Intelligence Core `breaking()`, which applies its evidence rules) | 100 | Next run |
| Daily Top 10, rank *r* | 50 + (11 − r) | Next run; or `CYBERALERTX_PUBLISH_TOP10_AT` (HH:MM, Kyiv) if set |
| Ordinary | 10 | Next run |

Each worker run takes due jobs by priority, capped per destination and locale.
For Telegram the cap is `--limit` or `CYBERALERTX_TELEGRAM_LIMIT`. Today's
timer passes `--limit 1` at 10 fixed times a day, and that cap *is* the
natural spread through the day. No new schedule exists. Stored times are UTC;
Kyiv is used only to compute the Top 10 slot, and it follows summer time.

Intelligence Core data is read with `write=False`, so the shadow state from
Phase 2 is untouched.

**Breaking follow-ups** are off unless `CYBERALERTX_PUBLISH_BREAKING_UPDATES=1`.
When on, a `breaking_update` Telegram job is created only if the story's
Breaking evidence fingerprint differs from the one recorded on its last
delivered post. Unchanged evidence produces nothing, and the original post and
its history are kept. The message is the current edition, prefixed
"🔄 Update" / "🔄 Оновлення".

## Execution

`run()`:

1. **Recover abandoned jobs** (lease expired). A worker that died *before*
   the external call leaves a job that becomes `retrying`. One that died
   *during* the call (`phase == "sending"`) leaves a Telegram job
   `outcome_unknown`. The website is idempotent, so it is simply retried.
2. **Claim** due jobs in one locked step.
3. **Load the edition.** If it is rejected or the article is gone, the job is
   cancelled. If it is held or not rendered, the job waits an hour without
   spending an attempt, and is cancelled once it falls outside the window.
4. **Prepare and deliver.** `phase = "sending"` is persisted immediately
   before anything leaves the process.
5. **Record** the result: published, retrying, failed or outcome_unknown.

`run` without `--send` is a preview: it claims nothing, writes nothing and
sends nothing.

### Error categories and what happens

| Category | Examples | Result |
|---|---|---|
| `network` | connect refused / connect timeout (request never sent) | retry with backoff |
| `temporary` | 502 / 503 / 504 | retry with backoff |
| `rate_limit` | 429 | retry no earlier than `retry_after`; channel paused for the rest of the run |
| `auth` | 401 | `failed`; channel paused; `OPERATOR ACTION NEEDED` logged at ERROR |
| `permission` | 403, chat not found | as `auth` |
| `invalid_content` | other 400s, quality gate, missing title or summary | `failed` (permanent) |
| `missing_media` | Telegram cannot fetch or use the card URL | text fallback (see below) |
| `unknown_outcome` | read timeout, dropped connection, 500, unreadable 200, crash mid-send | `outcome_unknown` |

Backoff is `120 s × 2^(n−1)`, capped at 6 h, with ±20 % jitter. A server's
`retry_after` acts as a floor. Defaults: `CYBERALERTX_PUBLISH_RETRY_BASE_S`,
`CYBERALERTX_PUBLISH_RETRY_CAP_S`, and `CYBERALERTX_PUBLISH_MAX_ATTEMPTS` (5).
A retryable job that runs out of attempts becomes `failed` and waits for an
operator.

## Idempotency: what is and is not guaranteed

**Internal:** one job per publication identity, claimed by one worker, and
never re-executed once published. This holds across timer re-fires,
concurrent workers, restarts, manual CLI runs, re-ingestion and story updates.
Each property is tested.

**Website:** delivery is internal and idempotent. The site is a read model
over the API: an edition is live the moment it is rendered and visible. The
website job validates it, fixes the canonical URL (`/{locale}/threat/{id}`,
unchanged) and its localized OG card, and records the delivery and content
hash.

Article updates:
- `generate` never overwrites a cached edition.
- A content change can only come from the editor or a manual re-render.
- Such a change creates a website `update` job for that locale only: same URL,
  history kept.
- No Telegram repost results from it.

**Telegram:** the Bot API has no idempotency key, so **exactly-once delivery
is not possible.** What is guaranteed:

- A request known *not* to have reached Telegram (connect failure, 429, 4xx,
  gateway 5xx) is retried.
- A request that *may* have been accepted is marked `outcome_unknown` and is
  never resent automatically. That covers timeouts, dropped connections, 500,
  an unreadable 200, and a crash mid-send.
- Before every send, the publish ledger is re-read for every article of the
  story. The legacy `publish-telegram` path and this worker therefore never
  double-post a story they can both see.
- A photo is only replaced by a text post when Telegram *refused* the photo.
  An uncertain photo send never triggers a text fallback.

The same rule is now applied in the legacy `publish_once`.

The remaining window is a send that succeeded but whose result could not be
recorded. It surfaces as `outcome_unknown`; it is not silently duplicated.

**Reconciling:** bots cannot read a channel's history, so reconciliation is a
human check. Look at the channel, then run one of:

```bash
python -m cyberalertx.tools.publish reconcile JOB --sent 1234   # it is there: record it (and in the ledger)
python -m cyberalertx.tools.publish reconcile JOB --not-sent    # it is not: send it again
```

## Telegram message format

`publish/format.py: render_message`, the same for EN and UA (labels localized):

1. **Headline** in bold.
2. **Summary**, plain.
3. **Detail** paragraph, only when it adds facts the summary lacks (a CVE,
   a product, a number).
4. **Why it matters:** one sentence, dropped when it repeats the summary.
5. **Status line:** threat level, plus exploitation or campaign status when
   known. Compromise ("data exposure confirmed") appears only for incident
   categories (breach, data leak, ransomware), never for a vulnerability.
6. **Not yet known:** only for unknowns a reader can act on (exposure, scope,
   timeline, attribution, whether a campaign is over). It never contradicts a
   stated fact.
7. **What to do:** at most two actions, and only when the story justifies
   them (actionable, high or critical, or exploitation observed).
8. **Also reported by**, **Source** with its link, **Read more** link to the
   article, at most two tags.

No emoji prefix, no link preview (the photo is the image). Before/after
examples: [OPERATIONS.md](../operations/OPERATIONS.md#7-telegram).

## Media

Each Telegram post is a photo: the story illustration, `telegram` variant
(1200×675), at `/media/{asset}/telegram.png` on the public site, the same
asset as the website. With `CYBERALERTX_TELEGRAM_REQUIRE_ILLUSTRATION=1` (the
default) a post waits until its illustration exists. It spends no attempt and
expires with the 48 h window. A refused photo is retried and is never sent as
text instead. Website jobs record the edition's `og` card. See
[IMAGE_GENERATION.md](../media/IMAGE_GENERATION.md).

## Threads (Phase 5)

Implemented. See `docs/threads/THREADS_SETUP.md`. Changes to the engine:

- **Destination name.** One `ThreadsDestination` instance per account slot,
  registered as `threads@{slot}`. The job identity
  `{story}:{locale}:threads@{slot}:{type}` keeps the two profiles apart, and
  pausing by `(destination, locale)` isolates their failures.
- **Planning.** `plan()` asks each `threads@*` destination `plans_for(locale)`
  and `qualifies(payload)`.
- **Per-run cap.** Its own: `CYBERALERTX_THREADS_LIMIT`.
- **New job field.** `PublicationJob.external_state` holds destination
  progress (the Threads container id).
- **Checkpointing.** `on_sending(phase=…, **state)` persists progress before
  each external step, so a retry or a recovered crash resumes the same
  container instead of creating a second post.
- **Compatibility.** Website and Telegram call `on_sending()` without
  arguments, exactly as before.
- **Enabling.** Threads destinations exist only with
  `CYBERALERTX_THREADS_PUBLISH=1`.
- **`cycle --send`** also refreshes due Threads tokens and auto-reconciles
  `outcome_unknown` Threads jobs before delivering.

## Operating it

```bash
python -m cyberalertx.tools.publish plan --dry-run --story FP   # what jobs would exist
python -m cyberalertx.tools.publish plan                        # create them (job store only)
python -m cyberalertx.tools.publish run --story s:…             # preview per destination (no --send = nothing sent)
python -m cyberalertx.tools.publish status | pending | failed | unknown | show JOB
python -m cyberalertx.tools.publish retry JOB                   # failed/cancelled → scheduled
python -m cyberalertx.tools.publish cancel JOB
python -m cyberalertx.tools.publish prune --older-than-days 90
python -m cyberalertx.tools.publish cycle --send --limit 1      # plan + deliver (the timer's command, once switched)
```

### The scheduled timer

`cyberalertx-telegram.timer` keeps its schedule (10 runs a day). The tracked
unit runs `cycle --send --limit 1` from `/home/cax/cyberalertx/current`.
`ops/release/telegram_activate.sh activate` installs it, imports the ledger,
cancels the backlog (`baseline --before now`) and enables the timer. The legacy
`main publish-telegram` command is no longer scheduled. Never run it next to
`cycle --send`. Procedure and emergency stop:
[OPERATIONS.md](../operations/OPERATIONS.md#7-telegram).

```bash
python -m cyberalertx.tools.publish check-telegram              # read-only Bot API check, sends nothing
python -m cyberalertx.tools.publish baseline --before ISO --dry-run   # what activation would cancel
```
