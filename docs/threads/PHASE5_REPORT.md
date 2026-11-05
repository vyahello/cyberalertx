# Phase 5 — Threads integration: final report

> **Status: historical record.** Paths such as `$APP_HOME-redesign` and the deployment steps described here predate the release layout; see [docs/README.md](../README.md) for current documents.

Everything was done in `$APP_HOME-redesign` (branch `redesign/cti-platform`).

- Nothing was deployed, committed or pushed.
- **No real Threads request was made and no post was sent.**
- No Meta app was created, and no real credentials or account ids were used.
- Production is untouched: its git status is clean, it has no Threads or job
  files, and `cryptography` is not installed in its venv.

**Status labels used below**

| Label | Meaning |
|---|---|
| **[mock-tested]** | Implemented and covered by automated tests against a stateful mock of the Threads Graph API |
| **[real-verified]** | Verified with real Meta credentials. **Nothing is in this category.** |
| **[blocked]** | Needs the Meta app, tester roles and/or App Review, which only the owner can set up |
| **[not implemented]** | Out of scope or deliberately left out |

## 1. Existing Publication Engine architecture

These Phase 4 pieces are reused without duplication:

- One `PublicationJob` per story, edition, destination and type, stored in a
  locked JSON job store.
- `plan()` uses the existing gates. `run()` handles claim/lease, then
  prepare → deliver, then records the result.
- Error categories drive retry with backoff, `failed`, or `outcome_unknown`.
  Pauses are keyed by `(destination, locale)`.
- The existing CLI (`tools.publish`), `/admin/publishing` and the timer path
  (`cycle --send`).

No new queue, worker or scheduler was added.

## 2. Threads adapter design **[mock-tested]**

- **One class, `ThreadsDestination`**, with one instance per account slot.
  Each is registered as destination `threads@{slot}`.
- **Same contract as the website and Telegram adapters:** `enabled`,
  `plans_for`, `qualifies`, `prepare` and
  `deliver(prepared, on_sending)`.
- **Two engine changes, both backward compatible:**
  - `PublicationJob.external_state` holds the container id.
  - `on_sending(phase=…, **state)` persists progress before each external
    step.
- **Unchanged:** website and Telegram identities and behaviour. Their full
  test suites pass.

## 3. Official API documentation checked (Nov 2026)

Source: developers.facebook.com/docs/threads. Pages read:
- get-access-tokens-and-permissions
- long-lived-tokens
- posts
- reference/publishing
- troubleshooting
- overview (rate limits and media specifications)
- threads-media
- threads-profiles
- get-started
- the changelog, latest entry 18 Aug 2026

What the code uses:

| Area | Details |
|---|---|
| Hosts | `threads.com/oauth/authorize`; `graph.threads.com` (the docs say `graph.threads.net` also works); Graph calls use `v1.0` |
| OAuth | `POST /oauth/access_token` (code → short-lived token + `user_id`); `GET /access_token?grant_type=th_exchange_token` (→ 60-day token); `GET /refresh_access_token?grant_type=th_refresh_token` (token ≥ 24 h old and unexpired → +60 days) |
| Publishing | `POST /{user}/threads` (`media_type` TEXT/IMAGE, `image_url`, `text`, `alt_text` ≤ 1000, `topic_tag`); `GET /{container}?fields=status,error_message` (`IN_PROGRESS`/`FINISHED`/`PUBLISHED`/`ERROR`/`EXPIRED`); `POST /{user}/threads_publish` (`creation_id`) |
| Retrieval | `GET /{media}?fields=permalink`; `GET /{user}/threads` (our posts, `since`) |
| Quota | `GET /{user}/threads_publishing_limit` (`quota_usage`, `config`) |
| Container timing | Wait about 30 s before publishing; poll at most once a minute, for up to 5 minutes; unpublished containers expire after 24 h |
| Text limits | 500 characters (emoji count as UTF-8 bytes); at most 5 links (enforced since 22 Dec 2025, `THREADS_API__LINK_LIMIT_EXCEEDED`); one topic tag (1–50 characters, no `.` or `&`) |
| Images | JPEG/PNG, ≤ 8 MB, width 320–1440, aspect ratio ≤ 10:1, sRGB; fetched by Threads from a public URL |
| Rate limits | 250 API-published posts per profile per 24 h (moving window); call quota 4800 × impressions per 24 h |

