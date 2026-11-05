# Threads setup — two accounts, OAuth, publishing

CyberAlertX publishes to two Threads profiles: **CyberAlertX EN** (slot `en`,
English edition) and **CyberAlertX UA** (slot `ua`, Ukrainian edition). Both
go through the existing Publication Engine. Publishing is **off** until you
switch it on.

> Status when this was written (Nov 2026): implemented and tested against a
> mocked Threads API only. No Meta app exists yet, no account is connected, no
> real request has been made and no post has been sent.

Endpoints and limits below come from Meta's official docs
(developers.facebook.com/docs/threads), checked in November 2026. Re-check the
[changelog](https://developers.facebook.com/docs/threads/changelog) before
going live.

---

## 1. Prerequisites

- A Meta developer account: developers.facebook.com, logged in with the
  Facebook/Meta account that will own the app.
- The two Threads profiles, **CyberAlertX EN** and **CyberAlertX UA**. You
  must be able to log in to each of them in a browser.
- Server access to edit `$APP_HOME/.env`, the EnvironmentFile of the
  systemd units.
- The deployed Phase 1–5 code. The callback route
  `/admin/threads/callback` must be live, and the Media Engine card routes
  must be public, because Threads downloads post images itself.

## 2. Create the Meta app

1. App Dashboard → **Create app**.
2. Choose the use case **Access the Threads API**.
3. Finish the wizard (app name, e.g. "CyberAlertX Publisher", and contact
   email).

The app shows **two** app IDs and secrets. Use the **Threads** App ID and
**Threads** App Secret, under *Use cases → Access the Threads API →
Settings*, not the Facebook ones.

## 3. Redirect URI

Under *Use cases → Access the Threads API → Settings*, add a **Redirect
Callback URL**:

```
https://cyberalertx.com/admin/threads/callback
```

It must match `CYBERALERTX_THREADS_REDIRECT_URI` **exactly**: scheme, host,
path, and any trailing slash. The dashboard sometimes adds a slash; copy back
whatever it shows.

The callback is under `/admin`. nginx forwards it to the API, and it needs the
admin login, which your browser already holds from starting the connection.

Meta also asks for uninstall and delete callback URLs. CyberAlertX does not
use them yet. Point them at `https://cyberalertx.com/admin/threads` if a value
is required.

## 4. Permissions

| Permission | Why |
|---|---|
| `threads_basic` | Required for every Threads endpoint: profile, token refresh, reading our own posts for reconciliation |
| `threads_content_publish` | Create media containers and publish |

Nothing else is requested: no replies, insights or deletion.

## 5. App roles and development mode

A new app starts in **development mode**. In that mode only users with a role
can grant permissions.

1. App Dashboard → **App roles → Roles → Add People → Threads Tester**. Add
   both profiles, CyberAlertX EN and CyberAlertX UA.
2. Each profile accepts the invitation: on threads.com go to **Settings →
   Account → Website permissions → Invites**.

A tester can then connect in step 9/10. This is enough to test the whole flow
with the real API.

## 6. App Review and production

Per Meta's docs, users **without** a role can grant a permission only after
that permission passes **App Review** and the app is published (Live mode).

Both CyberAlertX profiles are your own and can be testers, so App Review may
not be needed for publishing to them. Meta's docs do not say whether a
development-mode app may publish indefinitely for its testers. **Check in the
App Dashboard whether it asks for review or Live mode before relying on
this.**

If you submit for review, you will typically need:
- a screencast of the connect flow and of a published post;
- a privacy policy URL;
- an explanation that the app publishes the publication's own news posts to
  its own profiles.

Business verification may also be requested.

## 7. Environment configuration

Put these in `$APP_HOME/.env`. A placeholder template is in
`docs/threads/threads.env.example`.

| Variable | Value |
|---|---|
| `CYBERALERTX_THREADS_APP_ID` | Threads App ID |
| `CYBERALERTX_THREADS_APP_SECRET` | Threads App Secret. Server-side only; never shown in the UI. |
| `CYBERALERTX_THREADS_REDIRECT_URI` | `https://cyberalertx.com/admin/threads/callback` |
| `CYBERALERTX_THREADS_TOKEN_KEY` | Output of `python -m cyberalertx.tools.threads gen-key` |
| `CYBERALERTX_THREADS_ACCOUNTS` | `en:en,ua:ua` (slot:locale; `uk` is accepted for Ukrainian) |
| `CYBERALERTX_THREADS_PUBLISH` | `0` until step 15 |
| `CYBERALERTX_THREADS_MIN_LEVEL` | Optional, default `High` (same bar as Telegram) |
| `CYBERALERTX_THREADS_LIMIT` | Optional, default `1` post per account per timer run |

Also install the new dependency in the server venv:
`pip install 'cryptography>=42'` (it is listed in `requirements.txt`).

Then restart the API service so it reads the new environment.

**About the token key:** tokens are stored encrypted with this key (Fernet).
If you lose or change it, the stored tokens can no longer be read and both
accounts must be reconnected. Keep a copy wherever you keep the other
secrets.

## 8. Check the configuration

Open `https://cyberalertx.com/admin/threads`. The **Configuration** panel
must show every item as *set*:
- App ID
- App secret
- HTTPS redirect URI
- Token encryption key
- cryptography package

Values are never displayed.

## 9. Connect the English account

1. In the browser, log in to Threads as **CyberAlertX EN**, and only that
   profile.
2. `/admin/threads` → **Slot en → Connect**.
3. Click **Continue to Threads →**. The link is single-use and valid for 10
   minutes.
4. Approve `threads_basic` and `threads_content_publish`.
5. You land back on `/admin/threads`, and slot en shows **connected
   @<username>** with about 60 days of token life.

## 10. Connect the Ukrainian account

1. Log out of Threads, then log in as **CyberAlertX UA**.
2. `/admin/threads` → **Slot ua → Connect** → Continue → approve.

Each slot is decided by the one-time `state` that the Connect button issued
for it, not by anything in the callback URL. Connecting UA therefore cannot
land in the EN slot. If a slot is already connected to a *different* profile,
the connection is refused: disconnect that slot first. This protects against
connecting the wrong profile by accident.

## 11. Verify both connections

Press **Verify connection** on each slot. It makes one authenticated call
(`/me`) and checks the profile id. Both slots should show *connected* and a
fresh *Last verified* time.

From the server:

```bash
python -m cyberalertx.tools.threads status
python -m cyberalertx.tools.threads verify en
python -m cyberalertx.tools.threads verify ua
```

## 12. Token refresh

- **Lifetimes:** the connect flow exchanges the short-lived token for a
  long-lived one, valid 60 days.
- **When refresh is possible:** a long-lived token can be refreshed once it
  is at least 24 hours old and has not expired. Each refresh gives another
  60 days.
- **When it happens:** CyberAlertX refreshes any token with fewer than 30
  days left. This runs automatically at the start of every
  `tools.publish cycle --send` (the Telegram timer, 10 fires a day, once
  switched over) and by hand with `python -m cyberalertx.tools.threads
  refresh`.
- **An expired token cannot be refreshed.** The slot goes to
  `needs_reconnect`, and only that slot stops.

Refresh failures:
- **Refused** (invalid or revoked token, code 190, or a permission error):
  the slot goes to `needs_reconnect`, the error is shown on `/admin/threads`,
  `OPERATOR ACTION NEEDED` is logged, and that slot's jobs stop being claimed.
  The other slot keeps publishing. There is no retry loop.
- **Temporary** (network, 5xx): the error is recorded and refresh is tried
  again on the next run.

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Connection refused: unknown or already used state" | Link reused, page reloaded, or a second tab | Press Connect again |
| "…expired state" | More than 10 minutes on the Threads screen | Press Connect again |
| "…was not granted (user_denied)" | Cancelled on Threads | Connect again and approve |
| "Threads rejected the connection (auth)" | Wrong App ID or secret, redirect URI mismatch, or code already used | Compare `.env` with the dashboard (Threads ID/secret, exact redirect URI) |
| Profile can't approve, or the app isn't found | Profile not a Threads Tester, or the invitation not accepted (dev mode) | Step 5 |
| "connected to another Threads profile … disconnect it first" | Logged into the wrong profile | Disconnect the slot, log in to the right profile, connect |
| Slot shows `needs_reconnect` | Token expired, revoked, password changed, or app removed by the profile | Reconnect (step 14) |
| Jobs `retrying` with `rate_limit` | 429, Graph code 4/17/32/613, or the 250 posts/24 h quota | Nothing; they resume after `retry_after` |
| Jobs fall back to text-only posts | Card URL not public, or not a PNG/JPEG within Threads' size limits | Check `https://cyberalertx.com/{locale}/threat/{id}/card/threads-portrait.png` opens without login |
| Job `outcome_unknown` | The publish response was lost and the API could not confirm either way | `python -m cyberalertx.tools.threads reconcile`, or check the profile and `tools.publish reconcile JOB --sent ID / --not-sent` |
| "Token storage unavailable" | `CYBERALERTX_THREADS_TOKEN_KEY` missing or invalid, or `cryptography` not installed | Step 7 |

## 14. Safe reconnection

1. `/admin/threads` → the slot → **Reconnect**, with the browser logged in to
   that slot's profile.
2. Connecting to the same profile replaces the token in place. Job history
   and everything else is kept.
3. To move a slot to a different profile: **Disconnect** first, then
   **Connect**. Disconnecting deletes only the stored token. Published posts,
   job history and the other slot are untouched.

While a slot is disconnected, no new jobs are planned for it. After
reconnecting, stories from the last 48 hours (the publication window) are
planned again. Older ones are not, so the archive is never re-posted.

## 15. Enabling publication

Only after **both** slots verify, and only when you decide to:

1. On the server, preview what would go out (nothing is sent):
   ```bash
   CYBERALERTX_THREADS_PUBLISH=1 python -m cyberalertx.tools.publish plan --dry-run
   CYBERALERTX_THREADS_PUBLISH=1 python -m cyberalertx.tools.publish run
   ```
   The `run` here is a preview. Look at `threads@en` and `threads@ua` jobs:
   text, image URL, account.
2. Set `CYBERALERTX_THREADS_PUBLISH=1` in `.env`.
3. Publishing happens when the existing timer runs
   `tools.publish cycle --send` (see `docs/publish/PUBLICATION_ENGINE.md`).
   With the default `CYBERALERTX_THREADS_LIMIT=1`, that is at most one post
   per account per run, so 10 a day.
   Raise that service's `TimeoutStartSec` to 600: a Threads post can wait up
   to about 150 s for its container.
4. Watch `/admin/publishing` (Threads EN/UA tiles) and `/admin/threads`.

To stop: set `CYBERALERTX_THREADS_PUBLISH=0`, or disconnect a slot.

---

## Architecture

```
Publication Engine (Phase 4)                       Threads package
plan() ─┬─ website / telegram (unchanged)          config.py   settings, slot↔locale map
        └─ for each "threads@{slot}" destination   accounts.py slots, Fernet-encrypted tokens,
             plans_for(locale)? qualifies()?                    one-time OAuth states (0600 JSON)
run()  ── claim → prepare → deliver ──────────────▶ destination.py ThreadsDestination(slot)
              │                                     client.py   Graph API calls, error classes
              └─ on_sending(phase, **state) ─▶ job  format.py   Threads-native EN/UA text
                                                    oauth.py    connect / callback / refresh / verify
Admin: /admin/threads (accounts), /admin/publishing (jobs)
CLI:   tools.threads (accounts), tools.publish (jobs)
```

- **Identity:** `{story}:{locale}:threads@{slot}:{type}`. One adapter class,
  one instance per slot. A slot serves exactly its configured locale;
  `prepare` rejects any other locale. Website and Telegram identities are
  unchanged.
- **Isolation:** the pause key is `(destination, locale)`, so a 401/403/429 on
  `threads@ua` never pauses `threads@en`. Each slot has its own token,
  expiry, health, last error and rate-limit time.
- **Eligibility:** the same gates as Telegram, from the existing code:
  - rendered and review-visible edition;
  - in scope;
  - 48 h window;
  - source tier;
  - language gate (EN profile takes English-source stories; UA takes both);
  - severity bar `CYBERALERTX_THREADS_MIN_LEVEL`.

### Content

- **What a post is built from:** only that edition's own fields: headline,
  plain explanation, a specific fact when it adds a name, number or
  identifier the explanation lacks, why it matters, and the first action.
  Then the article link.
- **What it leaves out:** HTML, emoji, hashtag rows and "X reports" outlet
  attributions.
- **Topic tag:** one, sent as the `topic_tag` parameter:
  `Cybersecurity` / `Кібербезпека`.
- **Length limit:** 500 characters, counted as Threads counts them (emoji by
  UTF-8 bytes); at most 5 links.
- **When it's too long:**
  1. Drop *why it matters*.
  2. Drop the fact or the action. The fact is kept longer when it carries a
     CVE id, version or count.
  3. Shorten the explanation at a sentence or word boundary.

  Identifiers and URLs are never cut. Output is deterministic.

### Media

- **Image:** the edition's Media Engine card `threads-portrait`
  (1080×1350 PNG, versioned URL on the public site), with the card's
  localized alt text.
- **Check before use:** the URL is fetched without credentials and must return
  200, PNG/JPEG, ≤ 8 MB, width 320–1440, ratio ≤ 10:1.
- **Fallback:** if the check fails, or Threads refuses the image, the post is
  sent text-only. No illustration is required.

### Container state machine

```
                    ┌────────────── stored in job.external_state ───────────────┐
scheduled ─claim─▶ processing
   │                 │ create container (IMAGE, or TEXT)      ──▶ phase=container_created
   │                 │ poll status every 60 s, up to 120 s    (official: wait ~30 s; poll ≤ 1/min)
   │                 │   FINISHED ─▶ phase=sending ─▶ threads_publish ─▶ published (+ permalink)
   │                 │   IN_PROGRESS too long ─▶ retrying (same container next run)
   │                 │   ERROR (image) ─▶ one TEXT container   ERROR (text) ─▶ failed
   │                 │   EXPIRED (24 h) ─▶ new container
   │                 │ publish timeout / 5xx / unreadable reply:
   │                 │   container PUBLISHED ─▶ find our post in recent posts ─▶ published
   │                 │   container FINISHED  ─▶ retrying (same container — Threads publishes a container once)
   │                 │   otherwise / check failed ─▶ outcome_unknown
   └── a retry always starts by checking the stored container, never by creating a new one
```

- **Crash recovery** (expired lease):
  - `container_created`: retried, resuming the stored container.
  - `sending`: `outcome_unknown`.
- **`tools.threads reconcile`:** runs automatically before every
  `cycle --send`, and can be run by hand. It settles `outcome_unknown` jobs
  from the API:
  - PUBLISHED container plus exactly one post linking to the article:
    `published`.
  - FINISHED container: rescheduled, with the same container.
  - Anything else: left for a person, via `tools.publish reconcile JOB`.

### Guarantees and limits

Threads has no idempotency key, so **exactly-once delivery is not
guaranteed.** What is guaranteed:
- one job per story, edition and account;
- one claim per job;
- never a second container while an earlier one might still publish;
- an ambiguous publish is verified or held as `outcome_unknown`, never
  resent blindly.

### Error classes

The Threads docs publish no code table. Codes are classified by Meta's
general Graph API conventions:

| Code(s) | Class |
|---|---|
| 190 | auth |
| 10, 200–299 | permission |
| 4, 17, 32, 613, or HTTP 429 | rate_limit |
| 5xx | temporary |
| other 4xx mentioning image, media or URL | missing_media |
| other 4xx | invalid_content |
| request never sent | network |
| response lost | unknown_outcome |

### Secrets

- **The token** exists only in memory and as Fernet ciphertext in
  `data/threads_accounts.json` (mode 0600).
- **Never exposed:** tokens, the app secret and codes never appear in the
  admin HTML, JSON, job store or logs. A redaction filter on the `httpx`
  logger covers query-string tokens and the Telegram bot token in URL paths.
- **OAuth `state`:** 32 random bytes, stored only as a SHA-256 hash, bound to
  one slot, valid 10 minutes, single-use.
- **Admin actions:** POST with the admin CSRF token and same-origin check.
  The callback requires the admin login.
- **One remaining exposure:** the authorization `code` necessarily appears in
  the callback URL, so nginx access logs record it. It is single-use, valid
  1 hour, already consumed by then, and useless without the app secret.
