# CyberAlertX — Frontend

Modern cybersecurity awareness UI. Next.js App Router + TypeScript + Tailwind CSS.

## Run (development)

The frontend now server-fetches `/posts` from the Python API. Run both:

```bash
# Terminal 1 — the Python pipeline + API
cd ..
python -m cyberalertx.main once    # one ingest cycle (only needed on first run)
python -m cyberalertx.main serve   # API on http://localhost:8000

# Terminal 2 — the Next.js dev server
cd frontend
cp .env.local.example .env.local   # sets API_URL=http://localhost:8000
npm install
npm run dev                        # http://localhost:3000
```

When `API_URL` is unreachable the page still renders — `ThreatFeed` shows a
"no threats to show right now" empty state with a hint. Layout is stable
regardless of backend health.

## Builds

```bash
npm run build && npm run start
npm run type-check
```

## End-to-end tests

Playwright (`@playwright/test`) drives Chromium against a configurable target.
Specs live in `tests/e2e/` — `smoke.spec.ts` covers landing, feed, healthz,
locale toggle and 4xx/5xx network guards; `journeys.spec.ts` exercises article
detail navigation, the trending section, Ukrainian deep-links, basic a11y
heading order, and a mobile viewport pass.

```bash
# One-time, per machine (downloads browsers under ~/.cache/ms-playwright):
npx playwright install chromium

# Default target = http://localhost:3000 — Playwright boots `next dev` for you.
npm run test:e2e

# Run with the UI runner:
npm run test:e2e:ui

# Target the production deployment (no local server spun up):
npm run test:e2e:prod
# …or any environment via BASE_URL:
BASE_URL=https://staging.cyberalertx.com npx playwright test
```

CI gets `forbidOnly`, two retries, and `github` + `html` reporters. Traces,
screenshots, and video are kept on failure.

## Architecture

```
frontend/
├── app/
│   ├── globals.css          design tokens layered on Tailwind
│   ├── layout.tsx           fonts (Inter + JetBrains Mono), metadata
│   └── page.tsx             ↓ trivial — delegates to HomeShell
├── components/
│   ├── layout/
│   │   ├── HomeShell.tsx          single "use client" envelope; owns
│   │   │                          locale + filter state for the whole page
│   │   ├── Header.tsx             sticky top bar w/ live pulse
│   │   └── LanguageSwitcher.tsx
│   ├── hero/
│   │   ├── Hero.tsx               headline + live pulse + CTA
│   │   └── LivePulse.tsx          two-circle pulse (heartbeat, not strobe)
│   ├── threat/
│   │   ├── ThreatCard.tsx         the main piece — 8-tier hierarchy
│   │   ├── ThreatFeed.tsx         vertical list + entrance stagger
│   │   ├── ThreatBadge.tsx        Critical / High / Medium / Low
│   │   ├── ActionabilityBadge.tsx urgent / recommended / informational
│   │   ├── CredibilityBadge.tsx   source + tier shield
│   │   ├── QuickFacts.tsx         mobile-scan chips
│   │   └── ActionPanel.tsx        do / don't, side-by-side on desktop
│   ├── filters/
│   │   ├── FilterPanel.tsx        the actual filter UI (shared)
│   │   ├── FilterGroup.tsx        generic pill multi-select primitive
│   │   └── MobileFilterDrawer.tsx bottom sheet for phones
│   └── trending/
│       └── TrendingSection.tsx    horizontal scroller of hot items
└── lib/
    ├── types.ts             ThreatPost + filter state (mirrors backend)
    ├── mock-data.ts         14 realistic posts (EN + UK, all levels)
    ├── i18n.ts              EN + UK strings, single t-table per locale
    └── cn.ts                clsx + tailwind-merge helper
```

**Server vs client.** Only `HomeShell`, the filter UI, the language
switcher, and the drawer are `"use client"`. Everything else (cards,
badges, hero, trending, action panel) is a server component and ships
zero JS to the browser.

## Design tokens

All of the design system lives in `tailwind.config.ts`. The key sets:

- `bg.{base|elevated|elevated-2|inset}` — page → card → hover → footer
- `border.{subtle|strong|focus}` — three rungs of separation
- `text.{primary|secondary|tertiary}` — three rungs of readability
- `accent.{DEFAULT|soft|ring}` — the single brand accent (calm blue)
- `level.{critical|high|medium|low}.{fg|bg|border}` — threat colors
- `trust.{trusted|verified|unverified}.{fg|bg}` — credibility colors
- `signal.live` — the "currently active" pulse green

All threat / trust colors are kept below ~50% saturation by design. The
product reads alert, not alarmed.

## Locales

EN (default) + UK. Switch via the header toggle. To add a third locale:
extend `lib/i18n.ts` with a new `StringTable` constant and add the code
to the `LOCALES` array in `LanguageSwitcher.tsx`.

## Data flow

```
Python pipeline                Next.js frontend
─────────────────              ──────────────────
JsonNewsStore (data/items.json)
        │
        ▼
ContentGenerator               app/page.tsx (server component)
+ ThreatPostCache                      │
        │                              │ fetch(`${API_URL}/posts`)
        ▼                              ▼
FastAPI (`/posts` etc.)  ─────────► lib/api.ts  ──► HomeShell  ──► ThreatFeed
        ▲                              │
        │ ISR 60s                      │ (server-rendered HTML)
        └──────────────────────────────┘
```

Server-fetch only — the browser never talks to the API directly, so the JS
bundle stays tiny (~16 kB route / 119 kB First Load). Filters run client-side
in `HomeShell` against the hydrated `posts` array.

## Caching

Three layers, each with a different purpose:

| Layer | TTL | Purpose |
|---|---|---|
| `ThreatPostCache` (Python, on disk) | until invalidated | Avoid re-generating the same `ThreatPost` from the same `NewsItem`. Keyed by fingerprint. |
| `Cache-Control` on the API response | none yet — add if needed | Reverse-proxy / CDN cache between API and Next.js. |
| Next.js ISR | 60s (`export const revalidate = 60`) | The rendered HTML is served from the edge for 60s; revalidation happens in the background. |

`lib/mock-data.ts` is still present — kept for tests and offline design work,
no longer pulled into the production bundle.
