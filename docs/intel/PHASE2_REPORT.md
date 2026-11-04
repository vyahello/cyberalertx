# Phase 2 report — intelligence core (3 November 2026)

Worktree `/home/cax/cax-redesign`, branch `redesign/cti-platform`,
**uncommitted**. `/home/cax/cax` unchanged (clean, `73257f0`). Nothing deployed,
published or sent; no production environment variables, Postgres/Supabase or
Telegram touched. **AI calls used: 0.**

✅ verified · 🟡 implemented, not verifiable here · 📋 recommendation

## 1. What existed before this phase
Story clustering (`pipeline/dedup.py`, rules 0/A–E + vetoes), shared fact sheet
(`ai/fact_sheet.py`), protected-token fact check, scorecard, review state with
`/admin/review` and `review` CLI, hybrid relevance filter that dropped junk at
ingest, UA style guide + glossary, benchmark tool. Public "trending" was a
severity sort.

## 2. Reused, not duplicated
Clustering = `pipeline.dedup` (extended in place). Evidence = `ai.fact_sheet`
(extended; `cluster_evidence` is the only merged reading, consumed by the intel
layer). Relevance = `pipeline.relevance` (extended). Source reliability seeded
from `pipeline.credibility`. Admin = existing guard/UI/CSRF. Storage = existing
JSON stores and dual-write. No new service, scheduler, dependency or AI provider.

## 3. Open items from Phase 1
| Item | Result |
|---|---|
| 3.1 UA у/в normalisation | ✅ unconditional «уразлив→вразлив» removed; `apply_vrazlyv_euphony` corrects only unambiguous contexts (vowel-final → вразлив-, consonant/ь-final → уразлив-); pauses, digits, Latin names keep the author's form; 20 regression cases; glossary headword «уразливість» |
| 3.2 Relevance | ✅ `relevance_status` (in_scope / out_of_scope / needs_review) + reason + manual override; generate gate on; public gate behind `CYBERALERTX_HIDE_OUT_OF_SCOPE` (off) |
| 3.3 Review persistence | ✅ verified on a disposable Postgres 16; **two pre-existing bugs fixed** (below) |
| 3.4 Design findings | ✅ decided, not forced: rows ≈150 px is two-line headline + two-line summary; "who it hits" only from data |

## 4. Story counts reconciled
200 = **articles** in `items.json` (not stories) · 180 = stories under
production's stored ingest-time keys (old algorithm) · 169 = after the Phase 1
clustering fix · **170** = now: the only change caused by this phase's rules is
one stored PHP2Shell group splitting into "now exploited" + a linked earlier
"exploit attempts" follow-up (+1). The shadow run's 170 is this count.

## 5. Clustering and confidence (✅ dry-run, nothing rewritten)
- Every merge records `MatchDecision(rule, confidence, reason)`: 30 decisions,
  16 high / 14 medium; low-confidence matches become **links, never merges**
  (1 on the snapshot).
- False positive found and fixed: template headlines about different vendors
  (Zyxel vs SonicWall) no longer merge. Guarded: same CVE against different
  named victims; same ransomware family, different victims; follow-ups ≥ 36 h
  that announce a development become linked stories.
- `independent_sources` collapses identical bodies, same original URL,
  explicit credit to another outlet, repeat reports by one outlet.
- Corrections without data loss: `stories split|merge` → `data/stories/overrides.json`.
- Dry-run vs stored: 9 changed merges (all correct on inspection: «Повітряна
  тривога» ×5, Binance, Chainalysis, GitLab CVE, Cisco SD-WAN, HIMERA, GMO,
  PHP2Shell KEV, LiteLLM), 1 changed split (PHP2Shell, borderline, reversible).

## 6. Fact sheet evidence (✅ by tests; 🟡 no real sheets yet)
New optional fields: `event_type`, `attack_techniques` (MITRE only if the source
names it), `impact`, `mitigations`, `iocs` (verbatim), `contradictions`,
`evidence` (claim/identifier → source, URL, ≤25-word excerpt, primary flag).
Claim status: confirmed / reported / interpretation / unverified /
contradictory / unknown (old claimed/alleged map to reported). `cluster_evidence`
merges a story's sheets: confirmed only by two independent origins or a primary
source; syndicated copies never confirm. Old sheets load. Render prompts (EN/UA)
updated to the new statuses. The snapshot has no fact sheets (they need AI
calls), so evidence is verified by 46 + 23 fixture tests, not on real data.

