# Stage C runbook: controlled manual operation

> **Not executed. Nothing here is authorized yet.** Each step starts only after
> the administrator gives the approval named on it. Stage D (C12, the Telegram
> scheduler transition) needs its own separate authorization.
>
> Revision 2 (4 Nov 2026). It replaces revision 1 because migration 005 was
> applied while legacy writers were still running. Written against production
> as inspected read-only on 4 Nov:
> - `/home/cax/cax` on `main` @ `73257f0`;
> - units as in DEPLOYMENT_RUNBOOK §0;
> - server time zone EET.
>
> Run C0 first. If anything differs, stop.

## What changed in revision 2

| Before | Now |
|---|---|
| Migration 005 ran while legacy `run`, `generate` and `telegram` were live; timers paused only at activation | **Every legacy writer is stopped and disabled first (C5)**, a quiesced backup is taken, *then* 005 (C6), *then* activation (C7). Nothing legacy writes `items.json`, `threat_posts.json`, the ledger or `news_items` between the migration and the new release. |
| 005 rehearsed only on a local PG 16 | **005 is verified first on a separate Supabase test project (C2)**, then rehearsed on a local restore of the production dump (C3) |
| Legacy Telegram resumed after cutover | **The legacy publisher stays stopped, disabled *and* blocked** by a systemd condition until Stage D. Stage D replaces its command in the same unit, so old and new can never run together. |
| Release provenance not checked | **C1 verifies every file of the release against commit `4fa7a63`** (git blob hashes), and records commit, tree and lockfile hashes in `RELEASE` |

**Why the old order was unsafe, and what it actually exposed** [verified by reading `main`]:
- **Postgres:** old `PgNewsStore.upsert_many` updates an explicit column list, so it cannot overwrite the three 005 columns; new rows get the `''` default.
- **JSON:** production `items.json` has 0 of 200 items with `relevance_*` fields today.

So the window between the migration and activation could not strip anything *yet*. The strip (O19) happens when legacy code rewrites `items.json` or `threat_posts.json` **after** the new code has written them, i.e. a legacy process surviving cutover. Revision 2 removes that possibility, gives one consistent rollback point, and keeps the database and JSON in step.

## Approvals and labels

| Label | Meaning |
|---|---|
| **[RO]** | Read-only. No approval needed beyond P0. |
| **[NEW]** | Writes only new directories (`/home/cax/cyberalertx/…`, `/home/cax/backups/stagec-…`, `~/stagec-tools`) or a throwaway local container. No production effect. |
| **[TEST-DB]** | Writes to the Supabase **test** project. Never production. |
| **[PROD]** | Production write without sudo: production `data/`, `.env`, production Supabase, or an external channel |
| **[SUDO]** | Root: systemd units, timers, restarts |

| Approval | Covers | Give it when |
|---|---|---|
| **P0** | C0–C1: pre-flight, building the release | Stage C authorized in principle; D1–D7 confirmed |
| **P1** | C2: connecting to the Supabase **test** project and migrating it | C1 verified; the test project exists |
| **P2** | C3: **reading** production Supabase (dump) | C2 passed |
| **P3** | **The cutover window, C5 → C9.** Each step still lists what it does. | C1–C4 verified; time slot chosen. Covers: the legacy-writer stop (sudo), the quiesced backup (reads production Supabase), the `.env` pins, unit edits, restarts. **Excludes** 005 (P4) and resuming workers (P5). |
| **P4** | C6: **migration 005 on production Supabase** | C5 verified: no legacy writer left |
| **P5** | C9: resuming `generate` | C8 passed |
| **P6** | C10: private Telegram test | D4; test bot and channels exist |
| **P7** | C11: Threads OAuth (`.env` + API restart) | D5; Meta app ready |
| **P8** | C12: **Stage D**, the new publisher | Separate authorization; C10 passed |

Never put a secret on a command line, where it lands in history and `ps`. Use `read -rs`, a 0600 file, or `set -a; . file`.

> **dotenv hazard:** `cyberalertx/__init__.py` auto-loads the first `.env`
> found walking **up from the working directory**. Run release and test
> commands only from inside `$R` or `$T`, where none is found (checked in C0).
> **Never from inside `/home/cax/cax`**: that loads production `.env` into
> any process, including one meant to be isolated.

## Decisions confirmed (item 4 of the request)

| # | Setting | Value in Stage C | How it is ensured | Verified by |
|---|---|---|---|---|
| D1 | `CYBERALERTX_FACT_SHEET` | **`0` for the first 72 h** (default is *on*) | Added to `.env` in C7 | `settings_check` (C8) prints `fact_sheet_enabled False`; `/admin/usage` shows no `fact_sheet` calls |
| D2 | `CYBERALERTX_THREADS_PUBLISH` | **`0`** (default off; pinned) | Added to `.env` in C7 | `threads_publish_enabled False` |
| D3 | `CYBERALERTX_TELEGRAM_ATTACH_IMAGES` | **`0`** (default off; pinned) | Added to `.env` in C7 | `telegram_attach_images False` |
| D4 | `CYBERALERTX_HIDE_OUT_OF_SCOPE` | **`0`** (default off; pinned) | Added to `.env` in C7 | `hide_out_of_scope_publicly False` |
| D5 | Review mode | **Preserved: `CYBERALERTX_REVIEW_MODE` stays unset**, as it is today. The new code resolves unset to `flag`. Readers see no change: `pending` posts stay visible, and only a post an editor explicitly **rejects** in `/admin/review` is hidden. `off` would be the exact old behaviour, with no editor queue at all. | No `.env` change | `review_mode flag (… unset)` |
| D6 | Legacy Telegram publisher | **Stopped, disabled, and blocked** from cutover until Stage D | C5: `disable --now` plus the `ConditionPathExists` drop-in | C8: `inactive`, `disabled`, drop-in present |
| D7 | New publishing automation | **None.** The new publisher (`tools.publish cycle --send`) has no unit and no timer. No production `plan` is run in Stage C. Top-10 slot, breaking updates and the image provider stay unset (off / none). | Nothing is installed | `settings_check`; `systemctl list-timers` shows no publish timer |

**Consequence of D6:** the public Telegram channels get **no posts from C5
until Stage D**, which is normally 10 per channel per day. The website keeps
updating: website "delivery" is bookkeeping only, and the API serves new
posts without jobs. Schedule Stage D soon after C10 passes.

The old code reads none of the four pinned variables (checked with `git grep`
on `main`), so adding them cannot change a legacy process.

Other decisions (unchanged from revision 1):
- editorial benchmark: run during C1 against the snapshot, before D1 is turned on;
- private-channel test: do C10 before Stage D;
- Threads: C11 when the Meta app exists;
- shared admin token: keep while there is one administrator; per-user tokens before a second.

## Fixed values and tools

```bash
cat > ~/stagec.vars <<'EOF'
SHA=4fa7a63a982b8a79b5c511fcc56d1d53c2f85c14      # redesign/cti-platform, messages without trailers
TREE=fea7201cafc42b16b64337a957450c8c971c62e5     # its tree (identical to RC3's source tree)
ID=YYYYMMDD-HHMM-4fa7a63                          # set once at C1, e.g. $(date +%Y%m%d-%H%M)-4fa7a63
REPO=/home/cax/cax-redesign
PROD=/home/cax/cax
R=/home/cax/cyberalertx/releases/$ID
SNAP=/home/cax/cyberalertx/staging/$ID
B=/home/cax/backups/stagec-$ID                    # never name files data-*.tar.gz here: cax-backup rotates that pattern recursively
TOOLS=/home/cax/stagec-tools
EOF
chmod 600 ~/stagec.vars; . ~/stagec.vars
read -rs ADMIN_TOKEN       # admin pages; not echoed
# .env must be loaded with a parser, NOT `. .env`: line 28 (CYBERALERTX_UA) has unquoted "(…)", so bash aborts
# that line with a syntax error and the 7 variables after it (Telegram, admin token, …) silently stay unset.
loadenv() { eval "$(python3 -I -c 'import shlex,sys
for l in open(sys.argv[1]).read().splitlines():
    s=l.strip()
    if s and not s.startswith("#") and "=" in s:
        k,v=s.split("=",1); v=v.strip()
        if len(v)>=2 and v[0]==v[-1] and v[0] in "\"'"'"'": v=v[1:-1]
        print("export %s=%s" % (k.strip(), shlex.quote(v)))' "$1")"; }
adm() { curl -s --netrc-file <(printf 'machine %s login admin password %s\n' "${2:-127.0.0.1}" "$ADMIN_TOKEN") "$1"; }
```

Install the two helper scripts from **Appendix A** into `$TOOLS` [NEW]:
- `verify_release.py`: release provenance;
- `settings_check.py`: resolved settings, no secrets.

---

## C0. Pre-flight [RO]

**Approval:** P0.

```bash
. ~/stagec.vars
git -C $PROD rev-parse --short HEAD; git -C $PROD status --porcelain | wc -l          # 73257f0, 0
systemctl is-active cyberalertx-{api,frontend,run}.service cyberalertx-{generate,telegram,analytics}.timer   # 6× active
systemctl cat cyberalertx-telegram | grep ExecStart                                   # …cyberalertx.main publish-telegram --limit 1
stat -c '%a %U:%G' $PROD/.env                                                         # 600 cax:cax
grep -oE '^[A-Z_][A-Z0-9_]*=' $PROD/.env | tr -d = | sort | tr '\n' ' '; echo         # 18 names, none of the 4 pins
git -C $REPO rev-parse HEAD; git -C $REPO rev-parse $SHA^{tree}                        # = $SHA, = $TREE
git -C $REPO log --format=%B main..$SHA | grep -ci co-authored                        # 0
for d in /home/cax/cyberalertx /home/cax /home /; do [ -e $d/.env ] && echo "STOP: $d/.env exists"; done   # nothing
cat /etc/cron.d/cax-backup                                                            # only the 03:00 data backup (reads data/)
df -h /home | tail -1                                                                 # ≥ 5 GB free
journalctl -u cyberalertx-run -u cyberalertx-generate -u cyberalertx-telegram --since -6h | grep -cE 'Traceback|ERROR'   # baseline
```

| | |
|---|---|
| **Expected** | As commented |
| **Risk** | None |
| **Verify** | Every line matches. Write down the error baseline. |
| **Rollback** | Not needed. Any difference means **stop**. |

## C1. Build the production release from `4fa7a63` and verify provenance [NEW]

