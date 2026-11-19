# Editorial visual system V4 (`cax-editorial-4`)

V3 (`cax-svg-3`) drew every story as the same kit of isometric boxes with a
category overlay. Changing the scene label rearranged the boxes, and the
result read as generic technology wallpaper. V4 replaces that kit rather than
decorating it. Each image shows the thing the story is about: a workflow file,
a sign-in flow, a controller display, a court docket or a real photograph of
the named machine.

## Sources, in order

| Tier | What | When |
|---|---|---|
| A | Verified real photograph from `cyberalertx/media/v4/library/` + a restrained annotation | The story names the library entry's subject (`match` patterns) and the entry passes `library.validate` |
| B | Original editorial illustration (a scene module) | A catalogue scene is supported by the sources |
| C | Technical editorial visualisation (mechanism scenes: pinning, session relay, patch→exploit…) | The mechanism is stated by the sources |
| fallback | `dossier`: a restrained card with the story's own identifiers | Nothing in the catalogue is supported strongly enough (`confidence: low`) |

Tiers B and C share the scene library. A scene is whichever of the two tells the
story best.

## Architecture

```
cyberalertx/media/v4/
  brief.py      structured visual brief + scene catalogue (patterns, palette, alt text)
  library.py    Tier A photo library: licence validation, matching, data-URI embedding
  library/      photographs + library.json (provenance, licence, processing, marker box)
  kit.py        document, art directions (palettes), light/shadow, windows, code, pills,
                arrows, callouts, icons
  type.py       text as vector paths (glyphs.json, built by ops/media/build_glyphs.py)
  fonts/        OFL notices of the embedded outlines
  render.py     brief -> SVG (scene + shared grain + signature)
  scenes/       one module per scene; @scene("<id>") registers it
```

* **The brief** (`brief.build(story)`) holds the primary subject, action,
  target, environment, mechanism, entities, impact, supporting elements,
  exclusions, confidence, evidence (which phrase in which text chose the
  scene), the chosen scene and the runner-up alternatives, status (from
  `pipeline.evidence.assess`), facts (numbers, money, CVE IDs), and the
  library photo if one is used.
* **Scene selection** scores every catalogue entry against four texts. The
  headline's main clause has weight 3, the full headline 2, and the story's
  EN brief and source excerpt 1 each. An incidental word in a subordinate
  clause cannot outvote the subject. Below the thresholds the brief falls
  back to `dossier` with confidence `low`.
* **Determinism.** The seed is the story key plus the renderer version, so
  the same brief always renders to the same bytes. The inputs hash covers
  only the derived brief fields (scene, palette, facts, status, library id,
  confidence), not raw text. Rewording a post does not regenerate an image.
* **Text in images** is set as vector paths from the site's own fonts (Space
  Grotesk, Fira Sans Condensed) plus Geist Mono, all SIL OFL. There is no
  `<text>` element and no font lookup at rasterization. Text is limited to
  printable ASCII and is language-neutral by design, because one image serves
  both editions: identifiers, code, domains, numbers and a few short technical
  labels.
* **Sanitizer** (`svg_art.sanitize_svg`, shared with V3). V4 additions:
  `clipPath`, `feTurbulence` and `feColorMatrix` (film grain), and `<image>`,
  but only with an inline `data:image/{jpeg,png,webp};base64` `href`. External
  references are still rejected.

## Scene authoring rules

1. **Show the subject.** Draw the actual object, interface or mechanism. Use no
   cubes, orbs, rings, constellation dots, hooded figures, glowing brains or
   fake dashboards. Every element must say something about the story.
2. **One focal point.** The story's signal colour (`pal.danger` or
   `pal.accent`) marks the focal element. Everything else is ink or neutral.
3. **Evidence decides the drama.** Exploitation, theft or encryption appears
   only when `brief.status` or the brief's text supports it. A plain advisory
   shows exposure, not an attack. Do not invent technical detail.
4. **Figures only from `brief.facts`.** Never draw a number the sources do not
   state. Placeholder identifiers such as hashes and masked user IDs are
   fine. Invented domains use `.example`.
5. **No real logos or interfaces.** Brand names may appear as plain text where
   the story names them. Interfaces are generic.
6. **Distinct art direction per scene.** Use the palette from the catalogue:
   light directions such as `paper`, `glacier` and `court` exist so that a
   phishing story, a court case and a ransomware incident do not look alike.
   Vary composition (crop, scale, axis), not just colour.
7. **Thumbnail test.** At 360×203 the subject must still read. Prefer a few
   large forms over many small ones; small text is texture, not message.
