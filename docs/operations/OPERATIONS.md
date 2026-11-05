# CyberAlertX operations reference

The current procedure for running production: release layout, building and
switching releases, rollback, backups, the storage consistency model, the
Telegram publishing and recovery. Stage C documents in `docs/release/` are the
historical record of how this layout was introduced
([docs index](../README.md)).

**Tracked vs host-only.** Everything under `ops/release/` and `server/` is
version-controlled; the host runs installed copies:

| Tracked in Git | Installed on the host as | Purpose |
|---|---|---|
| `ops/release/release_switch.sh` | `/home/cax/stagec-tools/release_switch.sh` | make a release active (forward or back) |
| `ops/release/switch_when_idle.sh` | `/home/cax/stagec-tools/switch_when_idle.sh` | wait for idle writers, then switch |
| `ops/release/api_json_reads.sh` | `/home/cax/stagec-tools/c8_api_json_reads.sh` | JSON-only API override (recovery) |
| `ops/release/o35_units.sh` | run from a checkout | move analytics + held Telegram to `current` (applied) |
| `ops/release/telegram_activate.sh` | run from `current` | Telegram activate / emergency stop / check (§7) |
| `ops/release/verify_release.py`, `settings_check.py`, `loadenv.sh` | `/home/cax/stagec-tools/` | provenance check, resolved settings, safe `.env` loader |
| `server/systemd/*` | `/etc/systemd/system/` | units, timers, the Telegram hold drop-in (installed by `telegram_activate.sh`) |
| `server/backup.sh` | `/usr/local/bin/cax-backup` (cron 03:00) | daily `data/` archive |

Host-only (never in Git): `/home/cax/cax/.env`, `/home/cax/stagec-tools/api-json-backend.env`,
`/etc/cron.d/cax-backup`, TLS keys, the Stage C one-off scripts
(`c5_*`, `c7_*`, `c9_*`, `d1_switch.sh`, `release_rollback.sh`: superseded,
kept for the record).

Install or update the host copies from a reviewed checkout of `main`:
`install -m 0755 ops/release/{release_switch.sh,switch_when_idle.sh,verify_release.py,settings_check.py,loadenv.sh} /home/cax/stagec-tools/`.

## 1. Layout

```
/home/cax/cax/                       canonical git checkout of GitHub main (development only)
/home/cax/cax/.env                   production environment, mode 600 — never in a release, never in Git
/home/cax/cax/data/                  persistent data (JSON stores, media, analytics) — shared by every release
/home/cax/cyberalertx/releases/<id>/ immutable releases: git archive of one commit + venv + frontend build
    RELEASE                          provenance: commit, tree, archive/lock hashes, versions, test results
    data -> /home/cax/cax/data       symlink, never a copy
/home/cax/cyberalertx/current        symlink to the active release (switched atomically)
/home/cax/cyberalertx/staging/<id>/  build-time data snapshot and logs for that release
/home/cax/backups/                   daily data archives + per-change backup directories
```

Release ids are `YYYYMMDD-HHMM-<short sha>`. Code resolves `data/` through its
own release directory (`cyberalertx/config.py` uses `Path(__file__).resolve()`),
so `current/data` is the live data. A release directory has no `.env` on its
search path, so code started from it never auto-loads the checkout's `.env`;
the units pass `EnvironmentFile=/home/cax/cax/.env`, and shells use
`. ops/release/loadenv.sh && loadenv /home/cax/cax/.env` (**never** `source .env`:
an unquoted value aborts the parse and later variables silently stay unset).

## 2. Four different operations

| Operation | What changes | Tool | Restarts |
|---|---|---|---|
| **Build a release** | a new directory under `releases/` | §3 (commands) | none |
| **Switch the active release** | the `current` symlink | `switch_when_idle.sh` → `release_switch.sh` | api, frontend, run |
| **Roll back** | the same switch, to an earlier release id | `release_switch.sh <earlier id>` | api, frontend, run |
| **Database migration** | Postgres schema | `python -m cyberalertx.tools.pg_migrate`, run by hand from the release, separately authorized | none |

The switch scripts never build, migrate, edit `.env`, touch units or timers,
or enable publishing. `generate` (timer) picks up `current` at its next run.

## 3. Build a release (no production effect)