> Staging ports: **8190/3190**. Check that both are free (`ss -ltn`) before starting: a build whose `API_URL` port is answered by anything other than the staging API prerenders empty pages.

**Approval:** P0. No production effect. Do it the same day as the cutover, so
the prerendered pages are fresh. RC3 is **not** activated: its `RELEASE` names
`6956a5a`, its data link points at rehearsal data, and its pages were
prerendered against the rehearsal API.

```bash
. ~/stagec.vars
# 1. source: git archive of exactly $SHA, then a file-by-file check against the commit
mkdir -p $R && git -C $REPO archive $SHA | tar -x -C $R
python3 -I $TOOLS/verify_release.py $R $REPO $SHA          # "352 files in tree, 0 mismatched/missing, 0 unexpected extra", exit 0
# 2. Python: the tested lock (incl. cryptography 50.0.2, python-dotenv, pytest, mypy)
python3 -m venv $R/venv && $R/venv/bin/pip install -q --upgrade pip && $R/venv/bin/pip install -q -r $R/requirements.lock
$R/venv/bin/pip check
# 3. data link → a snapshot (it stays on the snapshot until C7)
mkdir -p $SNAP && cp -a $PROD/data $SNAP/data && ln -s $SNAP/data $R/data
(cd $R && venv/bin/python -c "import dotenv,cyberalertx.config as c;print(repr(dotenv.find_dotenv(usecwd=True)), c.DATA_DIR.resolve())")
#    → '' /home/cax/cyberalertx/staging/$ID/data
# 4. staging API over the snapshot; frontend prerendered against it with the production build config
( cd $R && env -i HOME=$HOME PATH=/usr/bin:/bin CYBERALERTX_STORAGE_BACKEND=json \
    venv/bin/python -m cyberalertx.main serve --host 127.0.0.1 --port 8190 > $SNAP/api.log 2>&1 & ); sleep 5
curl -sf 127.0.0.1:8190/healthz >/dev/null && echo staging-api-ok
cp -a $PROD/frontend/.env.production $R/frontend/.env.production
( cd $R/frontend && npm ci --no-audit --no-fund && API_URL=http://127.0.0.1:8190 NEXT_TELEMETRY_DISABLED=1 npm run build ) > $SNAP/build.log 2>&1; echo "build exit $?"
```

**Verify.** The tests write only to tmp and the snapshot:

```bash
grep -E 'Next.js 15.5.29|Compiled successfully' $SNAP/build.log
node -p "require('$R/frontend/node_modules/next/package.json').version"                       # 15.5.29
(cd $R/frontend && node -p "require('sharp').versions.sharp")                                 # 0.35.5
grep -c FORBIDDEN_HEADERS $R/frontend/node_modules/next/dist/server/send-response.js          # 3 (GHSA-pc58 fix)
grep -A3 '"node_modules/next"' $R/frontend/package-lock.json | grep -c 'sha512-93AMszTCdi9Az7fD5VzcWy46SHCdQF45'   # 1
(cd $R/frontend && npm audit --omit=dev)                                                      # found 0 vulnerabilities
(cd $R && env -i HOME=$HOME PATH=/usr/bin:/bin venv/bin/python -m pytest -q 2>&1 | tail -1)   # ≈1372 passed, 5 skipped
(cd $R && venv/bin/python -m mypy | tail -1)                                                  # Success
(cd $R/frontend && API_URL=http://127.0.0.1:8190 npx next start -p 3190 -H 127.0.0.1 > $SNAP/next.log 2>&1 &); sleep 6
for p in /en /ua /en/topic/malware /en/feed.xml /sitemap.xml; do curl -s -o /dev/null -w "$p %{http_code}\n" 127.0.0.1:3190$p; done   # 200
curl -s -o /dev/null -w '/_next/image %{http_code}\n' '127.0.0.1:3190/_next/image?url=/x.png&w=64&q=75'                  # 404
for p in 8190 3190; do PID=$(ss -ltnp | awk -v a=127.0.0.1:$p '$4==a' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
  [ -n "$PID" ] && case "$(readlink /proc/$PID/cwd)" in $R*) kill $PID;; esac; done           # stops only processes inside $R
python3 -I $TOOLS/verify_release.py $R $REPO $SHA        # still 0 mismatched (extras = build outputs and caches only)
```

**Record provenance:**

```bash
{ echo "release_id=$ID"; echo "commit=$SHA"; echo "tree=$(git -C $REPO rev-parse $SHA^{tree})"
  echo "archive_sha256=$(git -C $REPO archive $SHA | sha256sum | cut -d' ' -f1)"
  echo "requirements_lock_sha256=$(sha256sum < $R/requirements.lock | cut -d' ' -f1)"
  echo "package_lock_sha256=$(sha256sum < $R/frontend/package-lock.json | cut -d' ' -f1)"
  echo "next=$(node -p "require('$R/frontend/node_modules/next/package.json').version") sharp=$(cd $R/frontend && node -p "require('sharp').versions.sharp")"
  echo "verified_utc=$(date -u +%FT%TZ) verify_release=0-mismatch"; echo "stage=C (production release; not active)"; } > $R/RELEASE
cat $R/RELEASE
chmod -R a-w $R/cyberalertx $R/frontend/app $R/frontend/lib       # code read-only; .next stays writable (ISR cache)
```

| | |
|---|---|
| **Expected** | Verifier exit 0 (before and after the build); `tree` = `fea7201c…`; versions, audit, tests and pages as commented |
| **Risk** | Low. The staging API reads only the snapshot. The kill loop is limited to `$R`; never touch :8000 or :3000. |
| **Rollback** | `rm -rf $R $SNAP`. Production was not involved. |

## C2. Verify migration 005 on a separate Supabase test project [TEST-DB]

**Approval:** P1.

**Preconditions:**
- a Supabase project that is **not** production;
- its session-pooler URL in `~/secrets/supabase-test.url` (0600);
- a fresh, empty project, or a dedicated one.

```bash
. ~/stagec.vars; TEST=$(cat ~/secrets/supabase-test.url)
( loadenv $PROD/.env       # only to compare hostnames; nothing connects with the production URL here
  python3 -c 'import sys,urllib.parse as u;a,b=(u.urlsplit(x).hostname for x in sys.argv[1:]);print("DISTINCT" if a!=b else "SAME HOST: STOP")' \
    "$TEST" "${CYBERALERTX_PG_URL/postgresql+psycopg:/postgresql:}" )
cd $R && venv/bin/python -c "import dotenv;print(repr(dotenv.find_dotenv(usecwd=True)))"     # '' (no .env can leak in)
TDB() { (cd $R && env -i HOME=$HOME PATH=/usr/bin:/bin CYBERALERTX_PG_URL="$TEST" venv/bin/python -m cyberalertx.tools.pg_migrate "$@"); }
TDB --status          # fresh project: 001–005 pending
TDB                   # applies 001–005
TDB --status          # 001–005 applied
TDB                   # idempotent: nothing to apply
# migration and review-persistence live suites (own schemas; dropped afterwards)
(cd $R && env -i HOME=$HOME PATH=/usr/bin:/bin CYBERALERTX_TEST_DB_URL="$TEST" \
   venv/bin/python -m pytest -q tests/test_pg_migrations_live.py tests/test_pg_review_live.py)
```

| | |
|---|---|
| **Expected** | `DISTINCT`; `''`; 005 applies on the Supabase platform (pooler, permissions, version) and re-runs as a no-op; **4 + 3 passed**. These include upgrade-from-004 with rows, and review persistence (O5). |
| **Risk** | None to production after `DISTINCT`. On `SAME HOST`, stop. |
| **Verify** | As expected. Record O5 as verified in OPEN_ISSUES. |
| **Rollback** | Drop the test project, or keep it. It holds only test data. |

## C3. Production backups, complete and verified

**Approval:** P0 for the files [NEW]; **P2** for reading production Supabase.

```bash
. ~/stagec.vars; umask 077; mkdir -p $B && chmod 700 $B
tar -C $PROD -czf $B/prod-data-full.tgz data                 # 233 MB → ~55 MB; writers use atomic rename
install -m 600 $PROD/.env $B/env.bak                         # never printed
cp -a /etc/systemd/system/cyberalertx-* $B/                  # 9 files; world-readable, no sudo
cp -a $PROD/frontend/.env.production $B/frontend.env.production
# production Supabase, read-only; the URL never appears on a command line (P2)
( loadenv $PROD/.env; export URL="${CYBERALERTX_PG_URL/postgresql+psycopg:/postgresql:}"
  python3 -c 'import os,urllib.parse as u;p=u.urlsplit(os.environ["URL"]);print("port",p.port)'   # 6543 (transaction pooler) cannot pg_dump: use 5432
  docker run --rm -e URL postgres:17-alpine sh -c 'psql "$URL" -tAc "show server_version"; psql "$URL" -tAc "select count(*) from news_items"'
  docker run --rm -e URL postgres:17-alpine sh -c 'pg_dump --no-owner --no-privileges -n public -Fc "$URL"' > $B/supabase-full.dump; echo "dump exit $?" )
```

**Verify** [NEW: a throwaway local container]. The restore check doubles as
a production-shaped rehearsal of 005:

```bash
stat -c '%a %n' $B $B/env.bak; cmp -s $PROD/.env $B/env.bak && echo env-identical
gzip -t $B/prod-data-full.tgz && tar -tzf $B/prod-data-full.tgz | grep -cE 'data/(items|threat_posts)\.json$|telegram_published\.jsonl$'   # 3
docker run -d --rm --name cax-restorecheck -e POSTGRES_HOST_AUTH_METHOD=trust --tmpfs /var/lib/postgresql/data -v $B:/b:ro postgres:17-alpine; sleep 5
docker exec cax-restorecheck pg_restore -U postgres -d postgres --no-owner --no-privileges /b/supabase-full.dump; echo "restore exit $?"
docker exec cax-restorecheck psql -U postgres -tAc "select string_agg(version,',' order by version) from schema_migrations; select count(*) from news_items"
# rehearse 005 on the restored production data (local only) and time it
( cd $R && IP=$(docker inspect -f '{{.NetworkSettings.IPAddress}}' cax-restorecheck) && \
  time env -i HOME=$HOME PATH=/usr/bin:/bin CYBERALERTX_PG_URL="postgresql://postgres@$IP:5432/postgres" venv/bin/python -m cyberalertx.tools.pg_migrate && \
  env -i HOME=$HOME PATH=/usr/bin:/bin CYBERALERTX_PG_URL="postgresql://postgres@$IP:5432/postgres" venv/bin/python -m cyberalertx.tools.pg_migrate --status )
docker exec cax-restorecheck psql -U postgres -tAc "select count(*) from news_items where relevance_status=''"    # = row count (defaults)
docker stop cax-restorecheck
```

