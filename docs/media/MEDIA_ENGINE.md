# Media Engine

Every story gets a branded CyberAlertX card and one editorial illustration.
Illustrations are drawn on our own server as SVG, at no cost and with no
external service. How they are generated, the host findings and the ComfyUI
status are described in [IMAGE_GENERATION.md](IMAGE_GENERATION.md). This
document covers the shared machinery: cards, the asset store, the routes and
the admin view.

## What exists

| Piece | Where | What it does |
|---|---|---|
| Card renderer | `frontend/lib/media/card.tsx` | Satori/resvg (bundled with Next as `next/og`). It takes one edition's own text and renders a PNG at any of five sizes. |
| Card spec | `frontend/lib/media/spec.ts` | Builds the card from a post payload: headline, severity, category, "exploited" mark, CVE id and a localized date. Also computes the hash used in versioned URLs. |
| Card route | `frontend/app/[locale]/threat/[id]/card/[file]/route.ts` | Serves `GET /{en,ua}/threat/{id}/card/{variant}.{png,webp,avif}`. WebP/AVIF are converted by sharp, which Next already ships. |
| Illustration route | `frontend/app/media/[asset]/[file]/route.ts` | Serves `GET /media/{asset}/{variant}.{png,webp,avif}`. It crops each platform variant from one stored source and re-checks the bytes before serving. |
| Asset records + store | `cyberalertx/media/assets.py` | `MediaAsset` metadata in `data/media/assets.json`, file bytes in `data/media/files/`. Writes take a lock and are atomic. Bytes are validated by magic number. |
| Card records | `cyberalertx/media/cards.py` | Per-edition variant URLs, content hash and localized alt text. No image bytes are stored. |
| Illustrations | `cyberalertx/media/illustrations.py` | Eligibility rules, prompt builder (verified facts only), and the `ImageProvider` seam with its registry. |
| Engine | `cyberalertx/media/engine.py` | One run: record cards, then generate due illustrations, with reuse, retry and cost caps. |
| CLI | `python -m cyberalertx.tools.media` | `run [--dry-run] [--max-calls N]`, `status`, `regenerate STORY_KEY`, `validate-cards BASE_URL` |
| API | `cyberalertx/api/app.py` | Internal `GET /media/{asset_id}`. Adds `media.illustration` to a post only when a validated illustration exists. |
| Admin | `/admin/media`, `/admin/media.json` | Asset status, variants, attempts, errors, provider status and usage. Uses the same admin gate as every other `/admin` page. |
| Telegram | `cyberalertx/publish/*` | Can attach the card via `sendPhoto` with a caption that fits Telegram's limit. **Off by default.** |

No dependency was added. Satori, resvg and sharp were already in the Next.js
install. Fonts are static OFL TTFs in `frontend/assets/fonts/`, with their
licences beside them.

## Variants

| Variant | Size | Used for |
|---|---|---|
| `og` | 1200×630 | Open Graph, Twitter/X `summary_large_image`, JSON-LD `image` |
| `telegram` | 1200×675 | Telegram `sendPhoto` (16:9) |
| `threads-portrait` | 1080×1350 | Threads / Instagram-style 4:5 |
| `threads-square` | 1080×1080 | Threads 1:1 |
| `preview` | 640×360 | Small previews, admin |
| `article` (illustration only) | 1600×900 | Article figure on the site |

Formats: PNG for every variant, plus WebP and AVIF. Social platforms get PNG.
The site uses `<picture>` to serve AVIF, then WebP, then PNG.

## Branded cards

A card shows the **edition's own** headline, never text from the other
language. If an edition has no title, it gets no card: the route returns 404
and the page falls back to the static brand image. Marks are localized:
severity (`Critical` / `Критичний`), category, the "exploited" mark, and the
date (UTC for EN, Europe/Kyiv for UA). The headline size steps down for long
titles and is clamped to a fixed number of lines (3 landscape, 5 portrait).
It never shrinks below a legible size. Cyrillic gets a slightly wider em
estimate.

URLs are stable and versioned:
`/{locale}/threat/{id}/card/og.png?v={hash}`. The hash covers only what is
visible on the card: title, level, category, date, exploited flag and
illustration id. A changed headline therefore gets a fresh URL and social
caches refresh. Invisible fields don't change the URL.

