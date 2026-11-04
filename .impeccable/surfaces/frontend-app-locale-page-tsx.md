---
version: 1
slug: "frontend-app-locale-page-tsx"
primary_target: "frontend/app/[locale]/page.tsx"
related_targets: ["frontend/app/[locale]/threat/[id]/page.tsx"]
---

# Surface brief — CyberAlertX publication (home feed, topic pages, article)

Scope: `/{locale}` front page, `/{locale}/topic/{slug}`, `/{locale}/threat/{id}`. Visitor mode: **Read** (the feed is scanned, the brief is read). Audience, job and constraints: see PRODUCT.md. Brand commitments pinned by the owner: Aperture glyph + wordmark, cyan signal colour, dark ground.

## Direction contract

THESIS: Every story is a field-guide entry: its field marks (severity and why, exploitation status, who it hits, how many outlets confirmed it, when) hang in a fixed side-note margin off one vertical axis, and the headline and brief hang to the right of it. Refuses the category default of chip-stacked cards, KPI counters and a slogan hero.

OWN-WORLD: Graphite ground (#0E1116) with two tone steps, near-white ink, cyan (#06B6D4) as the one signal colour and as a whole-field colour for one closing section. Literata (reading face, optical sizes) for headlines and article text; Sofia Sans Semi Condensed for field marks, navigation and controls. Severity is a word plus a filled bar of 1–4 segments, coloured, never colour alone. No boxes, rules, pills, gradients or glows; surfaces separate by tone.

STORY: The reader sees the most significant story now and why it is rated that way, scans what else matters, narrows the feed to their stack, opens one brief, learns what happened, whether it touches them and what to do, and can follow the original reporting.

FIRST VIEWPORT: Top bar: wordmark left, section links starting on the 42% axis, language and Telegram right. Left of the axis: the edition title (h1) and date. On the axis: the lead story — headline at head size, plain summary at lead size, then its field marks (severity, exploitation, time, outlet and count, who it hits) and the severity reason, then a real "Read the brief" button. (Revised after the finish review: marks above the headline measured as an eyebrow under the Taste house rules.) Below, still on the first screen: the next stories as two-ended rows (headline left, field marks right).

FORM: Taste "printed annual" (editorial-report) composition fused with the field-guide entry anatomy, candidate 5 of 7 on the grounded list (advisory bulletin, intelligence daily brief, reference record, wire copy, field guide, civil-defence leaflet, timetable). seed:80c519ec8ddbfb1d

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Signature

The side-note margin (field marks on the axis) on the feed rows, the lead and the article header; the masked headline reveal on the lead story is the one loud motion.

## Decisions after the finish review (2026-11-03)

- The 7-day overview under "Also significant now" stays: the owner's brief asks the homepage to show the current threat situation from real data. It is a labelled bar list whose rows open the matching slice of the feed, not a hero metric.
- Sofia Sans replaced by Fira Sans Condensed: Sofia's default Cyrillic draws Bulgarian letterforms.

## Unresolved

- Story clustering (duplicates of one incident) is an ingest fix, outside this surface.
