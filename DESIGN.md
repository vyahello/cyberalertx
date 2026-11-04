---
name: CyberAlertX
description: An editorial cybersecurity brief, set as a field guide on one vertical axis.
colors:
  ground: "#0E1116"
  ground-raised: "#161B22"
  ground-high: "#1E242D"
  ground-sunk: "#0A0D11"
  ink: "#ECEEF1"
  ink-muted: "#A6AEBA"
  ink-faint: "#8C95A3"
  signal: "#06B6D4"
  signal-hover: "#22D3EE"
  signal-ink: "#071318"
  signal-deep: "#0B3A44"
  sev-critical: "#FF5C6C"
  sev-high: "#FF9F43"
  sev-medium: "#EDE58A"
  sev-low: "#8C95A3"
  line: "#2A313B"
typography:
  display:
    fontFamily: "Literata, Georgia, Cambria, serif"
    fontSize: "clamp(3rem, 1.8rem + 4.2vw, 5.5rem)"
    fontWeight: 300
    lineHeight: 0.98
    letterSpacing: "-0.03em"
    fontVariation: "'opsz' 72"
  headline:
    fontFamily: "Literata, Georgia, Cambria, serif"
    fontSize: "clamp(1.75rem, 1.15rem + 1.9vw, 2.75rem)"
    fontWeight: 600
    lineHeight: 1.12
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Literata, Georgia, Cambria, serif"
    fontSize: "clamp(1.625rem, 1.2rem + 1.2vw, 2.25rem)"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  lead:
    fontFamily: "Literata, Georgia, Cambria, serif"
    fontSize: "clamp(1.1875rem, 1.05rem + 0.4vw, 1.375rem)"
    lineHeight: 1.35
  body:
    fontFamily: "Literata, Georgia, Cambria, serif"
    fontSize: "clamp(1.0625rem, 1rem + 0.2vw, 1.125rem)"
    fontWeight: 400
    lineHeight: 1.6
  control:
    fontFamily: "Fira Sans Condensed, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1
  label:
    fontFamily: "Fira Sans Condensed, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "1.35rem"
  code:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "0.9em"
    fontWeight: 400
rounded:
  none: "0"
  sm: "2px"
spacing:
  margin: "clamp(1.25rem, 0.6rem + 2.8vw, 3rem)"
  gutter: "clamp(1.25rem, 0.8rem + 1.2vw, 2rem)"
  section: "clamp(4.5rem, 3rem + 5vw, 8rem)"
  panel: "1.25rem"
  page-max: "90rem"
  measure: "68ch"
components:
  button-primary:
    backgroundColor: "{colors.signal}"
    textColor: "{colors.signal-ink}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
    padding: "0 20px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.signal-hover}"
  button-quiet:
    backgroundColor: "{colors.ground-raised}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
    padding: "0 20px"
    height: "44px"
  button-quiet-hover:
    backgroundColor: "{colors.ground-high}"
  field:
    backgroundColor: "{colors.ground-raised}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
    padding: "0 12px"
    height: "44px"
  field-hover:
    backgroundColor: "{colors.ground-high}"
  toggle:
    backgroundColor: "{colors.ground-raised}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "0 12px"
    height: "40px"
  toggle-pressed:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ground}"
  panel:
    backgroundColor: "{colors.ground-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "{spacing.panel}"
  footer-field:
    backgroundColor: "{colors.signal}"
    textColor: "{colors.signal-ink}"
---

# Design System: CyberAlertX

## Overview

**Creative North Star: "The Field Guide on the Axis"**

Every story is an entry in a field guide. Its field marks (severity and why, whether it is exploited, when, who reported it and how many outlets confirmed it, who it hits) hang in a side-note margin; the headline and brief hang to the right of one vertical axis set at 42% of the content width. The masthead, lead story, feed, article header and footer all register to that same axis, so the product reads as one edited publication rather than a stack of widgets.

The world is graphite, calm and dense without being cramped: a dark ground in four tone steps, near-white ink, and one cyan signal that marks action, links, focus and a single whole-field closing section. A variable reading serif (Literata, optical sizes) carries everything meant to be read; a narrow interface sans (Fira Sans Condensed) carries the marks, navigation and controls. Surfaces separate by tone, never by outline or shadow. Corners are square.

Confirmed rejections: chip-stacked cards, KPI counters, a slogan hero, gradients, glows, glass, outlined boxes, tiny uppercase labels.

