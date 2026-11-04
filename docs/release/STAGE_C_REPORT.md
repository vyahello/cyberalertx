# Stage C deployment report: 4 November 2026 (EET)

**Result:** the redesigned CyberAlertX website and backend are live at
https://cyberalertx.com. They run from a fresh, verified release of commit
`4fa7a63`. Production data is preserved. Telegram and Threads publishing stay
off until their own stages.

## Release

| | |
|---|---|
| Commit | `4fa7a63a982b8a79b5c511fcc56d1d53c2f85c14`, tree `fea7201c…` (identical to RC3's tree) |
| Release | `/home/cax/cyberalertx/releases/20261104-1626-4fa7a63`, with `current` → it |
| Provenance | All 352 files match the commit's git blob hashes; 0 extra files (before and after the build). `RELEASE` records archive `3f341613…`, `requirements.lock` `88205da4…`, `package-lock.json` `1ee37afd…`. |
| Dependencies | venv == `requirements.lock` (pip check OK; pip-audit: none). Next.js **15.5.29** (1 copy), sharp **0.35.5** (2 copies, same version). npm audit 0 (full and runtime). The GHSA-pc58 fix is present. |
| Tests in the release | pytest 1372 passed, 5 skipped; mypy clean (119 files); smoke: pages 200, 30/30 cards, `/_next/image` 404 |
| Data | `data` → `/home/cax/cax/data` (live). No rehearsal path; the prerender used a staging API over a data snapshot. |
| Old application | `/home/cax/cax` untouched (`main` @ `73257f0`, clean), with its own venv and build |

## Timeline

| Time | Step | Result |
|---|---|---|
| 16:25 | C0 preflight | Clean. Baseline: last ingest 16:11, generate 16:01, Telegram 16:15 (sent 2), ledger 3054 lines, PG 2810 / 4498, migrations 001–004. |
| 16:26–16:30 | C1 release build | Verified (above). The first prerender ran against an occupied staging port and produced empty pages → rebuilt against a verified-free port (:8190). |
| 16:30–16:31 | C3 backups + restore rehearsal | Verified (below). Local PG 17: 005 in 0.37 s, idempotent, data unchanged; live suites 7/7. |
| 16:31 | C4 writer inventory | Matches the runbook table (refined after code review: API and frontend write only `feedback.jsonl` and `quality_metrics.json`) |
| 16:55:00–16:55:05 | **C5 quiesce** (`c5_quiesce.sh`, rev. 4) | Timers disabled first. Ingest stopped in a verified idle window (next cycle 968 s away, CPU 0), no cycle interrupted. Telegram hold loaded. |
| 16:55:27–16:57:28 | Quiet check | `QUIET`: no unexpected `data/` or PG change in 120 s |
| 16:57–16:59 | Final rollback backup | Restored and compared: identical (floats pinned, O30) |
| **16:59:11** | **C6 migration 005** | Applied once, 0.92 s. Details below. |
| 16:59 | C7 non-sudo steps | 4 flags appended to `.env` (append-only, 600); data link → live; `current` → release |
| **17:14:55–17:14:59** | **C7 activation** (`c7_activate.sh`) | 4 units switched (paths only); API/site healthy; new frontend confirmed; `run` started from the release |
| 17:15:05 | First ingest from the new code | `cycle complete`, no relevance warning |
| 17:16–17:27 | C8 verification | All checks passed except the UA feeds (O27) |
| **17:28** | Hotfix O27 (`c8_api_json_reads.sh apply`) | API on the JSON store only; UA pages repopulated |
| **17:34–17:35:53** | **C9** (`c9_resume_generate.sh`) | generate timer enabled; first run succeeded (2 brief calls, 0 fact-sheet calls, 1 new EN+UA post) |

## Backups (mode 700; secret and data files 600)

`/home/cax/backups/stagec-20261104-1626-4fa7a63/`. Full checksums are in `SHA256SUMS` there.

| File | sha256 (first 16) | Verification |
|---|---|---|
| `prod-data-full.tgz` | `357b5a831c104b8b` | gzip OK; 48 entries = live |
| `env.bak` | `2cd16188525a5764` | byte-identical to the pre-change `.env` |
| `supabase-full.dump` | `4ab10829596c28bc` | restored to PG 17; counts and schema match |
| `prod-data-quiesced.tgz` (**rollback point**) | `dd585bf8e8e2b8d2` | gzip OK; key files byte-identical |
| `supabase-quiesced.dump` (**rollback point**) | `5bd4c51f5a579691` | restored; `news_items` / `threat_posts` md5 identical to production |
| `quiesced-files/{items.json, threat_posts.json, telegram_published.jsonl}` | `f4beef67…`, `2acdb140…`, `6dd63a4b…` | byte-identical at quiesce |
| 9 unit files, `frontend.env.production` | in `SHA256SUMS` | — |

The earlier backup `/home/cax/backups/stagec-20261104-1613-4fa7a63/` is kept and intact.

## Migration 005 (production Supabase)

- **Target:** the database in production `.env` (identity hash `c6e332cf…`); PG 17.6, session pooler.
- **Before:** migrations 001–004; 2811 / 4498 rows; 40 columns, 16 indexes, 4 triggers.
- **After:**
  - migrations 001–005;
  - `relevance_status varchar(16)`, `relevance_reason text`, `relevance_override varchar(16)`, all `NOT NULL DEFAULT ''`;
  - 43 columns, 16 indexes, 4 triggers;
  - all 2811 rows at the defaults;
  - the existing-data md5 `255ee79f…` equals the pre-migration backup, and `threat_posts` md5 is unchanged;
  - an application-style query works;
  - a re-run reports "No pending migrations".
- **Afterwards:** the new ingest stamped relevance on 29 rows (27 `in_scope`, 2 `needs_review`).

## Services and systemd

| Unit | Before | Now |
|---|---|---|
| `cyberalertx-api` | `/home/cax/cax` | release; drop-in `stage-c-json-reads.conf` (O27) |
| `cyberalertx-frontend` | `/home/cax/cax/frontend` (Next 15.5.18) | release `frontend` (Next 15.5.29) |
| `cyberalertx-run` | `/home/cax/cax`, enabled | release, enabled |
| `cyberalertx-generate(.timer)` | `/home/cax/cax`, timer enabled | release; timer re-enabled 17:34 |
| `cyberalertx-telegram(.timer)` | legacy, timer enabled | **unchanged unit, timer disabled + hold drop-in** (`ConditionPathExists=/home/cax/cyberalertx/STAGE_D_AUTHORIZED`, marker absent) |
| `cyberalertx-analytics(.timer)` | `/home/cax/cax` | unchanged (code identical; `--dry-run` OK) |

Unit edits are paths only: 2 lines each for api/run/generate, 1 for frontend; 0 for telegram and analytics.

## Effective flags (resolved by the release code from `.env`)

| Flag | Value |
|---|---|
| fact sheet | **off** |
| Threads publishing | off |
| Telegram photo attachments | off |
| hide out of scope | off |
| review mode | `flag` (variable unset, as before) |
| top-10 slot | off |
| breaking updates | off |
| image provider | none |

`.env` changes: 4 lines appended; no existing line changed; mode 600.

## Verification (C8)

- **API:**
  - `/healthz` 200 locally and publicly;
  - feeds in 0.06–0.22 s after the hotfix (were 3.9–5.2 s);
  - same posts as `dual` (EN 105, UA 150).
- **Website:**
  - `/` → `/en`; `/en` and `/ua` 200 with the new design; `/_next/image` 404;
  - browser at 1440 and 390 px: no overflow, no broken images, no HTTP errors; search (`?q=`) and the exploited filter work;
  - visual check done on the desktop and mobile screenshots.
- **Admin:** 401 without login. With login, all 11 pages return 200 locally and through nginx: system, review, media, publishing, threads, stories, intel, usage, sources, feedback, metrics.
- **EN/UA articles:**
  - 20 sampled pre-cutover IDs × 2 locales: 40/40 pages 200 with the correct `html lang` and `og:locale`;
  - canonical URLs, source attribution links, and localized titles all correct.
- **Cards and media:**
  - 5 variants × png/webp/avif × 2 locales: 30/30 return 200 with the correct type;
  - `og:image` points at the card and resolves.
- **Feeds:** `/en/feed.xml` and `/ua/feed.xml` 40 items each; sitemap 265 URLs; robots and topic pages 200.
- **Data integrity:**
  - ledger (3054 lines) byte-identical to the quiesced copy;
  - of 198 items present before and after, 0 had their title, source, URL, dates, language or translations changed;
  - 2 oldest items left through the normal 200-item window (same rule in the old code);
  - the first generate added 2 posts and changed 0 existing posts; JSON and PG both hold 4500 posts.
- **Logs:** 0 errors in all CyberAlertX units since 17:14.
- **Workers:**
  - `run` cycles every 30 min from the release;
  - `generate` hourly (first run succeeded; skipped 9 out-of-scope items, O31);
  - analytics unchanged;
  - no publish timer exists.

## Telegram and Threads

- **Telegram:** no automated posts since 16:55 (by design, O32). The legacy publisher is held, and the new publisher has no unit or timer. No messages were sent. Private-channel testing is still to do (C10). **The new delivery paths are not proven against the real Telegram API.**
- **Threads:** not connected, publishing off, no credentials added. **Unverified.**
- **Fact sheet:** disabled, so **not operationally validated.**

## Remaining issues

O27–O32 (see OPEN_ISSUES.md). The two to act on:
1. **O27:** the code fix for the slow `dual` read path, so the API hotfix can be reverted.
2. **O32:** Telegram channels are silent until Stage D.

## Rollback readiness

- **Site back to the old app:** `sudo bash /home/cax/stagec-tools/c7_rollback.sh` (tested). It restores the 4 unit files from the backup, restarts the old API and frontend, and leaves all writers off. The API drop-in may stay; the old code supports JSON.
- **Before re-enabling legacy writers:** read C14 and O19. The old ingest drops relevance fields from `items.json`, and old code has no review gate.
- **Database:** migration 005 can stay, because old code ignores the columns. Otherwise use 006, or restore `supabase-quiesced.dump`.
- **Data:** never overwrite `data/` without an explicit decision. The rollback point is `prod-data-quiesced.tgz`.
