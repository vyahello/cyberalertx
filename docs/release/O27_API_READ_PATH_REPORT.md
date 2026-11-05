# O27: API read path in `dual` mode

> **Status: historical record; deployed 5 Nov 2026** in `b509775` ([release record](RELEASE_2026-11-05.md)). Current behaviour: [OPERATIONS.md §5](../operations/OPERATIONS.md).

Branch `feature/o27-api-latency` (from `main` `d98086f`). **Not deployed.** The
production API still runs with the Stage C JSON-reads drop-in
(`stage-c-json-reads.conf`), which stays in place until the release with this
fix is live and the O28 re-sync is done.

Labels: **[production]** = observed on the production host;
**[tested]** = isolated copy of production data and a throwaway PostgreSQL;
**[simulated]** = with an artificial network delay; **[assumption]** = not
proven here.

## 1. Cause

[production, 4 Nov] In `dual` mode a 40-post UA feed took ~5.2 s and EN ~3.9 s. The
frontend aborts at 5 s, so `/ua` and some topic pages rendered empty.

[tested, code reading] The cause was `DualWriteThreatPostCache.get` in `storage/dual_write.py`:

1. `/posts` walks the whole filtered store, one item at a time. For each item
   it asks the cache up to three times: the dedup probe, `render_if_cached`, and
   the generator's own `get`.
2. JSON is read first. Every JSON **miss** then ran one Postgres SELECT,
   sequentially. A miss means an item with no render in that locale, which is
   normal for most of the store.
3. Each SELECT costs four round trips (BEGIN, pool pre-ping, SELECT, ROLLBACK).

This is an N+1 with no batching and no negative cache. It predates Stage C
(the old code is identical) and was exposed by the new frontend's larger pools
(40–200 posts instead of 20).

## 2. Fix

`storage/dual_write.py`, `storage/pg/threat_cache.py`, `ai/cache.py`, `storage/factory.py`:

* **Key index.** The dual cache keeps an in-memory set of the
  `(fingerprint, locale)` keys Postgres holds. It is loaded with one keys-only
  SELECT. In the same load, the posts Postgres has but JSON lacks are fetched
  with **one batch query** (`get_many`, 500 keys per statement).
* **Read path.** JSON hit → returned (unchanged). Unreadable JSON → miss, fail
  closed (O28, unchanged, checked first). Key not in the index → miss, **no
  query**. Key only in Postgres → served from the batch. Indexed but not in the
  batch (JSON lost it after the load) → one lookup, memoized until the next
  load.
* **Loads never run on a request thread.** A background thread loads the index:
  * at start-up (warm-up when the cache is built);
  * then at most once per `CYBERALERTX_PG_INDEX_TTL_SECONDS` (default 60),
    started by the first read after expiry. That read is served from the old
    index (stale-while-revalidate).

  Only while the very first load is still running does a read wait, for at
  most 2 s. No lock is held during I/O. A hanging or unreachable database
  therefore cannot stall the feed or the writers. A failed load keeps the
  previous index and retries after 10 s; until a first load succeeds, misses
  stay misses (as before, when the per-item read failed).
* **Own writes.** `set` / `set_strict` / `delete` update the index immediately.
  Writes made while a load is running are re-applied on top of its snapshot, so
  a delete is never undone by a stale snapshot.
* **Evidence memoized.** `pipeline/evidence.assess` is pure in (title, excerpt,
  byline, category) and runs twice per rendered item. An LRU cache (8192) takes
  it from 1.4 ms to 1 µs per item. This removes the cost the stricter evidence
  checks (Part C) would otherwise add to every feed request.
* **Diagnostics.** `index_stats` (loads, failures, keys, PG-only). One INFO line
  per process: `PG key index loaded: N keys, P only in PG, ms=…`.

Unchanged: JSON stays authoritative for reads and writes; `shadow_stats`;
`all()`; JSON-only mode; the generator, publisher and admin code paths.

## 3. Method [tested + simulated]

