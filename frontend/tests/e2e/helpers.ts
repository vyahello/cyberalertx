import type { Page, Response } from "@playwright/test";

/**
 * Returns the locale segment of a Next.js localized URL.
 * `https://x.test/en/threat/abc` → `"en"`.
 */
export function localeFromUrl(url: string): string | null {
  const match = url.match(/\/(en|ua)(?:\/|$|\?|#)/);
  return match ? match[1] : null;
}

/**
 * Collects every response Playwright sees during a navigation. Caller can
 * inspect statuses afterwards to assert no 4xx/5xx slipped through. We
 * filter out:
 *   - data: / blob: URLs (not real network traffic)
 *   - 3xx redirects (expected: `/` → `/en`)
 *   - cross-origin telemetry (Cloudflare RUM, analytics) — these can fail
 *     transiently without breaking the page and aren't ours to fix.
 */
export function collectResponses(page: Page): { responses: Response[] } {
  const responses: Response[] = [];
  page.on("response", (r) => {
    const url = r.url();
    if (url.startsWith("data:") || url.startsWith("blob:")) return;
    responses.push(r);
  });
  return { responses };
}

/**
 * Filters a captured response list down to "things that should never be
 * 4xx/5xx for a healthy page": same-origin requests, ignoring 3xx.
 */
export function badStatuses(
  responses: Response[],
  origin: string,
): { url: string; status: number }[] {
  return responses
    .filter((r) => r.url().startsWith(origin))
    .map((r) => ({ url: r.url(), status: r.status() }))
    .filter((r) => r.status >= 400);
}
