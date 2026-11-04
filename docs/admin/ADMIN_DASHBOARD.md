# Admin control room

One protected workspace at `/admin`. It is server-rendered on the API, with
no JavaScript, behind the existing Basic-auth gate and a strict CSP. It
brings together the modules from Phases 1–5. Every number comes from a store
or record that already exists. Where no record exists, the page says so
instead of showing zero or "healthy".

## Navigation

| Group | Page | URL | Source |
|---|---|---|---|
| — | Overview | `/admin/` | Existing health view (feed, feedback, AI rendering, sources, logins, alerts), plus pipeline, destinations, intelligence and activity |
| Intelligence | Stories | `/admin/stories`, `/admin/stories/{key}` | Intelligence Core live view (`write=False`, cached 10 min) |
| | Daily selection | `/admin/intel` | Existing shadow-run page (unchanged) |
| Editorial | Review queue | `/admin/review` | Existing; decisions are now audited |
| | Reader feedback | `/admin/feedback` | Existing |
| | Brief quality | `/admin/metrics` | Existing |
| Media | Media studio | `/admin/media` | Existing, plus search and confirmed "queue regeneration" |
| Distribution | Publications | `/admin/publishing` | Existing, plus six-destination filters, pagination and confirmed actions |
| | Social accounts | `/admin/threads` | Existing Threads slots, plus a safe Telegram panel |
| Operations | Sources | `/admin/sources` | Existing feed health, plus connector, Core reliability profile, store/extraction health, confirmed test fetch |
| | AI usage | `/admin/usage` | Cumulative counters, plus the new per-call ledger |
| | System health | `/admin/system` (+ `.json`) | Real checks; recorded failures; audit log |
| (header) | Search | `/admin/search?q=` | Story keys, fingerprints, headlines, job ids, external ids |

All earlier URLs and their JSON endpoints are unchanged.

## Shell and design

