# Intelligence layer — scoring, Daily Top 10, Trending, Breaking

Status: **shadow / evaluation only** (introduced 3 Nov 2026). It computes and
stores; it changes nothing that readers see. The public feed, `/posts`,
`/posts/trending`, RSS and Telegram behave exactly as before.

Code: `cyberalertx/intel/` · CLI: `python -m cyberalertx.tools.intel` ·
admin: `/admin/intel` (+ `.json`, token-locked) · tests: `tests/test_intel.py`.
Story clustering, evidence and relevance (the inputs) are documented in
`docs/intel/STORIES_AND_EVIDENCE.md`.

## 1. The unit is the story

Everything ranks **stories** — clusters from `pipeline.dedup.cluster_items`,
the same clustering the feed uses — never individual articles. A story joins
its articles with what the system already stores: fact sheets
(`data/fact_sheets.json`), AI renders (`data/threat_posts.json`) and relevance.
Stories whose every article is `out_of_scope` never rank anywhere.

**Independent sources.** Several outlets repeating one original report count
once. `pipeline.dedup.independent_sources` is used when present; the fallback
collapses identical article bodies and articles that attribute the story to
another outlet in the same cluster ("according to BleepingComputer",
«як повідомляє dev.ua»). Corroboration, reliability and confidence only ever
use independent sources.

## 2. Four separate judgements

| | Question | Values | Never mixed into |
|---|---|---|---|
| **Importance** | How significant is the event? | 0–100 | — |
| **Confidence** | How much weight can the information bear? | high / medium / low (+0..1) | importance |
| **Verification** | Is the core claim established? | verified / partially_verified / unverified | importance |
| **Exploitation** | Is anyone exploiting it? | confirmed / reported / poc_available / unknown | — (feeds one importance component) |

A high-impact, low-confidence story stays high-impact and low-confidence; the
admin view and the selection explanations show both.

### Exploitation status (`intel/dimensions.py`)
- **confirmed** — a fact sheet records it as confirmed by the source, an
  official source (CERT, government, the vendor) reports exploitation, or the
  flaw is in a known-exploited-vulnerabilities catalogue.
- **reported** — exploitation is reported by media or a non-official source.
- **poc_available** — proof-of-concept or public exploit code is mentioned.
- **unknown** — no source says it is exploited.

### Verification status
- **verified** — a primary/official source with no contradictions, or ≥ 2
  independent sources above the reliability floor (0.45) with no
  contradictions and not claims-only.
- **partially_verified** — ≥ 3 independent outlets (any reliability, no
  contradictions), or one reliable independent source, or reliable sources with
  contradictions.
- **unverified** — claims only ("hackers claim…", «заявили»), or no
  independent source above the floor.

### Confidence (0..1 → high ≥ 0.7, medium ≥ 0.45, low)
best independent reliability · +0.1 per further reliable independent source
(max +0.2) · +0.05 per further independent outlet below the floor (max +0.15)
· +0.1 official source · −0.25 contradictions · −0.15 thin source text
(< 300 chars) · −0.15 claims only. Every step is recorded as a reason.

## 3. Importance score (`intel/scoring.py`)

`score = Σ component × weight`, weights in `intel/config.py` (overridable in
`data/intel/config.json`, rescaled to sum to 100):

| Component | Weight | Calculation (0..1) |
|---|---:|---|
| Potential impact | 25 | 0.7 × severity + 0.3 × reach. Severity: rendered level (Critical 1 · High 0.75 · Medium 0.45 · Low 0.2), else ingest threat score / 100; raised to max CVSS / 10. Reach: (platforms + audiences + products) / 4, max 1 |
| Confirmed exploitation | 20 | confirmed 1 · reported 0.6 · poc 0.4 · unknown 0 |
| Source reliability | 15 | best independent source's reliability + 0.1 per further reliable independent source (max +0.2) |
| Timeliness | 15 | 0.5 ^ (hours since newest article / 24), in whole-hour buckets |
| Audience relevance | 10 | max over audiences: enterprise/sysadmins 0.9 · everyday 0.85 · developers 0.8 · phones 0.75 · crypto 0.6; none 0.3 |
| Novelty | 10 | new 1 · featured before 0.2 (0.6 with new evidence since) · digest headline 0.3 |
| Practical usefulness | 5 | actions + fix/mitigation 1 · actions only 0.5 · none 0 |

No model returns a number. AI contributes only the stored, qualitative fact
sheet fields (exploitation status, patch status, CVSS as written by the source).