**Key Characteristics:**
- One vertical axis at 42% of the content width, shared by every section that uses it.
- Field marks in a side-note margin; text on the axis.
- Tone steps, not lines or shadows, separate surfaces.
- One signal colour; one whole-field section (the footer).
- Severity is always a word plus a 1–4 segment bar plus colour.
- Square corners; dark only.

## Colors

Graphite ground in tone steps, near-white ink in three strengths, one calm cyan signal, and a four-step severity scale that never travels alone.

### Primary
- **Calm Signal Cyan** (signal): the primary button, links in running text, the focus ring, the active-nav underline and the footer's whole field. Hover lifts to **Bright Signal** (signal-hover).
- **Field Ink** (signal-ink): text on the cyan field. **Deep Teal** (signal-deep) is the secondary text on the cyan field.

### Neutral
- **Graphite Ground** (ground): the page.
- **Raised Graphite** (ground-raised): filled panels (article context, "if you are already affected", the mobile side-note block), inputs, toggles, quiet buttons, inline code.
- **High Graphite** (ground-high): hover on raised surfaces, empty severity segments, scrollbar thumb.
- **Sunk Graphite** (ground-sunk): fenced code blocks and the dialog backdrop.
- **Paper White** (ink): all headlines and running text.
- **Slate** (ink-muted): summaries, standfirsts, inactive navigation, outlet names.
- **Ash** (ink-faint): the metadata floor (time, outlet count, audience); still clears 4.5:1 on every ground step.
- **Rule Grey** (line): table row rules and form-field strokes only.

### Severity
- **Critical Coral** (sev-critical), **High Amber** (sev-high), **Medium Straw** (sev-medium), **Low Ash** (sev-low, neutral by intent; the Low word renders in ink-muted). Also used for the "Exploited" mark (sev-critical) and the 7-day overview bars.

### Named Rules
**The One Signal Rule.** Cyan is the only accent. It marks action, links, focus and the one whole-field section; it never decorates. The brighter brand `#00E5FF` belongs to the glyph's ping and the OG card only.

**The Never Colour Alone Rule.** Severity is always the word, a filled count of 1–4 segments, and the colour, together.

**The Dark Only Rule.** The product stays dark (`color-scheme: dark`); there is no light theme.

## Typography

**Display Font:** Literata, variable with optical sizing (with Georgia, Cambria, serif)
**Body Font:** Literata (same family; optical size makes it a sturdy text face at 17px)
**Label/Mono Font:** Fira Sans Condensed 400/500/600 for interface; JetBrains Mono 400 for code, commands, hashes and indicators only. Space Grotesk 600 is the logotype, not part of the type system.

**Character:** A bookish serif that reads well in two scripts, set against a narrow, plain sans that fits a whole field-mark line on one row. Both cover Latin and standard Cyrillic.

### Hierarchy
- **Display** (300, 48→88px, 0.98, -0.03em, opsz 72): the masthead h1 only.
- **Headline** (600, 28→44px, 1.12, -0.015em): the lead story headline and the article h1.
- **Title** (600, 26→36px, 1.15): section headings (h2).
- **Lead** (19→22px, 1.35): feed headlines (600) and standfirsts/summaries (400).
- **Body** (400, 17→18px, 1.6): running text and feed summaries; article prose capped at 34em (~70 characters).
- **Control** (600, 16px, sans): buttons, fields, article sub-heads (h3), footer links, the article fact list.
- **Label** (400–600, 14px, sans, sentence case): field marks, filter toggles, overview rows, share buttons. Nothing meant to be read goes below this.

### Named Rules
**The Two Voices Rule.** Read in the serif, operate in the sans. Headlines, summaries and prose are Literata; marks, navigation and controls are Fira Sans Condensed.

**The Opt-in Figures Rule.** Tabular figures are applied per element (times, counts), never to body text, so hyphens stay hyphens.

## Layout

The frame is one pair of outer margins (20→48px), one gutter (20→32px) and one axis. The right zone is `(100% − gutter) × 0.58`; every section that uses the axis builds its last column from that value, so the axis lands on the same pixel whatever the column count. Content is capped at 1440px and centred with equal margins at wider widths.

- **Two-zone sections** (masthead and lead, method, footer): side notes left, text on the axis from 1024px; one column below.
- **The feed**: one column on phones with marks inline above each headline; from 768px a marks column (≤11rem) beside the text; from 1024px a filter rail, a marks column (≤12rem) and the text on the axis. Rows are subgrids, so every row's marks and text share the same tracks.
- **The article**: marks in a side column (sticky from 1024px), headline and brief on the axis.
- **Rhythm**: page sections are separated by the section step (72→128px), clearly larger than any gap inside a section. Feed rows are 12px apart in block padding; day groups open with 40px.
- Targets are at least 44px on controls (40px for filter toggles).

