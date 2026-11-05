# Single repository consolidation — 2026-11-04

> **Status: historical record.** `release_rollback.sh` is superseded by `ops/release/release_switch.sh` ([OPERATIONS.md](../operations/OPERATIONS.md)); `/home/cax/cax-redesign` still exists and can be retired with separate authorization.

`/home/cax/cax` is now the canonical checkout of GitHub `main`. Production
does not run from it: the website, API, ingest and generator run from the
immutable release behind `/home/cax/cyberalertx/current`. This change only
affects what the checkout contains and how rollback works.

Labels used below: **[verified]** = checked on the production host;
**[tested]** = exercised in an isolated copy or with mocks; **[assumption]** =
not proven here.

## 1. Before

| Item | State |
|---|---|
| Git repository | one repository, two worktrees: `/home/cax/cax` (main worktree, legacy HEAD `73257f0`) and `/home/cax/cax-redesign` (linked worktree, branch `feature/editorial-quality-ux`) |
| Production release | `/home/cax/cyberalertx/releases/20261104-1626-4fa7a63` via `current`; release `data` → `/home/cax/cax/data` |
| Units on `current` | api, frontend, run, generate (`EnvironmentFile=/home/cax/cax/.env`; API drop-in `stage-c-json-reads.conf`) |
| Units on `/home/cax/cax` | `cyberalertx-analytics` (timer 03:01, `venv/bin/python -m server.analytics ingest`), `cyberalertx-telegram` (held by `stage-c-hold.conf`, timer disabled) |
| cron | `cax-backup` 03:00 archives `/home/cax/cax/data` |
| Rollback | `c7_rollback.sh` restarted the site **from `/home/cax/cax`**, i.e. depended on the legacy code staying checked out there |

## 2. What was done

1. **Preservation** [verified] — `/home/cax/backups/repo-consolidation-20261104-2235/` (mode 0700):
   * `cyberalertx-all-refs.bundle` — every ref (11, including `refs/backup/*`
     and `refs/original/*`); `git bundle verify` reports *okay*;
   * `OLD_HEAD.txt` = `73257f01378b8e264b72e9e21eec65db5aedc3a4`;
   * `.env` hash and mode (`600`), never its content;
   * `data/` manifest and SHA-256 of all 46 files, taken before and after;
   * process list before/after, all `cyberalertx-*` unit files and drop-ins.
   * Local annotated tag `legacy-production-2026-11-04` → `73257f0` (not pushed).
2. **Rollback gate** [tested] — `stagec-tools/release_rollback.sh <release-id>`
   replaces `c7_rollback.sh`. It only switches the `current` symlink
   atomically and restarts api, frontend and run; its preflight requires the
   target release to record a commit, have a venv and a frontend build, link
   `data` to `/home/cax/cax/data`, and all four units to run from `current`.
   Eight mocked cases pass. Against the real releases: the production release
   passes preflight and `verify_release` (352 files, 0 mismatched); the
   rehearsal releases RC2/RC3 are refused (their `data` links point at
   rehearsal copies). **Not executed for real.**
   `c7_rollback.sh` now refuses (exit 3) unless `/home/cax/cax` is still at
   `73257f0`, and points at `release_rollback.sh`.
3. **Fast-forward** [verified] — `git merge --ff-only origin/main` in
   `/home/cax/cax` (`73257f0` → `d98086f`); `main` tracks `origin/main`. No
   reset, no force, no history rewrite.

## 3. Verification after the fast-forward [verified]

* Processes, unit states, timers and `current` unchanged (before/after lists identical).
* `.env` hash unchanged, mode still `600`.
* `data/` byte-identical (SHA-256 of all 46 files equal before/after).
* Untracked runtime files kept: `venv/`, `frontend/node_modules`, `frontend/.next`, `frontend/.env.production`.
* Analytics: `server/analytics`, `cyberalertx/config.py` and `cyberalertx/__init__.py`
  are identical between `73257f0` and `d98086f`; `python -m server.analytics ingest --dry-run`
  exits 0 and `analytics.sqlite3` is unchanged.
* Telegram: still held (`ConditionPathExists=/home/cax/cyberalertx/STAGE_D_AUTHORIZED`
  absent), timer disabled. When Stage D is authorized it will run the
  canonical `main` code with the old `/home/cax/cax/venv` — **[assumption]**
  that venv's packages satisfy `main`'s requirements; re-check
  (`pip install -r requirements.txt --dry-run`) before Stage D.

## 4. `/home/cax/cax-redesign`

[verified] 0 commits not on GitHub, clean worktree, no reference from any unit,
drop-in, cron entry or `stagec-tools` script (`~/stagec.vars` now uses
`REPO=/home/cax/cax`). Its branch `feature/editorial-quality-ux` is merged into
`main`.

**Safe to retire**, with separate authorization:
`git -C /home/cax/cax worktree remove /home/cax/cax-redesign` (refuses if
anything is uncommitted), then optionally delete the merged local branch. The
bundle above keeps every ref. Not done in this task.

## 5. Rules from now on

* Develop in `/home/cax/cax` on feature branches; production changes only through new immutable releases.
* Never run tests from inside `/home/cax/cax`: `cyberalertx/__init__.py` loads
  `find_dotenv(usecwd=True)`, i.e. the production `.env`. Use a copy outside it
  with `env -i … PYTHONPATH=<copy>`.
* Before Stage D or any analytics change, keep in mind that those two units run the checkout, not a release.