**Not in the Threads docs:** an error-code table. Graph codes are classified
by Meta's general Graph conventions; see item 13.

## 4. OAuth implementation **[mock-tested; real flow blocked]**

- **Connect** is a POST form, protected by the existing admin CSRF token and
  same-origin check. It issues a state bound to the slot and answers with a
  page holding a "Continue to Threads" link. A form redirect would be blocked
  by `form-action 'self'`.
- **The callback** `GET /admin/threads/callback` sits behind admin Basic auth.
  In order, it:
  1. consumes the state (one-time, 10-minute expiry, bound slot);
  2. handles `error=access_denied`;
  3. strips `#_` from the code;
  4. exchanges the code for a short-lived token, then a long-lived one;
  5. calls `/me` and checks the profile id matches the token's `user_id`;
  6. stores the encrypted token in **that slot only**.

  It refuses to move a connected slot to a different profile without a
  disconnect first.
- **Tested cases:** valid callback, forged state, reused state, expired
  state, denial, bad code, slot binding, slot conflict.

## 5. Permissions

`threads_basic` and `threads_content_publish`. Nothing else is requested.

## 6. Account connection model **[mock-tested]**

- **Mapping:** `CYBERALERTX_THREADS_ACCOUNTS` maps slot to locale
  (default `en:en,ua:ua`; `uk` is accepted). It is one-to-one: a duplicate
  locale or slot is rejected.
- **Per slot:** Threads user id, username and display name; encrypted token;
  token issue time and expiry; last refresh; last verification; status
  (`connected`, `needs_reconnect` or `disconnected`); last error; rate-limited
  until; connect and disconnect times.
- **Adding a third profile** is one more `slot:locale` pair, with no code
  change.

## 7. Token storage and lifecycle **[mock-tested]**

- **Storage:** Fernet (`cryptography`) under `CYBERALERTX_THREADS_TOKEN_KEY`,
  in `data/threads_accounts.json` with mode 0600. The project had no secret
  store; this is the smallest addition that fits its JSON conventions.
- **Fails closed:** with no key, a bad key or no package, nothing is stored,
  and a wrong key cannot decrypt.
- **Never exposed:** the public view, admin HTML and JSON never contain the
  token or its ciphertext.
- **Refresh:**
  - Any token with fewer than 30 days left, and at least 24 h old, is
    refreshed at the start of each `cycle --send` or via
    `tools.threads refresh`.
  - An expired token, or a refresh refused with code 190 or a permission
    error, sets the slot to `needs_reconnect` and logs
    `OPERATOR ACTION NEEDED`. Only that slot stops; there is no retry loop.
  - Temporary failures are recorded and retried on the next run.
- **Verify** makes one `/me` call per slot.

## 8. English and Ukrainian routing **[mock-tested]**

- A slot only ever receives jobs for its mapped locale.
- `prepare` rejects any other locale/slot combination as `invalid_content`.
- **Language gate**, as Telegram: the EN profile gets English-source stories
  only; the UA profile gets both.
- **Tests confirm:** EN posts carry `/en/` links and English text, UA posts
  carry `/ua/` and Ukrainian.
- **Isolation tests:** disconnecting EN leaves UA untouched; a UA auth
  failure (UA `needs_reconnect`, its job failed) does not stop EN publishing
  in the same run; one account's 429 does not pause the other.

## 9. Content formatting **[mock-tested]**

`threads/format.py` builds a Threads-native post. It is not the Telegram
message.

- **Structure:** headline, then the plain explanation.
- **Optional parts:**
  - a specific technical fact, only when it adds a name, number or CVE id
    that the headline and explanation lack; a "BleepingComputer reports"
    attribution alone does not count;
  - why it matters;
  - "What to do / Що зробити: <first action>".
