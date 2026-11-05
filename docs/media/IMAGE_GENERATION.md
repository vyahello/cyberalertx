# Article illustrations

Every public story has one canonical illustration. The website (cards, feed
rows, article page, Open Graph) and Telegram use that same asset. Images
are generated on our own server at no per-image cost. No paid or remote
image service is used, and no publisher image is ever copied or linked.

Labels: **[measured]** on the production host or a copy of its data;
**[tested]** by the test suite; **[assessment]** reasoning, not measured.

## 1. Production host and local AI models

| | [measured] 5 Nov 2026 |
|---|---|
| CPU | 2 vCPU, AMD EPYC Genoa (AVX2, AVX-512, AVX-512 VNNI), shared by every production service |
| Memory | 3.7 GiB RAM, 2.2 GiB available; swap 2 GiB with 0.9 GiB already in use |
| GPU | none (`lspci`: Virtio VGA only; no `nvidia-smi`; `/dev/dri` is the virtual display) |
| Disk | 33 GB free |
| Load | api ~120 MiB, frontend ~170–235 MiB, run ~60 MiB, Claude CLI ~375 MiB during generation |

**Local diffusion (ComfyUI) is not viable on this host [assessment].**
Open text-to-image models that may be used commercially (for example the
Stable Diffusion 1.5 family under CreativeML OpenRAIL-M) need about 2 GB for
their weights plus working memory. That is all of the RAM available, with
swap already in use. Without a GPU, inference would also occupy both CPU
cores, which the API, the site and ingestion share, for minutes per image.
Downloading a model or installing ComfyUI just to prove this would risk the
production services the task says must come first, so nothing was installed.

The ComfyUI adapter (`cyberalertx/media/comfyui.py`) is implemented, tested
with a mock worker and **disabled**. It is used only when all of these hold:
- `CYBERALERTX_COMFYUI_URL` points at a loopback worker;
- the workflow file is valid;
- the worker answers `/system_stats`;
- at least `CYBERALERTX_COMFYUI_MIN_FREE_MB` (default 2048) is free.

Then it runs one job at a time with a hard timeout, and any failure falls
back to SVG. It is ready for a future host with a GPU; nothing on the
current host enables it.

## 2. The working generator: server-side SVG

`cyberalertx/media/svg_art.py` (renderer `cax-svg-2`, see
[VISUAL_REVIEW.md](VISUAL_REVIEW.md)) draws one 1600×900 editorial illustration
per story. It needs no model, network or GPU. [measured] All 135 public
stories took 5.9 s on the production host's data copy, with a peak RSS of
100 MB, using 1.8 MB of disk in total.

How a story becomes an image (`media/illustrations.py: visual_brief`):

| Input (verified fields only) | Decides |
|---|---|
| Category + evidence labels (`pipeline/evidence.py`) | The **event** that is drawn. An attack path appears only when exploitation is confirmed, otherwise the image shows exposure. Records leave an archive only when the exposure is confirmed, otherwise it is an inspection. Ransomware seals systems; phishing leads to a counterfeit gateway; malware is a foreign component in the delivery chain; a disrupted campaign shows dismantled infrastructure; a compromised website script (analytics, third-party code, skimming, watering hole) is drawn inside a site, spreading to visitors' devices. |
| Affected platforms, audience, technology words in the source title | The **scene**: smartphone, server racks, network edge appliances, cloud identity layers, industrial control, build pipeline, mail system, corporate network and so on. Brands map to their technology category; logos are never drawn. |
| Story key | A stable **seed**: the same story always gets the same picture, and different stories get different layouts, counts and angles. |

Never drawn: text, numbers, logos, faces, hooded figures, padlocks, shields,
binary digits, fake interfaces, flags or attribution symbols. Alt text in EN
and UA describes what is drawn. The visible caption on the site says
"Illustration created for CyberAlertX. It is not a photograph or a
screenshot of the incident." The asset records `generation_method="svg"`.
These images are programmatic illustrations, never presented as model output.

