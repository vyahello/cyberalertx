# Stories, evidence and relevance

How CyberAlertX groups articles into stories, counts independent sources,
lets an editor correct both, and records what is in scope. Code:
`cyberalertx/pipeline/dedup.py`, `cyberalertx/pipeline/relevance.py`,
`cyberalertx/ai/fact_sheet.py`, CLI `cyberalertx/tools/stories.py`.

## 1. Clustering audit (November 2026 snapshot, 200 articles)

| Evidence | How the algorithm uses it | Verdict |
|---|---|---|
| CVE ids | VETO 1 (disjoint sets never merge), RULE A (identical sets), RULE B (overlap ≥ 0.5 + entity + title support). Scanned in title and whole body. | Strongest signal. Two risks: one CVE exploited against different victims (now a low link, see below), and a body truncated before its second CVE, which makes a two-CVE article look single-CVE (the Brotli/Adobe cluster below). |
| Product / version | Products enter as headline names and distinctive tokens; versions are not compared. | Correct for clustering: a different version range of the same CVE is the same story. The difference is recorded by `cluster_evidence` as a contradiction. |
| Malware family, threat actor, campaign | Only as names (RULE E) or distinctive tokens (RULE C). Category nouns ("ransomware", "malware") are stripped. | Risk found: a rare family/actor name shared by two victims' incidents could merge under RULE E. Now a low link. |
| Organization / victim | Names in the headline; RULE E vulnerability-family guard. | Risk found: incident headlines naming different victims. Guarded for CVE rules and RULE E. |
| Description similarity | RULE C (distinctive-token Jaccard + shared entity) and RULE D (same counted quantity). | Demonstrated false positive: "Critical flaw in Zyxel firewalls lets attackers run code" / "… SonicWall firewalls …" merged at 0.50. Fixed: RULE C no longer fires when both headlines name subjects and neither's names occur in the other headline. |
| Time proximity | 5-day window; RULE E 48 h. | Fine. Added: a development headline ≥ 36 h after the first report is a follow-up. |
| Syndication | RULE 0 (identical body digest). | Merges correctly, but corroboration counted every copy. Now `independent_sources`. |

Strengths kept: anchor-based assignment (no chaining), the CVE veto, digest
veto, Ukrainian stemming. Every merge in the snapshot was re-checked under
the new code: no existing merge changed except one follow-up (below).

### Match decisions and confidence

`match_story(a, b) -> MatchDecision | None` returns the rule, a confidence and
a reason; `same_story` (still pure and symmetric) is "a decision that merges".
`StoryCluster.decisions` holds one decision per joined member;
`StoryCluster.links` holds low-confidence relations to other stories.

| Confidence | Rules |
|---|---|
| high | same URL; RULE 0 identical body; RULE A with headline agreement; RULE C strong band; manual merge |
| medium | RULE A without shared wording (e.g. a KEV entry); RULE B; RULE C weak band; RULE D; RULE E |
| low (never merges) | `same_cve_different_incident`: both headlines report a victim incident and each names a subject the other lacks · `same_threat_different_victim`: RULE E matched on a family/gang/actor name ("Akira ransomware", "Qilin gang") with different victims · `follow_up`: the later headline announces a development (`now exploited`, arrest, sentenced, decryptor, "another", "two more" …), the earlier does not, ≥ 36 h apart |

## 2. Dry-run report

`python -m cyberalertx.tools.stories cluster-report` compares the stored
`story_key`s in `data/items.json` with a fresh batch clustering and writes
`data/stories/cluster_report.json`. Nothing else changes. Stored keys were
assigned incrementally at ingest by older rules, so most differences are the
previous phase's clustering fix, not this one.

Snapshot result: 180 stored stories (14 multi-article) → 170 recomputed (22).
9 changed merges, 1 changed split, 1 low-confidence link.

* Merges (all correct on inspection): the «Повітряна тривога» hack across 5
  UA outlets (RULE E); Binance withdrawals dev.ua/ain.ua; Chainalysis BC/THN;
  GitLab CVE-2026-97229 THN pair; Cisco SD-WAN KeyDrift BC/THN; HIMERA
  satellite dev.ua/itc.ua (off-topic, but a true duplicate); GMO BC/THN;
  PHP2Shell KEV entry + THN "CISA confirms"; LiteLLM BC/THN.
* Split: the stored PHP2Shell group (CISA KEV + 3 articles) becomes three
  stories: the KEV entry joins THN's "CISA Confirms Active Exploitation"
  (RULE B), BC "PHP2Shell … now successfully exploited" + THN "Hits
  Government Entity" stay together (RULE A), and THN "Exploit Attempts Hit
  Millions" (23 Oct, three days earlier) is a `follow_up` link. Verdict:
  defensible — attempts vs confirmed success — but borderline; overrule with
  `stories merge` if the desk prefers one story.
