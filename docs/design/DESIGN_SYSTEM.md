# CyberAlertX design system — "field guide on the axis"

Source of truth for values: `frontend/tailwind.config.ts` (Tailwind tokens) and
`frontend/app/globals.css` (CSS custom properties, components, motion). This
document explains them. If the two disagree, the code wins and this file is
stale.

---

## 1. Idea

Every story is an **entry in a field guide**. Its *field marks* — severity and
why, whether it is being exploited, when, who reported it and how many outlets
confirmed it — hang in a fixed side-note margin to the left of one vertical
**axis** at 42% of the content width. Headlines and text hang to the right of
it. The same axis organises the masthead, the lead story, the feed, the article
and the footer, so the whole product reads as one edited publication rather
than a stack of widgets.

What it refuses: chip-stacked cards, KPI counters, a slogan hero, gradients,
glows, glass, outlined boxes, tiny uppercase labels.

## 2. How the three design skills were combined

| Skill | Role in this redesign | What it decided |
|---|---|---|
| **UI UX Pro Max** | Design-system research and UX rules | Recommended an *Editorial Grid / Swiss* style and an editorial serif + sans pairing for news. Its first recommendation (Cyberpunk UI, Matrix green) and its palettes were **rejected** as contradicting the brief and the brand. Its UX/accessibility rules (4.5:1 contrast, 44px targets, visible focus, reduced motion, deep links) are applied throughout. |
| **Taste** | Art direction and visual implementation | Dealt the *"printed annual" (editorial-report)* direction: one fixed vertical axis at 42%, side notes left of it, text right of it, solid colour fields instead of decoration. Its house rules (no eyebrows, no hairlines, no gradients, no shadows at rest, two typefaces, sentence-case labels, ≥13px text) are enforced. Its inspector measured before/after. |
| **Impeccable** | Product record, direction contract, critique and refinement | PRODUCT.md, the direction contract (`.impeccable/surfaces/…`), the Read-mode rule that the world owns the frame while the reading column stays calm, the craft floor, the mechanical detector (0 findings at the end) and the finish review. |

Where the skills conflicted, the order of precedence was: **the owner's brief
and brand commitments → accessibility → Taste house rules → dealt blueprints**.

### Deliberate deviations from the dealt direction (Taste)

| Dealt | Done instead | Why |
|---|---|---|
| Imbue + Albert Sans | Literata + Fira Sans Condensed | Neither dealt face has Cyrillic; the Ukrainian edition would fall back to system fonts. |
| Hero: upper 60% empty, statement on axis | Masthead left of the axis, **lead story** on it | The brief requires the first screen to show the most important intelligence. |
| List: cards folding into spines (pinned, 4 screens) | Two-ended rows | A scroll-jacked deck is hostile to scanning news. |
| About: wide photo + colour tile | Side facts + paragraph | No honest photograph of the subject exists. |
| ≥4 real pictures | None | No per-story imagery exists, outlets' images are not licensed for reuse, and the brief forbids decoration. The only figure is a data figure (7-day overview). |
| Headlines ≤ 2 lines | Real pipeline headlines (6–14 words) may wrap to 3 | Headlines are content, not slogans. |

## 3. Colour

One ground, one ink, one signal colour; surfaces are separated by **tone
steps**, never by outlines or shadows. Dark only (a brand commitment).

| Token | Value | Use | Contrast on ground |
|---|---|---|---|
| `ground` | `#0E1116` | page | — |
| `ground-raised` | `#161B22` | filled panels, inputs, toggles, hover | — |
| `ground-high` | `#1E242D` | hover on raised, empty bar segments | — |
| `ground-sunk` | `#0A0D11` | code blocks, dialog backdrop | — |
| `ink` | `#ECEEF1` | all running text and headlines | 16.3:1 |
| `ink-muted` | `#A6AEBA` | secondary text (summaries, standfirst) | 8.5:1 |
| `ink-faint` | `#8C95A3` | metadata floor | 6.3:1 (5.2:1 on `ground-high`) |
| `signal` | `#06B6D4` | primary button, links, focus ring, footer field | 7.8:1 |
| `signal-ink` / `signal-deep` | `#071318` / `#0B3A44` | text on the cyan field | 7.8:1 / 5.1:1 |
| `sev-critical` | `#FF5C6C` | severity | 6.3:1 |
| `sev-high` | `#FF9F43` | severity | 9.3:1 |
| `sev-medium` | `#EDE58A` | severity | 14.6:1 |
| `sev-low` | `#8C95A3` | severity (neutral by intent) | 6.3:1 |
| `line` | `#2A313B` | real tables and form fields only | — |

The severity colours were re-stepped and checked with the dataviz palette
validator: colour-blind separation (worst adjacent pair ΔE 10.9, deuteranopia)
and the normal-vision floor (ΔE 16.2) both pass. Severity is **never colour
alone**: every mark carries the word and a 1–4 segment count.

The brand's brighter `#00E5FF` stays reserved for the glyph's alert ping and the
OG card.

## 4. Type

