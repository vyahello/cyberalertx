# Phase 3 — Media Engine: final report

> **Historical record.** Paths such as `$APP_HOME-redesign` predate the release layout; see [docs/README.md](../README.md) for current documents.

**Status:** branded cards are live in the worktree for every story edition.
Illustrations are **implemented but not operational**. No image provider is
configured, so no real image has been generated. Everything was built and
tested in `$APP_HOME-redesign` only. Nothing was deployed, committed,
pushed or sent. Production (`$APP_HOME`) has a clean git status and no
`data/media/`.

## 1. Media architecture before this phase

- Two static social images (`/brand/og-image.png`, `og-image-ua.png`). Every
  article shared the same one.
- Telegram used `sendMessage` with the link preview pinned to the article's
  deep link, so the preview showed that generic site image.
- There was no per-story image, no image storage and no media metadata.
- `scripts/brand-png.js` produced the brand PNGs at build time.

## 2. Existing components reused

- Next.js `next/og` (Satori + resvg) and `sharp`, both already installed.
- `fetchPost` and `API_BASE` on the frontend.
- The Intelligence Core (`intel.engine.run`): stories, scores, Daily Top 10,
  Breaking, fact sheets and evidence.
- `ThreatPostCache`, `FactSheetCache` and `JsonNewsStore`.
- The JSON-plus-lock storage pattern, the admin gate, `ui.page` and its CSP.
- `TelegramPublisher` (extended, not duplicated), `render_message`,
  `TelegramSettings` and `publish_once`.

## 3. New components

**Backend:**
- `cyberalertx/media/` (`assets`, `cards`, `illustrations`, `engine`)
- `cyberalertx/tools/media.py`
- `cyberalertx/api/admin/media_page.py`

**Frontend:**
- `frontend/lib/media/` (`card.tsx`, `spec.ts`, `illustration.ts`)
- The card route and the `/media` illustration route

Details are in `MEDIA_ENGINE.md`.

## 4. Branded card rendering

Each card is a JSX layout rendered to PNG by Satori/resvg on request, from the
edition's own headline, severity, category, exploited mark, date and CVE id.

- Headline size is stepped and line-clamped (3 lines landscape, 5 portrait).
- Fonts are static OFL TTFs, licences included.
- Output is deterministic: identical inputs give identical md5.
- URLs are versioned by a hash of the visible inputs.
- If rendering fails, the route returns 503 and pages fall back to the brand
  image.

## 5. Localization

- EN and UA cards are built only from each edition's own text. An edition with
  no text gets no card (404, brand fallback).
- Severity and category labels, the exploited mark and the date are localized
  (UA dates in Europe/Kyiv).
- Alt text and the illustration caption are written in each language.
- The longest UA headline (105 characters) was checked: it fits in 3 lines.

## 6. AI illustration provider: documented blocker

None is configured. The only AI credential is `ANTHROPIC_API_KEY`, which is
for text; Anthropic models do not generate images. No other image-provider
key exists. I checked env var names only and printed no values.

The `ImageProvider` protocol, its registry and
`CYBERALERTX_IMAGE_PROVIDER` (default `none`) are in place. Choosing and
paying for a provider is the owner's decision. Until then the engine runs in
branded-card-only mode, records no failures and makes no calls.

## 7. Selection rules for illustrations

All of these must hold:
- in scope
- verified or partially verified
- confidence not low
- at least 300 characters of source text, or a fact sheet

At least one of these must also hold:
- Breaking
- in the Daily Top 3
- importance ≥ 55
- exploitation confirmed with importance ≥ 45

On current worktree data, 10 stories qualify. A per-run cap of 3 calls,
3 attempts per input set, and reuse until the facts change keep cost bounded.

Prompts use verified facts only. Exploitation is drawn only when it is
confirmed. Brands, text, faces and anything photorealistic are excluded.

## 8. Formats and dimensions

| Variant | Size |
|---|---|
| `og` | 1200×630 |
| `telegram` | 1200×675 |
| `threads-portrait` | 1080×1350 |
| `threads-square` | 1080×1080 |
| `preview` | 640×360 |
| `article` (illustrations) | 1600×900 |

Every variant comes as PNG, WebP and AVIF. On the site, `<picture>` serves
AVIF, then WebP, then PNG.

## 9. Storage

- `data/media/assets.json`: the records. Writes take a lock, are atomic, and
  the in-process cache is keyed by inode, mtime and size.
- `data/media/files/{sha256}.{ext}`: validated illustration bytes.
- `data/media/usage.jsonl`: provider calls.
- Cards store no bytes.
- Illustrations are served internally by the API at `/media/{id}`. nginx does
  not route that path. The public route is the site's `/media/{id}/{variant}`,
  which re-validates every file before serving it.

## 10. Asset metadata

`MediaAsset` holds ids, story, type, locale, storage key, public URL and
variants, MIME, dimensions and aspect ratio, size, alt text per locale,
source and licence, generation method, model and prompt version, prompt,
input hash, member articles, status, attempts, last error, cost and
timestamps. The full field list is in `MEDIA_ENGINE.md`.