- **Always last:** the article link.
- **Never included:** HTML, emoji, a hashtag row, urgency words, or anything
  not already in that edition's validated text.
- **Topic tag:** one, `Cybersecurity` / `Кібербезпека`, sent as a parameter.
- **UA source:** UA posts come from the UA edition, never translated from
  EN.
- **Over 500 characters,** applied deterministically:
  1. Drop *why it matters*.
  2. Drop the fact or the action. A fact with a hard identifier outranks the
     action.
  3. Shorten the explanation at a sentence or word boundary.

  URLs and identifiers are never cut.
- **Examples:** real worktree samples are in the session scratchpad
  (`phase5_threads_sample.txt`). EN freezer story: 395/500 characters. UA:
  382/500. Synology EN/UA: 494 and 475.

## 10. Media integration **[mock-tested; public fetch unverified]**

- **Image:** the edition's existing Media Engine card, `threads-portrait`
  (1080×1350 PNG, versioned public URL), with the card's localized alt text
  as `alt_text`. Nothing new is generated, and no illustration is required.
- **Pre-flight check** before a container is created: the card is fetched
  without credentials and must return 200, PNG/JPEG, ≤ 8 MB, width 320–1440,
  ratio ≤ 10:1.
- **Fallback:** a failed check, a refused image container, or an image
  container in `ERROR` all lead to one text-only post.
- **Unverified:** whether Threads can actually fetch the cards depends on the
  card routes being deployed. Not tested live.

## 11. Container and publication states **[mock-tested]**

Job statuses stay Phase 4's. Container progress lives in `phase`
(`container_created`, `sending`) and `external_state`: container id,
creation time, media type.

| Situation | Result |
|---|---|
| Container `FINISHED` | Publish, then fetch the permalink |
| `IN_PROGRESS` past the poll budget | `retrying`, the same container next run |
| `EXPIRED` | New container |
| `ERROR` with image | One text container |
| `ERROR` without image | `failed` |
| Publish timeout, 5xx or unreadable reply | Check the container. `PUBLISHED`: find our post (exact text match) → `published`. `FINISHED`: `retrying` with the same container. Otherwise: `outcome_unknown` |

A crash after container creation resumes that container. A crash during
publishing becomes `outcome_unknown`.

## 12. Idempotency limitations

**Guaranteed:**
- one job per story, edition and account;
- one claim per job (tested with concurrent workers);
- every attempt starts by checking the stored container, so a second
  container is never created while the first could still publish;
- Threads publishes a container once.

**Not possible:** exactly-once delivery. Threads offers no idempotency key.
The remaining case is "the publish response was lost and the API could not
confirm either way". That becomes `outcome_unknown`; it is never retried
blindly.

## 13. Retry and reconciliation **[mock-tested]**

**Error classification.** Threads publishes no code table; these follow Meta's
general Graph conventions:

| Signal | Category |
|---|---|
| 429, codes 4/17/32/613, or quota used up | `rate_limit` (respects `Retry-After`; pauses that account only) |
| 190, or 401 | `auth` |
| 10, 200–299, or 403 | `permission` |
| 5xx | `temporary` |
| Connect error | `network` |
| Lost response | `unknown_outcome` |
| Other 4xx | `invalid_content` or `missing_media` |

Phase 4 backoff and retry limits apply unchanged. `auth` and `permission`
fail the job, set the account to `needs_reconnect` and log an operator alert.

**Reconciliation:** `tools.threads reconcile` runs before every
`cycle --send` and can be run by hand.

| Container state | Outcome |
|---|---|
| `PUBLISHED`, exactly one post linking to the article | `published` |
| `FINISHED` | Rescheduled, same container |
| Anything else | Left for `tools.publish reconcile JOB --sent ID / --not-sent` |

## 14. Admin UI changes **[mock-tested]**

- **New page, `/admin/threads`,** in the existing admin shell and design. It
  shows per slot: status, profile, token expiry date and days left (never the
  token), last refresh, last verification, rate-limit pause, last error.
  Actions: Connect, Reconnect, Verify, Disconnect.
