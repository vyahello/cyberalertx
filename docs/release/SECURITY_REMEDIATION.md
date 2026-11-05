# Frontend dependency remediation plan (O1)

> **Historical record** of the Nov 2026 dependency remediation (Next 15.5.29, sharp 0.35.5); index: [docs/README.md](../README.md).

**Status: APPLIED** on `redesign/cti-platform` (the remediation commit) and
built into release candidate 3. Sections 1–6 are the original plan and trial.
§7 records what was applied and verified, including the advisories Next.js
published on 3 November 2026.

**Correction of Phase 7.** PRODUCTION_READINESS.md first described the
`next` critical finding as a Server Actions issue. That was wrong. `npm audit`
reports **14 advisories** against `next@15.5.18`, and the **three critical
ones are not about Server Actions**. Two of them sit in the Image
Optimization API's decoders (`sharp` → libheif / librsvg), and that API is
**live and unauthenticated** on this deployment (verified below). The finding
is applicable and must be fixed. It does not depend on whether the app uses
Server Actions.

All facts below come from `npm audit --omit=dev --json` (4 Nov 2026), the
GitHub advisory pages, and tests against the Stage B rehearsal server (same
Next version as production, isolated data).

## 1. Installed versions and where they come from

| Package | Installed (RC and production) | Path | Used at |
|---|---|---|---|
| `next` | 15.5.18 (package.json `^15.0.3`, lockfile pins 15.5.18) | direct | runtime (`next start`) |
| `sharp` | 0.34.5, bundling libvips 8.17.3 | `next` optional dep; **imported directly** by `app/[locale]/threat/[id]/card/[file]/route.ts`, `app/media/[asset]/[file]/route.ts`, `lib/media/illustration.ts` | runtime |
| `postcss` | 8.4.31 (inside `next/node_modules`) and 8.5.14 (direct dev dep, Tailwind) | next / tailwind / autoprefixer | build time |
| `nanoid` | 3.3.12 | via postcss | build time |
| `source-map-js` | 1.2.1 | via postcss | build time |

## 2. Advisories and applicability

### 2.1 `next` (installed 15.5.18; **all fixed in 15.5.28; target 15.5.29**, the current 15.x backport)

