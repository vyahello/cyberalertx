# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Security practitioners** — SOC analysts, security researchers, sysadmins,
  DevOps and software engineers, enterprise security teams. They check the
  feed between tasks to learn what is being exploited right now, whether it
  touches their stack, and what to patch or hunt for first.
- **Technology readers who are not specialists** — people interested in
  cybersecurity who want to know whether a story affects them and what to do,
  without wading through jargon.
- **Two language audiences.** English readers at `/en`; Ukrainian readers at
  `/ua` (Ukrainian-sourced stories such as attacks on Ukrainian services are
  UA-only and are never auto-translated into English). Both editions are
  first-class publications.

## Product Purpose

CyberAlertX aggregates cybersecurity reporting from trusted outlets, clusters
coverage of the same event, scores severity and actionability, and publishes a
short editorial brief per story in English and Ukrainian, on the website and
two Telegram channels. Every brief answers: what happened, who is affected,
how serious it is and why, and what to do. Success means a reader knows within
seconds which stories matter to them, and trusts the brief enough to act on it
or to follow it to the original source.

## Positioning

An editorial intelligence brief, not an RSS mirror: each story is rewritten
from extracted facts (never paraphrased sentence by sentence), carries an
explicit severity rationale and concrete actions, keeps attribution to the
original reporting, and is written natively in each language rather than
translated.

## Operating Context

- Readers arrive from Telegram channel posts, search engines and direct
  visits; many read on phones.
- Content is produced by a batch pipeline: RSS ingest every 15–30 minutes →
  ranking and clustering → hourly AI render via the local Claude CLI →
  website (Next.js, ISR) and Telegram.
- The feed is read-only for visitors; there are no user accounts. Reader
  feedback is a thumbs up/down per brief. An internal `/admin` dashboard is
  token-locked.
- The project owner is the native Ukrainian editor who signs off on flagged
  Ukrainian briefs and on the editorial benchmark set.

## Capabilities and Constraints

- Stack: Python 3.11+ (FastAPI, APScheduler, SQLAlchemy) backend; Next.js 15
  App Router, React 19, TypeScript, Tailwind 3 frontend. JSON storage with
  optional Postgres (Supabase) dual-write.
- AI runs in exactly one place (`generate`). Budget: one shared fact-sheet
  extraction per story plus one render per locale (≈3 calls per bilingual
  story). The API, website and Telegram never call AI.
- Most sources ship only an RSS teaser (median 175–400 characters); the
  pipeline does not fetch full articles. Briefs must not exceed what the
  source supports.
- URL structure (`/en`, `/ua`, `/{locale}/threat/{16-hex-id}`), the `/uk → /ua`
  redirect, RSS feeds, sitemap and hreflang relationships must be preserved.
- No fabricated statistics, threat counters, quotes, research or indicators.
  Only data the pipeline really has may be displayed.

## Brand Commitments

- Name: CyberAlertX. Header lockup is the lowercase wordmark "cyberalert"
  followed by the Aperture glyph (radar rings with an alert ping) standing in
  for the X.
- Calm cyan (`#06B6D4`, hover `#22D3EE`) is the brand signal colour; the
  brighter `#00E5FF` belongs only to the glyph's ping and the OG card.
- The product stays dark. No light theme for now.
- Voice: calm, specific, no panic, no hype. "Alert, not alarmed."
- Brand assets: `frontend/public/brand/*` (glyph, logo, favicons, OG cards
  per locale), `docs/brand/*` (Telegram avatars).

## Evidence on Hand

- Real content: ~4,450 cached AI briefs (≈2,000 EN, ≈2,430 UA) in
  `data/threat_posts.json`; source items with outlet, URL, date, category,
  severity and clustering in `data/items.json`.
- Real signals per story: severity level, actionability level, source
  credibility tier, number of outlets covering the story, affected
  platforms, audiences, exploitation and impact flags.
- Absent, and not to be fabricated: subscriber or reader counts,
  testimonials, press mentions, original CyberAlertX research, IOCs beyond
  what sources state.

## Product Principles

1. Facts before prose: every claim traces to the source or is labelled as
   interpretation.
2. Severity is explained, never only asserted.
3. Each language edition is written for its own reader, with equal depth.
4. The reader's time is the scarcest resource: the most important story is
   the easiest one to find.
5. Calm authority: no manufactured urgency, no decoration standing in for
   information.

## Accessibility & Inclusion

WCAG 2.2 AA: 4.5:1 text contrast, visible focus, keyboard operation,
`prefers-reduced-motion` honoured, severity never conveyed by colour alone,
correct `lang` attributes (`uk` for the `/ua` edition) so screen readers use
the right voice.