- **Configuration panel:** shows only set/missing for each setting.
- **JSON:** `/admin/threads.json`, without secrets.
- **Security:** CSRF and same-origin checks; the form CSP is extended to
  `/admin/threads`.
- **Publishing view:** `/admin/publishing` shows Threads EN/UA tiles and jobs,
  with permalink, external id, failures and unknown outcomes.
- **Navigation:** a new "Threads" entry.
- **Screenshots:** desktop 1280 and mobile 390, with no horizontal overflow
  after a wrapping fix for long codes.

## 15. Configuration

Placeholders are in `docs/threads/threads.env.example`:

- `CYBERALERTX_THREADS_APP_ID`
- `CYBERALERTX_THREADS_APP_SECRET`
- `CYBERALERTX_THREADS_REDIRECT_URI`
- `CYBERALERTX_THREADS_TOKEN_KEY`
- `CYBERALERTX_THREADS_ACCOUNTS` (default `en:en,ua:ua`)
- `CYBERALERTX_THREADS_PUBLISH` (**default off**)
- `CYBERALERTX_THREADS_MIN_LEVEL` (default `High`)
- `CYBERALERTX_THREADS_LIMIT` (default 1 per account per run)

Production configuration was not changed.

## 16. Files

**Created:**
- `cyberalertx/threads/{__init__,config,accounts,client,oauth,format,destination}.py`
- `cyberalertx/logsafe.py`
- `cyberalertx/tools/threads.py`
- `cyberalertx/api/admin/threads_page.py`
- `tests/test_threads.py`
- `docs/threads/THREADS_SETUP.md`
- `docs/threads/threads.env.example`
- `docs/threads/PHASE5_REPORT.md`

**Modified:**

| File | Change |
|---|---|
| `cyberalertx/publish/jobs.py` | `external_state` |
| `cyberalertx/publish/orchestrator.py` | Threads planning branch, per-account cap, checkpointing `on_sending` |
| `cyberalertx/tools/publish.py` | Threads destinations behind the flag; refresh and reconcile before `cycle --send` |
| `cyberalertx/publish/telegram.py` | Installs the log redaction; no behaviour change |
| `cyberalertx/api/app.py` | Threads admin routes, CSP |
| `cyberalertx/api/admin/ui.py` | Navigation entry |
| `cyberalertx/api/admin/publishing_page.py` | Tile label |
| `requirements.txt` | `cryptography>=42.0` |
| `tests/test_publication.py` | Bot-token log test |
| `docs/publish/PUBLICATION_ENGINE.md` | Threads section |

## 17. Tests and actual results

| Run | Result |
|---|---|
| Project venv as-is (no `cryptography`) | 1275 passed, 5 skipped (the Threads suite skips cleanly) |
| With `cryptography` on `PYTHONPATH` (installed to a scratch directory, not the production venv) | **1318 passed, 4 skipped** |
| mypy strict | Clean, 113 files |
| tsc | Clean |

`tests/test_threads.py` has 43 tests, all against a stateful fake Threads API
(containers, publishing, posts):

- **Config:** account mapping and the default-off flag.
- **OAuth:** official authorize URL; valid callback with encrypted storage
  and 0600 file; invalid, reused, expired, denied and bad-code callbacks;
  slot binding; slot conflict.
- **Token lifecycle:** refresh lifecycle with isolation; 24-hour minimum age;
  verify detecting revocation; failing closed without a key; no secret in
  logs or the job store.
- **Routing and isolation:** EN and UA routing; wrong-locale rejection;
  disconnect isolation; auth-failure isolation; rate-limit isolation;
  permission failure.
- **Publishing:** image post with the localized portrait card and alt text;
  unreachable-card and refused-image fallbacks; slow container resumed;
  container error retried as text; expired container replaced.
- **Uncertain outcomes:** publish timeout after success recognised; 5xx
  retrying the same container; unknown outcome never retried and later
  auto-reconciled; requeue of an unpublished container; crash after container
  creation; quota limit.