| | |
|---|---|
| **Expected** | `700`/`600`; env-identical; 3; restore exit 0 (extension warnings are acceptable); migrations `001,…,004`; row counts equal production; local 005 takes well under 1 s and leaves every row at `''`; server version ≥ 11 |
| **Risk** | Low. The dump and `env.bak` hold production data and secrets, so they stay in `$B` (0700). |
| **Rollback** | Not needed |

## C4. Inventory of legacy writers [RO]

**Approval:** P0. **Affected data:**
- `news_items`: 005 and relevance;
- `items.json`: relevance fields;
- `threat_posts.json` and PG `threat_posts`: review fields;
- `telegram_published.jsonl`: the shared ledger.

Established from the **running legacy code** (`main` @ `73257f0`) and the installed units on 4 Nov 2026, not from service names:

| Process | Can write? | Exact targets | Safe to leave running in C5–C7? | Evidence |
|---|---|---|---|---|
| `cyberalertx-run` (ingest, every 30 min) | **Yes** | `data/items.json`, `source_health.json`, `quality_metrics.json`; PG `news_items` (dual-write upsert) | **No:** stopped and disabled in C5, in a verified idle window | `pipeline/orchestrator.py` (atomic `items.json` write); `storage/pg/news_store.py: upsert_many` |
| `cyberalertx-generate` (hourly oneshot) | **Yes** | `data/threat_posts.json` (AI cache), `quality_metrics.json`; PG `threat_posts` | **No:** timer disabled first; a running job finishes naturally | `ai/generator.py: generate` → `cache.set` on the provider path; `storage/dual_write.py: set` |
| `cyberalertx-telegram` (10×/day oneshot) | **Yes** | `data/telegram_published.jsonl` (ledger), Telegram channels | **No:** timer disabled; hold drop-in blocks the service until Stage D | `publish/service.py` → `PublishLedger.record` |
| `cyberalertx-api` (old API) | **Yes, two benign paths** | (1) `data/feedback.jsonl`: append on public `POST /feedback` (size-capped). (2) `data/quality_metrics.json`: atomic rewrite when a post is rendered rule-based (no cached locale). | **Yes.** Neither target is affected data. Nothing else is written: no review state, no ledger, no `items.json`/`threat_posts.json`, no Postgres, no media. | Only routes: `GET /posts…`, `/healthz`, read-only `/admin` (feedback, metrics, sources) and `POST /feedback`. **No review endpoints in the old code** (review state is new). Serve path builds the generator with `use_llm=False` and `_provider=None`; `generate()` calls `cache.set` only after a provider render, and rule-based output is explicitly not cached. `DualWriteThreatPostCache.get` reads JSON, then PG (read-only `SELECT`). `JsonNewsStore.__init__` only loads. `QualityMetrics.bump` → `_flush` (temp + `os.replace`). No `BackgroundTasks`, threads or startup hooks. Observed: `quality_metrics.json` last written 16:01:42 by generate; no API write since. |
| `cyberalertx-frontend` (old Next.js 15.5.18) | **Indirectly, one path** | Reader feedback via `POST $API/feedback` (`lib/api.ts`) → `feedback.jsonl`. Own ISR cache in `/home/cax/cax/frontend/.next` (not shared, not used by the release). | **Yes** | Only route handler: `feed.xml` (GET). No server actions, no `fs` writes; `middleware.ts` only redirects. |
| `cyberalertx-analytics` (daily 03:01 oneshot) | **Yes, own files only** | `data/analytics.sqlite3`, `data/analytics/report.html`; **reads** `items.json` titles and `data/nginx-archive` | **Yes** (code identical in `main` and `4fa7a63`); C5 aborts if it is running | `server/analytics/__init__.py` (DB and archive paths); `__main__.py` reads `_ITEMS_PATH`; last write 03:01:59 |
| cron `cax-backup` (03:00) | Backups only | `/home/cax/backups/data-*.tar.gz` (reads `data/`; rotates that pattern) | **Yes** | `/usr/local/bin/cax-backup` |
| Root crontab, `/etc/crontab` | Unknown without sudo / none | — | Verified by `c5_quiesce.sh` preflight as root: aborts if either schedules `/home/cax/cax` or `cyberalertx` | `/etc/crontab`, `cron.{hourly,daily,weekly}`: no CyberAlertX entries |
| Manual tools (`server.scripts.refresh_feed`, `tools.delete_post`, `import_ai_cache_to_postgres`) | **Yes** | delete or overwrite items and posts, JSON and PG | **Not to be run** during Stage C | Source docstrings |

**Conclusion:** after C5, no running process can modify `items.json`,
`threat_posts.json`, review state, the ledger, Postgres or media. The API and
frontend stay up. Their only remaining writes are `feedback.jsonl` (reader
feedback) and `quality_metrics.json` (a render counter):
- neither is touched by migration 005 or the release switch;
- both are explicitly allowed, and everything else is rejected, by the C5 quiet check;
- feedback received after the quiesced backup is not in that backup, but it stays in the live file (rollback never overwrites `data/`);
- the metrics file can lose counter increments when two processes write it. That is pre-existing behaviour, metrics only.

```bash
systemctl list-units --all --no-pager 'cyberalertx*'; systemctl list-timers --all --no-pager | grep -i cyberalertx
pgrep -u cax -af 'cyberalertx|server\.analytics' | while read pid rest; do echo "$pid $(readlink /proc/$pid/cwd) :: $rest"; done
ls /etc/cron.d/; crontab -l 2>/dev/null | grep -v '^#'
```

| | |
|---|---|
| **Expected** | Exactly the processes in the table: api, frontend and run running from `/home/cax/cax`; no other cyberalertx process; no cron besides `cax-backup` |
| **Risk** | None |
| **Rollback** | Not needed. An unknown writer means **stop**: add it to this table first. |

---

## ⏸ P3: cutover window (C5 → C9, one session, ~1.5 h)

**Start:** shortly after a `generate` run has finished (e.g. hh:10 EET), and
right after a `run` cycle has logged `cycle complete`. The site stays up until
the C7 restart (~10 s).

## C5. Stop every legacy writer, then take the quiesced backup

**Approval:** P3. Steps 1–3 are [SUDO], run as **one script**. Step 5 is [NEW] and reads production Supabase.

**Steps 1–3: `sudo bash /home/cax/stagec-tools/c5_quiesce.sh`.** Revision 3 of the script; the full source is in Appendix B.

Why a script, and what it checks:

| Concern | How the script handles it |
|---|---|
| **Is an ingest cycle running?** `run` is `Type=simple`, and its 30-min cycles run inside the process (APScheduler, no lock file). A journal "cycle complete" line alone proves nothing. | It reads only the **current PID's** scheduler records (`journalctl -b _PID=<MainPID> _SYSTEMD_UNIT=…`). The executor logs `Running job …` before a cycle and `executed successfully` / `raised an exception` after it. Idle requires: (a) the last record is a completion (or the startup record); (b) the record's `next run at:` time is more than **180 s** away; (c) the process used ≤ 20 CPU ticks in a 2 s sample. Otherwise it waits (up to 35 min) and then **aborts without stopping `run`**. |
| **New jobs starting while waiting** | **Timers first:** `disable` + `stop` of both timers, each verified (`disabled`, `inactive`). Stopping a timer never stops its service (`Requires=` points the other way). |
| **Running oneshots** | Waits for `generate`/`telegram` to finish **naturally**, including queued start jobs. It never stops them. After 420 s (more than their `TimeoutStartSec=300`) it **aborts**, names the unit still active, and installs no hold. |
| **Stopping `run`** | Only in a verified idle window: `disable`, then `stop` (bounded to 120 s). Then it checks `inactive`, `disabled` and **`Result=success`**, and that no new `Running job` appeared during the stop; otherwise it aborts with **INTERRUPTED**. The legacy SIGTERM handler shuts the scheduler down without waiting for a job, which is why the idle check comes first. |
| **Fail-fast** | `set -Eeuo pipefail` with an ERR trap. Every `disable`, `stop`, `mkdir`, write and `daemon-reload` is checked, and so is the resulting state. On any failure it prints the partial state, says "C5 did NOT complete", exits 1, and **reverts nothing**. |
| **Telegram hold** | Written atomically (temp file + `mv`) to `/etc/systemd/system/cyberalertx-telegram.service.d/stage-c-hold.conf`. After `daemon-reload` it must appear in `DropInPaths` with `NeedDaemonReload=no`, and `systemd-analyze condition ConditionPathExists=/home/cax/cyberalertx/STAGE_D_AUTHORIZED` must evaluate **false**. The marker must be absent before and after. The script never creates it. |
| **Site stays up** | API and frontend must be `active` at preflight and at the end. They are never touched. |
| **Re-runs** | Idempotent: already-disabled timers, an already-stopped `run` and an identical drop-in are verified, not redone |

**Tested on 4 Nov 2026, without sudo, against no production unit:**
- **Mock harness: 37/37 checks pass.** Covered: happy path; root crontab scheduling a legacy command (abort) and a commented-out entry (ignored); analytics running (abort); repeat run; a oneshot past the timeout (abort, not stopped); a oneshot finishing after 2 polls; a queued start job; an active ingest cycle; the next cycle within the margin; a next-run time already passed; only an old "cycle complete" line; a busy CPU; failing `disable`/`stop` (timer, `run`); a hanging stop; `Result=timeout`; a cycle started during the stop (INTERRUPTED); a failing `daemon-reload`; the marker present; the API down; a condition evaluating true; a wrong unit path; an unreadable journal; non-root; a freshly started process.
- **Real systemd 255 (user instance, throwaway units):**
  - the drop-in condition blocks a direct start (`ConditionResult=no`, the command did not run) and a start via a `Requires=` timer, and runs once the marker exists;
  - `DropInPaths` and `systemd-analyze condition` report the hold;
  - a SIGTERM-handled exit gives `Result=success`, and a hang gives `Result=timeout`.
- **Read-only against the live `run` process:** the 16:41:09–16:41:17 cycle was recognized; the detector reported "next due in 1749 s, CPU 0 ticks/2s".

**4. Verify quiescence** [RO, no sudo]: `bash /home/cax/stagec-tools/c5_verify_quiet.sh 120` (source in Appendix C).

