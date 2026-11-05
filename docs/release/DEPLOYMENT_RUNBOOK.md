# Deployment runbook (release directories)

> **Status: historical (superseded).** Written for the first release (Phase 7, built from the old `cax-redesign` worktree). Current build/switch/rollback procedure: [OPERATIONS.md](../operations/OPERATIONS.md).

> **Nothing in this file has been executed.** Every command is for the
> administrator, run only after the stage is explicitly authorized.
> `sudo` steps change root-owned systemd units.
> Stages: A (done in Phase 7) → B → C → D → E. Never skip ahead automatically.

## 0. What production looks like today [verified, read-only]

| Part | Today |
|---|---|
| Code, venv, data, env | One git checkout: `$APP_HOME` (`main` @ `73257f0`), venv `$APP_HOME/venv`, data `$APP_HOME/data` (233 MB), env `$APP_HOME/.env` (0600) |
| Units | Root-owned copies in `/etc/systemd/system/` (**they differ from `server/systemd/` in git**: ingest runs `--interval 30` live) |
| `cyberalertx-api.service` | `WorkingDirectory=$APP_HOME`, `…/venv/bin/python -m cyberalertx.main serve --host 127.0.0.1 --port 8000` |
| `cyberalertx-frontend.service` | `WorkingDirectory=$APP_HOME/frontend`, `npm start`, `PORT=3000` |
| `cyberalertx-run.service` | `… cyberalertx.main run --interval 30` |
| `cyberalertx-generate.service` + `.timer` | Hourly; `generate --limit 1 --use-llm`; `TimeoutStartSec=300` |
| `cyberalertx-telegram.service` + `.timer` | 10× a day at :15; `publish-telegram --limit 1`; `TimeoutStartSec=300` |
| `cyberalertx-analytics.service` + `.timer` | Daily 03:00; `python -m server.analytics ingest` |
| nginx | `/(posts\|healthz\|admin\|feedback)` → `127.0.0.1:8000`; everything else → `127.0.0.1:3000`; Cloudflare in front |
| Data path | `DATA_DIR = <code root>/data` (no env override). A release directory therefore **symlinks** `data` to the live data directory. The data is never copied or moved. |

## 1. Target layout

```
$APP_ROOT/
  releases/
    20261105-1000-<sha>/        immutable: git archive of the reviewed commit
      venv/                     built here from requirements.lock
      frontend/node_modules, frontend/.next   built here
      data -> $APP_HOME/data             shared, never copied
  current -> releases/20261105-1000-<sha>    atomic symlink switch
$APP_HOME/.env               stays the EnvironmentFile (shared config)
$APP_HOME                    canonical git checkout of main (since 4 Nov 2026); NOT a rollback target
                                 (rollback = release_switch.sh <previous-release>, OPERATIONS.md §4)
```

`config.PROJECT_ROOT` uses `Path(__file__).resolve()`, so code imported through
`current` resolves to its own release directory. `<release>/data` (the
symlink) then points at the live data [assumption, follows from
`config.py:10–11`; checked in §4 step 5].

## 2. Prerequisites and backups (before Stage B)

1. **A reviewed commit.** The Phase 1–7 work is uncommitted in
   `$APP_HOME-redesign`. Commit it on `redesign/cti-platform` yourself and
   note the SHA. This includes `frontend/assets/fonts/` and
   `requirements.lock`.
2. **Stage B authorized.**
3. **Backups:**

   ```bash
   TS=$(date +%Y%m%d-%H%M); mkdir -p $BACKUPS/$TS
   tar -C $APP_HOME -czf $BACKUPS/$TS/data.tgz data      # 233 MB
   cp -a $APP_HOME/.env $BACKUPS/$TS/env.bak && chmod 600 $BACKUPS/$TS/env.bak
   sudo cp -a /etc/systemd/system/cyberalertx-* $BACKUPS/$TS/
   ```