## 11. Website and Open Graph

- `og:image` and `twitter:image` use the article's own versioned card, with
  width, height, type and localized alt.
- JSON-LD `NewsArticle.image` points to the same card.
- The article figure and the home lead image appear only when a validated
  illustration exists, with explicit dimensions and the "not a photo"
  caption.
- Feed rows remain text-only (deliberate).

## 12. Telegram

- The existing publisher gains `send_photo()`.
- New caption renderer with a 1024-character limit, counted in UTF-16 units
  as Telegram counts them.
- `CYBERALERTX_TELEGRAM_ATTACH_IMAGES` defaults to **off**.
- If the photo fails for one post, that post goes out as text. Errors that
  affect the whole channel stop the channel.
- Dry run logs the photo URL and caption.
- Tested only against `httpx.MockTransport` and fake chat ids. **No message
  was sent.**
- Telegram fetches the card URL itself, so enable this only after the cards
  are deployed.

## 13. Threads preparation

Portrait and square variants exist for both editions, for both cards and
illustrations. There is no publishing, no OAuth and no account connection.

## 14. AI calls and costs

**0 calls, $0.** No text model and no image model were called in this phase.

## 15. Files

**Created:**
- `cyberalertx/media/{__init__,assets,cards,illustrations,engine}.py`
- `cyberalertx/tools/media.py`
- `cyberalertx/api/admin/media_page.py`
- `tests/test_media.py`
- `frontend/lib/media/{card.tsx,spec.ts,illustration.ts}`
- `frontend/app/[locale]/threat/[id]/card/[file]/route.ts`
- `frontend/app/media/[asset]/[file]/route.ts`
- `frontend/assets/fonts/` (4 TTF + 3 OFL licences)
- `frontend/tests/e2e/media.spec.ts`
- `docs/media/MEDIA_ENGINE.md`
- `docs/media/PHASE3_REPORT.md`

**Modified:**
- `cyberalertx/api/app.py`: internal `/media`, `media` field, `/admin/media(.json)`
- `cyberalertx/api/admin/ui.py`: nav entry
- `cyberalertx/publish/{telegram,format,config,service}.py`
- `frontend/lib/{types,i18n}.ts`
- `frontend/app/[locale]/threat/[id]/page.tsx`
- `frontend/components/seo/JsonLd.tsx`
- `frontend/components/threat/ThreatDetail.tsx`
- `frontend/components/home/LeadStory.tsx`

## 16. Dependencies added

**None.** Python and npm dependency lists are unchanged.

## 17. Tests and actual results

- **pytest:** 1237 passed, 4 skipped. `tests/test_media.py` adds 37 tests:
  cards, eligibility, prompt rules, storage validation and path safety, mock
  provider success, timeout, failure, retry limit, reuse and regeneration, the
  per-run cap, dry run, storage failure, API exposure, admin lock and CSP, and
  Telegram on/off, fallback, fatal error, dry run and caption limit.
- **mypy (strict):** clean, 98 files.
- **tsc:** clean. **`next build`:** OK.
- **Playwright:** 38 passed, 2 skipped. 2 failed: `/healthz` against bare
  `next start`, because there is no nginx in the local setup to route it to
  the API. That is environment-only and pre-existing.
- **`tools.media validate-cards`:** 12 cards × 5 variants, 0 failures.

Bugs found and fixed during this work:
- `NoProvider` counted as a configured provider, so it would have logged
  failed attempts.
- The asset-index cache went stale when two writes landed in the same kernel
  tick.
- `constructor.png` slipped past variant validation through a prototype
  lookup: the illustration route returned 200 and the card route 503.

## 18. Browser visual verification

Checked with Chromium screenshots:
- EN and UA cards in all variants, with and without art.
- The EN article on desktop (1440) and mobile (390) with an illustration: the
  AVIF source was served at 1600×900, with alt text and caption.
- The UA article on mobile without an illustration.

No horizontal overflow at any width.

The illustration used for these checks was a **local SVG test fixture**
rasterised by sharp, not AI output. It was removed afterwards.

## 19. Remaining limitations

- No real image generation has happened; a provider is needed (item 6).
- Cards render on request. A cold PNG `og` render measured about 0.1 s
  locally (6 samples, 0.087–0.107 s); Cloudflare caches after that.
- A withdrawn illustration can still be served from caches for up to 1 hour
  (site) or 1 day (CDN/browser). Purge Cloudflare for an urgent takedown.
- Telegram photos stay off until the card routes are deployed.
- Threads variants exist, but there is no publisher.
- Some cached EN headlines are truncated at the source (for example
  `772d27d38d32d901`). The card shows them faithfully; that is a content
  issue, not a media one.
- Bulk regeneration and editor-uploaded art are not supported.

## 20. Recommended next phase

1. Owner decides on an image provider and budget.
2. Implement that provider (one class) and test it with `--max-calls 1`.
3. Deploy the card routes.
4. Turn on `CYBERALERTX_TELEGRAM_ATTACH_IMAGES` for one channel.
5. Add `tools.media run` after `generate` on the existing timer.

Threads publishing is a separate, later phase. **Not started.**
