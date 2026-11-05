# O28: editorial review-state consistency

> **Status: historical record; deployed and re-synced 5 Nov 2026** ([release record](RELEASE_2026-11-05.md)).

4 November 2026. This investigates the Stage C layout:
- **API:** JSON store only (drop-in `stage-c-json-reads.conf`);
- **ingest and generate:** `dual` (JSON plus Postgres);
- **review mode:** `flag`.

Code is on `redesign/cti-platform` (commit `fix(review): preserve decisions across storage backends`), **not deployed**.

## Summary

- **JSON is authoritative.** Every reader of review state uses it whenever it has the post:
  - the API;
  - the generator's cache-hit check;
  - the public visibility gate shared by the site, RSS and Telegram;
  - the new publisher's `EditionSource`.

  So a decision saved by the JSON-only API **is** respected by the dual-mode generator and publisher. A stale Postgres copy cannot override it in normal operation. **The O28 condition as filed (Postgres not mirrored) is not a correctness defect on its own.**
- **Three real edge-case defects** were found and fixed. Each was reproduced first, then mutation-checked:
  1. `generate --refresh` turned a **rejected** edition into a fresh `pending` post, which is visible in `flag` mode. It also reset an **approval**, so in `hold` mode an approved article went back on hold.
  2. If `threat_posts.json` was unreadable, the next write (a render or a decision) **replaced the whole cache** with an almost empty store.
  3. If `threat_posts.json` was unreadable, dual-mode readers fell back to Postgres for every post. With Postgres lagging (O28), that **resurrects a rejected post** as `auto`, which a dual-mode publisher (Stage D) could then publish.
- **Production:** no review decision has ever been made, and JSON and Postgres agree for all 4500 posts. No defect has occurred.

## Code paths

| Concern | Where | Behaviour |
|---|---|---|
| Decision endpoint | `cyberalertx/api/app.py: admin_review_decide` (POST `/admin/review/decide`) | Same-origin and CSRF checked. Decisions: `approve`, `reject` (`ai/review.py: DECISIONS`). `pending`/`auto` come from the generator scorecard (`initial_status`). Audited via `_record`. |
| Decision write | `cyberalertx/ai/review.py: apply_decision` | Copies the post with `review_status`, `reviewed_by`, `reviewed_at`. Uses `set_strict` when the cache has it (dual), otherwise `set`. A missing post raises `KeyError` → 404. Any other error propagates → HTTP 5xx, never a redirect to "done". |
| API store | `_post_cache()` = the generator's cache = `storage/factory.py: build_threat_post_cache` | With the Stage C drop-in: `ThreatPostCache` (JSON) only |
| JSON persistence | `cyberalertx/ai/cache.py: ThreatPostCache` | `set` and `delete` hold an exclusive `fcntl` lock (`threat_posts.json.lock`), reload under the lock, then write atomically (temp file + `os.replace`). Readers take no lock and reload on mtime change. |
| Postgres persistence | `storage/pg/threat_cache.py: PgThreatPostStore.set` | Upsert of the whole payload, review fields included, on `(fingerprint, locale)` |
| Dual write | `storage/dual_write.py: DualWriteThreatPostCache` | `set`: JSON first (authoritative, raises), then Postgres as a shadow (logged). `set_strict`: same, but raises `SecondaryWriteError` if Postgres fails. `delete`: both. `all`: JSON only. |
| Dual read | `DualWriteThreatPostCache.get` | JSON first; Postgres only on a JSON **miss**. **New:** no fallback while the JSON file is unreadable. |
| Generator | `cyberalertx/main.py: cmd_generate` (L225: `cache.get` → cache hit, skip); `ai/generator.py: ContentGenerator.generate` (cache hit returns the cached post; writes only new renders) | A reviewed post is never re-rendered or overwritten on normal runs. Only `--refresh` deletes and re-renders, now decision-aware. |
| Public gate | `api/app.py: _PostService._cached_visible`, `render` (L350), `ai/review.py: is_publicly_visible` | `flag`: hide `rejected`. `hold`: hide `pending` and `rejected`. Shared by the site, RSS, trending, Telegram and the publisher payload. |
| New publisher | `publish/orchestrator.py: EditionSource.review_status` / `payload` | Through the same cache and gate |

## Scenarios

| Situation | Outcome |
|---|---|
| API approves in JSON, generator reads it in dual mode | JSON hit → `approved`; no re-render, no AI call **[tested]** |
| Postgres holds an older or conflicting decision | Ignored while JSON has the post **[tested]** |
| JSON and Postgres conflict | JSON wins (read order) |
| JSON missing (no file) | Empty store; dual falls back to Postgres (legitimate: fresh instance) |
| JSON malformed | Before: reads missed, dual served stale Postgres, the next write wiped the file. **Now:** reads miss, dual fails closed, writes refuse **[tested]** |
| Two decisions at once, or decisions during a generate run | Serialized by the lock; nothing lost **[tested: 3 OS processes, 120 decisions plus 80 renders]** |
| Rejected post published because of stale Postgres | Only through the malformed-JSON fallback (fixed) or `--refresh` (fixed) |
| Approved article wrongly on hold | Only through `--refresh` (fixed) |

## Production observations (read-only, 4 Nov 2026)

- `data/admin_audit.jsonl` does not exist, so no admin action has ever been recorded.
- JSON: 4500 posts, all `auto`, 0 with `reviewed_at`.
- Postgres `threat_posts`: 4500 rows, all `auto`.
- The two stores hold the same keys, and 0 `review_status` mismatches.
- Nothing was modified.

