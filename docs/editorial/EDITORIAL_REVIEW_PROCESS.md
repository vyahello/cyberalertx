# Editorial review process

Who: the owner, as native Ukrainian editor (and English reviewer). What: the
briefs the pipeline flags, plus a periodic benchmark. AI review never stands in
for this: no brief is ever described as "approved by an editor" unless
`reviewed_by` was set by a person through the tools below.

## 1. What the pipeline does on its own (per story)

1. **Fact sheet** (1 AI call, cached in `data/fact_sheets.json`): what the
   source actually claims — entities, CVEs, CVSS, versions, dates, numbers,
   exploitation and patch status, claims with attribution, open questions.
2. **EN and UA renders** (1 call each), both written independently from the
   source + fact sheet. UA is never a translation of the EN text.
3. **Deterministic checks** (no AI):
   - *Protected tokens* (`ai/fact_check.py`): a CVE ID, hash, IP or CVSS score
     absent from source and sheet **rejects** the render (rule-based fallback,
     not cached). Versions, numbers, dates, domains and unsourced names are
     recorded as soft findings.
   - *EN ↔ UA consistency*: different CVE sets or key numbers between the two
     editions are recorded.
   - *Language*: banned EN filler; UA Russianisms, calques and term deviations
     (`ai/uk_glossary.py`, sourced from `UKRAINIAN_STYLE_GUIDE.md` and
     `UKRAINIAN_CYBERSECURITY_GLOSSARY.md`).
4. **Scorecard** (`ai/scorecard.py`): internal indicator, weights 25 language /
   25 accuracy / 20 structure / 15 editorial value / 10 attribution / 5 SEO.
   Any hard factual finding sets `needs_review` whatever the score.
5. **Review status**: `auto` (clean) or `pending` (needs a human).

### Evidence gate (Nov 2026)

Every brief is also checked against what its source establishes
(`ai/scorecard.py: _evidence_issues`, using `pipeline/evidence.py`). A brief
that states exploitation, data theft/exposure or an active campaign the
source does not support, or that mentions AI authorship, gets a hard issue
and goes to the queue with the reason "evidence: …", whatever its score.
Hedged wording is not flagged. The gate never rejects or regenerates (no
extra AI calls); the editor decides. Measured on the 4 Nov archive: 7 of 256
editions with a stored source were flagged.

## 2. Review modes (`CYBERALERTX_REVIEW_MODE`) — as implemented

Read from the environment on every call (`ai/review.py`), so a restart is not
needed to change it. **An unrecognised value falls back to `flag`, not `off`.**

| Mode | At generation | `pending` posts | `rejected` posts |
|---|---|---|---|
| `off` | nothing is queued (status `auto`) | — | **visible** |
| `flag` (default) | flagged posts saved as `pending` | **visible**, listed in `/admin/review` | hidden |
| `hold` | flagged posts saved as `pending` | **hidden** from feed, RSS, trending, latest, `/posts/{id}` (404) and Telegram | hidden |

"Hidden" is enforced in one place, the API's render path
(`api/app.py` → `is_publicly_visible`), which the feed, RSS, the detail page and
the Telegram publisher all go through.

Threshold: `CYBERALERTX_REVIEW_THRESHOLD` (default 85). On the 2 Nov archive
snapshot, 85 flags ~0.4% of all posts and ~1–3% of posts that can be checked
against their source; `hold` would still leave 117/121 EN and 162/164 UA posts
of the feed pool visible. Re-run `review score-archive` after the first week of
the new pipeline and adjust.

### Persistence of review decisions (verified 3 Nov 2026)

- A decision rewrites only the review fields (`review_status`, `reviewed_by`,
  `reviewed_at`); the brief text is untouched.
- **JSON** (`data/threat_posts.json`) is authoritative and read first. Writes
  are now serialised across processes with a file lock (`ai/cache.py`). Before
  this fix, a decision made in the API process while `generate` was writing
  could be silently overwritten: reproduced as 50 of 75 concurrent writes lost
  without the lock, 0 lost with it.
