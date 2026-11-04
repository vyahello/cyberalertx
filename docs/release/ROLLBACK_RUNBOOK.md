# Rollback runbook

> Not executed. These are administrator steps (sudo) for the moment a release
> misbehaves. Each section undoes exactly one stage of DEPLOYMENT_RUNBOOK.md,
> newest first. Roll back the smallest stage that fixes the problem.

## 1. Decision guide

| Symptom | Roll back |
|---|---|
| Duplicate or wrong-language posts, or many `outcome_unknown` after the scheduler switch | §3 (Stage D only) |
| Threads posting problems | Set `CYBERALERTX_THREADS_PUBLISH=0` (takes effect at the next run) |
| Photo problems | Set `CYBERALERTX_TELEGRAM_ATTACH_IMAGES=0` |
| Site, API or admin broken, or generate failing after §6 | §4 (whole release) |
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

## 4. Undo the release (back to `/home/cax/cax`, the previous known-good code)

```bash
sudo systemctl stop cyberalertx-generate.timer cyberalertx-telegram.timer
systemctl is-active cyberalertx-generate.service cyberalertx-telegram.service   # inactive

# restore the unit files saved in DEPLOYMENT_RUNBOOK §2 (they point at /home/cax/cax)
sudo cp -a /home/cax/backups/<TS>/cyberalertx-* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart cyberalertx-api cyberalertx-frontend cyberalertx-run
curl -sf 127.0.0.1:8000/healthz && curl -s -o /dev/null -w '%{http_code}\n' 127.0.0.1:3000/en
sudo systemctl start cyberalertx-generate.timer cyberalertx-telegram.timer
```

The old checkout still has its own venv and its last frontend build, because
the release never touched it. The `current` symlink can stay; nothing uses it
after the units are restored.

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