| Advisory | Sev. | Fixed in | Applicability here |
|---|---|---|---|
| GHSA-2464-fhr4-w9xw: RCE in Image Optimization API with **SVG** | **critical** | 15.5.28 (and sharp ≥ 0.35.5) | **Applicable environment.** The advisory states it occurs "when Next.js runs on glibc-based Linux", which this host is. `/_next/image` is live and public (rehearsal: `GET /_next/image?url=/brand/og-image.png&w=640&q=75` → 200; nginx routes `/` to Next). Local SVG is refused today (`dangerouslyAllowSVG` is off → 400). The fix workaround is `sharp ≥ 0.35.5`, i.e. the librsvg bug (sharp GHSA-wq5f-xc86-pv6w). |
| GHSA-2xp9-vwfh-vxw4: RCE in Image Optimization API with **AVIF** | **critical** | 15.5.24 | **Applicable.** The optimizer **does** decode AVIF from same-origin routes: `/_next/image?url=/en/threat/<id>/card/og.avif` → 200 (re-encoded as JPEG). Today those AVIF bytes are produced by us, and no route returns attacker-chosen image bytes (`/media` serves only validated provider images; none exist). That is an assessment, not a guarantee. CVSS lists "attack requirements: present". |
| GHSA-p293-qw3h-jr36: RCE on **Windows**-hosted servers | **critical** | 15.5.24 | **Not applicable in practice:** the host is Linux, and the advisory ties it to Windows filesystems (it does not explicitly confirm Linux is unaffected). Fixed by the same upgrade. |
| GHSA-m99w-x7hq-7vfj, GHSA-p3m5-59mp-jv5r: DoS in App Router via Server Actions | high | 15.5.21 / 15.5.28 | Low: no `"use server"` in the app (0 files). App Router request handling is still the vulnerable framework code. Fixed by the upgrade. |
| GHSA-89xv-2m56-2m9x: SSRF in Server Actions on **custom servers** | high | 15.5.21 | Not applicable: `next start`, no custom server, no Server Actions |
| GHSA-p9j2-gv94-2wf4: SSRF in **rewrites** | high | 15.5.21 | Not applicable: `next.config.ts` has only `redirects()` |
| GHSA-4jqv-mc3x-m676, GHSA-mcj8-r9mp-w47p: cache poisoning of SSG/**ISR** pages, self-hosted | moderate | 15.5.27 | **Applicable:** self-hosted ISR (`/[locale]`, `/[locale]/threat/[id]`, topics) behind Cloudflare |
| GHSA-68g3-v927-f742, GHSA-4633-3j49-mh5q: cache confusion for requests with bodies | moderate | 15.5.21 | Possibly applicable (self-hosted); fixed by the upgrade |
| GHSA-q8wf-6r8g-63ch: DoS in Image Optimization with SVG | moderate | 15.5.21 | Applicable surface (optimizer live) |
| GHSA-955p-x3mx-jcvp: disclosure of Server Function endpoints | moderate | 15.5.21 | Low (no Server Functions) |
| GHSA-4c39-4ccg-62r3: unbounded Server Action payload, Edge runtime | moderate | 15.5.21 | Not applicable (Node runtime) |

### 2.2 `sharp` (installed 0.34.5; **fixed in 0.35.5**)

| Advisory | Sev. | Fixed in | Applicability |
|---|---|---|---|
| GHSA-f88m-g3jw-g9cj: inherited libvips CVE-2026-33327 / 33328 / 35590 / 35591 | high | 0.35.0 | **Applicable:** sharp decodes in the optimizer, in our `/media` route (provider images, once configured) and in the card route |
| GHSA-rgj7-g3m4-5g8c: libheif (GHSA-g89c-p67h-r497, GHSA-2jg2-4ch7-h545) | high | 0.35.4 | **Applicable:** the AVIF/HEIF decode path (see GHSA-2xp9) |
| GHSA-wq5f-xc86-pv6w: librsvg CVE-2026-96889 | high | 0.35.5 | **Applicable:** the SVG path (see GHSA-2464). Our card route does not decode SVG input; the optimizer would if SVG were allowed. |

### 2.3 `postcss` / `nanoid` / `source-map-js` (build time)

| Advisory | Sev. | Fixed in | Applicability |
|---|---|---|---|
| GHSA-6g55-p6wh-862q, GHSA-r28c-9q8g-f849, GHSA-fxqj-rqcc-2cmp: postcss source-map path traversal / file read | high / high / moderate | postcss 8.5.23+ (target 8.5.32) | Low: build time only, and the CSS is ours. Next 15.5.29 **still pins postcss 8.4.31**, so an override is required. |
| GHSA-qx2v-qp2m-jg93: postcss XSS via unescaped `</style>` in stringify | moderate | 8.5.10 | Low: build time, our CSS |
| GHSA-28wg-ghj8-5hjv, GHSA-2v37-7h3g-55p8: nanoid infinite loop | high | 3.3.18 (target 3.3.20) | Low: build time |
| GHSA-68fv-2mgg-jv7q: source-map-js event-loop DoS | high | 1.2.2 | Low: build time |

After the fix, `npm audit` (full tree) also cleared three dev-tooling
advisories through a non-forced `npm audit fix`:
- `browserslist`: high;
- `postcss-selector-parser`: moderate;
- `baseline-browser-mapping`: moderate.

## 3. Remediation (exact change)

`frontend/package.json`:

```diff
   "dependencies": {
-    "next": "^15.0.3",
+    "next": "15.5.29",
+    "sharp": "0.35.5",
   ...
   "devDependencies": {
-    "postcss": "^8.4.49",
+    "postcss": "^8.5.32",
   ...
+  "overrides": {
+    "postcss": "$postcss",
+    "nanoid": "^3.3.20",
+    "source-map-js": "^1.2.2"
+  }
```

Then run `npm install && npm audit fix` (non-forced) and commit
`package-lock.json`. The changes:
- `sharp` becomes a **direct** dependency, because our own routes import it.
  Today it arrives only transitively through Next, which is what kept it on
  0.34.5.
- Next 15.5.29 accepts `^0.35.5`.

`frontend/next.config.ts` (defense in depth; the app never uses `next/image`):

```ts
images: { unoptimized: true },   // removes the public /_next/image optimizer
```

Optional, administrator: nginx `location ^~ /_next/image { return 404; }`
as a second layer in production.

## 4. Trial results [verified, scratch copy of the release frontend]

| Check | Result |
|---|---|
| Resolved versions | next 15.5.29 · sharp 0.35.5 (×2) · postcss 8.5.32 (×8, no 8.4.31 left) · nanoid 3.3.20 · source-map-js 1.2.2; tailwind 3.4.19 and autoprefixer 10.5.0 unchanged |
| `npm audit --omit=dev` | **0 vulnerabilities**; full tree after `npm audit fix`: **0** |
| `tsc --noEmit` | clean |
| `next build` | compiled (Next.js 15.5.29) |
| Playwright (chromium + mobile), before and after `images.unoptimized` | 39 passed, 1 skipped, 2 failed: only the environmental `/healthz` (same as the release candidate) |
| Card regression vs the release candidate, all 7 variants × EN/UA | PNG and WebP **byte-identical** (10/12). AVIF re-encoded by the new libheif: 4–5 % of channels differ, max delta 50/255. Visually identical (side-by-side check). |
| `/_next/image` after `images.unoptimized: true` | **404** (endpoint removed); site pages and `/…/card/og.avif` still 200 |

## 5. Regression-testing plan for the remediated release candidate (RC3)

1. **Static and build:**
   - `npm ci` from the committed lockfile;
   - `npm audit` (expect 0) and `npm audit --omit=dev` (expect 0);
   - `tsc --noEmit`;
   - `next build`, which must show Next 15.5.29.
2. **Backend unchanged:** `pytest` (1383 passed / 1 skipped with an isolated
   PG) and `mypy`.
3. **Browser:** Playwright, both projects (expect 39 passed; only `/healthz`
   environmental).
4. **Cards:** all variants × EN/UA return 200 with the right MIME type and
   dimensions. Pixel-compare against the previous RC: PNG/WebP identical,
   AVIF visually identical. Also `tools.media validate-cards`.
5. **Optimizer:** `/_next/image?url=/brand/og-image.png&w=640&q=75` → 404.
   No page references `/_next/image` (grep the built HTML).
6. **ISR:** a home or article page revalidates after its window (fetch twice
   across `revalidate`); `Cache-Control` headers unchanged.
7. **Visual QA:** home and article at 375 / 1440 px, both locales.
8. **Runtime:** `node -e "require('sharp').versions"` shows sharp 0.35.5 /
   libvips ≥ 8.17; an AVIF card renders.
9. **After deploy (Stage C):** `npm audit` in `current/frontend`, the
   `/_next/image` probe on the public host, and card renders on the live
   article pages.

## 6. Order

1. Apply §3 in the worktree.
2. Commit.
3. Build RC3 in a new release directory (Stage B procedure).
4. Run §5.
5. Only then is Stage C eligible.

The production checkout (`/home/cax/cax`, same vulnerable versions) is
fixed by deploying RC3, not by patching it in place.

## 7. Applied and verified (release candidate 3)

### Change

Applied exactly as in §3:
- `next` 15.5.29;
- `sharp` 0.35.5 as a direct dependency;
- `postcss ^8.5.32` with the `$postcss` override, plus `nanoid ^3.3.20` and
  `source-map-js ^1.2.2`;
- the lockfile from the trial (including the non-forced `npm audit fix`);
- `images: { unoptimized: true }` in `next.config.ts`.

### Installed after `npm ci` [verified]

| Package | Version |
|---|---|
| next | 15.5.29 (one copy) |
| sharp | 0.35.5: direct, plus Next's, deduplicated to one install |
| Bundled image libraries | libvips 8.18.7, libheif 1.23.5, librsvg 2.63.2 |
| postcss | 8.5.32 (all 8 copies; no 8.4.31 left) |
| nanoid | 3.3.20 |
| source-map-js | 1.2.2 |

### `npm audit` [verified]

- Full tree: **0** (critical 0, high 0, moderate 0, low 0, info 0).
- `--omit=dev`: **0**.

### Upstream advisories re-checked [verified, GitHub advisory API and vercel/next.js repository advisories]

- **`next`, GitHub reviewed database:** every 15.x range ends at ≤ 15.5.27 or
  < 15.5.24, so all are patched in 15.5.28 and 15.5.29. The newest entries
  (22 Oct: GHSA-2464, GHSA-p3m5, and the 16.x-only GHSA-673q / GHSA-h694) are
  covered.
- **`sharp`:** GHSA-wq5f (< 0.35.5), GHSA-rgj7 (< 0.35.4), GHSA-f88m (< 0.35.0),
  all patched in 0.35.5.
- **3 November 2026, vercel/next.js repository advisories.** These are not yet
  in the reviewed database, so `npm audit` does not report them. 15.5.29 was
  released the same day.

| Advisory | Affects | Status for this app |
|---|---|---|
| GHSA-f3mh-rxg3-f5g2: HttpOnly cookie exposure via `x-middleware-set-cookie` on Edge routes | 15.0.0–15.5.28 | 15.5.29 is outside the range. Also not applicable: 0 Edge-runtime routes, no cookies set; `middleware.ts` only redirects `/` (live headers show no `x-middleware-set-cookie`). |
| GHSA-7qx7-33qx-rqx2: SVG rejection bypass in image optimization | 15.0.0–15.5.28 | 15.5.29 is outside the range, and the optimizer is removed (`/_next/image` → 404) |
| GHSA-pc58-hwjq-p385 (CVE-2026-119348, CVSS 4.0 6.3 Moderate): cross-client response injection in self-hosted App Router / fetch cache behind a pipelining HTTP/1.1 proxy | Advisory record says "< 16.0.0" with an **empty** patched-versions field; the v15.5.29 release notes list it as fixed | **Fixed in 15.5.29, and not applicable here anyway (O25, closed).** Evidence in §7.1. |
| GHSA-rhh4, GHSA-vvgp, GHSA-vc7v, GHSA-mfr8 | 16.x only (`use cache`, Cache Components, root params) | Not applicable to 15.x |

### Image compatibility [verified; before = previous RC on Next 15.5.18 with the optimizer, after = remediated build, same API and data]

- **Six pages, five widths, 60 browser loads:**
  - pages: home, article and topic, in EN and UA;
  - widths: 375, 390, 768, 1440 and 1920;
  - results: all 200, 0 `/_next/image` requests (none before either), 0
    failed responses, 0 broken `<img>`, 0 `<img>` without width/height, no
    horizontal overflow.
- **No raster images on these pages.** Icons and marks are inline SVG, so
  the image set is identical (empty) before and after.
- **Page weight:** 0.6–0.8 % lower (the newer Next runtime bundle).
- **Editorial illustration** (a temporary local test fixture on a fresh
  article, removed afterwards; data checksum restored):
  - both builds load the pre-generated `/media/<id>/article.avif` through
    `<picture>` (AVIF, WebP, PNG fallback);
  - natural size 1600×900, matching the `width`/`height` attributes;
  - identical rendered size at every width (335×188 at 375 px up to 762×429
    at 1440 px), a 16:9 ratio, no overflow, no optimizer request.
- **All seven card variants** (5 PNG + WebP + AVIF) return 200 in both
  locales. PNG and WebP are byte-identical before and after; AVIF is
  re-encoded by the new libheif.
- **Built output:** 0 source references to `next/image` or `/_next/image`.
  The only mention in the built output is Next's default client image config,
  now carrying `unoptimized: true`.

### Performance impact [verified, local]

- **Disabling the optimizer: no transfer or latency impact.** No page ever
  requested it (0 requests before and after). Every image is a pre-generated
  variant from its own route.
- **AVIF transfer (new libheif encoder):**
  - real cards are **13–21 % smaller**: `og.avif` 18,812 → 15,984 B,
    `threads-square.avif` 22,028 → 17,644 B;
  - all 15 card files together: 507,811 → 491,915 B (−3.1 %);
  - the flat synthetic illustration's AVIF variants are 7–17 % larger
    (+190 to +440 B);
  - PNG and WebP are unchanged.
- **Server-side cold render, median of 5** (cached by HTTP and Cloudflare
  after the first request):

  | Variant | Before | After | Change |
  |---|---|---|---|
  | Card PNG | 89 ms | 99 ms | +11 % |
  | Card WebP | 120 ms | 148 ms | +23 % |
  | Card AVIF | 668 ms | 713 ms | +7 % |
  | Media `article.avif` | 1.33 s | 1.60 s | +20 % |

  Cached page responses were unchanged or faster (2.5–3.5 ms after, vs
  3.8–4.2 ms before).

### Tests

The Playwright result on the remediated build matches the pre-remediation
release candidate exactly: 39 passed, 1 skipped, and 2 failed (the
environmental `/healthz` only). For the backend, frontend and build results of
release candidate 3, see its `RELEASE` and `RELEASE-INVENTORY.txt`.


### 7.1 GHSA-pc58-hwjq-p385 reconciled (O25) [verified, 4 Nov 2026]

**Conflicting upstream information:**
- The repository advisory (`/repos/vercel/next.js/security-advisories/GHSA-pc58-hwjq-p385`, published 2026-11-03 18:39 UTC) lists `>= 16.0.0` and `< 16.0.0`, both with an **empty `patched_versions`**.
- It is not yet in the global reviewed database (`/advisories/GHSA-pc58-hwjq-p385` → 404), which is why `npm audit` is silent.
- The v15.5.29 release (tag commit `17014e9cf7891cc353ebfd8fb4a407f9e4cbbf47`, published 18:38 UTC, one minute earlier) lists it under "This release contains security fixes".

The empty field reads as missing metadata, not a missing fix. The evidence:

1. **The fix is in the tag.** `compare/v15.5.28...v15.5.29` has seven commits. One is `848ec29a3` "Fix stale compressed framing for forwarded fetch responses (#273)". It adds `test/e2e/app-dir/stale-compressed-framing/`, a route that does `return fetch(<gzip upstream>)`, which is exactly the advisory's scenario. The code change:
   - `send-response.ts` adds `FORBIDDEN_HEADERS = ['content-length', 'content-encoding', 'transfer-encoding']`, dropped when a web `Response` is written to the Node response;
   - `next-server.ts` filters the same three headers on the second response path, where it previously filtered only `content-encoding`.

   Cause: `fetch` transparently decodes gzip but keeps the upstream `Content-Length` of the *compressed* body, so the decoded bytes overrun the declared frame.
2. **The fix is in the installed build.**
   - The release candidate's `node_modules/next/dist/server/send-response.js` contains `FORBIDDEN_HEADERS` with the three names.
   - `next-server.js` contains `key !== 'content-length' && key !== 'content-encoding' && key !== 'transfer-encoding'`.
   - Production's 15.5.18 has neither; it has only `key !== 'content-encoding'`.
   - The lockfile integrity (`sha512-93AMszTC…`) equals the registry's for `next@15.5.29`, and the registry entry carries provenance attestations.
3. **Behaviour reproduced (scratch app, not CyberAlertX code).**
   - Setup: a two-route app (`return fetch(upstream)`, with `no-store` and with `revalidate: 3600`), built with each version. The upstream serves a gzip body whose 116 decoded bytes end in a complete `HTTP/1.1 200 OK … injected` response; the compressed body is 70 bytes. The `next/dist` used is byte-identical to the release candidate's.
   - **15.5.18:** `content-length: 70`, `content-encoding: gzip`, then 116 raw bytes. A proxy reading by Content-Length sees 46 trailing bytes that begin `HTTP/1.1 200 OK` as the next response. Reproduced on both routes, including the fetch-cache hit.
   - **15.5.29:** no `content-length` and no `content-encoding`; `transfer-encoding: chunked` with the decoded body. The framing is consistent on both routes and on the cache hit.
4. **The deployment lacks the preconditions anyway.**
   - **Route handlers:** all three (`[locale]/feed.xml`, `[locale]/threat/[id]/card/[file]`, `media/[asset]/[file]`) return `new Response(<own bytes>, {headers: <own headers>})`. Upstream responses are consumed with `.json()` or `.arrayBuffer()` and never returned. No `rewrites`; `middleware.ts` only redirects.
   - **Upstream:** the only fetched upstream is the CyberAlertX API on localhost (gzip comes from nginx, not the API), so no attacker controls the upstream response.
   - **nginx:** the CyberAlertX site uses bare `proxy_pass` with no `upstream {}` block, so there is no `keepalive` and no upstream connection reuse. `location /` also sends `Connection: upgrade`. nginx never pipelines upstream requests. Clients reach nginx over HTTP/2 from Cloudflare.

**Conclusion:** fixed in the installed Next.js version, and not applicable to this deployment. O25 is closed. One follow-up: if GitHub later imports the advisory into the reviewed database without a patched version, `npm audit` will start flagging 15.5.29. That would be a metadata false positive; this section is the evidence for dismissing it.