From a reviewed commit of `main` whose CI passed. Staging ports 8190/3190 must be free.

```bash
SHA=<40-char commit>; ID=$(date +%Y%m%d-%H%M)-${SHA:0:7}
R=/home/cax/cyberalertx/releases/$ID; SNAP=/home/cax/cyberalertx/staging/$ID
mkdir -p $R && git -C /home/cax/cax archive $SHA | tar -x -C $R
python3 -I /home/cax/stagec-tools/verify_release.py $R /home/cax/cax $SHA        # 0 mismatched, exit 0
python3 -m venv $R/venv && $R/venv/bin/pip install -q --upgrade pip \
  && $R/venv/bin/pip install -q -r $R/requirements.lock && $R/venv/bin/pip check
# data snapshot for prerendering (the release reads it until it is linked to live data)
mkdir -p $SNAP/data && cp -a /home/cax/cax/data/{items.json,threat_posts.json,media} $SNAP/data/ && ln -s $SNAP/data $R/data
(cd $R && env -i HOME=$HOME PATH=/usr/bin:/bin CYBERALERTX_STORAGE_BACKEND=json \
   venv/bin/python -m cyberalertx.main serve --host 127.0.0.1 --port 8190 > $SNAP/api.log 2>&1 &)
cp -a /home/cax/cax/frontend/.env.production $R/frontend/.env.production
(cd $R/frontend && npm ci --no-audit --no-fund && API_URL=http://127.0.0.1:8190 NEXT_TELEMETRY_DISABLED=1 npm run build) > $SNAP/build.log 2>&1
# verify inside the release
(cd $R && env -i HOME=$HOME PATH=/usr/bin:/bin venv/bin/python -m pytest -q -p no:cacheprovider | tail -1)
(cd $R && venv/bin/python -m mypy | tail -1); (cd $R/frontend && npm run -s type-check && npm audit --omit=dev | tail -1)
# pages on 3190 against the staging API, then stop both (only processes whose cwd is inside $R)
# link live data, record provenance, protect code
ln -sfn /home/cax/cax/data $R/data.tmp && mv -T $R/data.tmp $R/data
{ echo "release_id=$ID"; echo "commit=$SHA"; echo "tree=$(git -C /home/cax/cax rev-parse $SHA^{tree})"
  echo "requirements_lock_sha256=$(sha256sum < $R/requirements.lock | cut -d' ' -f1)"
  echo "package_lock_sha256=$(sha256sum < $R/frontend/package-lock.json | cut -d' ' -f1)"
  echo "created_utc=$(date -u +%FT%TZ)"; } > $R/RELEASE
chmod -R a-w $R/cyberalertx $R/frontend/app $R/frontend/lib
python3 -I /home/cax/stagec-tools/verify_release.py $R /home/cax/cax $SHA
```

The 5 Nov 2026 cutover followed exactly these steps
([release record](../release/RELEASE_2026-11-05.md)).

## 4. Switch (and roll back)

1. **Backup first** (§6): `threat_posts.json`, `items.json`, the current
   `RELEASE`, unit files and drop-ins, `.env` hash + mode (never its contents),
   and a `pg_dump -t public.threat_posts` when Postgres is in use.
2. `sudo bash /home/cax/stagec-tools/switch_when_idle.sh <release-id>`
   * waits up to 10 min for `generate` to be inactive and no ingest cycle to be
     running; fails closed (exit 3, nothing switched) if they stay busy or their
     state cannot be read; never stops a writer;
   * then `release_switch.sh`: preflight (commit recorded, venv, frontend
     build, `data` link, units on `current`), lock against concurrent switches,
     atomic `current` switch, restart api/frontend/run, wait for `/healthz` and
     `/en` = 200. Output names the previous and the new release, both commits,
     the health result and the command to go back.
3. Verify: `readlink /home/cax/cyberalertx/current`; each service's
   `readlink /proc/<MainPID>/cwd`; EN/UA feeds; journals since the switch.
4. **Rollback** = `sudo bash /home/cax/stagec-tools/release_switch.sh <previous-id>`
   (old releases are never deleted). If a switch fails its health check,
   `current` is left on the new release and the exact switch-back command is
   printed: run it.

## 5. Storage and consistency