| Item | Setup |
|---|---|
| Data | copy of production `data/` (5 Nov: 200 items, 4,520 rendered editions) in a scratch directory; secrets-free subset only |
| Postgres | throwaway `postgres:17-alpine` container on 127.0.0.1, restored from the Stage C quiesced Supabase dump (4,498 `threat_posts`, 2,811 `news_items`, migrations 001–004), `log_statement=all` for query counting |
| Network | TCP proxy adding 35 ms each way, **72 ms measured round trip** (≈ Supabase from this host) [simulated] |
| Servers | `python -m cyberalertx.main serve` from an isolated copy, `env -i`, explicit `PYTHONPATH`, no `.env` on the search path; old = `d98086f`, new = this branch |
| Requests | `/posts?language={en,ua}&limit={20,40,100,120,200}&cached_only=1` (20/40 = home pools, 120 = overview, 200 = topic pages), `/posts/trending`, `/posts/latest`, `/posts/{id}`; 30 warm repetitions (5 for the old code), 3 cold starts, 8 concurrent clients × 5 |
| Queries | counted from the Postgres log between markers |

The old code in this simulation is about 2× slower than the production
measurement (10.9 s vs ~5.2 s for UA40). The proxy delays every packet, so the
absolute numbers are pessimistic; the query counts are exact.

## 4. Results

### Latency, warm (ms; p50 / p95 / p99)

| Request | JSON backend (new code) | dual, **new code** | dual, old code (n=5) |
|---|---|---|---|
| UA 20 | 30 / 34 / 42 | 31 / 53 / 56 | 8,191 / 8,220 / 8,223 |
| **UA 40** | 57 / 77 / 81 | **58 / 77 / 81** | 10,863 / 10,893 / 10,895 |
| UA 100 | 140 / 164 / 182 | 141 / 158 / 159 | 13,735 / 13,787 / 13,796 |
| UA 120 (overview) | 167 / 191 / 193 | 171 / 198 / 207 | 13,791 / 13,864 / 13,878 |
| UA 200 (topic) | 215 / 233 / 244 | 215 / 241 / 255 | 13,883 / 13,898 / 13,899 |
| EN 20 | 32 / 50 / 55 | 30 / 51 / 68 | 7,330 / 7,342 / 7,343 |
| **EN 40** | 59 / 83 / 107 | **59 / 82 / 87** | 10,039 / 10,063 / 10,065 |
| EN 100 | 154 / 174 / 188 | 151 / 167 / 172 | 10,231 / 10,267 / 10,270 |
| EN 200 (113 items exist) | 176 / 191 / 193 | 174 / 209 / 225 | 10,274 / 10,290 / 10,292 |
| trending UA / EN | 43 / 42 | 43 / 42 | 7,439 / 7,434 |
| latest | 21 | 20 | 1,518 |
| `/posts/{id}` | 3 | 2–3 | 4 |

### Postgres queries per request

| | dual, old code | dual, new code |
|---|---|---|
| UA 40 / EN 40 / UA 200 | 37 / 34 / 46 per-key SELECTs (148 / 149 / 184 round trips) | **0 / 0 / 0** |
| 8 × 5 concurrent UA 40 | 1,480 SELECTs | 0 |
| per process | — | 1 keys SELECT + ≤ 1 batch SELECT at start, then 1 keys SELECT per 60 s (+ batch if PG-only keys exist) |

### Cold start (first request after process start, UA 40 / EN 40)

| | p50 | queries |
|---|---|---|
| JSON | 120 / 119 ms | 0 |
| dual, new code, request immediately after `/healthz` | 1,206 / 1,176 ms | index load (1 keys SELECT; engine connect ≈ 13 round trips) — the request waited for the first load |
| dual, new code, request 4 s after start | 150 / 61 ms | 0 (index already warm) |
| dual, old code | 11,786 / 10,927 ms | 37 / 34 per-key SELECTs |

In production a cold request after a restart happens once per process. It
stays under the frontend's 5 s abort even when it races the warm-up.

### Concurrency (8 clients × 5 UA 40 requests, 2-core host)

