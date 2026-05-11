# CyberAlertX

**Real-time cybersecurity awareness for normal users, developers, and IT professionals.**

Threat intelligence — ingested from trusted sources, ranked for impact, translated into human language, served as a calm, scannable feed.

CyberAlertX is **not** a blog, not a hacker dashboard, not a Twitter firehose. It's a focused product whose job is to answer three questions for every cybersecurity story:

1. **What happened?**
2. **Does it affect me?**
3. **What should I do?**

---

## Table of contents

- [Architecture overview](#architecture-overview)
- [Repository layout](#repository-layout)
- [Local setup](#local-setup)
- [Daily workflow](#daily-workflow)
- [Multilingual content](#multilingual-content)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

---

## Architecture overview

```
                ┌─────────────────────────────────────────────┐
                │              Python pipeline                │
RSS feeds ────▶ │ ingest → filter → categorize → rank → store │
                │                                             │
                │            ContentGenerator                 │
                │  rule-based  ←  optional LLM (Anthropic)    │
                │       │                                     │
                │       ▼                                     │
                │   ThreatPost cache (JSON)                   │
                └──────────────────┬──────────────────────────┘
                                   │
                              FastAPI surface
                          /posts, /posts/{id},
                       /posts/trending, /posts/latest
                                   │
                                   ▼
                        ┌────────────────────┐
                        │   Next.js App      │
                        │  (server-rendered) │
                        │                    │
                        │  /[locale]         │  ← homepage feed
                        │  /[locale]/threat  │  ← detail pages
                        │   /[id]            │
                        └────────────────────┘
```

**Backend** is a single Python process per role (pipeline + API), reads/writes JSON files on disk, no database, no queue, no workers.

**Frontend** is a Next.js App Router project, server-rendered with ISR, ~120 kB First Load JS, fully localized via URL routing.

**Multilingual** is structural, not runtime: each post ships with a `translations` object containing one or more locales. The frontend filters to the active locale before rendering — no mixed-language content is ever shown.

---

## Repository layout

```
cyberalertx/
├── cyberalertx/             ← Python package (the intelligence pipeline)
│   ├── pipeline/            ← ingest, normalize, filter, categorize,
│   │                          platforms, audience, actionability,
│   │                          credibility, ranker
│   ├── ai/                  ← ContentGenerator + providers + templates
│   │   ├── providers/       ← Anthropic + OpenAI stub
│   │   ├── rule_based.py    ← offline fallback (the MVP default)
│   │   └── cache.py         ← per-(fingerprint, locale) on-disk cache
│   ├── api/                 ← FastAPI surface
│   │   └── app.py           ← /posts, /posts/{id}, trending, latest
│   ├── sources/             ← RSS source plugins
│   ├── storage/             ← JSON store (atomic writes, dedup)
│   ├── models.py            ← NewsItem domain type
│   ├── config.py            ← settings (env-overridable)
│   └── main.py              ← CLI: once, run, top, generate, serve
├── tests/                   ← pytest suite (140+ tests)
├── frontend/                ← Next.js + TypeScript + Tailwind
│   ├── app/                 ← App Router pages
│   │   ├── [locale]/        ← homepage + detail under each locale
│   │   ├── layout.tsx       ← fonts, metadata, viewport
│   │   └── page.tsx         ← root → redirects to default locale
│   ├── components/          ← grouped by feature domain
│   │   ├── threat/          ← cards, badges, action panel, detail
│   │   ├── filters/         ← sidebar + mobile drawer
│   │   ├── hero/, trending/ ← homepage sections
│   │   └── layout/          ← header, language switcher, shell
│   ├── lib/                 ← types, api client, i18n, mock data
│   └── tailwind.config.ts   ← single source of truth for design tokens
├── data/                    ← JSON state (not committed)
│   ├── items.json           ← ingested NewsItems
│   └── threat_posts.json    ← generator output cache
├── requirements.txt
└── README.md                ← you are here
```

---

## Local setup

You need **Python 3.13+** and **Node 20+**.

### Backend

```bash
git clone <repo> cyberalertx
cd cyberalertx

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Verify with the test suite:

```bash
python -m pytest tests/ -q
# ……………………………………………………………………………… 136 passed
```

### Frontend

```bash
cd frontend
cp .env.local.example .env.local   # sets API_URL=http://localhost:8000
npm install
```

Verify with a type-check + build:

```bash
npm run type-check
npm run build
```

---

## Daily workflow

Run two terminals. The pipeline writes; the API + frontend read.

### 1. Ingest fresh news (one-shot or scheduled)

```bash
# Single cycle — fetches, filters, categorizes, scores, persists to data/items.json
python -m cyberalertx.main once

# Continuous on a 15-minute interval
python -m cyberalertx.main run --interval 15
```

### 2. Serve the API

```bash
python -m cyberalertx.main serve --port 8000

# Endpoints:
#   GET /healthz                         — liveness + stored_items count
#   GET /posts?limit=50&language=en      — main feed
#   GET /posts/trending?limit=10         — urgent_action / Critical only
#   GET /posts/latest?limit=20           — most recently published
#   GET /posts/{id}                      — single post (detail page)
```

### 3. Run the frontend

```bash
cd frontend
npm run dev    # http://localhost:3000 → redirects to /en
```

### 4. Inspect content from the CLI

```bash
# Top N posts (raw JSON output)
python -m cyberalertx.main top --limit 10

# Force-regenerate ThreatPost content (compact summary by default)
python -m cyberalertx.main generate --limit 5

# Full ThreatPost printout
python -m cyberalertx.main generate --limit 3 --print-only

# Ukrainian rendering (force locale on the generator)
python -m cyberalertx.main generate --limit 5 --language uk

# Opt into the LLM for one run (requires ANTHROPIC_API_KEY)
ANTHROPIC_API_KEY=sk-... python -m cyberalertx.main generate --limit 5 --use-llm
```

### 5. Test the API directly

```bash
curl http://localhost:8000/healthz | jq

# Top item, pretty-printed
curl "http://localhost:8000/posts?limit=1" | jq '.items[0] | {id, source, threat_level, available_locales}'

# Filter by locale (only items with that translation available)
curl "http://localhost:8000/posts?language=uk&limit=5" | jq '.total'
```

### 6. Switch UI language

Click `EN` / `UK` in the header. The URL changes (`/en/...` ↔ `/uk/...`), the entire UI re-renders, and any post missing a translation in the new locale is filtered out automatically — no mixed-language content is ever displayed.

---

## Multilingual content

The data model has **one** shared set of metadata per post (threat level, source, timestamps, platforms) and **N** localized text bundles inside `translations`:

```jsonc
{
  "id": "5a38a188af401d84",
  "source": "The Hacker News",
  "source_tier": "trusted",
  "threat_level": "Critical",
  "actionability_level": "urgent_action",
  "available_locales": ["en"],
  "translations": {
    "en": {
      "title": "Hackers Used AI to Develop First Known Zero-Day 2FA Bypass…",
      "short_summary": "…",
      "why_it_matters": "Working exploit, in the wild, today. Patch or mitigate now.",
      "affected_users": ["Anyone with 2FA on the affected services"],
      "what_to_do": ["Watch for the vendor advisory…", "…"],
      "what_not_to_do": ["Don't assume 2FA alone is enough…"],
      "quick_facts": ["Actively exploited", "Active exploit"],
      "reading_time_seconds": 22
    }
  }
}
```

### Generation flow

```
NewsItem (data/items.json)
       │
       ▼
ContentGenerator.generate(item, language="en")  →  EN ThreatPost
ContentGenerator.generate(item, language="uk")  →  UK ThreatPost   (only when LLM is enabled —
                                                                    rule-based path can't translate
                                                                    raw_content)
       │
       ▼
ThreatPostCache  (keyed by fingerprint:locale)
       │
       ▼
_PostService.render(item)
       │
       ▼
API response:   { available_locales: [...], translations: {...} }
```

### Routing

- `/` → 307 redirect to `/en`
- `/en` and `/uk` are statically generated at build time (`generateStaticParams`)
- `/en/threat/{id}` and `/uk/threat/{id}` are server-rendered on demand (ISR, 60s)
- The language switcher is a `<Link>` to the current path with the opposite locale prefix — bookmarkable, refresh-stable, no client-side flicker

### Handling missing translations

When a post exists but has no content for the active locale:

- On the homepage, it's silently filtered out (`postsAvailableIn`)
- On a direct detail link, the detail page renders an explicit "this threat isn't translated yet" empty state and offers a one-tap switch to a locale that does have content

---

## Deployment

### Frontend → Vercel (one click)

```bash
cd frontend
vercel --prod
```

Set the `API_URL` environment variable in the Vercel project settings to point at the public Python API URL (e.g. `https://api.cyberalertx.com`). Everything else is static.

### Backend → simple VPS

No Kubernetes, no Docker orchestration. Two processes managed by systemd:

```ini
# /etc/systemd/system/cyberalertx-api.service
[Unit]
Description=CyberAlertX API
After=network.target

[Service]
Type=simple
WorkingDirectory=/srv/cyberalertx
ExecStart=/srv/cyberalertx/venv/bin/python -m cyberalertx.main serve --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/cyberalertx-pipeline.timer
[Unit]
Description=CyberAlertX pipeline cycle (every 15 minutes)

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/cyberalertx-pipeline.service
[Service]
Type=oneshot
WorkingDirectory=/srv/cyberalertx
ExecStart=/srv/cyberalertx/venv/bin/python -m cyberalertx.main once
```

Put nginx in front of uvicorn for TLS termination + rate-limiting + access logs.

### Environment variables

| Variable                    | Side     | Purpose                                                    | Default                  |
| --------------------------- | -------- | ---------------------------------------------------------- | ------------------------ |
| `API_URL`                   | Frontend | Where Next.js fetches posts from                           | `http://localhost:8000`  |
| `CYBERALERTX_INTERVAL_MIN`  | Backend  | Scheduled fetch interval in minutes                        | `15`                     |
| `CYBERALERTX_AI_ENABLE_LLM` | Backend  | Opt into the LLM provider (`1` / `0`)                      | `0` (offline by default) |
| `CYBERALERTX_AI_MODEL`      | Backend  | Anthropic model when `enable_llm` is on                    | `claude-opus-4-7`        |
| `ANTHROPIC_API_KEY`         | Backend  | Required only when `CYBERALERTX_AI_ENABLE_LLM=1`           | unset                    |
| `CYBERALERTX_AI_CACHE`      | Backend  | Cache generated posts to disk (`1` / `0`)                  | `1`                      |

---

## Troubleshooting

### Empty feed on the homepage

- Run `python -m cyberalertx.main once` to seed `data/items.json` for the first time.
- Hit `http://localhost:8000/healthz` — `stored_items` should be > 0.
- If `stored_items` is 0 but the pipeline ran, check the source feed URLs in `cyberalertx/config.py` — one or more may have moved.

### API unreachable from the frontend

- The Next.js page falls back to an empty-state automatically — it never errors.
- Check `frontend/.env.local` has `API_URL=http://localhost:8000`.
- `curl http://localhost:8000/healthz` should return 200.
- If you started `next dev` before the API was up, hard-refresh (`Cmd-Shift-R`) to bust the ISR cache.

### Stale cache after iterating on prompts

- The generator caches output to `data/threat_posts.json`. To force regeneration:
  - Delete `data/threat_posts.json`, OR
  - Set `CYBERALERTX_AI_CACHE=0` for a single run.
- The cache key is `fingerprint:locale`, so editing an item's title in the source feed does *not* invalidate the cache — the fingerprint is URL-based.

### "This threat isn't translated yet" on every UK page

This is **expected** with rule-based-only generation: the rule-based generator can't translate `raw_content`, so an EN article only ships an EN translation. To get full multilingual coverage:

1. Set `ANTHROPIC_API_KEY` and `CYBERALERTX_AI_ENABLE_LLM=1`.
2. Re-run `python -m cyberalertx.main once` (or just hit `/posts` — the API generates both locales when the LLM provider is wired).
3. Verify with `curl "http://localhost:8000/posts?limit=1" | jq '.items[0].available_locales'` — should now show `["en", "uk"]`.

### Backend mismatch ("Cannot read properties of undefined")

If you upgraded the backend mid-session and the frontend renders blank cards: the on-disk cache (`data/threat_posts.json`) may have legacy entries from before the locale-aware cache landed. Delete the file and let it rebuild — the JSON store at `data/items.json` is the source of truth, not the cache.

### Tests fail after pulling new commits

```bash
# Backend
source venv/bin/activate
pip install -r requirements.txt   # in case deps changed
python -m pytest tests/ -q

# Frontend
cd frontend
npm install                       # in case deps changed
npm run type-check
npm run build
```

---

## License

MIT — see `LICENSE`.