* Borderline, unchanged: four THN articles about Brotli CVE-2026-111497
  (Node2Shell PoC → Bun/Python impact → PHP Windows rebuild → "Adobe Commerce
  PolyShell attacks … as Brotli exploit traffic emerges"). The last headline
  covers two flaws, but its stored body is cut before the second CVE, so
  RULE A sees an identical set. One story for the reader is acceptable; a
  split is one `stories split` away.

## 3. Source independence

`independent_sources(cluster) -> list[str]` (and `source_origins(members)`
for `{fingerprint: origin}`) collapses: identical bodies; identical
normalised URLs or a body citing another member's URL; explicit attribution
to a known outlet ("according to BleepingComputer", "as first reported by The
Record", «повідомляє dev.ua», «за даними …» — list in `KNOWN_OUTLETS`); and
one outlet reporting twice. Attribution to a vendor ("according to
Microsoft") is not syndication. Count corroboration as
`len(independent_sources(c))`, not `len(c.sources)`.

## 4. Manual corrections (records are never changed)

`data/stories/overrides.json`:

```json
{"version": 1,
 "split": [{"fingerprint": "9d0cfa945b257eb4", "reason": "…", "at": "…"}],
 "merge": [{"fingerprints": ["A", "B"], "reason": "…", "at": "…"}]}
```

* `split X`: X stands alone; no rule can join its story.
* `merge [A, B]`: B joins A's story whatever the rules say (transitive).
  A merge outranks a split.

Applied by `cluster_items(..., overrides=)`, `assign_story_keys`,
`assign_incremental(..., overrides=)` (the pipeline loads the file each
cycle), and `apply_story_overrides(items, ov)` for stored items at read time
(in memory: re-keys and re-points `duplicate_of`, never writes). Commands:

    python -m cyberalertx.tools.stories split FP --reason "…"
    python -m cyberalertx.tools.stories merge FP_A FP_B --reason "…"

## 5. Fact sheet v2 (extends, does not duplicate)

New optional fields on `FactSheet` (old cached sheets load unchanged):
`event_type`, `attack_techniques` (description + `mitre_id` only if printed),
`impact`, `mitigations`, `iocs` (type/value verbatim), `contradictions`
(statement + sources), `evidence` (claim, source, url, verbatim excerpt ≤ 25
words, `primary`, status). Claim vocabulary: `confirmed`, `reported`,
`interpretation`, `unverified`, `contradictory`, `unknown`; legacy `claimed`
→ `reported`, `alleged` → `unverified`. Sanitisation drops IOCs, MITRE ids
and excerpts that are not verbatim in the source; evidence source/URL default
to the article. One sheet per fingerprint still feeds both EN and UA renders.

`cluster_evidence(members, sheets) -> ClusterEvidence` merges a story's
sheets: a fact is `confirmed` only with two independent origins or a primary
source stating it as confirmed; syndicated copies never confirm each other.
Exploitation/patch disagreements and differing affected versions become
contradictions.

Note for `ai/templates.py` (not changed here): the render prompts still name
the statuses "claimed"/"alleged" (EN ~line 175, UA ~line 798). The fact-sheet
block itself now explains the new vocabulary; update those lines when
convenient.

## 6. Relevance scope

`NewsItem.relevance_status` (`in_scope` | `out_of_scope` | `needs_review`, ""
on legacy items), `relevance_reason`, `relevance_override`.
`effective_relevance(item)` = override, else status, else a fresh
deterministic classification. `is_renderable(item)` = not out_of_scope.

`classify_scope(item, decision=None)` is deterministic: IT news digests and
podcasts → out; off-topic subjects (esports, games/trailers, TV, hardware
reviews, transport, wine, satellites, energy, defence procurement, careers,
business deals) → out unless the headline carries security evidence (then
needs_review); security evidence in the headline (CVE, patch, exploited flaw,
breach, hack, supply chain, malware, …) → in, whether or not the word
"security" appears; otherwise two body security terms → in, the existing AI
gray-zone verdict (only where it already runs) → in/out, a weak signal →
needs_review. Security digests (ThreatsDay, Weekly Recap) → needs_review.

The pipeline stamps kept items and applies
`data/stories/relevance_overrides.json`. Items are never deleted.

    python -m cyberalertx.tools.stories relevance-report
    python -m cyberalertx.tools.stories relevance-override FP out_of_scope --reason "…"

Snapshot: 184 in_scope, 9 out_of_scope, 7 needs_review. The audit's 28
off-topic UA fingerprints: 24 out_of_scope, 4 needs_review (4 classified from
their source items; 24 aged out of items.json, classified from the published
brief as a proxy; the 4 needs_review are proxies whose brief text says
«не стосується кібербезпеки», i.e. the brief's own disclaimer). No security
story is classified out_of_scope; the 5 "security category but out_of_scope"
items are category misfires (two DOU digests, two satellite launches, a
nuclear-fuel repository).

### Render gate (wired 3 Nov 2026)

`relevance.is_renderable(item)` is false only for `out_of_scope`
(`needs_review` items still render).

| Path | Behaviour |
|---|---|
| `main.py` `cmd_generate` | **Always on.** Out-of-scope items get no new brief; the run prints `skipped N out_of_scope item(s)` (9 on the 2 Nov snapshot). |
| `api/app.py` feed paths (`/posts`, trending, latest, RSS via the feed) | Only when `CYBERALERTX_HIDE_OUT_OF_SCOPE=1`. Off by default, because hiding already-published briefs changes what readers see. |
| `publish/service.py` (Telegram) | Same switch as the feed. |
| `/posts/{id}` | Never gated: existing links keep working. |

Tests: `tests/test_relevance_gates.py`.

### Postgres

`storage/pg/serializers.py` maps fields explicitly. `row_to_news_item` now
reads the three relevance fields when present; `news_item_to_row` does NOT
write them, because `news_items` has no such columns and an unknown key would
break the insert. To persist them in Postgres: add migration
`005_relevance.sql` (`ALTER TABLE news_items ADD COLUMN IF NOT EXISTS
relevance_status VARCHAR(16) NOT NULL DEFAULT ''`, same for
`relevance_reason VARCHAR(160)` and `relevance_override VARCHAR(16)`), the
columns in `schema.py`, the keys in `news_item_to_row`, and the upsert's
update set in `news_store.py`.