| | p50 / p95 / p99 | wall |
|---|---|---|
| JSON | 525 / 730 / 799 ms | 2.7 s |
| dual, new code | 450 / 685 / 733 ms | 2.5 s |
| dual, old code | 11,503 / 12,245 / 12,459 ms | 58.9 s |

CPU-bound rendering, the same in both backends.

## 5. Correctness [tested]

* **Same answers as JSON.** Full data, final code: IDs and order are identical
  between the JSON backend and new-code dual for every feed size, trending,
  latest and five article pages, in both languages, and all 23 response
  bodies are byte-identical (sorted JSON). Earlier runs differed only in
  `evidence`, because they ran the evidence code from before Part C.
* **Postgres-only posts.** Scenario: 15 UA + 15 EN feed renders removed from
  JSON only.
  * New-code dual served all 30 from the batch load, with 0 queries per request.
  * Old-code dual served the same IDs in the same order, with identical bodies
    apart from the evidence-derived fields (old evidence code), at 325 per-key
    SELECTs and 25 s per UA 40 request.
  * The JSON backend, as expected, served none of them.
* **Write then read** (a second process writing through the dual wrapper to the
  same files and database):
  * deleted → hidden at once, and still hidden after an index reload (no
    resurrection);
  * re-written → visible at once, with the modified text served at once;
  * written **only** to Postgres by a peer → visible after 1.0 s;
  * deleted only in Postgres → hidden after 5.6 s, with TTL 5 s under steady
    reads. Bound: TTL + one load.
  * A JSON rejection with Postgres still `auto` stays hidden.
* **Restart.** Same IDs and bodies before and after a restart.
* **Failure.** Unit tests cover:
  * a hanging database: the first read returns within the 2 s bound, and
    writers don't wait;
  * a failed load: miss plus backoff, the previous index kept;
  * concurrent readers: one load for 8 threads;
  * a delete during a load: not undone.
* **Tests.** `tests/test_o27_pg_index.py` (17); the full suite (1,458 passed
  without Postgres, 1,484 (1 skipped: no non-C locale) with the live-Postgres tests enabled); mypy clean.

## 6. Acceptance

| Criterion | Result |
|---|---|
| 40-post UA < 500 ms in `dual` | **58 ms** p50, 81 ms p99 warm [simulated 72 ms RTT]; first request after restart ≤ 1.3 s |
| EN < 500 ms | **59 ms** p50, 87 ms p99 |
| IDs, order, content identical to JSON | yes (full data, all feed sizes, both languages) |
| ≤ 1 batch fallback query per request | **0** per request; the batch runs at most once per index load, off the request path |
| No N+1 | 0 per-item queries |
| Correct after writes and restarts | yes (§5) |

**Met on the isolated copy.** Production confirmation needs the release; see §8.

## 7. Risks and limits

* **Peer writes only to Postgres** become visible within TTL + one load (≈ 61 s
  by default). Nothing in production writes only to Postgres today; every writer
  goes through the dual wrapper, which writes JSON first. Code reading: the
  only direct `PgThreatPostStore()` writer is the O28 import tool itself;
  `compare_storage` only reads.
* **Memory:** 4,520 keys ≈ 1 MB per API process.
* **The engine has no `connect_timeout`.** The read path no longer depends on
  it, but writers in `run`/`generate` still wait for TCP timeouts when Postgres
  is unreachable (unchanged behaviour). Adding
  `connect_args={"connect_timeout": 10}` is a separate, small hardening.
* **The JSON-reads drop-in stays** until deployment, the re-sync and its removal
  are authorized.

## 8. Rollout (not executed)

1. Release this branch with the Stage C procedure (new release directory, verify, switch `current`).
2. O28 re-sync: O28_RECONCILIATION_RUNBOOK.md (dry run, run, verify).
3. Remove the drop-in: `c8_api_json_reads.sh revert`. Watch the
   `PG key index loaded` line and `/ua` timings; the frontend journal must show
   no "This operation was aborted".
4. Rollback of step 3: `sudo bash $OPS_TOOLS/c8_api_json_reads.sh apply` (re-applies the drop-in). Rollback
   of step 1: `release_switch.sh <previous release>` (then `release_rollback.sh`).