4. **Supabase backup** (before migration 005). Use the Supabase dashboard
   (Database → Backups), or `pg_dump` through a throwaway container so no
   client needs installing. Never print the URL:

   ```bash
   set -a; . $APP_HOME/.env; set +a
   URL="${CYBERALERTX_PG_URL/postgresql+psycopg:/postgresql:}"
   docker run --rm -e URL="$URL" postgres:16-alpine sh -c 'pg_dump --no-owner "$URL"' \
     > $BACKUPS/$TS/supabase.sql
   ```

   If the pooler refuses `pg_dump`, use the dashboard backup.

## 3. Build the release (Stage B — no service impact)

```bash
SHA=<reviewed commit>; ID=$(date +%Y%m%d-%H%M)-${SHA:0:7}
R=$APP_ROOT/releases/$ID
mkdir -p "$R"
git -C $APP_HOME-redesign archive "$SHA" | tar -x -C "$R"

# Python: exactly the set tested in Phase 7 (pip-audit clean)
python3 -m venv "$R/venv"
"$R/venv/bin/pip" install --upgrade pip
"$R/venv/bin/pip" install -r "$R/requirements.lock"      # includes cryptography 50.0.2

# Frontend: same build-time config as production
cp $APP_HOME/frontend/.env.production "$R/frontend/.env.production"
( cd "$R/frontend" && npm ci && npm run build )

# Shared data (symlink, never a copy)
ln -s $APP_HOME/data "$R/data"
chmod -R a-w "$R/cyberalertx" "$R/frontend/app" "$R/frontend/lib"   # optional: immutable code
```

The O1 fix (frontend dependency upgrade) is applied (F5, release candidate 3).
For Stage C, build the production release as in STAGE_C_RUNBOOK.md C2: it prerenders
against a staging API over a data snapshot, then points `data` at the live data.

## 4. Verify the release candidate (still no service impact)

1. **Tests in the release venv** (`json` backend, tmp data; no production
   writes):

   ```bash
   cd "$R" && env -u CYBERALERTX_STORAGE_BACKEND venv/bin/python -m pytest -q   # expect ≈1383 passed
   venv/bin/python -m mypy                                                     # expect: no issues
   ```

2. **Dependency audit:** `venv/bin/pip install pip-audit && venv/bin/pip-audit`
   (expect none), and `cd frontend && npm audit --omit=dev` (expect 0
   critical/high once O1 is done).

3. **Smoke instance on spare ports.** This uses production data read-only, and
   the json backend so nothing is written to Postgres:

   ```bash
   cd "$R" && set -a && . $APP_HOME/.env && set +a
   CYBERALERTX_STORAGE_BACKEND=json venv/bin/python -m cyberalertx.main serve --host 127.0.0.1 --port 8190 &
   (cd frontend && API_URL=http://127.0.0.1:8190 PORT=3190 npx next start -p 3190 -H 127.0.0.1 &)
   curl -sf 127.0.0.1:8190/healthz; curl -sf -o /dev/null -w '%{http_code}\n' 127.0.0.1:3190/en
   curl -s -u admin:"$CYBERALERTX_ADMIN_TOKEN" -o /dev/null -w '%{http_code}\n' 127.0.0.1:8190/admin/system
   ```

   Then stop both (`kill %1 %2`, or kill by port). Never stop
   `127.0.0.1:8000` or `:3000`.

4. **Publication dry run.** It writes nothing, sends nothing and calls no AI:

   ```bash
   cd "$R" && set -a && . $APP_HOME/.env && set +a
   venv/bin/python -m cyberalertx.tools.publish cycle --limit 1    # prints "preview only"
   venv/bin/python -m cyberalertx.tools.pg_migrate --status        # shows 005 pending
   ```

5. **Data path check:**

   ```bash
   venv/bin/python -c "import cyberalertx.config as c; print(c.DATA_DIR.resolve())"
   ```

   It must print `$APP_HOME/data`.

## 5. Migration 005 (needs authorization; safe before or after §6)