Cards are rendered on request and cached by HTTP (`max-age=3600,
s-maxage=86400, stale-while-revalidate`). Nothing is stored, so a card can
never be stale relative to its post. The same inputs render byte-identical
output (verified by md5).

Alt text is written in the card's own language and describes the image:
"CyberAlertX card, critical severity, exploited in attacks: “…”" /
"Картка CyberAlertX, рівень загрози критичний, уже використовують в атаках: «…»".

## Editorial illustrations

### Eligibility

All of these must hold (`EligibilityConfig`; env overrides shown):

- in scope
- verification `verified` or `partially_verified`
- confidence not `low`
- at least 300 characters of source text, or a fact sheet

At least one of these must also hold:

- Breaking candidate
- in the Daily Top N (`CYBERALERTX_ILLUSTRATION_TOP_N`, default 3)
- importance ≥ `CYBERALERTX_ILLUSTRATION_MIN_SCORE` (default 55)
- exploitation confirmed with importance ≥ threshold − 10

On today's worktree data, 10 stories qualify.

### Prompt

The prompt is built from verified story information only: the fact sheet or
cluster evidence, else the category. The event type picks an abstract motif.
"Active exploitation" is drawn **only** when exploitation is `confirmed`;
otherwise it is downgraded to "vulnerability disclosure". Product names from
fact sheets are described as a *category* and never as a brand. The fixed
style forbids text, logos, faces, screenshots, terminals, padlocks, hooded
hackers, matrix rain, neon and photorealism. An illustration must never look
like evidence. The prompt version is `illus-2`; the SVG renderer is
`cax-svg-1`.

The input hash covers prompt version, event, exploited flag, category and
products. **Editing a headline does not regenerate an illustration.** A change
in the facts does.

### Lifecycle

Each story has one illustration, `illus:{story_key}`, shared by both editions.
States: `generating` → `validated` | `failed`.

- **Reuse:** a validated asset whose input hash still matches is reused.
  Membership changes only update `members`.
- **Retries:** a failure keeps its attempt count across runs. After 3
  attempts with the same inputs, the story is skipped until its inputs change
  or `tools.media regenerate` resets it.
- **Run cap:** at most `CYBERALERTX_ILLUSTRATION_MAX_PER_RUN` generations
  per run (default 25). Each one is logged to `data/media/usage.jsonl` with
  method, model or renderer, cost (0 for SVG) and errors.
- **Validation:** before storing, the bytes must be PNG, JPEG or WebP by magic
  number, or an SVG that passes `sanitize_svg` (see IMAGE_GENERATION.md), match the declared MIME type, be ≤ 8 MB, and have sides between 768
  and 4096 px. Files are named by SHA-256, so the same image is stored once
  and no input can reach a file path.
- **Not blocking the site:** an article and its card never wait on an
  illustration; the page shows a branded placeholder meanwhile. A Telegram post
  does wait for it (`CYBERALERTX_TELEGRAM_REQUIRE_ILLUSTRATION=1`), within the
  48 h publication window. Every generator, validation or storage error is
  caught and recorded.

### Generators

The production generator is the server-side SVG renderer. An optional local
ComfyUI worker (`media/comfyui.py`) is implemented but disabled on the current
host; SVG is always the fallback. Paid or remote image APIs are not used and
none is wired in. The `register_provider` seam remains for a future local
generator: a class with `generate(prompt, *, width, height, timeout_s) ->
GeneratedImage(data, mime, model, cost_usd, method)` that raises
`ProviderError` or `TimeoutError`.

## Storage and URLs

Production has no object store or CDN client. The Media Engine follows the
same JSON-plus-files pattern as the rest of `data/`.

```
data/media/assets.json      MediaAsset records (locked, atomic, cached by inode+mtime+size)
data/media/files/{sha256}.png|jpg|webp
data/media/usage.jsonl      provider calls
```

How an illustration reaches the public:

1. The API serves `GET /media/{sha16}` on 127.0.0.1:8000. That route is
   **internal**: nginx only forwards `posts|healthz|admin|feedback` to the API.
2. The site route `/media/{sha16}/{variant}.{fmt}` fetches it, checks type,
   size (≤ 8 MB) and dimensions (≥ 512 px) again, then crops and encodes the
   variant.
3. The asset id is 16–64 lowercase hex characters; anything else is a 404.
   Only `validated` or `published` assets are served.