### Named Rules
**The One Axis Rule.** Any new section that splits text from notes registers its text to the shared axis value; never introduce a second split ratio.

## Elevation & Depth

Flat. There are no shadows at rest or in state. Depth is tonal: ground → raised → high for hover, and sunk for code and the dialog backdrop. The only line in the system is Rule Grey on real tables and form fields.

### Named Rules
**The Tone Not Line Rule.** Surfaces are told apart by a tone step. Filled raised panels are native to this world; outlined boxes, dividers between rows, and shadows are not.

## Shapes

Square-cornered throughout (0). A 2px radius exists only to soften the leading end of a data bar in the 7-day overview. Severity marks are stepped vertical segments (5px wide, rising 8→14px). The focus ring follows the element's square corners.

## Components

### Buttons
Plain, filled and square; they press, they do not lift.
- **Shape:** square (0).
- **Primary:** cyan fill with field ink, control type, 44px tall, 20px inline padding. "Read the brief" on the lead story.
- **Hover / Focus:** hover lifts to Bright Signal; press moves 1px down; colour transitions 150ms. Focus is the global 2px cyan ring offset 3px.
- **Quiet:** raised graphite with ink, hovering to high graphite. Share buttons and feedback buttons use the quiet treatment at label size with a 16px inline SVG icon.

### Chips (filter toggles)
- **Style:** raised graphite, slate label text, square, 40px tall, no border.
- **State:** hover to high graphite and ink; pressed (`aria-pressed`) inverts to ink fill with ground text.

### Cards / Containers
There are no cards. Stories are rows, not boxes.
- **Panels:** raised graphite, square, 20px padding (28px from 640px). Used for article context and remedial-action blocks, and for the article's side-note block on narrow screens.
- **Shadow / Border:** none.

### Inputs / Fields
- **Style:** filled raised graphite, no outline at rest, square, 44px tall, 12px inline padding, Ash placeholder.
- **Focus:** fill steps to high graphite plus the 2px cyan ring.

### Navigation
- **Header:** a plain solid bar (64px): wordmark left, section links starting on the axis, language and Telegram right.
- **Links:** sans 600; inactive slate, hover ink; current page in ink with a 2px cyan underline offset 6px. On phones a menu replaces the links; language stays visible.
- **Text links:** cyan, 1px underline at 45% opacity offset 3px, full-opacity underline on hover.

### Field Marks (signature)
The side-note column of every story: severity mark, "Exploited" in Critical Coral, time (tabular) · outlet (slate) plus "+N outlets", and the audience it hits, all at label size in Ash. Stacked in the side column from 768px; one wrapping line on phones and on the lead story.

### Severity Mark (signature)
Word plus four stepped segments, filled count 1–4 in the severity colour, empty segments in high graphite. Screen readers hear "Severity: Critical".

### Story Row (signature)
Two-ended entry: field marks left, headline (lead, serif 600) and a two-line summary (body, slate) on the axis. One stretched link per row, so one tab stop; the focus ring wraps the whole row and hover underlines the headline in cyan.

### Footer Field
The one whole-field colour section: cyan ground, field ink text, deep teal secondary text, and the wordmark set full width.

### Motion
The lead headline and the article h1 reveal behind a clip-path mask (900ms, `cubic-bezier(0.16, 1, 0.3, 1)`), the one loud motion. Masthead and lead parts rise in an 80ms stagger. Below the fold, sections enter on a scroll-driven timeline where supported and are otherwise simply visible. Reduced motion collapses everything to the final state.

## Do's and Don'ts

### Do:
- **Do** register any new text-and-notes section to the shared 42% axis.
- **Do** carry severity as word plus segment count plus colour, every time.
- **Do** separate surfaces with a tone step (ground → raised → high).
- **Do** set reading text in Literata and interface text in Fira Sans Condensed, sentence case, never below 14px.
- **Do** keep cyan for action, links, focus and the footer field.
- **Do** give every control a 44px target and the 2px cyan focus ring offset 3px.
- **Do** apply tabular figures only to times and counts.

### Don't:
- **Don't** use shadows, glows, gradients or glass.
- **Don't** outline boxes or draw dividers between rows; the only line is on real tables and form fields.
- **Don't** wrap stories in cards or stack chips on them.
- **Don't** add KPI counters or a slogan hero; data figures must be labelled lists that link into the feed.
- **Don't** put kickers, eyebrows or tiny uppercase labels above headlines.
- **Don't** round corners beyond the 2px bar end.
- **Don't** add a light theme.
