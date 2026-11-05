# O28 reconciliation runbook: JSON review state → Postgres

> **Not executed.** Administrator steps for the release that reverts the O27
> hotfix (API back to `dual`). Run them in this order, on the production host,
> after the release containing the O27 read-path fix is live and before
> `c8_api_json_reads.sh revert`.

## Why

Since the Stage C hotfix (O27) the API reads and writes JSON only. Editor
decisions made in `/admin/review` since then (status, reviewer, time,
quality) exist in `data/threat_posts.json` but not in Postgres. JSON is
authoritative. Every reader, including the new dual read path, uses JSON when
it has the post, so this is not a live defect. But Postgres must match before
anything relies on it: the dual fallback, `hold` mode, or a future Postgres
read path.

`python -m cyberalertx.tools.import_ai_cache_to_postgres` copies JSON → Postgres:
* upserts every JSON entry whose payload differs (insert or update), review fields included;
* never deletes, and never writes JSON;
* reports Postgres rows that JSON lacks (`PG-only`) and leaves them alone;
* re-reads Postgres afterwards; exit 2 unless every JSON entry matches;
* refuses (exit 3) if the JSON file exists but cannot be parsed.

## 0. Preconditions

* The release with the O27/O28 fixes is `current` (the tool's diff, verify and
  refusal logic are in that release, not in older ones).
* `run` is between cycles, or briefly stopped. The `generate` timer fired more
  than 10 minutes ago, or is stopped.
* Recent backup: `ls -l /home/cax/backups/data-$(date +%F)*.tar.gz` (cron 03:00).

## 1. Snapshot (2 min)

```bash
TS=$(date +%Y%m%d-%H%M); B=/home/cax/backups/o28-resync-$TS; mkdir -m 700 -p $B
cp -a /home/cax/cax/data/threat_posts.json $B/
sha256sum $B/threat_posts.json > $B/threat_posts.json.sha256
# Postgres copy of the one table the tool writes (read-only for the database):
. /home/cax/stagec-tools/loadenv.sh && loadenv /home/cax/cax/.env   # never `source .env`
docker run --rm -e URL="${CYBERALERTX_PG_URL/postgresql+psycopg:/postgresql:}" postgres:17-alpine \
  sh -c 'pg_dump --no-owner --no-privileges -t public.threat_posts -Fc "$URL"' > $B/threat_posts.pg.dump
ls -l $B
```

## 2. Dry run (read-only)

Run it as `cax` from the release, in the shell from step 1 (environment
loaded with `loadenv`). The tool contacts Postgres only to read. `--cache`
points at the step-1 snapshot, so the plan and the run see the same file.

```bash
cd /home/cax/cyberalertx/current
venv/bin/python -m cyberalertx.tools.import_ai_cache_to_postgres --dry-run \
  --cache $B/threat_posts.json --report $B/plan.json
```

Expected output: one summary line, for example
`[dry-run] JSON entries N, PG rows M: insert I, update U (F only add fields the PG copy predates) (review status changes {...}), unchanged K; PG-only rows P {...} (reported, not deleted)`.

On a restore of the Stage C snapshot with today's JSON (isolated test,
5 Nov): `JSON entries 4520, PG rows 4501: insert 19, update 4498 (4498 only
add fields the PG copy predates), review status changes none, unchanged 3,
PG-only 0`. The 4498 format-only updates are rows written before the review
and new brief fields existed (`review_status`, `quality`, `am_i_affected`, …):
same content, older shape. Production numbers will differ by what was
generated since.

**Go / no-go:**

| Check | Go when |
|---|---|
| `insert` | ≈ number of renders generated while the API was JSON-only and PG writes failed; normally 0–30 (the generator stayed `dual`) |
| `update` | equals the format-only count, plus renders regenerated while PG writes failed |
| status transitions | every transition is one an editor made (cross-check with `data/admin_audit.jsonl`: `grep review_decision`) |
| `PG-only` | expected 0. Any PG-only key is a post JSON deleted (refresh) while the PG delete failed. **Stop** if any PG-only row is `auto`/`approved`: the dual fallback would serve it. Decide per key with the editor; removing one stale PG row is `venv/bin/python -c 'from cyberalertx.storage.pg.threat_cache import PgThreatPostStore as S; print(S().delete("<fp>", "<locale>"))'` (`delete_post` removes the whole post from both stores). Then re-run the dry run. |
| exit code | 0 |

`plan.json` holds keys and statuses only, no content; keep it with the snapshot.

## 3. Run

```bash
cd /home/cax/cyberalertx/current
venv/bin/python -m cyberalertx.tools.import_ai_cache_to_postgres --cache $B/threat_posts.json; echo "exit $?"
```

Duration: about 4 round trips per written row. Locally (no network) 4,517
rows took 12 s; over the Supabase round trip (~70 ms) expect **20–25 minutes**
for a full first re-sync [estimate]. It holds no lock on JSON and readers are
unaffected (JSON is read first).

Expected: `Done. Upserted X of X changed entries; verify: 0 JSON entries still differ from PG; P PG-only rows left untouched.`, exit 0.
Exit 2 = a write failed or a row still differs; re-run (idempotent) after
checking the warning lines. The second run must report `Upserted 0 of 0`.

If JSON changed between snapshot and run (a decision made meanwhile), run the
dry run once more against the live file without `--cache`; it must show only
those changes.

## 4. Verify

```bash
# the same dry run must now be empty:
venv/bin/python -m cyberalertx.tools.import_ai_cache_to_postgres --dry-run   # live file; expect insert 0, update 0
```

Then revert the hotfix (`c8_api_json_reads.sh revert`) and watch:
`journalctl -u cyberalertx-api --since -5min | grep "PG key index"` shows one
`PG key index loaded: N keys, P only in PG` line at start (later reloads every
60 s log at debug level); no `PG key index load failed` or `PG fallback read
failed` lines.

## 5. Undo

The tool only upserted rows of `threat_posts`. To restore the previous
Postgres state of that table:

```bash
docker run --rm -i -e URL="${CYBERALERTX_PG_URL/postgresql+psycopg:/postgresql:}" postgres:17-alpine \
  sh -c 'pg_restore --no-owner --no-privileges --clean --if-exists -t threat_posts -d "$URL"' < $B/threat_posts.pg.dump
```

JSON was never written, so nothing to undo there. Undo is only needed if the
plan was wrong; while the API reads JSON first, a JSON → PG copy cannot change
what readers see.

## Tested

`tests/test_import_ai_cache_live.py` against a throwaway PostgreSQL 17 (6
tests): an exact dry-run plan with no writes; mapping and payload equality;
status/reviewer/time/quality carried JSON → PG with a stale PG decision
overwritten; a second run is a no-op; no resurrection (JSON never written,
PG-only rows kept and not copied back, a JSON rejection stays hidden under the
dual read path); an unreadable JSON file refused; a failed write fails the run.
The dry run was also run against a restore of the Stage C Supabase snapshot and
a copy of today's JSON; see O27_API_READ_PATH_REPORT.md §6.