It refuses unless `run`, `generate` and `telegram` are inactive, the timers disabled and the hold loaded. Then, for 120 s:
- **`data/`:** every changed file must be `data/feedback.jsonl` or `data/quality_metrics.json` (top level only). Any other change, including new files, fails.
- **Postgres:** `news_items`, `threat_posts` and `schema_migrations` must be byte-identical at start and end (md5 over every row, ordered), read-only.

Exit 0 = `QUIET`. Otherwise it lists each offending file or table, and **C6 must not start.**

Tested: 8/8 cases pass, and a real run on the current (un-quiesced) production refuses before touching Postgres. The cases: no change; only allowed files; `items.json` changed; allowed name in a subdirectory; new file; Postgres row update; Postgres unreachable; writers still active.

**5. Quiesced backup.** This is the rollback point: the data as of the migration.

```bash
umask 077
tar -C $PROD -czf $B/prod-data-quiesced.tgz data && gzip -t $B/prod-data-quiesced.tgz
cp -a $PROD/data/items.json $PROD/data/threat_posts.json $PROD/data/telegram_published.jsonl $B/
( loadenv $PROD/.env; export URL="${CYBERALERTX_PG_URL/postgresql+psycopg:/postgresql:}"
  docker run --rm -e URL postgres:17-alpine sh -c 'pg_dump --no-owner --no-privileges -n public -Fc "$URL"' > $B/supabase-quiesced.dump; echo "dump exit $?" )
docker run --rm -v $B:/b:ro postgres:17-alpine pg_restore -l /b/supabase-quiesced.dump | grep -c 'TABLE DATA'   # same as C3
```

| | |
|---|---|
| **Expected** | All checks as commented; no file in `data/` changes during the 2-minute watch except possibly `feedback.jsonl` |
| **Risk** | Low. Ingest and generate pause; the site keeps serving. **Public Telegram stops here, until Stage D (D6).** |
| **Rollback** | `sudo rm -r /etc/systemd/system/cyberalertx-telegram.service.d && sudo systemctl daemon-reload && sudo systemctl enable --now cyberalertx-run cyberalertx-generate.timer cyberalertx-telegram.timer`. Both timers declare `Requires=` on their service, so **starting a timer also starts its service immediately** (one legacy Telegram run and one generate run). That is normal, and the ledger prevents duplicates. |

## C6. Apply migration 005 to production Supabase [PROD]

**Approval:** **P4**, explicit, inside the window. C5 step 4 must be clean.

```bash
. ~/stagec.vars
( loadenv $PROD/.env; cd $R
  venv/bin/python -m cyberalertx.tools.pg_migrate --status     # 001–004 applied, 005 pending
  venv/bin/python -m cyberalertx.tools.pg_migrate              # applies 005 only, in one transaction
  venv/bin/python -m cyberalertx.tools.pg_migrate --status )   # 005 applied
( loadenv $PROD/.env; export URL="${CYBERALERTX_PG_URL/postgresql+psycopg:/postgresql:}"
  docker run --rm -e URL postgres:17-alpine sh -c \
   'psql "$URL" -tAc "select column_name from information_schema.columns where table_name='"'"'news_items'"'"' and column_name like '"'"'relevance_%'"'"' order by 1"' )
```

| | |
|---|---|
| **Expected** | 005 goes from pending to applied; 3 columns (`relevance_override`, `relevance_reason`, `relevance_status`). Metadata-only `ADD COLUMN … DEFAULT ''`, as rehearsed in C2 and C3. |
| **Risk** | Low. No writer is running, so the brief `ACCESS EXCLUSIVE` lock meets no contention. |
| **Verify** | As above; the old API still answers (`curl -sf 127.0.0.1:8000/healthz`) |
| **Rollback** | Normally none: old code updates an explicit column list and ignores the new columns. Otherwise ROLLBACK_RUNBOOK §5 (`006_drop_relevance.sql`), or restore `$B/supabase-quiesced.dump`. |

## C7. Activate the new release

**Approval:** P3. Step 1 is [PROD] (`.env`); steps 2–4 are [SUDO].

```bash
. ~/stagec.vars; umask 077
# 1. .env pins (D1–D4): safe edit; old code reads none of these
install -m 600 $PROD/.env $PROD/.env.new
[ -n "$(tail -c1 $PROD/.env.new)" ] && echo >> $PROD/.env.new          # ensure a final newline before appending
printf 'CYBERALERTX_FACT_SHEET=0\nCYBERALERTX_THREADS_PUBLISH=0\nCYBERALERTX_TELEGRAM_ATTACH_IMAGES=0\nCYBERALERTX_HIDE_OUT_OF_SCOPE=0\n' >> $PROD/.env.new
diff <(grep -oE '^[A-Z_][A-Z0-9_]*=' $PROD/.env | sort) <(grep -oE '^[A-Z_][A-Z0-9_]*=' $PROD/.env.new | sort)   # exactly 4 added
grep -c '^CYBERALERTX_REVIEW_MODE=' $PROD/.env.new                                                               # 0 (D5: unchanged)
stat -c '%a %U:%G' $PROD/.env.new && mv $PROD/.env.new $PROD/.env                                                # 600 cax:cax; atomic
# 2. point the release at the live data and at `current`
ln -sfn $PROD/data $R/data
(cd $R && venv/bin/python -c "import dotenv,cyberalertx.config as c;print(repr(dotenv.find_dotenv(usecwd=True)), c.DATA_DIR.resolve())")   # '' /home/cax/cax/data
ln -sfn $R /home/cax/cyberalertx/current
# 3. units: paths only, for api, frontend, run, generate. NOT telegram (held), NOT analytics (unchanged).
sudo sed -i 's#^WorkingDirectory=/home/cax/cax/frontend$#WorkingDirectory=/home/cax/cyberalertx/current/frontend#' /etc/systemd/system/cyberalertx-frontend.service
for u in api run generate; do
  sudo sed -i -e 's#^WorkingDirectory=/home/cax/cax$#WorkingDirectory=/home/cax/cyberalertx/current#' \
              -e 's#/home/cax/cax/venv/bin/python#/home/cax/cyberalertx/current/venv/bin/python#' /etc/systemd/system/cyberalertx-$u.service
done
sudo systemctl daemon-reload
for u in api frontend run generate telegram; do echo "== $u"; diff $B/cyberalertx-$u.service /etc/systemd/system/cyberalertx-$u.service; done
#    api/run/generate: 2 lines (WorkingDirectory, ExecStart path); frontend: 1; telegram: no change
# 4. start the new code: api and frontend restart; run is re-enabled from the release (its first cycle starts at once)
sudo systemctl restart cyberalertx-api cyberalertx-frontend
sudo systemctl enable --now cyberalertx-run
```

| | |
|---|---|
| **Expected** | The diffs exactly as commented. The `generate` timer stays **disabled** until C9; telegram stays held. |
| **Risk** | **Medium:** this is the switch, with ~10 s of site downtime. The new code's first ingest creates its new files in `data/` (`intel/`, `stories/`, `media/`, `ai_usage.jsonl`, …). |
| **Rollback** | See C14, row "C7–C9" |

## C8. Verify application and database [RO]

**Approval:** P3.

```bash
. ~/stagec.vars
# processes: every cyberalertx process runs the release; the legacy publisher is held
pgrep -u cax -af 'cyberalertx|next-server|next start' | while read pid rest; do echo "$(readlink /proc/$pid/cwd) :: $rest"; done   # all under $R
systemctl is-active cyberalertx-{api,frontend,run}; systemctl is-enabled cyberalertx-telegram.timer cyberalertx-generate.timer      # active×3; disabled×2
systemctl show cyberalertx-telegram.service -p DropInPaths -p ActiveState                                                          # hold drop-in; inactive
# effective settings, resolved by the release code from the production environment (prints no secrets)
( cd $R && loadenv $PROD/.env && venv/bin/python -I -c "import sys;sys.path.insert(0,'.');exec(open('$TOOLS/settings_check.py').read())" )
# application
curl -sf 127.0.0.1:8000/healthz; echo; curl -s -o /dev/null -w 'site %{http_code}\n' 127.0.0.1:3000/en
curl -s -o /dev/null -w 'public %{http_code}\n' https://cyberalertx.com/en; curl -sf https://cyberalertx.com/healthz; echo
curl -s -o /dev/null -w 'optimizer %{http_code}\n' 'https://cyberalertx.com/_next/image?url=/x.png&w=64&q=75'                       # 404 = new frontend
curl -s -o /dev/null -w 'admin-unauth %{http_code}\n' https://cyberalertx.com/admin/system                                          # 401
for p in system publishing review stories intel media usage sources; do adm http://127.0.0.1:8000/admin/$p -o /dev/null -w "$p %{http_code}\n"; done
ID1=$(curl -s '127.0.0.1:8000/posts?limit=1' | python3 -c 'import json,sys;print(json.load(sys.stdin)["items"][0]["id"])')
curl -s -o /dev/null -w 'article %{http_code}\n' https://cyberalertx.com/en/threat/$ID1
curl -s -o /dev/null -w 'card %{http_code} %{content_type}\n' https://cyberalertx.com/en/threat/$ID1/card/og.png
( cd $R && loadenv $PROD/.env && venv/bin/python -m cyberalertx.tools.publish cycle --limit 1 2>&1 | tail -3 )        # "preview only"; writes nothing
# database and JSON, after the first new ingest cycle (`cycle complete` in the journal, ≤ 2 min after C7)
journalctl -u cyberalertx-run --since -10min -o cat | grep -E 'cycle complete|lacks relevance|Traceback' | tail -3
adm http://127.0.0.1:8000/admin/system.json | python3 -c 'import json,sys;d=json.load(sys.stdin);print("overall:",d["overall"])'
( loadenv $PROD/.env; export URL="${CYBERALERTX_PG_URL/postgresql+psycopg:/postgresql:}"
  docker run --rm -e URL postgres:17-alpine sh -c 'psql "$URL" -tAc "select coalesce(nullif(relevance_status,'"''"'),'"'"'(empty)'"'"'), count(*) from news_items group by 1 order by 2 desc"' )
python3 -c "import json;d=json.load(open('$PROD/data/items.json'));it=d if isinstance(d,list) else d.get('items',d);it=list(it.values()) if isinstance(it,dict) else it;print(len(it),'items,',sum(1 for x in it if x.get('relevance_status')),'with relevance')"
journalctl -u cyberalertx-api -u cyberalertx-run -u cyberalertx-frontend --since -20min | grep -cE 'Traceback|ERROR'
```