- **Idempotency:** planning and running twice, and concurrently, post exactly
  once; per-account run cap.
- **Formatting:** Threads-native EN, UA from the UA edition, deterministic
  shortening that keeps CVE ids whole, emoji length counting, attribution
  versus fact rule.
- **Compatibility and admin:** website and Telegram identities unchanged with
  Threads enabled; the full admin flow over HTTP (401 without login, CSRF and
  Origin refusals, connect → callback → reused-state refusal → verify →
  disconnect, no secrets in HTML or JSON).

The existing website, Telegram, media and review suites all pass.

## 18. Dependencies added

`cryptography>=42.0`, for token encryption. It is imported only when Threads
is used and is **not installed in the production venv**; installing it is a
deployment step. Nothing else was added.

## 19. Meta App Review requirements still outstanding **[blocked]**

- Create the app with the "Access the Threads API" use case.
- Register the redirect URI.
- Add both profiles as Threads Testers, and accept the invitations.
- Decide whether to stay in development mode with testers or go Live. Going
  Live requires App Review of `threads_basic` and `threads_content_publish`,
  probably with a screencast and privacy policy, and possibly business
  verification.

Meta's docs do not say whether a development-mode app may publish
indefinitely for its tester profiles; confirm in the dashboard.

## 20. Remaining limitations

- **Nothing verified for real.** No call has been made to the real API, so
  all endpoint and field names rest on the documentation.
- **Error codes:** Graph code classification is by general convention.
- **Post matching:** finding a post after a lost publish response relies on
  exact text match (adapter) or the article link (auto-reconcile). An edited
  or flagged post (no permalink) stays `outcome_unknown`.
- **Container polling** waits inside the run: 30 s typically, worst case 30 s
  plus 120 s per post.
  - With two accounts at the worst case, plus Telegram, a run can exceed the
    timer's `TimeoutStartSec=300`.
  - Raise it (e.g. to 600) when switching the timer to `cycle --send`.
  - A run killed mid-poll is safe: the job resumes the same container. A run
    killed mid-publish becomes `outcome_unknown` and is auto-reconciled.
- **No Breaking follow-ups** to Threads. The Telegram-only flag is unchanged.
- **The authorization code** appears in nginx access logs. It is single-use
  and short-lived; documented.
- **Planning while disconnected:** no jobs are planned for a disconnected
  slot. Stories inside the 48 h window are picked up after reconnecting.

## 21. Exact steps to connect both accounts

Full detail is in `docs/threads/THREADS_SETUP.md`.

1. Create the Meta app (Threads use case). Add the redirect URI
   `https://cyberalertx.com/admin/threads/callback`. Add both profiles as
   Threads Testers and accept the invitations on threads.com.
2. Deploy, then on the server: `pip install 'cryptography>=42'` and
   `python -m cyberalertx.tools.threads gen-key`.
3. Put the app id, secret, redirect URI and key in `.env`, with
   `CYBERALERTX_THREADS_PUBLISH=0`. Restart the API.
4. Check that the Configuration panel on `/admin/threads` shows everything as
   *set*.
5. Log in to Threads as CyberAlertX EN. On `/admin/threads`: Slot en →
   Connect → Continue → approve.
6. Log out of Threads and log in as CyberAlertX UA. Slot ua → Connect →
   Continue → approve.
7. Press Verify on both slots (or `tools.threads verify en|ua`).
8. When you decide to go live: preview with
   `CYBERALERTX_THREADS_PUBLISH=1 python -m cyberalertx.tools.publish run`
   (no `--send`), then set `CYBERALERTX_THREADS_PUBLISH=1`.

## 22. Recommended next phase

After a supervised first live post on each profile and a review of
`/admin/publishing`: a small operations pass.
- Alert delivery for `OPERATOR ACTION NEEDED` (today it is the journal and
  the admin page only).
- Scheduled `tools.threads refresh` independent of the publish timer.
- Optionally, Threads follow-ups for materially changed Breaking stories,
  behind their own flag.

**Phase 6 not started; real Threads publishing not activated.**
