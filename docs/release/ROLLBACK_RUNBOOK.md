# Rollback runbook

> **Status: current for its §3 (undo Stage D) and §5 (migration 005 notes); release rollback is [OPERATIONS.md §4](../operations/OPERATIONS.md).**

> Not executed. These are administrator steps (sudo) for the moment a release
> misbehaves. Each section undoes exactly one stage of DEPLOYMENT_RUNBOOK.md,
> newest first. Roll back the smallest stage that fixes the problem.

## 1. Decision guide

| Symptom | Roll back |
|---|---|
| Duplicate or wrong-language posts, or many `outcome_unknown` after the scheduler switch | §3 (Stage D only) |
| Threads posting problems | Set `CYBERALERTX_THREADS_PUBLISH=0` (takes effect at the next run) |
| Photo problems | Set `CYBERALERTX_TELEGRAM_ATTACH_IMAGES=0` |
| Site, API or admin broken, or generate failing after §6 | §4 (whole release: `release_switch.sh <previous-release>`) |
| Migration 005 suspected | §5. Usually no action: old code ignores the columns. |

## 2. Before any rollback

```bash
TS=$(date +%Y%m%d-%H%M); mkdir -p /home/cax/backups/rollback-$TS
cp -a /home/cax/cax/data/items.json /home/cax/cax/data/threat_posts.json \
      /home/cax/cax/data/telegram_published.jsonl /home/cax/backups/rollback-$TS/
[ -f /home/cax/cax/data/publish_jobs.json ] && cp -a /home/cax/cax/data/publish_jobs.json /home/cax/backups/rollback-$TS/
```

Note any `outcome_unknown` jobs on `/admin/publishing`. Check those messages
in the channel before rolling back the worker.

## 3. Undo the scheduler transition (Stage D → legacy publisher)

```bash
sudo systemctl stop cyberalertx-telegram.timer
systemctl is-active cyberalertx-telegram.service                    # wait for inactive
sudo sed -i 's#-m cyberalertx.tools.publish cycle --send --limit 1#-m cyberalertx.main publish-telegram --limit 1#' \
  /etc/systemd/system/cyberalertx-telegram.service
sudo systemctl daemon-reload && systemctl cat cyberalertx-telegram | grep ExecStart
sudo systemctl start cyberalertx-telegram.timer
```

**Safety:**
- The new worker recorded every Telegram send in the shared
  `telegram_published.jsonl`. The legacy command skips those stories, so
  nothing already delivered is sent again [verified: ledger import and ledger
  checks are tested].
- If the timeout was raised for Threads, set it back to 300 in the same edit.

## 4. Undo the release (switch `current` back to an earlier release)

Since 4 Nov 2026 `/home/cax/cax` is the canonical checkout of GitHub `main`
(SINGLE_REPOSITORY_CONSOLIDATION_REPORT.md). It is **not** a rollback target
any more: it holds new code with the old venv and build. Roll back between
immutable releases only:

```bash
ls /home/cax/cyberalertx/releases/                 # pick the previous release id
sudo bash /home/cax/stagec-tools/release_switch.sh <release-id>   # tracked: ops/release/release_switch.sh
# (until the host copy is installed: the older release_rollback.sh, same logic)
```

The script refuses unless the target release records a commit, has its venv
and frontend build, links `data` to `/home/cax/cax/data`, and the api, run,
generate and frontend units all run from `current`. It switches `current`
atomically, restarts api, frontend and run, and waits for `/healthz` and
`/en`. It never touches `.env`, the API JSON-reads drop-in, the Telegram
hold, timers, `data/` or the database. On failure it prints the command that
switches back. [tested with mocks and against the real releases' preflight;
not executed]

`c7_rollback.sh` (Stage C) now refuses with exit 3, because it restarted the
site from `/home/cax/cax`.

**Going back to the legacy (pre-Stage C) application** is no longer a
one-step rollback. Its code is kept as the local tag
`legacy-production-2026-11-04` (`73257f0`) and in
`/home/cax/backups/repo-consolidation-20261104-2235/cyberalertx-all-refs.bundle`.
Build it as a release with the Stage C procedure (git archive of the tag,
venv, frontend build, `data` link), then switch to it with
`release_switch.sh`. The data notes below apply.

**Data compatibility when going back** [verified by reading `main`'s code]:
- **Tolerated:** old code reads `items.json` and `threat_posts.json` written by
  the new code and ignores unknown fields. The new files in `data/` are never
  read by the old code: `publish_jobs.json`, `admin_audit.jsonl`,
  `ai_usage.jsonl`, `fact_sheets.json`, `intel/`, `stories/`, `media/`.
- **Changes after rollback (O19):**
  - On its first ingest cycle (≤ 30 min), the old code **rewrites `items.json`
    without the relevance fields**, including editor relevance overrides.
  - **Old code has no review gate:** editions rejected in `/admin/review`
    become visible again.
- **To roll forward again later:**
  - restore the relevance fields from the copy saved in §2 (or from Postgres
    once 005 is applied);
  - re-apply rejections;
  - re-run `python -m cyberalertx.tools.stories relevance-override …` for
    overrides, which are recorded in `data/stories/relevance_overrides.json`.

**Postgres:** nothing to undo. The old code writes the columns it knows; the
005 columns keep their defaults or values.

## 5. Migration 005

Migrations are forward-only (`storage/pg/migrations/README.md`), and 005 is
additive. If the columns themselves must go, write `006_drop_relevance.sql`
with `ALTER TABLE news_items DROP COLUMN IF EXISTS relevance_status,
relevance_reason, relevance_override;` and apply it with `pg_migrate`. **Do
this only after deploying code without 005 awareness**, or restarting the new
code. The new code re-checks the table on restart and simply stops writing the
columns.

As a last resort, restore the Supabase backup taken in DEPLOYMENT_RUNBOOK §2.

## 6. After any rollback

- `/admin/system` (if the new code is still running) or the journal:
  `journalctl -u cyberalertx-* --since -1h`.
- Telegram channels: no duplicate of the last ledger entries.
- Record what happened in OPEN_ISSUES.md before trying again.