| | |
|---|---|
| **Expected** | All processes under `$R`; telegram and generate disabled, telegram held; `settings_check`: `fact_sheet_enabled False`, `threads_publish_enabled False`, `telegram_attach_images False`, `hide_out_of_scope_publicly False`, `review_mode flag (… unset)`, `top10_slot (off)`, `breaking_updates False`, `image_provider none`. Health 200 locally and publicly; optimizer 404; admin 401 / 200; article and card 200 `image/png`; preview only. `cycle complete` with **no** `lacks relevance` warning; `overall` `healthy`, or `degraded` only because of the disabled timers. In PG, rows from this cycle carry a relevance status and older rows show `(empty)`. `items.json` items gain relevance fields as they are re-ingested. No new Tracebacks. |
| **Risk** | None (read-only) |
| **Rollback** | Any failure: C14 row "C7–C9", **before** C9 |

**⏸ P5: go/no-go to resume compatible workers.**

## C9. Resume only workers confirmed compatible [SUDO]

**Approval:** P5.

| Worker | Compatible? | Evidence | Action |
|---|---|---|---|
| `run` (ingest) | Yes, new code | C1 tests; C8 cycle verified | Already running since C7 |
| `generate` | Yes, new code, `FACT_SHEET=0` | C1 tests; Stage B dry runs; `settings_check` | **Resume now** |
| `analytics` | Yes, unchanged code | `server/analytics` byte-identical in `main` and `$SHA`; it reads `items.json` titles only; `--dry-run` below | Leave as is (03:00) |
| Legacy `telegram` | **Not resumed** | D6 | Held until Stage D |
| New publisher (`tools.publish cycle --send`) | Not scheduled | D7 | Nothing |

```bash
. ~/stagec.vars
(cd $PROD && venv/bin/python -m server.analytics ingest --dry-run | tail -3)    # [RO] "write nothing", exit 0, against the new data/
sudo systemctl enable --now cyberalertx-generate.timer
systemctl list-timers 'cyberalertx-*' --no-pager                                # generate + analytics only; telegram absent (disabled)
```

The timer declares `Requires=cyberalertx-generate.service`, so `enable --now` **starts a generate run immediately**, in addition to `Persistent=true` catch-up. That is
the first new generate run; watch it:
- `journalctl -u cyberalertx-generate -n 40` shows no Traceback;
- `/admin/usage` shows `brief` calls and **no** `fact_sheet` calls;
- the newest article shows its brief.

**Window closes.** Stage C now runs in its steady state:
- new site, API, ingest and generate;
- no Telegram posting;
- no Threads.

## C10. Private Telegram test channel [PROD: an external private channel]

**Approval:** P6.

**Purpose:** prove the new delivery paths before Stage D: the job worker,
`sendPhoto` with the card, the text path, and per-locale routing (O8).

**Isolation:**
- the ledger key is `(fingerprint, locale)`, not the channel, so the test uses its **own code copy with its own data copy** (`DATA_DIR` follows the code directory) and a **test bot**;
- the legacy publisher is held, so the old and new publishers never operate together;
- the test publisher only addresses the private channels.

**Preconditions:**
- the test bot is not the production bot, and is admin of two private channels (EN test, UA test);
- their ids `-100…` are in `~/secrets/telegram-test.env` (0600), with `CYBERALERTX_TELEGRAM_BOT_TOKEN`, `_CHANNEL_EN`, `_CHANNEL_UA`, `_MIN_LEVEL=Medium`;
- the new site is live (Telegram fetches the card from the public URL).

```bash
. ~/stagec.vars
python3 - <<'EOF'                         # [RO] no values printed
import re,os
r=lambda p:dict(re.findall(r'^(CYBERALERTX_TELEGRAM_[A-Z_]+)=(.*)$',open(os.path.expanduser(p)).read(),re.M))
t,p=r('~/secrets/telegram-test.env'),r('/home/cax/cax/.env')
for k in ('CYBERALERTX_TELEGRAM_BOT_TOKEN','CYBERALERTX_TELEGRAM_CHANNEL_EN','CYBERALERTX_TELEGRAM_CHANNEL_UA'):
    print(k,'DISTINCT' if t.get(k) and t.get(k)!=p.get(k) else 'SAME/MISSING: STOP')
EOF
T=/home/cax/cyberalertx/telegram-test/$ID; mkdir -p $T
git -C $REPO archive $SHA | tar -x -C $T && cp -a $PROD/data $T/data          # a real copy, never a symlink   [NEW]
(cd $T && $R/venv/bin/python -c "import dotenv,cyberalertx.config as c;print(repr(dotenv.find_dotenv(usecwd=True)), c.DATA_DIR)")   # '' $T/data
TT() { (cd $T && env -i HOME=$HOME PATH=/usr/bin:/bin bash -c "set -a; . ~/secrets/telegram-test.env; set +a;
        export CYBERALERTX_STORAGE_BACKEND=json CYBERALERTX_TELEGRAM_ATTACH_IMAGES=${ATTACH:-1};
        exec $R/venv/bin/python -m $*"); }
TT cyberalertx.tools.publish cycle --limit 1              # preview: targets must be the -100… test ids
TT cyberalertx.tools.publish cycle --send --limit 1       # photo path   [PROD: private channels]
ATTACH=0 TT cyberalertx.tools.publish cycle --send --limit 1   # text path
TT cyberalertx.tools.publish status
```

| | |
|---|---|
| **Expected** | 3× `DISTINCT`; `''` and `$T/data`; the preview names only test ids; EN channel: an English post with the card; UA channel: a Ukrainian one; text run: text with a link preview; `status`: Telegram jobs `published` with message ids |
| **Risk** | Low. Only private channels; production data and ledger are untouched by design. |
| **Verify** | Language matches channel; the card shows; links open the right article. `grep -c -- '-100<test-id>' $PROD/data/telegram_published.jsonl` → 0. The production ledger is unchanged (`md5sum` before and after: legacy is held, so nothing else writes it). |
| **Rollback** | Delete the test messages; `rm -rf $T` |

The legacy `publish-telegram` command is deliberately **not** tested from the
new code. It is never used again: Stage D replaces it.

## C11. Threads EN and UA OAuth verification

**Approval:** P7. Step 1 is [PROD] (`.env`); step 2 is [SUDO]; step 3 is
[PROD] (`data/threads_accounts.json`).

`CYBERALERTX_THREADS_PUBLISH=0` is already pinned (C7) and stays.

**Preconditions:**
- THREADS_SETUP.md steps 1–6: the Meta app, both profiles as testers, redirect URI `https://cyberalertx.com/admin/threads/callback`;
- `cryptography` is in the release venv.

```bash
. ~/stagec.vars; umask 077
install -m 600 $PROD/.env $B/env.before-threads
(cd $R && venv/bin/python -m cyberalertx.tools.threads gen-key)     # copy the printed key into the editor below
install -m 600 $PROD/.env $PROD/.env.new
${EDITOR:-nano} $PROD/.env.new       # add _APP_ID, _APP_SECRET, _REDIRECT_URI, _TOKEN_KEY, _ACCOUNTS=en:en,ua:ua   (PUBLISH=0 already there)
diff <(grep -oE '^[A-Z_][A-Z0-9_]*=' $PROD/.env | sort) <(grep -oE '^[A-Z_][A-Z0-9_]*=' $PROD/.env.new | sort)   # 5 added, none removed
grep -c '^CYBERALERTX_THREADS_PUBLISH=0$' $PROD/.env.new                                                         # 1
stat -c '%a %U:%G' $PROD/.env.new && mv $PROD/.env.new $PROD/.env
sudo systemctl restart cyberalertx-api && curl -sf 127.0.0.1:8000/healthz
```

**Browser:**
1. `/admin/threads` → Configuration: every item *set*.
2. Logged in to Threads as **EN only**: Slot en → Connect → approve.
3. Log out; logged in as **UA**: Slot ua → Connect → approve.

```bash
( cd $R && loadenv $PROD/.env
  venv/bin/python -m cyberalertx.tools.threads status
  venv/bin/python -m cyberalertx.tools.threads verify en; venv/bin/python -m cyberalertx.tools.threads verify ua
  venv/bin/python -I -c "import sys;sys.path.insert(0,'.');exec(open('$TOOLS/settings_check.py').read())" | grep threads )   # False
stat -c '%a %n' $PROD/data/threads_accounts.json                                                                         # 600
python3 -c 'import json,sys
def w(o):
    if isinstance(o,dict):
        for k,v in o.items():
            if k=="token_ciphertext": print(k,"fernet" if str(v).startswith("gAAAA") else "NOT ENCRYPTED: STOP")
            w(v)
    elif isinstance(o,list): [w(x) for x in o]
w(json.load(open(sys.argv[1])))' $PROD/data/threads_accounts.json                                                         # 2× fernet
```

| | |
|---|---|
| **Expected** | Both slots connected to the right profiles (different user ids); verified; tokens encrypted only; publication still off |
| **Risk** | Low. The slot is bound by the OAuth `state`; a different profile in a connected slot is refused. |
| **Rollback** | Disconnect both slots (`/admin/threads`, or `tools.threads disconnect en|ua`), then `install -m 600 $B/env.before-threads $PROD/.env && sudo systemctl restart cyberalertx-api` |

## C12. Stage D: Telegram scheduler transition [SUDO]. Separately authorized.

**Approval:** **P8**, separate from Stage C.

**Preconditions:**
- C8/C9 healthy for at least 24 h;
- C10 passed.

The old publisher is replaced **in the same unit**. No step leaves both
startable.

```bash
. ~/stagec.vars
systemctl is-enabled cyberalertx-telegram.timer; systemctl is-active cyberalertx-telegram.service   # disabled, inactive
cp -a $PROD/data/telegram_published.jsonl $B/ledger.before-stage-d                                   # [NEW]
( cd /home/cax/cyberalertx/current && loadenv $PROD/.env
  venv/bin/python -m cyberalertx.tools.publish cycle --limit 1      # [RO] preview
  venv/bin/python -m cyberalertx.tools.publish plan                 # [PROD] creates jobs; imports the ledger as "published"
  venv/bin/python -m cyberalertx.tools.publish status )
# one edit: release paths + the new command; the legacy command disappears from the unit
sudo sed -i -e 's#^WorkingDirectory=/home/cax/cax$#WorkingDirectory=/home/cax/cyberalertx/current#' \
            -e 's#/home/cax/cax/venv/bin/python -m cyberalertx.main publish-telegram --limit 1#/home/cax/cyberalertx/current/venv/bin/python -m cyberalertx.tools.publish cycle --send --limit 1#' \
            /etc/systemd/system/cyberalertx-telegram.service
sudo rm -r /etc/systemd/system/cyberalertx-telegram.service.d          # the hold is no longer needed: the old command is gone
sudo systemctl daemon-reload
systemctl cat cyberalertx-telegram | grep -E 'WorkingDirectory|ExecStart|TimeoutStartSec|Condition'   # current, cycle --send --limit 1, 300, no Condition
sudo systemctl enable --now cyberalertx-telegram.timer                 # Persistent=true: the first new run may start at once; watch it
```

