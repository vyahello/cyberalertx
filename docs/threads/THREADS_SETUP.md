# Threads: two accounts, one Meta app

CyberAlertX publishes to two Threads accounts through **one** Meta app,
"CyberAlertX Publisher" (its Threads App ID is set as `THREADS_APP_ID`):

| Account | Language | Site | Content |
|---|---|---|---|
| `@cyberalertx` | English | https://cyberalertx.com/en | EN editions only |
| `@cyberalertx_ua` | Ukrainian | https://cyberalertx.com/ua | UA editions only |

Each account authorizes the app and gets its own **user access token**
(Meta's User Token Generator) with `threads_basic` and
`threads_content_publish`. The app stays in Development Mode: both
accounts are Threads Testers. App Review is only needed for accounts
beyond the testers.

## Configuration (.env)

```env
THREADS_ENABLED=0                 # the switch; 0 = Threads off, Telegram and the site unaffected
THREADS_APP_ID=                   # one shared app id (not a secret, not a user id)
THREADS_EN_USERNAME=cyberalertx
THREADS_EN_ACCESS_TOKEN=          # written by `setup`, never by hand
THREADS_UA_USERNAME=cyberalertx_ua
THREADS_UA_ACCESS_TOKEN=          # written by `setup`, never by hand
# THREADS_APP_SECRET=             # only if a short-lived token had to be exchanged
# THREADS_DAILY_LIMIT=3           # posts per account per 24 h (pilot)
```

There is no per-account App ID, no per-account secret and no configured
user id. Each account's Threads user id is read from
`GET /v1.0/me?fields=id,username` with **its own token**. It is stored,
with the username, token expiry, scopes and health, in the account
registry `data/threads_accounts.json` (mode 600, no token, no secret).

## Setup (once, and whenever a token is replaced)

As the application user, from the active release:

```bash
cd $APP_ROOT/current && venv/bin/python -m cyberalertx.tools.threads setup
```

1. It asks for the EN and UA tokens with **hidden input**. Pressing Enter
   keeps the current token. Tokens are never command-line arguments.
2. For each token, independently:
   - `/me` must return exactly the expected username;
   - `debug_token` (authenticated by the tester's own token) must report a
     valid token, the same user id, both permissions and the expiry;
   - the two accounts must be different Threads users.
3. A short-lived token is exchanged for a long-lived one (`th_exchange_token`).
   Only then does it ask once for the shared App Secret.
4. Only if **both** accounts pass:
   - the current .env is copied to `~/backups/threads/` (directory 0700,
     file 0600);
   - the THREADS_* lines are rewritten atomically, keeping every other line;
   - both accounts are registered.

   If either account fails, nothing changes.
5. An account already registered to another Threads user is refused unless
   `--allow-identity-change` is given. Identities are never swapped silently.
6. Setup never sets `THREADS_ENABLED=1`.

Check with `venv/bin/python -m cyberalertx.tools.threads status --live`. It
shows the app id, both accounts (username, user id, expiry, scopes, last
verification and publication, queue counts, last error) and the switch.
It never shows a token or the secret.

## Token lifecycle

Long-lived tokens last 60 days. The actual expiry comes from `debug_token`
and is never assumed. Before every sending run each account is checked
(`/me`: same user id and username). A token with less than 30 days left
that is at least 24 h old is refreshed (`th_refresh_token`):
- the new token is validated first;
- it is then written into .env atomically, with the previous file backed
  up until the write is confirmed;
- the process uses it immediately.

A refusal is logged as `OPERATOR ACTION NEEDED`. An expired, refused or
mis-mapped token stops **only its own account** (`needs_reconnect`). The
other account keeps publishing. Fix: generate a new token and run `setup`.

## Publishing

The Telegram timer's run (`tools.publish cycle --send`) also serves
Threads when `THREADS_ENABLED=1`, as destinations `threads@en` and
`threads@ua`. Its rules:
- **Language:** EN editions go to `@cyberalertx`, UA editions to
  `@cyberalertx_ua`. A story without that language is skipped for that
  account, and nothing is translated for Threads.
- **No backlog:** on the first sending run with Threads on, each account
  records `publishing_since`. Older articles are never posted, and Telegram
  history is not imported.
- **Pilot pace:** at most 1 post per account per run and
  `THREADS_DAILY_LIMIT` (default 3) per 24 h.
- **Image:** the story's canonical illustration, the same asset as the
  website and Telegram (`/media/{asset}/telegram.png`, 1200×675 PNG), with
  its own alt text in the post's language. Without it, or if Threads cannot
  fetch it, the post waits; it is never sent text-only or with another
  picture.
- **Text** (`threads/format.py`): headline, what happened, a "why it
  matters" line or an action only when the evidence justifies one, the
  source, and the article link. It targets 450 characters (hard limit 500)
  and drops whole blocks, never cutting a sentence. A threat actor's claim
  is labelled "Unconfirmed: this is the attackers' own claim." / «Не
  підтверджено: це заява самих зловмисників.» Suspected exploitation is
  labelled as suspected.

Two-step publication, with the container id saved before every step:

```
create IMAGE container ─▶ FINISHED ─▶ threads_publish ─▶ published (post id, permalink)
   ERROR / image refused → retried later with the image (never text)
   publish timeout / 5xx → container checked: PUBLISHED → the post is found, not re-sent;
                           FINISHED → the same container is retried
```

The job id `{story}:{locale}:threads@{slot}` is the uniqueness key, one per
story per account. The job store records:
- the account and its user id;
- the container and post ids, and the permalink;
- the time, the status and redacted errors.

Restarts resume the saved container, and an unclear outcome becomes
`outcome_unknown` instead of a second post.

## Test posts and activation

After deployment, with `THREADS_ENABLED=0`:

```bash
venv/bin/python -m cyberalertx.tools.publish cycle            # preview: no --send, nothing posted
venv/bin/python -m cyberalertx.tools.threads test-post en --asset <16-hex asset id> --alt "<alt>" --confirm
venv/bin/python -m cyberalertx.tools.threads test-post ua --asset <16-hex asset id> --alt "<alt>" --confirm
```

Each `test-post` publishes **one** post that says it is a test, with a
canonical illustration, and prints the permalink. After both are checked
on Threads, set `THREADS_ENABLED=1` (an operator edit of .env). Emergency
stop: set `THREADS_ENABLED=0`. Telegram and the website are unaffected
either way.