* **JSON is authoritative** (`data/items.json`, `data/threat_posts.json`).
  With `CYBERALERTX_STORAGE_BACKEND=dual` (production) every write also goes
  to Postgres (shadow; editorial decisions use a strict write that reports a
  Postgres failure).
* **Reads (O27):** JSON first. A JSON miss is answered from an in-memory
  index of the keys Postgres holds (one keys query, refreshed in the
  background every `CYBERALERTX_PG_INDEX_TTL_SECONDS`, default 60) plus one
  batch load of posts only Postgres has. Requests make no Postgres queries.
  Journal: one `PG key index loaded: N keys, P only in PG` line per process.
* **Connections (O36):** `connect_timeout` 10 s (`CYBERALERTX_PG_CONNECT_TIMEOUT_S`;
  0 = libpq default). Pool: 2 + 8 overflow, pre-ping, recycle 30 min. A dead
  database costs a writer at most the timeout per attempt; the API's first
  feed read waits at most 2 s for the index, later reads never wait.
* **Re-sync (O28):** `python -m cyberalertx.tools.import_ai_cache_to_postgres
  --dry-run` (read-only plan) then without `--dry-run` copies JSON → Postgres,
  writes only differing rows, verifies, never deletes and never writes JSON.
  Runbook: [O28_RECONCILIATION_RUNBOOK.md](../release/O28_RECONCILIATION_RUNBOOK.md).
  A dry run on the live file must show `insert 0, update 0`.
* Migrations live in `cyberalertx/storage/pg/migrations/` (001–005 applied in
  production). Never run them from a switch; never re-run 005.

## 6. Backups

| What | Where | Made by |
|---|---|---|
| `data/` daily archive (14 days kept) | `/home/cax/backups/data-YYYYMMDD-HHMMSS.tar.gz` | cron 03:00 `cax-backup` (`server/backup.sh`) |
| Per-change backups (cutover, unit migration) | `/home/cax/backups/<change>-<timestamp>/`, mode 700, `SHA256SUMS` | the operator / `o35_units.sh` |
| Repository refs before consolidation | `/home/cax/backups/repo-consolidation-20261104-2235/` | 4 Nov 2026 |
| Postgres | Supabase's own daily backups; `pg_dump` before any write | Supabase / operator |

Verify a backup directory with `(cd <dir> && sha256sum -c SHA256SUMS)` and a
dump with `pg_restore -l <dump>`. Never delete backups or old releases as part
of a change.

## 7. Telegram

**Scheduling.** `cyberalertx-telegram.timer` (10 runs a day, at :15 past
00, 06, 08 … 22 UTC) starts `cyberalertx-telegram.service`. The service runs
`tools.publish cycle --send --limit 1` from `current`: it plans jobs, imports the
publish ledger and sends at most one post per channel, inside a 48 h window.
Job ids are deterministic and the ledger is checked before every send, so a
re-run cannot post twice.

**The hold is the emergency control.** The drop-in `stage-c-hold.conf`
(`ConditionPathExists=/home/cax/cyberalertx/STAGE_D_AUTHORIZED`) stays
installed permanently. While the marker exists, runs proceed. Remove it and every
run is skipped without an error.

| Action | Command (as root) |
|---|---|
| Status, read-only | `bash /home/cax/cyberalertx/current/ops/release/telegram_activate.sh check` |
| **Emergency stop** | `bash …/telegram_activate.sh deactivate` (removes the marker, disables the timer) |
| Activate / resume | `bash …/telegram_activate.sh activate` |

`activate` runs these steps in order and stops at the first failure:
1. preflight on the active release;
2. read-only Bot API check (`check-telegram`: bot identity, each channel
   reachable, bot is an administrator allowed to post; nothing is sent);
3. a media run, so current stories have their illustration;
4. backup of the units, ledger and job store to
   `/home/cax/backups/telegram-activation-*`;
5. installs the tracked units;
6. **baseline**: cancels the Telegram jobs of every article published before
   now, so there is no backlog and no replay;
7. creates the marker and enables the existing timer.

If the bot check or the media run fails, nothing has changed yet. The first
scheduled run is the live verification; no test message is ever sent. To
resume after a long stop, run `activate` again: its baseline cancels whatever
accumulated meanwhile.