| | |
|---|---|
| **Expected** | Every ledger entry is imported as published, so nothing old is re-sent; each run posts at most 1 per channel, newest first |
| **Risk** | **Medium:** the first automated publishing by new code. Bounded by `--limit 1`, the 48 h expiry, the ledger import and the single unit. |
| **Verify** | `journalctl -u cyberalertx-telegram -n 50` shows `published` 1–2; `/admin/publishing` shows EN and UA published with message ids; the ledger tail matches; one post per channel in the right language, no duplicate; `outcome_unknown` = 0 |
| **Rollback** | `sudo systemctl disable --now cyberalertx-telegram.timer`, then restore `$B/cyberalertx-telegram.service` and the hold drop-in, then daemon-reload. **Not** back to the legacy command while the new code runs; see ROLLBACK_RUNBOOK §3 for the full release rollback. |

## C13. Monitoring [RO], first 72 h

| When | Check | Healthy |
|---|---|---|
| Twice daily | `adm http://127.0.0.1:8000/admin/system.json \| python3 -c 'import json,sys;print(json.load(sys.stdin)["overall"])'` | `healthy` (until Stage D: `degraded` only for the disabled Telegram timer) |
| Twice daily | `journalctl -u 'cyberalertx-*' --since -12h \| grep -cE 'Traceback\|OPERATOR ACTION'` | at or below the C0 baseline |
| Twice daily | `systemctl is-enabled cyberalertx-telegram.timer` (until Stage D) | `disabled` |
| Daily | `/admin/usage` | `brief` calls only, no `fact_sheet` (D1), about 25 a day |
| Daily | `/admin/sources`; `du -sh $PROD/data`; `df -h /home` | no source silent for more than 24 h; steady growth; > 15 % free |
| Daily | the `settings_check` line from C8 | unchanged |
| After 72 h | D1 review: turn the fact sheet on (`CYBERALERTX_FACT_SHEET=1`, safe `.env` edit) only after the benchmark has passed | — |
| Weekly | `npm audit --omit=dev` in `$R/frontend`; the vercel/next.js advisories | 0 |

## C14. Rollback matrix

| Reached | Undo |
|---|---|
| C0–C4 | Nothing in production. Optionally `rm -rf $R $SNAP`; drop the test project. |
| C5 (writers stopped) | `sudo rm -r /etc/systemd/system/cyberalertx-telegram.service.d && sudo systemctl daemon-reload && sudo systemctl enable --now cyberalertx-run cyberalertx-generate.timer cyberalertx-telegram.timer` |
| C6 (005 applied) | As C5. 005 can stay: old code ignores it. Or ROLLBACK_RUNBOOK §5, or restore `$B/supabase-quiesced.dump`. |
| **C7–C9 (new release active)** | 1. `sudo systemctl disable --now cyberalertx-generate.timer`, then wait for `cyberalertx-generate.service` to be inactive. 2. Copy the current `items.json`, `threat_posts.json` and ledger to `$B/at-rollback/` (ROLLBACK_RUNBOOK §2). 3. `sudo cp -a $B/cyberalertx-{api,frontend,run,generate}.service /etc/systemd/system/`. 4. `sudo rm -r /etc/systemd/system/cyberalertx-telegram.service.d`. 5. `sudo systemctl daemon-reload`. 6. `install -m 600 $B/env.bak $PROD/.env`. 7. `sudo systemctl restart cyberalertx-api cyberalertx-frontend cyberalertx-run`. 8. Health check. 9. `sudo systemctl enable --now cyberalertx-generate.timer cyberalertx-telegram.timer`: the legacy publisher resumes, and its catch-up run is de-duplicated by the ledger. **Known effects (O19):** the old ingest rewrites `items.json` without relevance fields, and editor rejections stop applying. To roll forward again, restore those from `$B/at-rollback/`. Restore `prod-data-quiesced.tgz` only if data is damaged; it loses everything ingested since. |
| C10 | Delete the test messages; `rm -rf $T` |
| C11 | C11 rollback |
| C12 (Stage D) | C12 rollback |

**After any rollback:**
- check `/admin/system` or the journal;
- check the channels for duplicates;
- add a line to OPEN_ISSUES.md.

---

**Rollback after the O27 hotfix.** `c7_rollback.sh` restores the four unit files but does not remove the API drop-in `cyberalertx-api.service.d/stage-c-json-reads.conf`. The old API also supports the JSON backend, so the drop-in is harmless after a rollback and keeps the old site fast. To remove it **before** rolling back, run `sudo bash /home/cax/stagec-tools/c8_api_json_reads.sh revert` while the API still runs from the release. After a rollback, remove it by hand (`sudo rm -r /etc/systemd/system/cyberalertx-api.service.d && sudo systemctl daemon-reload && sudo systemctl restart cyberalertx-api`).

## Appendix A: helper scripts (write them to `$TOOLS` [NEW])

```bash
mkdir -p $TOOLS && cat > $TOOLS/verify_release.py <<'EOF'
"""verify_release.py <release_dir> <repo> <commit>: each file in the commit's tree must exist in the release with the
same git blob hash. Files not in the tree are listed, except build outputs and caches. Exit 0 only if both are clean."""
import hashlib, os, subprocess, sys
rel, repo, commit = sys.argv[1:4]
BUILD = ("venv/", "frontend/node_modules/", "frontend/.next/", "frontend/next-env.d.ts", "frontend/tsconfig.tsbuildinfo",
         "frontend/.env.production", "data", "RELEASE", "RELEASE-INVENTORY.txt")
CACHES = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
tree = {}
out = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "-z", commit], capture_output=True, check=True).stdout
for rec in out.split(b"\0"):
    if not rec: continue
    meta, path = rec.split(b"\t", 1); mode, typ, sha = meta.split()
    if typ == b"blob": tree[path.decode()] = (mode.decode(), sha.decode())
bad = 0
for path, (mode, sha) in tree.items():
    p = os.path.join(rel, path)
    if mode == "120000":
        data = os.readlink(p).encode() if os.path.islink(p) else None
    else:
        data = open(p, "rb").read() if os.path.isfile(p) and not os.path.islink(p) else None
    if data is None or hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != sha:
        bad += 1; print("MISMATCH", path)
extra = []
for root, dirs, files in os.walk(rel):
    r = os.path.relpath(root, rel); r = "" if r == "." else r + "/"
    if any(r.startswith(b) for b in BUILD if b.endswith("/")): dirs[:] = []; continue
    if any(c in r.split("/") for c in CACHES): dirs[:] = []; continue
    for n in files + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
        q = r + n
        if n in CACHES: continue
        if q not in tree and not any(q == b or q.startswith(b) for b in BUILD): extra.append(q)
    dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d)) and not (r + d + "/").startswith(BUILD)]
print(f"commit {commit}: {len(tree)} files in tree, {bad} mismatched/missing, {len(extra)} unexpected extra")
for q in extra[:20]: print("EXTRA", q)
sys.exit(1 if bad or extra else 0)
EOF
cat > $TOOLS/settings_check.py <<'EOF'
# Prints the settings the release code actually resolves from the environment. No secrets.
import os
from cyberalertx.ai.config import AISettings
from cyberalertx.ai.review import review_mode
from cyberalertx.media.illustrations import provider_from_env
from cyberalertx.pipeline.relevance import hide_out_of_scope_publicly
from cyberalertx.publish.config import build_telegram_settings
from cyberalertx.publish.orchestrator import PublishPolicy
from cyberalertx.threads.config import ThreadsSettings
p = PublishPolicy.from_env(None)
rows = {
    "fact_sheet_enabled": AISettings().fact_sheet_enabled,
    "threads_publish_enabled": ThreadsSettings.from_env().publish_enabled,
    "telegram_attach_images": build_telegram_settings().attach_images,
    "hide_out_of_scope_publicly": hide_out_of_scope_publicly(),
    "review_mode": review_mode() + ("  (CYBERALERTX_REVIEW_MODE unset)" if "CYBERALERTX_REVIEW_MODE" not in os.environ else ""),
    "top10_slot": p.top10_at or "(off)",
    "breaking_updates": p.breaking_updates,
    "image_provider": provider_from_env().name,
}
for k, v in rows.items(): print(f"{k:28} {v}")
EOF
```

Both scripts were tested on 4 Nov 2026, in scratch only:
- **`verify_release.py`:** a fresh archive of `4fa7a63` gives 352 files, 0 mismatched and 0 extra (exit 0). One changed byte is reported as `MISMATCH` (exit 1). RC3, built from `6956a5a`, matches the `4fa7a63` tree with 0 mismatches.
- **`settings_check.py`:** with the four pins, every flag resolves to off and `review_mode flag (unset)`. With nothing set, only `fact_sheet_enabled` is `True`.

## Appendix B: `c5_quiesce.sh` (revision 4: adds root-crontab and analytics preflight)

