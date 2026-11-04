# Frontend dependency remediation plan (O1)

**Status:** plan, verified by a trial; **not yet applied** to the release
candidate. **Must be applied before Stage C.**

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