| Role | Face | Notes |
|---|---|---|
| Reading (headlines, standfirsts, article text, feed summaries) | **Literata** (variable, optical size 7–72) | One family is a crisp display face at 88px and a sturdy text face at 17px. Latin + Cyrillic. |
| Interface (field marks, navigation, controls, labels) | **Fira Sans Condensed** | Narrow enough for one-line metadata; standard Cyrillic forms. (Sofia Sans was tried first and dropped: its default Cyrillic draws Bulgarian letter shapes.) |
| Logotype only | Space Grotesk 600 | The ten letters of "cyberalert"; part of the logo, not the type system. |
| Code, commands, hashes, indicators | JetBrains Mono 400 | Not preloaded; only inside `<code>`/`<pre>`. |

Five steps, nothing meant to be read below 14px:

| Step | Size | Use |
|---|---|---|
| `small` | 14px | field marks, labels, controls |
| `body` | 17→18px, leading 1.6 | running text |
| `lead` | 19→22px | feed headlines, standfirsts |
| `head` | 28→44px | article h1; section h2 uses 26→36px; article h2 22→28px |
| `display` | 48→88px | masthead h1 only |

Tabular figures are **opt-in** (`.tnum`). The old site set `tnum` on the whole
body, which in Inter also swapped the hyphen for a wide tabular glyph and
rendered every compound word as "real - world".

## 5. Space and frame

- Outer margins `--margin`: 20→48px, equal on both sides at every width.
- Gutter `--gutter`: 20→32px.
- Axis: the right zone is `--right = (100% − gutter) × 0.58`. Every section
  that uses the axis builds its last column from `--right`, so the axis lands on
  the same pixel whatever the column count (2-column `.axis`, 3-column
  `.feed-grid` with filter rail + marks + text).
- Content max width 1440px (90rem); centred with equal margins at 1920.
- Section rhythm `section`: 72→128px between page sections, clearly larger
  than any gap inside a section.
- Reading measure: 68ch.
- Radius: square system (0); 2px only where a bar end needs softening.

## 6. Components

| Component | File | Notes |
|---|---|---|
| SeverityMark | `components/marks/SeverityMark.tsx` | word + 4 segments + colour; screen readers hear "Severity: Critical" |
| FieldMarks | `components/marks/FieldMarks.tsx` | severity, exploited, time, source (+N outlets); stacked in the side column from `md`, inline on phones |
| TimeAgo | `components/marks/TimeAgo.tsx` | relative time with absolute date in `title`, `<time datetime>` |
| StoryRow | `components/feed/StoryRow.tsx` | one stretched link per row (one tab stop), focus ring on the row |
| FeedSection | `components/feed/FeedSection.tsx` | filters, live result count (`aria-live`), day groups, empty states, deep links `?level=`, `?exploited=1`, `?q=` |
| FilterPanel / FilterSheet | `components/feed/*` | toggle buttons with `aria-pressed`; on phones a native `<dialog>` sheet |
| LeadStory | `components/home/LeadStory.tsx` | masthead + most significant story (`lib/significance.ts`) |
| PriorityList | `components/home/PriorityList.tsx` | two-ended rows |
| ThreatOverview | `components/home/ThreatOverview.tsx` | 7-day counts by severity / exploited / topic; every row links into the feed |
| MethodSection | `components/home/MethodSection.tsx` | how the product works, outlets in this edition (from data) |
| ThreatDetail | `components/threat/ThreatDetail.tsx` | the brief as one article; marks in a sticky side column |
| RichText | `components/article/RichText.tsx` | paragraphs, `code`, fenced blocks, CVE → NVD links; text nodes only |
| Header / SiteNav / MobileMenu / LanguageSwitcher | `components/layout/*` | plain solid bar; topics as navigation; language always visible |
| SiteFooter | `components/layout/SiteFooter.tsx` | the one whole-field colour section; wordmark full width |

Buttons: `.btn-primary` (cyan fill, dark ink, ≥44px), `.btn-quiet` (raised
tone). Links in text: cyan with underline offset. Inputs: filled, no outline at
rest, cyan focus ring.

## 7. Motion

- Signature: the lead headline (and article h1) reveals with a clip-path mask,
  900ms, strong ease-out.
- Masthead and lead parts rise in sequence (80ms stagger).
- Below the fold, sections and day groups enter with a scroll-driven
  animation (`animation-timeline: view()`) where supported; elsewhere they are
  simply visible. Nothing is hidden by default.
- Controls: colour/tone transitions 150ms, 1px press.
- `prefers-reduced-motion: reduce` collapses all of it to the final state.

## 8. Accessibility rules in force

WCAG 2.2 AA contrast for every text token (lowest 5.1:1); visible 2px focus
ring with offset on every control; one tab stop per story; 44px minimum targets
on phones; `lang="uk"` on the Ukrainian edition; heading outline without gaps
(h1 → h2 → h3 → h4, adjusted on topic pages); landmarks (banner, nav, main,
contentinfo); `aria-live` result count when filters change; native `<dialog>`
for the filter sheet; skip link; no information carried by colour alone.