```bash
#!/bin/bash
# =============================================================================
# CyberAlertX Stage C, step C5 (STAGE_C_RUNBOOK.md rev. 2): quiesce the legacy writers.
#
#   sudo bash /home/cax/stagec-tools/c5_quiesce.sh
#
# Order (each step verified before the next; any failure stops the script):
#   0. Preflight: root, unit files, API+frontend active, journal readable, Stage D marker ABSENT.
#   1. Timers first: disable + stop cyberalertx-generate.timer and cyberalertx-telegram.timer,
#      so no new scheduled job can start.
#   2. Wait for any running generate/telegram oneshot to FINISH NATURALLY. Never stopped.
#      Timeout -> abort, naming the unit still active. No hold, no run stop.
#   3. cyberalertx-run (long-running; its 30-min cycles run inside the process, no lock file):
#      wait for a verified idle window -- last scheduler record for the CURRENT PID is a
#      completion, the next scheduled start is > MARGIN s away, and the process is not using
#      CPU -- then disable + stop it. Afterwards: clean exit (Result=success) and no cycle
#      started during the stop. Timeout -> abort.
#   4. Telegram hold: atomic drop-in with ConditionPathExists=<Stage D marker>, daemon-reload,
#      verified LOADED (DropInPaths) and evaluating FALSE (systemd-analyze condition).
#   5. Final verification and summary.
#
# Never: stops the API or frontend, stops a running oneshot, kills an ingest cycle, creates the
# Stage D marker, touches data/, .env or the database, or reverts anything automatically.
# Safe to re-run: completed steps are detected and verified, not repeated.
#
# Exit 0 = "C5 COMPLETED". Any other exit = C5 NOT completed; the printed state is authoritative.
# =============================================================================
set -Eeuo pipefail

# ---- configuration -----------------------------------------------------------------------------
# Test overrides are honoured only with C5_TEST=1 (sudo resets the environment, so a production
# run always uses the real tools and paths).
if [ "${C5_TEST:-0}" = 1 ]; then
  SYSTEMCTL=${C5_SYSTEMCTL:-systemctl}; JOURNALCTL=${C5_JOURNALCTL:-journalctl}
  ANALYZE=${C5_ANALYZE:-systemd-analyze}; UNIT_DIR=${C5_UNIT_DIR:?}; PROC=${C5_PROC:-/proc}
  MARKER=${C5_MARKER:?}
else
  SYSTEMCTL=systemctl; JOURNALCTL=journalctl; ANALYZE=systemd-analyze
  UNIT_DIR=/etc/systemd/system; PROC=/proc; MARKER=/home/cax/cyberalertx/STAGE_D_AUTHORIZED
fi
CRON_FILES=${C5_CRON_FILES:-"/var/spool/cron/crontabs/root /etc/crontab"}   # read as root in preflight
[ "${C5_TEST:-0}" = 1 ] || CRON_FILES="/var/spool/cron/crontabs/root /etc/crontab"
ONESHOT_WAIT=${C5_ONESHOT_WAIT:-420}   # > TimeoutStartSec=300 of both oneshots
RUN_WAIT=${C5_RUN_WAIT:-2100}          # 35 min: longer than one 30-min ingest interval
MARGIN=${C5_MARGIN:-180}               # seconds required before the next scheduled cycle
POLL=${C5_POLL:-5}
CPU_TICKS=${C5_CPU_TICKS:-20}          # > 0.2 s CPU in a 2 s sample = treat as busy
STOP_TIMEOUT=${C5_STOP_TIMEOUT:-120}   # bound on `systemctl stop` (unit TimeoutStopSec is 90 s)

RUN=cyberalertx-run.service
GEN_T=cyberalertx-generate.timer; GEN_S=cyberalertx-generate.service
TG_T=cyberalertx-telegram.timer;  TG_S=cyberalertx-telegram.service
DROPIN_DIR=$UNIT_DIR/cyberalertx-telegram.service.d
DROPIN=$DROPIN_DIR/stage-c-hold.conf
DROPIN_BODY="[Unit]
# Stage C hold: the legacy publisher must not run until Stage D is authorized.
ConditionPathExists=$MARKER"

STEP="0 preflight"

# ---- helpers -----------------------------------------------------------------------------------
log()  { printf '%s [C5 %s] %s\n' "$(date '+%F %T')" "$STEP" "$*"; }
st()   { $SYSTEMCTL is-active  "$1" 2>/dev/null || true; }      # non-zero exit is normal
en()   { $SYSTEMCTL is-enabled "$1" 2>/dev/null || true; }
prop() { $SYSTEMCTL show -p "$2" --value "$1" 2>/dev/null || true; }

state() {
  echo "----- state at failure -----"
  for u in $GEN_T $TG_T $GEN_S $TG_S $RUN cyberalertx-api.service cyberalertx-frontend.service; do
    printf '  %-32s active=%-12s enabled=%s\n' "$u" "$(st "$u")" "$(en "$u")"
  done
  printf '  %-32s %s\n' "telegram hold drop-in" "$( [ -f "$DROPIN" ] && echo present || echo absent )"
  printf '  %-32s %s\n' "Stage D marker" "$( [ -e "$MARKER" ] && echo PRESENT || echo absent )"
}
fail() {
  trap - ERR
  echo; echo "C5 FAILED in step '$STEP': $*"; state
  echo "C5 did NOT complete. Nothing after the failed step was done. Nothing was reverted."
  exit 1
}
trap 'fail "unexpected error (line $LINENO): $BASH_COMMAND"' ERR

busy_state() { case "$1" in active|activating|deactivating|reloading|refreshing) return 0;; *) return 1;; esac; }
queued()     { $SYSTEMCTL list-jobs --no-legend 2>/dev/null | grep -qE "[[:space:]]$1[[:space:]]" ; }

cpu_ticks() { awk '{print $14+$15}' "$PROC/$1/stat" 2>/dev/null; }

# Scheduler records for the CURRENT run process only (this boot, this PID).
markers() {
  $JOURNALCTL -b "_PID=$1" "_SYSTEMD_UNIT=$RUN" -o cat --no-pager 2>/dev/null \
    | grep -E 'apscheduler\.executors[^]]*\] (Running job|Job .*(executed successfully|raised an exception))|\] scheduler started; interval=' \
    || true
}

# Sets IDLE_REASON; returns 0 only when an ingest cycle is provably not running and none is due
# within MARGIN seconds. Also sets LAST_MARKERS (count) for the interruption check.
run_idle() {
  local pid=$1 m last next_txt next now left t0 t1
  m=$(markers "$pid"); LAST_MARKERS=$(printf '%s\n' "$m" | grep -c 'Running job' || true)
  last=$(printf '%s\n' "$m" | grep -v '^$' | tail -1)
  now=$(date +%s)
  if [ -z "$last" ]; then IDLE_REASON="no scheduler records for PID $pid (cannot prove idle)"; return 1; fi
  case "$last" in
    *"Running job"*) IDLE_REASON="a cycle is running (last record: Running job)"; return 1 ;;
    *"scheduler started; interval="*)
      # Startup kick cycle finished (it runs before the scheduler starts); first scheduled run is
      # start + interval. Use the record's own timestamp.
      local ts iv; ts=$(printf '%s' "$last" | grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:]{8}')
      iv=$(printf '%s' "$last" | grep -oE 'interval=[0-9]+' | cut -d= -f2)
      [ -n "$ts" ] && [ -n "$iv" ] || { IDLE_REASON="unparseable startup record"; return 1; }
      next=$(( $(date -d "$ts" +%s) + iv * 60 )) ;;
    *) next_txt=$(printf '%s' "$last" | grep -oE 'next run at: [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:]{8} UTC' | sed 's/next run at: //')
       [ -n "$next_txt" ] || { IDLE_REASON="completion record without a next-run time"; return 1; }
       next=$(date -d "$next_txt" +%s) ;;
  esac
  left=$(( next - now ))
  if [ "$left" -le "$MARGIN" ]; then IDLE_REASON="next cycle due in ${left}s (need > ${MARGIN}s)"; return 1; fi
  t0=$(cpu_ticks "$pid"); sleep 2; t1=$(cpu_ticks "$pid")
  if [ -z "$t0" ] || [ -z "$t1" ]; then IDLE_REASON="cannot read CPU of PID $pid"; return 1; fi
  if [ $(( t1 - t0 )) -gt "$CPU_TICKS" ]; then IDLE_REASON="process busy: $((t1-t0)) CPU ticks in 2 s"; return 1; fi
  IDLE_REASON="idle: last cycle completed, next due in ${left}s, CPU $((t1-t0)) ticks/2s"; return 0
}

# ---- 0. preflight ------------------------------------------------------------------------------
if [ "${C5_TEST:-0}" != 1 ] && [ "$(id -u)" != 0 ]; then echo "run with: sudo bash $0"; exit 1; fi
for u in $RUN $GEN_S $TG_S $GEN_T $TG_T; do
  [ "$(prop "$u" FragmentPath)" = "$UNIT_DIR/$u" ] || fail "unit $u is not loaded from $UNIT_DIR"
done
[ ! -e "$MARKER" ] || fail "Stage D marker $MARKER exists; it must not exist in Stage C"
for u in cyberalertx-api.service cyberalertx-frontend.service; do
  [ "$(st $u)" = active ] || fail "$u is not active (the site must keep serving)"
done
$JOURNALCTL -u "$RUN" -n 1 --no-pager >/dev/null 2>&1 || fail "cannot read the journal of $RUN"
# No other scheduler may run legacy code against data/ (root's crontab is unreadable without sudo).
for c in $CRON_FILES; do
  if [ -f "$c" ] && grep -vE '^[[:space:]]*#' "$c" | grep -qE '/home/cax/cax|cyberalertx'; then
    fail "$c schedules CyberAlertX/legacy commands; add them to the C4 inventory first"
  fi
done
# Analytics (03:01) writes only data/analytics*, but must not be mid-run during the quiet check.
if busy_state "$(st cyberalertx-analytics.service)"; then fail "cyberalertx-analytics.service is running; wait for it to finish"; fi
log "preflight OK"

# ---- 1. timers first ---------------------------------------------------------------------------
STEP="1 timers"
for t in $GEN_T $TG_T; do
  if [ "$(en $t)" != disabled ]; then
    $SYSTEMCTL disable "$t" >/dev/null 2>&1 || fail "systemctl disable $t failed"
  fi
  if [ "$(st $t)" != inactive ]; then
    $SYSTEMCTL stop "$t" || fail "systemctl stop $t failed"
  fi
  [ "$(en $t)" = disabled ] || fail "$t is '$(en $t)' after disable"
  [ "$(st $t)" = inactive ] || fail "$t is '$(st $t)' after stop"
  log "$t disabled and inactive"
done

# ---- 2. let running oneshots finish naturally --------------------------------------------------
STEP="2 oneshots"
deadline=$(( $(date +%s) + ONESHOT_WAIT ))
while :; do
  still=""
  for s in $GEN_S $TG_S; do
    if busy_state "$(st $s)" || queued "$s"; then still="$still $s($(st $s))"; fi
  done
  [ -z "$still" ] && break
  [ "$(date +%s)" -lt "$deadline" ] || fail "still active after ${ONESHOT_WAIT}s:$still (not stopped; let it finish, then re-run)"
  log "waiting for running oneshot(s) to finish:$still"; sleep "$POLL"
done
log "$GEN_S and $TG_S are not running"

# ---- 3. ingest loop: stop only in a verified idle window ---------------------------------------
STEP="3 run"
if [ "$(st $RUN)" = inactive ] && [ "$(en $RUN)" = disabled ]; then
  log "$RUN already inactive and disabled (re-run): nothing to do"
else
  [ "$(st $RUN)" = active ] || fail "$RUN is '$(st $RUN)' (expected active); investigate before continuing"
  PID=$(prop $RUN MainPID); [ -n "$PID" ] && [ "$PID" != 0 ] || fail "no MainPID for $RUN"
  deadline=$(( $(date +%s) + RUN_WAIT ))
  until run_idle "$PID"; do
    [ "$(date +%s)" -lt "$deadline" ] || fail "no idle window within ${RUN_WAIT}s: $IDLE_REASON ($RUN left running)"
    [ "$(prop $RUN MainPID)" = "$PID" ] || fail "$RUN changed PID during the wait ($PID -> $(prop $RUN MainPID))"
    log "not idle yet: $IDLE_REASON"; sleep "$POLL"
  done
  log "$IDLE_REASON"
  BEFORE=$LAST_MARKERS
  $SYSTEMCTL disable "$RUN" >/dev/null 2>&1 || fail "systemctl disable $RUN failed"
  timeout "$STOP_TIMEOUT" $SYSTEMCTL stop "$RUN" || fail "systemctl stop $RUN failed or exceeded ${STOP_TIMEOUT}s"
  [ "$(st $RUN)" = inactive ] || fail "$RUN is '$(st $RUN)' after stop"
  [ "$(en $RUN)" = disabled ] || fail "$RUN is '$(en $RUN)' after disable"
  [ "$(prop $RUN Result)" = success ] || fail "$RUN did not exit cleanly (Result=$(prop $RUN Result))"
  after=$(markers "$PID")
  n_after=$(printf '%s\n' "$after" | grep -c 'Running job' || true)
  if [ "$n_after" -gt "$BEFORE" ]; then
    case "$(printf '%s\n' "$after" | grep -v '^$' | tail -1)" in
      *"Running job"*) fail "INTERRUPTED: a cycle started during the stop and did not complete; check data/ and Postgres before continuing" ;;
      *) log "note: a cycle started and completed during the stop (not interrupted)" ;;
    esac
  fi
  log "$RUN stopped cleanly and disabled (PID $PID, no cycle interrupted)"
fi

# ---- 4. Telegram hold --------------------------------------------------------------------------
STEP="4 telegram hold"
if busy_state "$(st $TG_S)"; then fail "$TG_S became active; not installing the hold"; fi
if [ -f "$DROPIN" ] && [ "$(cat "$DROPIN")" = "$DROPIN_BODY" ]; then
  log "hold drop-in already present with the expected content"
else
  mkdir -p "$DROPIN_DIR" || fail "cannot create $DROPIN_DIR"
  tmp=$(mktemp "$DROPIN_DIR/.stage-c-hold.XXXXXX") || fail "cannot create a temp file in $DROPIN_DIR"
  printf '%s\n' "$DROPIN_BODY" > "$tmp" || { rm -f "$tmp"; fail "cannot write $tmp"; }
  chmod 0644 "$tmp" && mv -f "$tmp" "$DROPIN" || { rm -f "$tmp"; fail "cannot install $DROPIN"; }
  [ "$(cat "$DROPIN")" = "$DROPIN_BODY" ] || fail "$DROPIN content differs after write"
  log "hold drop-in written: $DROPIN"
fi
$SYSTEMCTL daemon-reload || fail "systemctl daemon-reload failed (drop-in written but NOT loaded)"
case " $(prop $TG_S DropInPaths) " in *" $DROPIN "*) ;; *) fail "systemd did not load $DROPIN (DropInPaths='$(prop $TG_S DropInPaths)')";; esac
[ "$(prop $TG_S NeedDaemonReload)" = no ] || fail "$TG_S still needs daemon-reload"
if $ANALYZE condition "ConditionPathExists=$MARKER" >/dev/null 2>&1; then
  fail "condition ConditionPathExists=$MARKER evaluates TRUE; the hold would not block"
fi
[ ! -e "$MARKER" ] || fail "Stage D marker appeared"
log "hold loaded; ConditionPathExists=$MARKER evaluates false (legacy publisher cannot run)"

# ---- 5. final verification ---------------------------------------------------------------------
STEP="5 verify"
for u in $RUN $GEN_S $TG_S $GEN_T $TG_T; do if busy_state "$(st $u)"; then fail "$u is $(st $u)"; fi; done
for u in $RUN $GEN_T $TG_T; do [ "$(en $u)" = disabled ] || fail "$u is $(en $u)"; done
for u in cyberalertx-api.service cyberalertx-frontend.service; do [ "$(st $u)" = active ] || fail "$u is not active"; done
trap - ERR
echo "----- C5 COMPLETED -----"
for u in $GEN_T $TG_T $GEN_S $TG_S $RUN cyberalertx-api.service cyberalertx-frontend.service; do
  printf '  %-32s active=%-10s enabled=%s\n' "$u" "$(st "$u")" "$(en "$u")"
done
echo "  telegram hold: $DROPIN (loaded); Stage D marker: absent"
```