8. **Determinism and cost.** Use only the passed `rng`. Rendering must take
   less than 100 ms, the SVG must stay under 400 KB (a Tier A plate adds
   about 165 KB), and rasterization must take under 2 s at 1600×900.
9. **ASCII text only, via `doc.text`.** Other characters are dropped by
   `type.supported`.

## V4.1 rules (18 Nov 2026)

V4.1 tightened the authoring rules after the first review. They apply to every
scene.

1. **Evidence first.** A scene distinguishes:
   * facts the source states;
   * the confirmed mechanism;
   * plausible details;
   * editorial interpretation.

   Only the first two become concrete content. Scenes never invent code, shell
   commands or output, CVEs, hashes, product interfaces, legal documents,
   victim details, attack stages, malware behaviour, infrastructure, numbers
   or status indicators. Anything conceptual is drawn as visibly conceptual:
   an abstract token, a silhouette, a redacted block or a symbol. Examples:
   * a commit SHA is drawn as a fingerprint glyph, never hex;
   * an unstated delimiter is a marked token;
   * the contents of an undescribed trojanised update are redacted.
2. **Thumbnail first.** The feed shows 176 × 99 px, cropped to `doc.focus`.
   Each image therefore has:
   * one dominant subject filling at least 40% of that crop;
   * no more than two or three text items that must be read, each with a cap
     height of at least 60 px inside a crop about 1,100 px wide;
   * strong value contrast.

   Everything smaller is texture.
3. **No formula.** No more "window, then arrow, then status card" diagrams.
   Each scene has its own object, metaphor, crop and light.
4. **Variants say what they show.** A scene that draws story-dependent
   variants exposes `alt_for(brief)`, and `brief.alt_text` uses it. For
   example:
   * a court case: leaked videos, a crypto amount, or a sentence in years;
   * a disputed breach: "breach denied" / "alleged";
   * an agents-only automation story.
5. **Alternatives.** A scene may expose `ALTERNATIVES = {"a": fn, "b": fn}`.
   The registered function is the selected composition. The review gallery
   renders the others side by side.

### Routing additions

* New scenes `police_takedown`, `crypto_theft` and `payment_skimmer`. They
  cover the takedown, crypto-theft and checkout-skimming stories that
  previously fell back. An IoT-camera scene was considered and not built: one
  story in the current window does not justify it.
* `SceneSpec.excludes`: a scene never applies when its pattern matches the
  headline. A court decision or a deepfake method is the subject, not the
  theft it involves. A phishing story about passwords is not password policy.
* Fact extraction:
  * a CVSS score is no longer read as a flaw count;
  * a number cannot start inside a decimal ("9.8" is not "8");
  * counts allow up to three words between the number and its noun
    ("90 GTA VI videos").
* The fallback (`dossier`) now covers 22 of 152 eligible stories (14%), down
  from 28. It is a designed cover built from the story's own identifiers, not
  a blank form.

### Routing additions (V4.1.1, 18 Nov 2026)

* **Headline first.** `EditorialBrief.headline` carries the published
  headline (it is not part of the inputs hash). The fallback takes its lead
  word from the headline's main clause, then the full headline, never from
  the article body. A canary image led with "AI" because the body mentioned
  an AI calling tool; the headline is about a police action.
* **Actors.** `SceneSpec.actor`: the headline must name this actor.
  `police_takedown` needs a law-enforcement body in the headline:
  * English: police, FBI, Europol, Interpol, prosecutors, DOJ;
  * Ukrainian: Нацполіція, кіберполіція, ФБР, правоохоронці, СБУ,
    прокуратура;
  * an operation name such as "Operation Endgame".

  It also needs an action: exposed, arrested, detained, charged, dismantled,
  seized, taken down; викрили, затримали, заарештували, ліквідували,
  вилучили. "Exposed" alone (a vulnerability) or an operation name alone (a
  research campaign) never routes there.
* **Police scene variants.** Seizure or takedown of named infrastructure keeps
  the taped rack. Exposure or arrest without a stated seizure draws:
  * the group's tool of contact (a phone taking an "IT SUPPORT" call, when
    the sources say so) under tape carrying the headline's own action word;
  * tags with the actors in English, the reported figure, and secondary
    context such as an AI calling platform.
* **Named entities.** Names from our published headline count only when the
  source text contains them. Site counts are a fact
  ("178 sites"). `third_party_script` labels the named sites and shows the
  count. When the source says the sites served malware to visitors, it also
  draws the visitors receiving the payload.
* **Cloud credentials** route to `cloud_breach`. `compromised_sites` draws a
  single site when the headline names one.

### Label and alt-text integrity (V4.1.2, 18 Nov 2026, O54)