## 7. Relevance (✅ dry-run)
200 articles: 184 in_scope · 9 out_of_scope · 7 needs_review. Out of scope:
2 DOU digests, 2 eSports, 2 satellite launches, mobilisation policy, a business
acquisition, nuclear-fuel storage — **no security story**. Of the 28 audit
fingerprints (not 29): 24 out_of_scope, 4 needs_review. Nothing deleted or
rewritten. Generate dry-run on the snapshot: "skipped 9 out_of_scope item(s)".

## 8. Intelligence (✅ shadow run on the snapshot)
Importance 0–100 with the requested weights, all deterministic; confidence,
verification and exploitation kept separate; history + diffs; recalculation
skipped on unchanged input hash. Daily Top 10 (Kyiv, 06:00 cutoff, threshold,
one pick per event), Trending (24 h, ≥ 2 signals, article count not an input),
Breaking (R1–R5 evidence rules, alert only on new evidence; never published).
Run as of 2 Nov 18:00 UTC: 170 stories (156 in scope / 8 out / 6 review);
10 picks (Ivanti reported exploitation first; «Повітряна тривога» 4 independent
outlets → partially verified, 3rd); Trending 1; Breaking 0 (no officially
confirmed exploitation in the window). Details: `docs/intel/INTELLIGENCE.md`.

## 9. Persistence (✅ isolated Postgres 16 in a throwaway container)
- **Bug fixed — lost review decisions.** The JSON cache had no cross-process
  lock; a decision made in the API while `generate` wrote was overwritten.
  Reproduced: 50 of 75 concurrent writes lost; with the new `flock`, 0.
- **Bug fixed — silent PG mismatch.** Decisions now use `set_strict`: JSON first,
  PG failure raises `SecondaryWriteError` (CLI exit 2); retry syncs.
- Live: JSONB round-trip of all review fields, both stores updated, survives
  engine restart, PG fallback serves the decision with JSON gone, transitions
  update one row, outage reported + recovery. 12/12 persistence + PG tests pass.
- Not verified: production Supabase (never connected).

## 10. Tests and builds
| Check | Result |
|---|---|
| pytest (with live PG enabled) | ✅ 1208 passed, 1 skipped (locale not installed on host) |
| mypy strict | ✅ 91 files, no issues |
| Lint | not configured in the project (CI deliberately has no lint step) |
| Frontend `tsc` | ✅ |
| `next build` | ✅ 15 static pages |
| Playwright e2e | 31 passed, 1 skipped, 2 failed: `/healthz` (served by nginx→API in production; absent behind bare `next start`) |
| Generate dry-run / review list / Telegram dry-run (fake channel, no token) | ✅ work; nothing sent, no ledger written |
| Data integrity | ✅ `items.json`, `threat_posts.json` md5 unchanged |

## 11. Storage changes
JSON only, new files under `data/intel/` (scores, editions, breaking state,
latest run) and `data/stories/` (overrides, dry-run reports). NewsItem gains
three relevance fields (JSON, backward compatible). **No Postgres migration was
applied**; relevance fields are JSON-only until `005_relevance.sql` (specified in
`STORIES_AND_EVIDENCE.md`) is added.

## 12. Remaining issues
- Fact-sheet evidence and the new scoring have never seen a real fact sheet; the
  first `generate --use-llm` runs will be the first real test.
- Source-reliability axis values are editorial judgements.
- Keyword-based exploitation/supply-chain detection on teasers is a fallback.
- PHP2Shell split and Brotli/PolyShell grouping are borderline (reversible).
- Two e2e `/healthz` checks need the nginx setup.

## 13. Before production deployment (exact steps)
1. Review and commit the branch; deploy from a **separate release directory**,
   not by editing `/home/cax/cax` in place.
2. Keep `CYBERALERTX_REVIEW_MODE=flag` (unset = flag). Leave
   `CYBERALERTX_HIDE_OUT_OF_SCOPE` unset initially.
3. Run `tests/test_pg_review_live.py` once against a **Supabase test project**
   with the same pooler URL style (`CYBERALERTX_TEST_DB_URL`) before `hold`.
4. Run `python -m cyberalertx.tools.stories cluster-report` on the production
   store; review changed merges/splits before trusting the new keys.
5. Run the cost-controlled benchmark (4 stories, 10 calls; see
   `docs/editorial/EDITORIAL_REVIEW_PROCESS.md` §5) at a quiet hour; review UA.
6. `npm ci && npm run build` in the release dir; restart services; then run
   `python -m cyberalertx.tools.intel evaluate` manually (shadow only; no timer).
7. After a week: decide `hold`, the public relevance gate, and whether to add
   the `005_relevance.sql` migration.
