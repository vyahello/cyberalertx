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

## Scenes

There are 34 scene modules: the 32 catalogue scenes, `hpc_drawn`
(supercomputer stories without a library photo) and the `dossier` fallback.

| Group | Scenes |
|---|---|
| Infrastructure | `hpc_hall` (photo), `hpc_drawn`, `ics_controller`, `refrigeration_controller`, `gpu_cryptominer`, `edge_wiper`, `telecom`, `kernel_dos` |
| Software and web | `ci_pinning`, `session_theft`, `rmm_console`, `patch_to_exploit`, `ai_code_audit`, `third_party_script`, `compromised_sites`, `dev_supply_chain`, `irc_injection`, `code_signing` |
| People, legal, data | `court_case`, `deepfake_call`, `breach_notice`, `cloud_breach`, `espionage_backdoor`, `usb_worm`, `credential_phish` |
| Analysis and advisories | `weekly_recap`, `disclosure_deadline`, `ai_offensive_tool`, `ransomware_impact`, `mfa_policy`, `selfhosted_saas`, `governance`, `vuln_advisory`, `dossier` |

Shared drawing helpers live in `scenes/_objects.py` (product elevations for
advisories) and `scenes/_editorial.py`.

## Thumbnails

A scene may set `doc.focus = Box(...)`, a 16:9 region around its subject. The
SVG then carries an invisible `<rect id="cax-focus">`, which the site's
`/media/.../preview` route crops to for the feed thumbnail (176 px wide).
Without one, a V4 image is shown whole. Older images keep the central 62%
crop. Telegram, Threads and the article page always use the whole frame.