**Safety.** `sanitize_svg` accepts only the element and attribute subset the
renderer emits. It rejects scripts, `foreignObject`, images, links, event
handlers, external `url()` references, DOCTYPE/entities and text, and checks
the dimensions. The media store will not save an SVG that fails it; the
site re-validates before rasterizing.

## 3. Pipeline

```
generate (hourly)  ->  media run (ExecStartPost of the same unit)
                         for each public story, newest first:
                           canonical asset exists with the same brief hash -> reuse (alt text refreshed)
                           else ComfyUI if enabled + healthy -> validate
                                 else / on failure -> SVG (always)
                           save bytes (content-addressed), record metadata + usage
Telegram (10x/day) ->  posts only stories whose illustration exists; others wait
```

- **One asset per story**, shared by EN and UA (`illus:<story key>`).
- **Idempotent and resumable.** Asset statuses persist in
  `data/media/assets.json`, so a restart simply rescans. Unchanged stories
  are never regenerated, and a headline edit does not change the brief.
- **Bounded.**
  - Per run: `--max-calls` (unit: 25).
  - Retries: 3 attempts per brief.
  - ComfyUI: a hard timeout, and pausing below the free-memory floor.
  - Spending caps (`CYBERALERTX_IMAGE_BUDGET_*`) exist for any future
    metered generator; they never apply to SVG, which costs nothing.
  - The generate unit has `MemoryMax=1200M`.
- **Metadata per asset:**
  - asset id and story key;
  - `generation_method` (`svg` or `comfyui`) and model or renderer version
    (`cax-svg-2`);
  - prompt/brief version (`illus-2`) and brief hash;
  - SHA-256 storage key, width, height and size;
  - alt text in EN and UA;
  - status, attempts and last error (including a ComfyUI error that fell
    back to SVG).

## 4. Storage and delivery

- **Storage.** Files live in `data/media/files/<sha256>.svg` and metadata in
  `data/media/assets.json`. That is persistent data shared by every release,
  so switching or rolling back a release never loses images.
- **API.** Posts carry `media.illustration` (`asset_id`, alt text).
  `GET /media/{id}` serves the source internally only.
- **Website.** The site route `/media/{id}/{variant}.{png,webp,avif}`
  rasterizes the same source with sharp (librsvg). [measured]
  - `article` is 1600×900, `og` 1200×630, `telegram` 1200×675 and
    `preview` 640×360. The preview uses a central crop so thumbnails stay
    legible.
  - Pages use `<picture>` with AVIF, then WebP, then PNG; explicit width,
    height and aspect ratio (no layout shift); and lazy loading below the fold.
  - Feed rows show a thumbnail from `sm` width up. The lead story and the
    article page show the full image. While an image is pending, the static
    branded `/brand/visual-pending.svg` is shown, never a publisher image.
- **Telegram.** Each post is sent with `sendPhoto` and the URL
  `https://cyberalertx.com/media/{id}/telegram.png`, the same asset as the
  website. A story without its illustration waits (no attempt spent) and
  expires with the 48 h publication window. A refused photo is retried,
  never posted as text.

## 5. Backfill

`python -m cyberalertx.tools.media backfill` with no flags is a read-only
plan: eligible public stories, how many already have an image, what is left
to generate, the method and the CPU estimate. `--batch N` then generates up
to N images now, newest first, resumably. [measured] On the data copy:
135 eligible, 135 generated, 0 failed.

Only stories the site can actually serve are eligible: the items in
`items.json` (the newest 200) that have a published AI brief. The ~4,500
older editions in `threat_posts.json` belong to items that have left the
store; their pages return 404, so they need no image.

## 6. Operations

```bash
cd $APP_ROOT/current && . ops/release/loadenv.sh && loadenv $APP_HOME/.env
venv/bin/python -m cyberalertx.tools.media backfill            # plan, read-only
venv/bin/python -m cyberalertx.tools.media backfill --batch 50 # generate up to 50
venv/bin/python -m cyberalertx.tools.media status              # counts and failures
```

`/admin/media` shows asset status, method, attempts and errors.