```bash
journalctl -u cyberalertx-telegram -n 50 --no-pager          # last runs
cd /home/cax/cyberalertx/current && . ops/release/loadenv.sh && loadenv /home/cax/cax/.env
venv/bin/python -m cyberalertx.tools.publish status           # jobs by state
venv/bin/python -m cyberalertx.tools.publish pending          # what is due next
```

**Message format** ([PUBLICATION_ENGINE.md](../publish/PUBLICATION_ENGINE.md#telegram-message-format)).
Each post is a photo (the story illustration, same asset as the website) with
this caption. Before, from the legacy publisher:

```text
🟠 Storm-2603 breaks into SharePoint servers without leaving files on disk
The Storm-2603 group broke into a company's SharePoint server and ran its tools from memory, …
Kaspersky researchers on Securelist analyze a fileless SharePoint intrusion …
✅ What to do
• Read Kaspersky's "The SOC Files 5" report on Securelist for its detection guidance.
• Hunt for Storm-2603 activity on SharePoint servers using the detection methods in that report.
• Don't treat a clean file scan as proof a SharePoint server is uncompromised.
Source: Securelist (Kaspersky)
🔗 Read more — the full brief
#exploit
```

After (same story, the publication engine):

```text
Storm-2603 breaks into SharePoint servers without leaving files on disk
The Storm-2603 group broke into a company's SharePoint server and ran its tools from memory, …
Kaspersky researchers on Securelist analyze a fileless SharePoint intrusion …
Why it matters: Storm-2603 runs its code in memory instead of saving files, so a SharePoint
server that passes a disk-based antivirus scan can still be compromised.
Severity: High
What to do:
• Read Kaspersky's "The SOC Files 5" report on Securelist for its detection guidance.
• Hunt for Storm-2603 activity on SharePoint servers using the detection methods in that report.
Source: Securelist (Kaspersky)            ← linked to the original article
Read more: the full brief on CyberAlertX
#exploit
```

What changed, from a review of 40 live posts (20 EN, 20 UA):
- The source is always present and linked. Before, it was missing from 15 of
  the 20 EN posts and 6 of the 20 UA posts.
- A sentence that repeats the summary is dropped.
- Status lines state only facts, and compromise is never claimed for a
  vulnerability.
- Actions are capped at two and appear only when the story justifies them.
- The illustration replaces the link preview, which had repeated the headline
  a third time.

**Threads** stays off: `CYBERALERTX_THREADS_PUBLISH=0`. Resolved flags,
including `review_mode` (production: `flag`):
`cd /home/cax/cyberalertx/current && . ops/release/loadenv.sh && loadenv /home/cax/cax/.env && PYTHONPATH=. venv/bin/python ops/release/settings_check.py`.

## 8. Services

| Unit | Restarted by a switch | Notes |
|---|---|---|
| `cyberalertx-api` | yes | FastAPI :8000 |
| `cyberalertx-frontend` | yes | Next.js :3000 |
| `cyberalertx-run` | yes | ingest every 30 min |
| `cyberalertx-generate` | no (timer, hourly) | then the media run (illustrations); next run uses the new `current` |
| `cyberalertx-analytics` | no (timer, 03:00) | after O35: runs from `current` |
| `cyberalertx-telegram` | no (timer, 10/day) | runs from `current`; hold marker = on/off switch (§7) |

## 9. Recovery

| Symptom | Action |
|---|---|
| New release unhealthy after a switch | `release_switch.sh <previous-id>` (printed by the failed switch) |
| Dual-mode API slow, `PG key index load failed`, feeds empty | `sudo bash /home/cax/stagec-tools/c8_api_json_reads.sh apply` (JSON-only API, restarts only the API); diagnose; re-sync (§5) before `revert` |
| Postgres unreachable | nothing to do for readers (JSON); writers log `dual-write: PG … FAILED` and continue; re-sync after recovery |
| `threat_posts.json` unreadable | readers fail closed (no stale Postgres fallback); writes refuse; restore the file from the newest backup |
| A feed keeps failing (e.g. CISA `http_403`) | `/admin/sources` shows `Fetch failing: <error>`; the source backs off (30 min doubling, max 24 h for refusals, 6 h for transient errors) and recovers by itself |