- **Postgres** (dual-write) stores the whole post as JSONB, so every review
  field round-trips. Render writes stay shadow writes (a PG failure is logged).
  **Editorial decisions use a strict write**: if PG fails, JSON keeps the
  decision and the editor gets an error (`SecondaryWriteError`; CLI exit code 2)
  instead of a silent mismatch. Repeating the decision syncs PG.
- Verified against a disposable Postgres 16 (`tests/test_pg_review_live.py`,
  run with `CYBERALERTX_TEST_DB_URL`): round-trip, both stores updated,
  survives an engine restart, PG fallback serves the decision when the JSON file
  is gone, transitions update one row, outage reported and retry syncs.
- Not verified: the production Supabase instance itself (never touched).
  Before switching to `hold` in production, run the live test once against a
  Supabase **test** database with the same pooler settings.

Recommended rollout: deploy in `flag`, review the queue for a week, then switch
to `hold`.

## 3. Daily routine (about 10 minutes)

1. Open `/admin/review` (token-locked admin). Each pending brief shows the
   source title and link, both editions, the fact-check findings and the
   scorecard issues.
2. For each: read the UA text aloud (style guide §"reading aloud"), check the
   flagged facts against the source link, then **Approve** or **Reject**.
   Rejecting hides it; regenerate by deleting the cache entry if you want a new
   render (`python -m cyberalertx.tools.delete_post`).
3. CLI equivalents: `python -m cyberalertx.main review list`,
   `review approve FP:ua`, `review reject FP:en`.

## 4. Weekly

- `python -m cyberalertx.main review score-archive` → distribution, flag rate,
  top issue types (`data/editorial/archive_scores.json`). Add any new recurring
  calque to `uk_glossary.py` and the style guide in the same change.
- Read 5 random UA briefs that were *not* flagged. If you would have changed
  them, the checks are too loose: add the pattern.

## 5. Benchmark (before / after) — cost-controlled

`python -m cyberalertx.tools.benchmark --fp … [--fp …]` re-renders chosen
stories through the current pipeline into `data/editorial/benchmark/` (never
served) and writes `REPORT.md` next to the live version.

Cost per story: 1 fact-sheet call + 1 render per locale it appears in
(EN-sourced story = 3 calls, UA-only story = 2 calls). The full 14 renderable
benchmark stories ≈ 38 calls. **Proposed first step: 4 stories, 10 calls**,
one per failure class, so the result is informative before spending more:

| Story | Why | Calls |
|---|---|---|
| `0f81648bf5c6b707` Synology/C3RB3R (EN) | unattributed background, gloss formula | 3 |
| `690940732ff7fbfe` HPE ArubaOS (EN) | speculation in EN, «закрила» calque in UA | 3 |
| `51db3aa02d6f157a` «Повітряна тривога» (UA) | native UA control; one of a merged cluster | 2 |
| `526db699eaf589d6` Node.js (UA) | «закрили вразливості» headline, empty analysis | 2 |

Run it at a quiet hour (the hourly `generate` timer shares the subscription):

    python -m cyberalertx.tools.benchmark --fp 0f81648bf5c6b707 --fp 690940732ff7fbfe \
        --fp 51db3aa02d6f157a --fp 526db699eaf589d6

Approving a benchmark render does **not** publish it. Publishing improved
archive versions is a separate, explicit step (copy the entry into the live
cache with a backup), deliberately not automated.

## 6. Known gaps

- (Resolved 3 Nov 2026) The UA normaliser no longer forces «вразлив-»;
  `apply_vrazlyv_euphony` picks the form from the preceding word.
- Scores bunch in the 90s by design of the weights; treat the score as a
  ranking signal, not a grade.
- 29 UA-only items in the archive are not security news; relevance
  classification (`relevance_status`) now marks such items `out_of_scope`
  (see `docs/intel/STORIES_AND_EVIDENCE.md`). Historical items are classified,
  not deleted or rewritten.
