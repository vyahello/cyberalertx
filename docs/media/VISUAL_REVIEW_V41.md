# Illustration review: V4 → V4.1

**Status: candidate.** V3 (`cax-svg-3`) remains the production renderer. The
V4 canary was paused before it produced any image. The 18 Nov activation was
followed by the pause before the next hourly run, so there is no canary output.
V4.1 is built, tested and on `main`. Activation and any backfill still need
the owner's approval: see [V4_ACTIVATION_PLAN.md](V4_ACTIVATION_PLAN.md).

The rules V4.1 applies (evidence first, thumbnail first, no formula, variant
alt text, alternatives) are in [VISUAL_SYSTEM_V4.md](VISUAL_SYSTEM_V4.md#v41-rules-18-nov-2026).

## Review set

There are 46 real stories in the set:
* the 32 representative stories of the V3/V4 reviews;
* the 4 supplementary ones (advisory and fallback);
* the stories of the three new scenes (police takedown ×2, crypto theft ×3,
  checkout skimmer);
* three more fallback stories;
* the re-routed Microsoft 365 phishing story;
* the Binance breach denial.

Each story is shown with:
* the previous V4 image, rendered from release `20261118-0856-90c0c82`;
* the V4.1 image;
* every alternative composition;
* 176 px feed crops of each;
* a chat preview;
* the brief, what changed and why, the known uncertainties, and scores.

The full gallery is on the host (`$REVIEW_DIR/illustrations-v41/index.html`),
built by `ops/media/build_review_gallery.py`.

Two materially different alternatives were made for each of these:
* M365 phishing, Fugaku and GitHub SHA pinning;
* Siemens, the Ethereum decision, the Lapsus$ leak and the extradition case;
* ARTEX;
* each new scene.

The deepfake call has three alternatives.

## Scores (46 stories, 1–5, from the rendered images at full size and 176 px)

| Criterion | Average | Hard gate |
|---|---|---|
| Relevance | 4.72 | ≥ 4 |
| Recognition | 4.30 | ≥ 4 (the fallback is exempt) |
| Visual quality | 4.15 | ≥ 4 |
| Composition | 4.00 | average ≥ 3.8 (met) |
| Distinctiveness | 4.26 | – |
| Technical accuracy | 5.00 | ≥ 4 |
| Thumbnail readability | 4.46 | ≥ 4 |
| Evidence integrity | 5.00 | = 5 |

### Hard-gate failures

| Story | Gate | Why |
|---|---|---|
| Trigram campaign (fallback) | relevance 3 | Honest fallback: names the subject, does not depict the story |
| Tor emergency update amid DDoS (fallback) | relevance 3 | A DDoS scene would serve it |
| German military drone operations (fallback) | relevance 3 | Honest fallback |
| Beget rebuilds after data wiper (fallback) | relevance 3 | A data-wiper scene would serve it |

All four are the honest fallback, which covers 22 of 152 eligible stories
(14%). No non-fallback image fails a gate. Every image scores 5 on evidence
integrity.

### Weaker but above the gates

* **The two Retadup stories** share one composition (distinctiveness 2).
* **Advisories** share a family look (distinctiveness 3), although status
  types now differ by form as well as colour: a crack burst for exploited, a
  dashed reticle for proof of concept, a sticking-plaster patch, a magnifying
  lens for disclosed.
* **Huawei telecom resilience and the cybersecurity-governance column** are
  analysis pieces with conceptual images (relevance 4).

## What changed

**Evidence integrity.** Everything invented was removed from every scene:
* fake YAML;
* hex hashes;
* diffs and exploit scripts;
* kernel traces;
* log lines;
* hostnames, file names and process names;
* invented UIs;
* LED and CPU statuses;
* policy clause numbers;
* ransom notes;
* temperature readouts;
* attack-chain stages.

Unstated mechanisms are drawn as visibly conceptual elements:
* a fingerprint glyph for a SHA;
* a delimiter token;
* the redacted contents of a trojanised update.

A breach the company denies is drawn sealed and disputed, not leaking. A
researchers' proof of concept is never stamped "exploited".

**Composition.** One dominant subject per image, built to read at 176 px.
Examples:
* the 90 video tiles;
* ACQUITTED over chained blocks carrying $25M;
* 27 tally strokes;
* a SEIZED-taped rack;
* a masked caller;
* a cut tape measure;
* a cracked wax seal;
* a marionette bar over a fleet.

**Photography.** Fugaku keeps the verified CC0 photograph, now cropped to the
machine. The account figure is set as type with 40 tokens ("1 = 100
accounts"), and no rack is marked as an intrusion point.

**Routing:**
* three new scenes;
* headline-based exclusions;
* the M365 phishing story moved from password policy to phishing;
* a film premiere no longer reads as governance;
* CVSS scores and decimals are no longer read as flaw counts;
* video counts with words in between ("90 GTA VI videos") are recognised.

**Alt text.** Rewritten for 34 scenes to describe the new images. Variant
scenes describe the variant actually drawn.

## Limits

* Fallback stories (14%) remain generic by design. The next scenes worth
  adding, by archive coverage, are a DDoS scene and a data-wiper scene.
  An IoT-camera scene is not yet justified (one story).
* Only one real photograph (Fugaku) is in the library. Adding photographs
  needs a public-domain or CC0 source verified per entry.
* Rendering takes 1–80 ms per image. SVGs are 5–250 KB (with a photo up to
  about 250 KB). Rasterizing takes 0.4–1.0 s per variant. Cost is $0. No
  external service is used.