- The shell follows the public site:
  - **Colours:** graphite surfaces, the single cyan accent, and the Aperture
    glyph (design system "One Signal Rule": the bright `#00E5FF` only in the
    glyph's ping).
  - **Typography:** the site's interface face, Fira Sans Condensed, served to
    the admin from the bundled OFL TTFs at `/admin/assets/…`.
  - **Tables:** tabular figures.
- **Navigation:** a grouped sidebar on desktop; a horizontal tab strip under
  900 px.
- **Headings:** breadcrumbs show the group, story keys are shown case-exact,
  and a search box is in the header.
- **Responsiveness:** checked at 375, 390, 768, 1440 and 1920 px with no
  horizontal overflow.

## What each number means

- **Articles and stories are separate.**
  - An *article* is one source item.
  - A *story* is an Intelligence Core cluster.
  - The overview's "Stories · <day>" tile says "from N articles fetched".
  - "Awaiting review" counts stories, with editions alongside.
- **Days** are Kyiv editorial days (Europe/Kyiv, with summer time); stored
  timestamps stay UTC.
- **Selection** (Top 10, trending, breaking) is the *live* view. It is not
  published, and is labelled so.
- **Pipeline stages** show their last *recorded* execution:

  | Stage | Record used |
  |---|---|
  | Sources | fetch cycle time |
  | Normalization | newest stored article |
  | Clustering, relevance | audit report times |
  | Fact sheets | store presence |
  | Scoring | shadow run time, plus live computation |
  | Generation | last brief cache write |
  | Media | last media run |
  | Publication | job and ledger records |

  No record means `no record`. "Not configured" (for example, no fact sheet
  store) is not a failure.
- **Destinations:** six rows (Website / Telegram / Threads × EN / UA).
  - Counts come from publication jobs. Telegram also shows legacy ledger
    sends.
  - Threads shows *publishing enabled/off* separately from *account
    connected*.
- **Activity** lists recorded events only, each with its own timestamp:
  - audit-log actions;
  - job history events;
  - Telegram ledger sends;
  - review decisions (`reviewed_at`);
  - illustration updates;
  - new stories (first article fetched).

## Actions

Every state change is a POST form protected by:
1. the existing admin gate;
2. `same_origin()`;
3. the admin CSRF token;
4. a required "confirm" box.

Each one is written to the audit log.

| Action | Where | Uses |
|---|---|---|
| Retry a failed/cancelled job | Publications | `orchestrator.retry_job`. Refused for `outcome_unknown`. |
| Cancel an undelivered job | Publications | `orchestrator.cancel_job` |
| Reconcile an unknown outcome (delivered + id / not delivered) | Publications | `orchestrator.reconcile_job` (+ Telegram ledger) |
| Queue an illustration regeneration | Media studio | Same as `tools.media regenerate`. Only shown when an image provider is configured; no provider call from the page. |
| Test a feed | Sources | One fetch through the existing RSS connector; nothing stored |
| Approve / reject | Review queue | Existing; now audited with the previous status |
| Connect / verify / disconnect Threads | Social accounts | Existing Phase 5 flow; now audited |

**Not available**, because no model for them exists:
- **Enabling or disabling sources:** sources are configured in code.
- **Manual story merge or split from the UI:** the existing override CLI
  (`tools.stories`) is named on the story page instead.

## Audit log

`data/admin_audit.jsonl` is append-only, written under a lock with `fsync`,
mode 0600. Each line records:
`{at, actor, address, action, target, result, meta}`

- `actor` is the Basic-auth username.
- `address` is the nginx-reported client address.
- `meta` is filtered: credential-looking keys are dropped, and values pass
  through the same redaction as the HTTP logs (tokens, secrets, codes, the
  bot token in URL paths).

The latest 50 entries are shown on System health, and audit entries also
feed the overview's activity list.

## AI usage

- **Before Phase 6:** only cumulative counters existed (`quality_metrics.json`,
  totals since 12 May, with no dates). They are still shown as-is.
- **Now:** each provider call is also appended to `data/ai_usage.jsonl`, at
  the same place the counters are bumped. Each row records provider, model,
  stage (`fact_sheet` / `brief` / `unspecified`), tokens and any cost figure.
- **Cost** is one of three things:

  | Kind | Meaning |
  |---|---|
  | *Measured* | No provider here returns a billed amount, so nothing is measured |
  | *Estimated* | The Claude CLI's own `total_cost_usd` (notional on a subscription login), or token counts × operator rates in `CYBERALERTX_AI_PRICES` (JSON, USD per million tokens) |
  | *Unavailable* | Everything else. Never shown as $0. |

- **Views:** daily (Kyiv) and monthly.
- **Image calls** come from the Media Engine usage log. Their cost appears
  only if a provider reported one.
- **Cost controls:** shows the current non-secret settings (providers, caps,
  retry limit, review mode).

## System health

States: **healthy / warning / critical / unknown / not configured**. The
overall state is the worst *required* check; "not configured" never raises
it.

| Check | Source |
|---|---|
| API | Serving the page |
| Website | `GET CYBERALERTX_FRONTEND_PROBE_URL` (default `http://127.0.0.1:3000/en`; `off` disables it); 2.5 s timeout |
| Database | `SELECT 1` through the existing engine when `CYBERALERTX_STORAGE_BACKEND=dual`, otherwise not configured. Never shows the URL. |
| Storage | Data directory writable; free disk space |
| Schedules | `systemctl show` for the API, frontend, ingest, generate and Telegram units and timers (state, last result, next run) |
| Ingestion / generation / Intelligence Core | Records as on the overview |
| Publication | Job worker (not configured until switched on), unknown or abandoned jobs; Telegram configured; each Threads slot (needs-reconnect is critical only when publishing is enabled) |
| Media | Cards recorded; image provider (not configured = branded cards by design) |

- **Probe caching:** probes are cached for 60 s.
- **Recorded failures:** jobs, media, the intel run and Threads errors, each
  marked *persistent* (failed / exhausted / needs an operator) or
  *temporary*.

## Performance

- **No AI or provider calls** on any page load. The only network probe is the
  frontend probe, cached 60 s. The source test fetch runs only when you click
  it.
- **Caching:** the Intelligence Core view is computed once per store change
  or 10 minutes (memoised). Probes are memoised for 60 s.
- **Bounded reads:** server-side pagination (50 per page) for stories and
  jobs; tails of the audit, ledger and usage files only.
- **Measured** (local, worktree data, 170 stories, 200 articles):

  | Page | Time |
  |---|---|
  | First overview after a data change | ≈ 1.3 s |
  | Overview, warm | ≈ 0.25 s |
  | Stories, publishing, usage, warm | < 10 ms |
  | System health | ≈ 0.36 s cold, 6 ms warm |
  | Public `/posts` (unaffected) | ≈ 0.06 s |