```bash
cd "$R" && set -a && . $APP_HOME/.env && set +a
venv/bin/python -m cyberalertx.tools.pg_migrate --status
venv/bin/python -m cyberalertx.tools.pg_migrate          # applies 005 only
venv/bin/python -m cyberalertx.tools.pg_migrate --status # 005 ✓
```

- **Effect:** three `ADD COLUMN IF NOT EXISTS … DEFAULT ''` on `news_items`.
  There is no table rewrite on PG 11+.
- **Old code:** unaffected, because it never names these columns.
- **New code:** starts writing them after its next restart.
- **Failure:** the file is one transaction, so nothing changes. Fix it and re-run.

## 6. Switch services to the release (Stage C — controlled, needs sudo)

> **The step-by-step Stage C procedure, with pause points, verification and
> rollback per step, is STAGE_C_RUNBOOK.md.** This section is the summary.

Choose a quiet slot, just after a generate run (for example hh:05) and not
near hh:15 Telegram fires.

```bash
# 1. pause scheduled work and wait for running oneshots
sudo systemctl stop cyberalertx-generate.timer cyberalertx-telegram.timer
systemctl is-active cyberalertx-generate.service cyberalertx-telegram.service   # both must be inactive

# 2. point `current` at the release
ln -sfn $APP_ROOT/releases/$ID $APP_ROOT/current

# 3. install the unit changes (paths only; commands, users and timers unchanged)
sudo sed -i 's#WorkingDirectory=$APP_HOME/frontend#WorkingDirectory=$APP_ROOT/current/frontend#' \
  /etc/systemd/system/cyberalertx-frontend.service
for u in api run generate telegram; do
  sudo sed -i -e 's#WorkingDirectory=$APP_HOME$#WorkingDirectory=$APP_ROOT/current#' \
              -e 's#$APP_HOME/venv/bin/python#$APP_ROOT/current/venv/bin/python#' \
              /etc/systemd/system/cyberalertx-$u.service
done
#   EnvironmentFile=$APP_HOME/.env stays as it is.
#   cyberalertx-analytics: optional, same two substitutions.
sudo systemctl daemon-reload
systemctl cat cyberalertx-api cyberalertx-telegram | grep -E 'WorkingDirectory|ExecStart'   # review

# 4. restart long-running services
sudo systemctl restart cyberalertx-api cyberalertx-frontend cyberalertx-run

# 5. health
curl -sf 127.0.0.1:8000/healthz && curl -sf -o /dev/null -w '%{http_code}\n' 127.0.0.1:3000/en
curl -sf https://cyberalertx.com/healthz && curl -s -o /dev/null -w '%{http_code}\n' https://cyberalertx.com/en
#    admin: /admin/system → Platform rows healthy; Schedules show the timers stopped (expected now)

# 6. resume scheduled work (Telegram is STILL the legacy command, now from the release)
sudo systemctl start cyberalertx-generate.timer cyberalertx-telegram.timer
```

**Expected behaviour after §6:**
- the redesigned site and admin;
- `generate` adds the fact-sheet call (O7);
- the Telegram channel behaves as before (legacy command), plus the no-text-
  fallback-after-unknown-photo fix (photos are off anyway).

**Stage C checks (manual, authorized):**
- `/admin/system` healthy;
- one generate run produces briefs (watch `/admin/usage` for `fact_sheet` and
  `brief` calls);
- `/admin/review` works;
- cards render on article pages;
- with a private test channel, verify sendPhoto and the fallback through a
  *separate* env file;
- for Threads, see THREADS_SETUP.md;
- confirm the logs are clean: `journalctl -u cyberalertx-api -u cyberalertx-run --since -1h`.

## 7. Publication scheduler transition (Stage D — needs authorization)

**Current:** `cyberalertx-telegram.service` runs
`publish-telegram --limit 1` (legacy, one per channel per run, newest first).