## Changes (uncommitted)

| File | Change |
|---|---|
| `cyberalertx/ai/review.py` | `keep_on_refresh(post)` (rejected → keep) and `carry_review_decision(...)` (carry an approval onto the re-rendered text, strict under dual-write) |
| `cyberalertx/main.py` | `generate --refresh`: skip deleting rejected editions (they cache-hit: no AI call); carry approvals after the render; restore an approved post if the re-render fails |
| `cyberalertx/ai/cache.py` | `_unreadable` flag and `unreadable` property; `_flush` refuses while the file is unreadable; the flag clears when the file parses again |
| `cyberalertx/storage/dual_write.py` | `get`: no Postgres fallback while the JSON file is unreadable |
| `tests/test_publication.py` | `test_bot_token_never_reaches_the_logs` sets the `httpx` log level itself. It failed whenever an earlier test had imported `cyberalertx.main`, which is pre-existing and reproduced on HEAD. |
| `tests/test_o28_review_consistency.py` (new) | 13 tests: real JSON files, a real Postgres schema, the real API endpoint, the real `generate --refresh` command, and OS processes |

There are no new AI calls. A refresh of a rejected edition now makes **one fewer** call.

## Tests

| Run | Result |
|---|---|
| O28 suite (PG 17, disposable) | **13 passed**. Items 1–9 of the brief, plus the stale-fallback case. |
| Mutation: revert the `main.py` refresh handling | 2 refresh tests fail |
| Mutation: revert the `cache.py` write guard | the unreadable-file test fails |
| Mutation: revert the `dual_write.py` guard | the stale-fallback test fails |
| Full suite, no Postgres | 1377 passed, 13 skipped |
| Full suite, live PG 17 | **1397 passed, 1 skipped** |
| Full suite, live PG 17, reverse file order | 1396 passed, 1 skipped (before the last test was added) |
| mypy (project scope `cyberalertx`) | clean, 119 files |

Unaffected:
- **Ingest and localization:** e2e pipeline, normalize and relevance tests pass.
- **Generation:** generator and journalist tests pass.
- **Feed performance:** the JSON read path is unchanged, apart from one property on a miss in dual mode.
- **Telegram and Threads:** the publication and Threads suites pass.
- **Feature flags:** the release-readiness defaults test passes.

## Remaining risks

1. **Postgres lags JSON for any decision made while the API is JSON-only.** Nothing reads Postgres while JSON has the post. Re-sync before reverting the O27 hotfix, before `hold` mode, and before any Postgres-only consumer: run `python -m cyberalertx.tools.import_ai_cache_to_postgres --dry-run`, then the real run. It upserts every JSON post into Postgres, review fields included. Verify afterwards: 0 `review_status` mismatches, using the comparison in this report.
2. **Readers while JSON is unreadable:** the feed is empty and cards miss. A detail URL may serve a rule-based summary built from source data, which is the existing fallback for any uncached item; it never serves the rejected AI text. Repair: restore `threat_posts.json` from a backup. Writes refuse until then, so nothing is lost.
3. `generate --refresh` UA renders that fail validation are still deleted and not replaced. That's existing behaviour, unrelated to review state.

## Release

Not urgent. Production has no review decisions, `--refresh` isn't scheduled (the timer runs `generate --limit 1 --use-llm`), and the JSON file is healthy. Ship these fixes in the **same release as the O27 fix**, through the normal release procedure (new release directory, C7-style switch).

## Recommended next step for O27

- **Fix the read path, not the deployment.** `DualWriteThreatPostCache.get` makes a Supabase round-trip on every JSON miss. On `/posts` that means every item and locale without a cached post, 3–5 s per request. JSON is authoritative and complete for every post dual-write produced, so:
  - either drop the Postgres fallback from the request path (keep it for ops tooling via an explicit method);
  - or cache negative lookups per process with a short TTL.
- **Then:**
  1. Run the re-sync (risk 1).
  2. Verify that a UA 40-post feed answers in under 0.5 s in `dual` mode on a staging copy.
  3. Deploy as a new release.
  4. Remove the API drop-in with `c8_api_json_reads.sh revert`.

## Update — 5 Nov 2026 (branch `feature/o27-api-latency`, not deployed)

* **O27 read path fixed** as recommended above, without dropping the fallback:
  the dual cache answers JSON misses from an in-memory Postgres key index plus
  one batch load of the posts only Postgres has; no per-item query remains
  (O27_API_READ_PATH_REPORT.md). The fail-closed rule for an unreadable JSON
  file is checked first, unchanged.
* **The re-sync tool is ready, not run.**
  * `tools.import_ai_cache_to_postgres` now computes a plan against Postgres
    (read-only with `--dry-run`): inserts, updates, review-status transitions,
    and Postgres-only rows (reported, never deleted).
  * The real run writes only rows that differ. It re-reads Postgres and fails
    unless every JSON entry matches. It refuses an unreadable JSON file, and it
    never writes JSON.
  * `--report` writes the plan without content.
  * Tests: `tests/test_import_ai_cache_live.py`, 6 live-PostgreSQL tests, all passing.
  * Production steps: **O28_RECONCILIATION_RUNBOOK.md**.
* The order for the release that reverts the O27 hotfix is unchanged:
  1. deploy;
  2. re-sync (runbook);
  3. `c8_api_json_reads.sh revert`.