Canary 2 stopped on a breach image that printed `IT` as the sender: the
headline said "IT provider hack". The fix is in the extraction and the
checks, not in the art.

* **Generic terms are never names.** `brief.GENERIC_TERMS` lists technology,
  role and place abbreviations: IT, AI, RCE, CPU, API, MSP, SaaS, UK, EU and
  others. `brief.DEMONYMS` lists nationalities. Alone, neither ever becomes
  an entity.

  "IT" and "AI" may end a company name. They join the name directly before
  them only when the source writes that exact compound: "Wellington IT",
  "Scale AI", "Fireworks AI". Other generic terms never join a name, so the
  extractor produces no "Roller RCE" or "Turin CPU".
* **Whole words only.** Scenes test whether a name occurs with
  `brief.mentions(name, text)`. The earlier substring test found "it" inside
  "with".
* **Roles come from the sources.** The breach scene stamps the supplier
  context ("IT PROVIDER HACK", "SUPPLIER BREACH"), using the sources' own
  event word. It names the supplier only when the sources call that entity
  the supplier.

  A name the sources show notifying, saying or warning is the sender, never
  the supplier. Adjacent name parts are joined: "Baker Tilly", not "Tilly".
* **Counts of organisations are facts.** "40 Irish credit unions" gives
  `orgs` and `orgs_noun`.

  Money keeps the sources' qualifier and a decimal point. "понад $40,5 млн"
  becomes `money` $40.5M with `money_plus` set. The police tag reads
  `OVER $40.5M` (O52).
* **Alt text describes what is drawn.**
  * `Doc.labels` records every string an image sets as type.
  * `v4/consistency.check` reports a number, a quoted Latin-script label or a
    name in the alt text that no label shows, and a claimed figure when no
    number is drawn.
  * Scenes with variants build their alt text from the same plan as the
    drawing: breach, police, crypto theft, the drawn supercomputer hall,
    advisory, ICS and compromised sites. The advisory alt text, for
    example, names the drawn status badge and severity; it used to say
    "patch status" under an EXPLOITED badge.
  * The audit's hand review of every distinct alt text found three
    mismatches that no pattern can catch: the advisory's "patch status", the
    compromised-sites phone (drawn only in the attack + iPhone variant) and
    the ICS "identifier" when only "ADVISORY" is drawn.
* **Where the check runs.**
  * Tests cover every scene across facts, entities and statuses.
  * `ops/media/alt_audit.py` runs it on the live eligible set: it is
    read-only and exits 1 on a mismatch. It also lists every drawn label
    that is a bare generic word ("AI" as a topic, "GPU" on a graphics card),
    for review by eye.
  * The renderer logs any mismatch at run time.
* **Alt text and image are written together.** When a story's inputs are
  unchanged, the engine replaces its stored alt text only if the current
  code draws the stored image byte for byte.

### Hybrid policy: confidence routing (V4.1.2)

With `CYBERALERTX_ILLUSTRATION_RENDERER=editorial-4`, V4 draws a story only
when its brief found an evidence-backed scene: confidence `high` or `medium`,
with the headline supporting it. A low-confidence brief is the generic
`dossier` fallback. It is served by V3 (`renderer.v4_applies`,
`renderer.plan_for`), so V4 coverage never grows through a weak generic
card.

This is the permanent policy, not a workaround:

* **Identity is unchanged.** Story key, asset id and URLs are the same
  whichever renderer draws a story.
* **No churn on V3 images.** A routed story gets exactly the V3 plan, with
  the same alt text and inputs hash, so an existing V3 image is reused,
  never redrawn.
* **Coverage on 18 Nov 2026:** 123 of 145 eligible stories are drawn by V4
  and 22 by V3. `ops/media/alt_audit.py` reports both numbers.
* **Backfill.** A backfill moves routed stories from cax-svg-2 to cax-svg-3,
  not to a dossier card. `backfill --dry-run` lists them as `renderer change
  (cax-svg-2 -> cax-svg-3)`.

The `dossier` scene stays in the code and the catalogue. It is no longer
published under the hybrid policy.

### Advisories are drawn as exposure (V4.1.3, O55)

Canary 3 stopped on an F5 advisory ("flaws CAN crash traffic") drawn as a
server being knocked over. `brief.advisory_without_incident(headline,
status)` is true for a headline that announces a flaw, fix or warning when
neither the evidence status nor the headline reports an attack. Such a story
never wins a scene in `brief.INCIDENT_SCENES`, which covers scenes whose
picture asserts that an attack or compromise took place: kernel DoS, wiper,
ransomware, breach, skimmer and others. The next-ranked scene decides,
normally `vuln_advisory`.