**New:** `python -m cyberalertx.tools.publish cycle --send --limit 1`, from
the same unit and timer.

| Item | Detail |
|---|---|
| What changes | Plans jobs (website, Telegram; Threads only if enabled), then delivers due jobs. Same Telegram cap; newest first; 48 h expiry; retries and reconciliation. |
| Timeout | **Keep `TimeoutStartSec=300`** while Threads is off (measured budget ≪ 300 s). Raise to **600** in the same edit that enables Threads. |
| Environment | No new variables. The existing `CYBERALERTX_TELEGRAM_*` values are used; the photo flag stays off. |

**Dry run (no effect):**

```bash
cd $APP_ROOT/current && set -a && . $APP_HOME/.env && set +a
venv/bin/python -m cyberalertx.tools.publish cycle --limit 1        # preview; check targets and text
```

**Activation:** right after a Telegram fire, so you have 2 h of slack.

```bash
sudo systemctl stop cyberalertx-telegram.timer
systemctl is-active cyberalertx-telegram.service                     # inactive
cd $APP_ROOT/current && set -a && . $APP_HOME/.env && set +a
venv/bin/python -m cyberalertx.tools.publish plan                    # creates jobs; imports the ledger
venv/bin/python -m cyberalertx.tools.publish status                  # Telegram: published (imported) + scheduled
sudo sed -i 's#-m cyberalertx.main publish-telegram --limit 1#-m cyberalertx.tools.publish cycle --send --limit 1#' \
  /etc/systemd/system/cyberalertx-telegram.service
sudo systemctl daemon-reload && systemctl cat cyberalertx-telegram | grep ExecStart
sudo systemctl start cyberalertx-telegram.timer
```

**Never run** `cyberalertx.main publish-telegram` by hand after this. The old
and new commands then never run at the same time, because there is only one
unit and systemd never runs a oneshot twice concurrently.

**Verify, at the next fire:**
- `journalctl -u cyberalertx-telegram -n 50` shows a summary with `published`
  of 1 or 2;
- `/admin/publishing` shows Telegram EN/UA jobs published with message ids;
- the last lines of `data/telegram_published.jsonl` match;
- the channels show one new post each, in the correct language, and no
  duplicate of a ledger entry.

**Rollback:** ROLLBACK_RUNBOOK §3. That is a one-line ExecStart revert. The
shared ledger keeps the legacy command from re-sending what the new one sent.

## 8. Later stages (each separately authorized)

| Stage | Change | How |
|---|---|---|
| E1 | Telegram photos | `CYBERALERTX_TELEGRAM_ATTACH_IMAGES=1` in `.env`, then restart nothing (oneshot reads env each run). Watch fallbacks. |
| E2 | Threads | THREADS_SETUP.md; set `TimeoutStartSec=600` and `CYBERALERTX_THREADS_PUBLISH=1` |
| E3 | Top 10 slot, Breaking follow-ups | `CYBERALERTX_PUBLISH_TOP10_AT`, `CYBERALERTX_PUBLISH_BREAKING_UPDATES` after editorial review |
| — | `hold` review mode | Only after O5 |

## 9. Post-deployment monitoring (first 72 h)

- **Twice daily: `/admin/system`.** Overall should be healthy. Any critical:
  investigate.
- **`/admin/publishing`:** `outcome_unknown` = 0. Failed jobs reviewed daily.
- **`/admin/usage`:** call rate matches expectations (about 2–3 calls per new
  article).
- **Journal:**

  ```bash
  journalctl -u cyberalertx-* --since -6h | grep -E "ERROR|OPERATOR ACTION|Traceback"
  ```

- **Disk:** `df -h /home` above 15 % free. Job file under 5 MB; prune weekly:

  ```bash
  venv/bin/python -m cyberalertx.tools.publish prune --older-than-days 30
  ```

- **Release retention:** keep the current release plus the two previous ones,
  plus the old `$APP_HOME` checkout until the first release has run for
  2 weeks.