**Source reliability** (`intel/sources.py`): per source, five axes —
historical (seeded from `pipeline.credibility`), primary, official, technical,
methodology — combined as 0.40/0.20/0.15/0.15/0.10. Editorial judgements are
in code with notes; override in `data/intel/sources.json`.

**Explainability.** Each evaluation stores total, weighted components, raw
0..1 values, reasons per component, the three dimensions with reasons,
`calculation_version`, `evaluated_at`, an input hash and a diff against the
previous evaluation ("score 41.2 → 55.0; exploitation_status reported →
confirmed"). History keeps the last 20 per story (`data/intel/scores.json`).

**Recalculation.** The input hash covers members, independent sources, fact
sheets, renders, the age bucket, novelty state, the config and the source
table. Same hash → the stored evaluation is reused, not recomputed.

## 4. Daily Top 10 (`intel/selection.py`)

- Edition *D* covers (cutoff on *D−1*, cutoff on *D*] in the editorial timezone
  (default `Europe/Kyiv`, cutoff `06:00`), plus 12 h carry-over for late
  stories.
- selection score = importance × verification multiplier (verified 1.0 ·
  partially 0.9 · unverified 0.7).
- Quality threshold 35: **fewer than ten picks if fewer qualify.**
- One event, one pick: candidates sharing a CVE or with strongly overlapping
  headlines (distinctive-token Jaccard ≥ 0.6) are collapsed to the stronger.
- Deterministic order: selection score, importance, newer, story key.
- Each pick carries its top three score reasons; every left-out candidate
  carries why (threshold, same event, outside top positions).
- Editions are kept in `data/intel/editions/YYYY-MM-DD.json`. While an edition
  is open, new evidence that changes the picks rewrites it and the previous
  version is kept under `revisions`.

## 5. Trending

Window 24 h (configurable). A story trends when ≥ 2 signals fire and their
weights sum to ≥ 40: new information (an article joined inside the window, 20),
development (exploitation newly confirmed, or a new independent source in the
window, 25), corroboration (≥ 2 independent sources, 15), exploitation
(confirmed/reported, 15), audience (≥ 0.75, 10), importance (≥ 60, 15).
**Article count is not an input**; syndicated copies fire nothing.

Today's public `/posts/trending` is different and unchanged: a severity sort
(threat level, actionability, date) with no window and no corroboration.

## 6. Breaking

Independent of the Top 10. A story qualifies when it is active in the last
24 h, not unverified, in scope, and meets at least one rule:

| Rule | Evidence required |
|---|---|
| R1 critical_exploited | exploitation **confirmed** AND (CVSS ≥ 9, Critical, or KEV) AND (official source OR ≥ 2 independent confirmers with reliability ≥ 0.45) |
| R2 supply_chain | supply-chain compromise AND **verified** |
| R3 official_warning | official government/CERT source, level ≥ High, AND (exploitation confirmed OR urgent action) |
| R4 ransomware_incident | ransomware incident, ≥ partially verified, importance ≥ 55 |
| R5 infrastructure | widely deployed product, exploitation confirmed, importance ≥ 55 |

Alert state (`data/intel/breaking_state.json`) stores each story's evidence
fingerprint (rules, exploitation, verification, independent sources, CVEs,
CVSS). Same fingerprint → `unchanged`, no new alert; a material change →
`update`. **Nothing is published**; this phase only classifies.

## 7. Running it

    python -m cyberalertx.tools.intel evaluate [--now ISO] [--no-write]
    python -m cyberalertx.tools.intel explain STORY_KEY

No AI calls, no scheduler, no publishing. Writes only `data/intel/`.

## 8. First shadow run (snapshot of 2 Nov 2026, as of 18:00 UTC)

170 stories (200 articles). Top 10: 10 picks; Ivanti Connect Secure (reported
exploitation, one source) first; the «Повітряна тривога» incident (4
independent Ukrainian outlets → partially verified, medium confidence) third;
the DOU weekly digest excluded by novelty. Trending: 1 story. Breaking: none —
no story had exploitation *confirmed* by an official source within 24 h.
Compare: today's `/posts/trending` lists five Critical items from 27 Oct–2 Nov,
two of them about Ivanti Connect Secure (different flaws, correctly separate stories).

## 9. Known limits

- Exploitation and supply-chain detection read English and Ukrainian keywords
  in titles/teasers; fact sheets (when present) are the stronger signal.
  Fact sheets exist only for stories rendered by the new pipeline.
- Source-reliability axis values are editorial judgements, recorded for
  review, not measured.
- The engine reads JSON stores only (the authoritative store); results are
  JSON files, not Postgres tables (no migration needed for this phase).