An exploitation status (`exploited`, `confirmed`, `attacks_observed`,
`compromise`) or incident wording in the headline reopens the incident
scenes. Incident wording means "exploited", "hackers exploit", "attacked",
"breached", "stolen" or "in the wild".

### Roles, subjects and sources (V4.1.4, O56/O57)

Canary 4 and the sweep that followed showed one pattern: a keyword chose a
picture that asserted more than the sources do. The rules:

* **Law enforcement (O56).** The action, the acting authorities, the
  arrested group and the seized objects are separate. A seized object is
  only a name that follows a seizure or takedown verb. It is never a place,
  a nationality or an agency. Arrests draw the group as a case file; the
  phone appears only when calls are the stated channel. Takedowns and
  seizures keep the rack, with the headline's own action on the tape.
* **The headline states the subject** (`SceneSpec.head_requires`):
  * court: a legal action, not "charges" on a bill or "fake court notices";
  * GPU mining, a wiper, a cloud backdoor, an extension supply chain: each
    needs its subject named in the headline.
* **Damage needs an incident** (`brief.IMPACT_SCENES`). Locked systems,
  leaking records or a wiped host need an attack status or incident wording.
  "Could/may/lets …" is a possibility, not a report.
* **Advisories.**
  * PATCH AVAILABLE only when the sources say a fix exists. "Fixes coming"
    and "unpatched" mean pending.
  * A KEV list, or KEV wording with several vendors, is drawn as the
    catalogue. A CVE is never drawn under a product it is not tied to.
  * A third party that warns *of* another product is not the product.
  * "Hackers target X" is exploitation.
* **Sentences.** A sentence handed down is not "faces up to".
* **Canary 5 review fixes:**
  * A protocol version stays in the product name ("NGINX HTTP/2"); it is
    never listed as a product of its own.
  * KEV alt text lists every CVE the catalogue draws. When the headline
    counts more additions than the sources list, the catalogue shows
    "+N more" instead of padding.
  * Figures come from the sources only: the headline, then the excerpt. Our
    own published summary never adds a figure. It may carry another
    subject's number: Oracle's 11 Java SE fixes are not CVE-2026-114938. A
    CVE id from the summary stays only when a source article of the story
    contains that exact id.
  * When the headline rounds an amount ("$40M") and the excerpt states it
    precisely ("more than $40.5 million"), the precise figure is drawn with
    its qualifier (`OVER $40.5M`).
  * A country that acts is named as the sources name it ("Ukrainian
    authorities + FBI").
  * An appeal to patch is not a statement that a fix exists. The advisory
    shows PATCHING URGED unless a source states availability ("fixed
    versions … came out", "patches", "updates released").
  * Secondary products are listed only when the source headline names them.
* **Recognition (hybrid policy).** V4 draws a story only when the drawing
  names something of it, or shows a verified library photograph. That
  means an entity, figure, identifier or acting authority. Unlabelled
  metaphors (the AI gears, a bare mast) stay on V3.

## Scenes

There are 37 scene modules: the 35 catalogue scenes, `hpc_drawn`
(supercomputer stories without a library photo) and the `dossier` fallback.

| Group | Scenes |
|---|---|
| Infrastructure | `hpc_hall` (photo), `hpc_drawn`, `ics_controller`, `refrigeration_controller`, `gpu_cryptominer`, `edge_wiper`, `telecom`, `kernel_dos` |
| Software and web | `ci_pinning`, `session_theft`, `rmm_console`, `patch_to_exploit`, `ai_code_audit`, `third_party_script`, `compromised_sites`, `dev_supply_chain`, `irc_injection`, `code_signing`, `payment_skimmer` |
| People, legal, data | `court_case`, `deepfake_call`, `breach_notice`, `cloud_breach`, `espionage_backdoor`, `usb_worm`, `credential_phish`, `police_takedown`, `crypto_theft` |
| Analysis and advisories | `weekly_recap`, `disclosure_deadline`, `ai_offensive_tool`, `ransomware_impact`, `mfa_policy`, `selfhosted_saas`, `governance`, `vuln_advisory`, `dossier` |

Shared drawing helpers live in modules prefixed `_`:
* `_objects.py`: product elevations;
* `_editorial.py`: type helpers;
* `_camera.py`: a small perspective camera;
* `_hpc.py`: the supercomputer type column and account tokens.

## Thumbnails

A scene may set `doc.focus = Box(...)`, a 16:9 region around its subject. The
SVG then carries an invisible `<rect id="cax-focus">`, which the site's
`/media/.../preview` route crops to for the feed thumbnail (176 px wide).
Without one, a V4 image is shown whole. Older images keep the central 62%
crop. Telegram, Threads and the article page always use the whole frame.