## Appendix C: `c5_verify_quiet.sh`

```bash
#!/bin/bash
# =============================================================================
# CyberAlertX Stage C, C5 step 4: prove production state is quiet after c5_quiesce.sh.
# Runs as cax, no sudo, read-only (it never writes data/, .env or the database).
#
#   bash /home/cax/stagec-tools/c5_verify_quiet.sh [seconds]      (default 120)
#
# PASS only if, over the whole window:
#   * no file under data/ changed, except the ALLOWED legacy-API writes that remain
#     (see STAGE_C_RUNBOOK C4): data/feedback.jsonl (reader feedback, POST /feedback)
#     and data/quality_metrics.json (+ its .quality_metrics.*.tmp) (render counter);
#   * Postgres news_items, threat_posts and schema_migrations are byte-identical
#     (md5 over every row, ordered) at the start and at the end;
#   * the legacy writers are still inactive, the timers disabled, and the hold loaded.
# Exit 0 = QUIET. Exit 1 = NOT QUIET (each offending file / table is listed).
# =============================================================================
set -Eeuo pipefail
WINDOW=${1:-120}
if [ "${C5Q_TEST:-0}" = 1 ]; then
  DATA=${C5Q_DATA:?}; PGURL_CMD=${C5Q_PGURL_CMD:?}; SYSTEMCTL=${C5Q_SYSTEMCTL:-systemctl}; PSQL_CMD=${C5Q_PSQL_CMD:?}
else
  DATA=/home/cax/cax/data; SYSTEMCTL=systemctl
  # URL from .env via the parser (never `. .env`), passed to the container by name only.
  PGURL_CMD='. /home/cax/stagec-tools/loadenv.sh; loadenv /home/cax/cax/.env; printf %s "${CYBERALERTX_PG_URL/postgresql+psycopg:/postgresql:}"'
  PSQL_CMD='docker run --rm -i -e URL postgres:17-alpine sh -c "psql \"\$URL\" -X -q -tA -v ON_ERROR_STOP=1"'
fi
ALLOWED='^(feedback\.jsonl|quality_metrics\.json|\.quality_metrics\..*\.tmp)$'
fail=0; bad() { echo "NOT QUIET: $*"; fail=1; }

pg_fingerprint() {
  URL=$(bash -c "$PGURL_CMD") || { echo "ERR"; return; }
  [ -n "$URL" ] || { echo "ERR"; return; }
  export URL
  bash -c "$PSQL_CMD" <<'SQL' || echo "ERR"
select 'news_items '||count(*)||' '||coalesce(md5(string_agg(t::text, '|' order by t.fingerprint)),'-') from news_items t;
select 'threat_posts '||count(*)||' '||coalesce(md5(string_agg(t::text, '|' order by t::text)),'-') from threat_posts t;
select 'schema_migrations '||count(*)||' '||coalesce(md5(string_agg(version, ',' order by version)),'-') from schema_migrations;
SQL
}

for u in cyberalertx-run.service cyberalertx-generate.service cyberalertx-telegram.service; do
  a=$($SYSTEMCTL is-active "$u" 2>/dev/null || true); [ "$a" = inactive ] || [ "$a" = failed ] || bad "$u is $a"
done
for u in cyberalertx-run.service cyberalertx-generate.timer cyberalertx-telegram.timer; do
  e=$($SYSTEMCTL is-enabled "$u" 2>/dev/null || true); [ "$e" = disabled ] || bad "$u is $e"
done
case " $($SYSTEMCTL show -p DropInPaths --value cyberalertx-telegram.service 2>/dev/null || true) " in
  *stage-c-hold.conf*) ;; *) bad "Telegram hold drop-in not loaded";; esac
[ "$fail" = 0 ] || { echo "Run c5_quiesce.sh first."; exit 1; }

MARK=$(mktemp); trap 'rm -f "$MARK"' EXIT
PG0=$(pg_fingerprint); case "$PG0" in *ERR*) echo "NOT QUIET: cannot read Postgres fingerprint"; exit 1;; esac
echo "$(date '+%T') start: watching $DATA for ${WINDOW}s"; printf '%s\n' "$PG0" | sed 's/^/  pg  /'
touch "$MARK"; sleep "$WINDOW"
changed=$(find "$DATA" -newer "$MARK" \( -type f -o -type l \) -printf '%P\n' | sort)
PG1=$(pg_fingerprint); case "$PG1" in *ERR*) echo "NOT QUIET: cannot read Postgres fingerprint"; exit 1;; esac

allowed_hits=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if printf '%s\n' "$(basename "$f")" | grep -qE "$ALLOWED" && [ "$(dirname "$f")" = . ]; then
    allowed_hits="$allowed_hits $f"
  else
    bad "data/$f changed"
  fi
done <<< "$changed"
[ "$PG0" = "$PG1" ] || { bad "Postgres changed during the window"; diff <(printf '%s\n' "$PG0") <(printf '%s\n' "$PG1") | sed 's/^/  /'; }

echo "$(date '+%T') end"
if [ -n "$allowed_hits" ]; then echo "  allowed legacy-API writes seen:$allowed_hits"; fi
if [ "$fail" = 0 ]; then echo "QUIET: no unexpected writes to data/ or Postgres in ${WINDOW}s"; exit 0; fi
exit 1
```