The site route is served with `max-age=86400`. The route itself revalidates
hourly. **Withdrawing an image:** set the asset's status to something other
than `validated`, or run `tools.media regenerate`. Pages stop referencing it
on their next revalidation. Cached copies of the URL expire within a day;
purge Cloudflare if a takedown can't wait.

## MediaAsset fields

`asset_id`, `story_key`, `asset_type` (`branded_card` | `editorial_illustration`),
`locale` (`""` = shared), `storage_key`, `public_url`, `variants`
{variant → URL}, `mime_type`, `width`, `height`, `aspect_ratio`, `file_size`,
`alt_text` {locale → text}, `source`, `license`, `generation_method`
(`deterministic-svg` | `ai-image`), `generation_model`, `prompt_version`,
`prompt`, `content_hash` (hash of the inputs), `members` (article
fingerprints), `status`, `attempts`, `last_error`, `cost_usd`, `created_at`,
`updated_at`.

## Website integration

- **Article page:** `og:image` and `twitter:image` point to the story's own
  versioned `og` card, with width, height, type and localized alt. If the
  edition has no card, the static brand image is used.
- **JSON-LD:** `NewsArticle.image` points to the same card.
- **Article figure:** shown only when `media.illustration` exists. It uses
  `<picture>` (AVIF/WebP/PNG) at 1600×900 with explicit width and height, so
  there is no layout shift. The caption reads: "Illustration created for
  CyberAlertX. It is not a photograph or a screenshot of the incident." /
  "Ілюстрацію створено для CyberAlertX. Це не фото й не знімок екрана з
  інциденту."
- **Home lead story:** shows the `og` crop of the illustration when present.
- **Feed rows:** a small `preview` thumbnail (central crop) from the `sm`
  breakpoint up, decorative (`aria-hidden`), lazy-loaded. On phones the rows
  stay text-only.
- **Pending:** until a story's illustration exists, the static
  `/brand/visual-pending.svg` is shown in its place (no caption).

## Telegram

Every post is sent with `sendPhoto`. The photo is the story illustration at
`https://cyberalertx.com/media/{asset}/telegram.png` (1200×675), the same
asset as the website. A post waits while its story has no validated
illustration; it spends no attempt and expires with the 48 h window. Set
`CYBERALERTX_TELEGRAM_REQUIRE_ILLUSTRATION=0` to fall back to the edition card
(`CYBERALERTX_TELEGRAM_ATTACH_IMAGES=1`) or text.

The caption is the usual message limited to Telegram's 1024 characters
(counted the way Telegram counts them). Blocks are dropped in this order: the
detail paragraph, the action, the status lines, "why it matters". As a last
resort the summary is trimmed. Headline, source and read-more link are always
kept. If Telegram refuses a required photo, the post is retried later; it is
never sent as text instead. Errors that affect the whole channel (401/403,
chat not found) stop the channel. The message layout is described in
[PUBLICATION_ENGINE.md](../publish/PUBLICATION_ENGINE.md).

## Threads

Only variants are prepared: `threads-portrait` (4:5) and `threads-square`
(1:1), in both editions. There is no Threads publishing, no OAuth and no
account connection.

## Security and copyright

- Images from news sites are never downloaded or republished. Cards are drawn
  only from our text. Illustrations are drawn by our own renderer from
  verified story fields and never contain text.
- Every byte is validated by magic number, never by extension or declared
  type alone. SVG is accepted only when it passes the element/attribute
  allowlist in `sanitize_svg`; the website re-checks before rasterizing.
- The internal `/media` route is not routed publicly. The admin pages use the
  same token gate and CSP as every other admin page; they run no script and
  show no external images, only links.
- No image service credentials exist. Nothing is hardcoded and no secret is
  logged.

## Operating it

```bash
python -m cyberalertx.tools.media run --dry-run     # what would happen
python -m cyberalertx.tools.media run               # record cards and generate due illustrations
python -m cyberalertx.tools.media backfill          # plan for existing public stories (--batch N to generate)
python -m cyberalertx.tools.media status
python -m cyberalertx.tools.media validate-cards http://127.0.0.1:3000 --limit 20
python -m cyberalertx.tools.media regenerate s:0a9c51117848e8
```

No new timer was added. Running it after `generate` is enough: the cards
themselves need no run at all, because they render on request.
