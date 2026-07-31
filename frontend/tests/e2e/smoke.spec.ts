import { test, expect, request } from "@playwright/test";
import { badStatuses, collectResponses } from "./helpers";

test.describe("smoke @smoke", () => {
  test("root redirects to default locale and renders hero", async ({ page, baseURL }) => {
    const { responses } = collectResponses(page);

    const resp = await page.goto("/");
    expect(resp, "navigation must produce a response").not.toBeNull();
    // After following redirects we should be on /en (default locale).
    await expect(page).toHaveURL(/\/en\/?$/);

    // Hero is a labelled region with the single h1 on the page.
    const hero = page.getByRole("region", { name: /Cyber threats\..*/i });
    await expect(hero).toBeVisible();
    await expect(page.locator("h1#hero-headline")).toBeVisible();

    // No 4xx/5xx from our own origin during initial render.
    const origin = new URL(baseURL!).origin;
    expect(badStatuses(responses, origin)).toEqual([]);
  });

  test("feed section is present and either lists articles or shows the empty state", async ({ page }) => {
    await page.goto("/en");

    const feed = page.locator("#feed");
    await expect(feed).toBeVisible();
    // Target the section heading specifically — every article inside also
    // has an <h2>, so an unscoped getByRole would trip strict-mode.
    await expect(feed.locator("#feed-heading")).toBeVisible();

    // Healthy path: ≥1 article. Backend-empty path: an explicit status
    // message. Either is acceptable for a smoke test — what we reject is
    // a feed section that renders nothing recognisable.
    const articles = feed.locator("article");
    const emptyState = feed.getByRole("status");
    const articleCount = await articles.count();
    if (articleCount === 0) {
      await expect(emptyState).toBeVisible();
    } else {
      expect(articleCount).toBeGreaterThan(0);
      await expect(articles.first().locator("h2")).toBeVisible();
    }
  });

  test("/healthz returns 200 JSON", async ({ baseURL }) => {
    const ctx = await request.newContext({ baseURL });
    try {
      const resp = await ctx.get("/healthz");
      expect(resp.status(), `healthz status was ${resp.status()}`).toBe(200);
      const contentType = resp.headers()["content-type"] ?? "";
      expect(contentType).toMatch(/json/i);
      // Body should parse and have *some* shape — we don't pin the
      // schema here, just that it's a JSON object.
      const body = await resp.json();
      expect(body).toEqual(expect.any(Object));
    } finally {
      await ctx.dispose();
    }
  });

  test("/uk legacy locale redirects permanently to /ua", async ({ baseURL }) => {
    const ctx = await request.newContext({ baseURL, maxRedirects: 0 });
    try {
      const resp = await ctx.get("/uk");
      // Next.js `permanent: true` redirect → 308 (or 301 on some setups).
      expect([301, 308]).toContain(resp.status());
      const location = resp.headers()["location"] ?? "";
      expect(location).toMatch(/\/ua\/?$/);
    } finally {
      await ctx.dispose();
    }
  });

  test("locale toggle navigates EN → UA and back (URL only)", async ({ page }) => {
    await page.goto("/en");
    const langSwitcher = page.getByRole("group", { name: "Language" });
    await expect(langSwitcher).toBeVisible();

    // EN should be aria-current, UA should be a navigable link.
    await expect(langSwitcher.getByRole("link", { name: "EN" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await langSwitcher.getByRole("link", { name: "UA" }).click();
    await expect(page).toHaveURL(/\/ua\/?$/);
    await expect(
      page.getByRole("group", { name: "Language" }).getByRole("link", { name: "UA" }),
    ).toHaveAttribute("aria-current", "page");

    // And back to EN.
    await page.getByRole("group", { name: "Language" }).getByRole("link", { name: "EN" }).click();
    await expect(page).toHaveURL(/\/en\/?$/);
    await expect(
      page.getByRole("group", { name: "Language" }).getByRole("link", { name: "EN" }),
    ).toHaveAttribute("aria-current", "page");
  });

  test("html lang carries the language subtag, not the URL segment", async ({ page }) => {
    await page.goto("/en");
    await expect(page.locator("html")).toHaveAttribute("lang", "en");

    // The route is /ua because that's how the audience refers to itself,
    // but `ua` is a COUNTRY code. Ukrainian's language subtag is `uk`, and
    // that is what belongs in the lang attribute — otherwise a screen
    // reader can't identify the language and reads Ukrainian text with an
    // English pronunciation engine.
    await page.goto("/ua");
    await expect(page.locator("html")).toHaveAttribute("lang", "uk");
  });

  test("page has main, header banner, and footer landmarks", async ({ page }) => {
    await page.goto("/en");
    await expect(page.getByRole("banner")).toBeVisible();
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("contentinfo")).toBeVisible();
  });

  test("footer links to the real Telegram channel for each locale", async ({ page }) => {
    // Both channels carry the locale suffix. A bare `@cyberalertx` looks
    // plausible and resolves with HTTP 200, but it is Telegram's "contact"
    // stub, not a channel — clicking it pops "username not found". These
    // must stay in sync with CYBERALERTX_TELEGRAM_CHANNEL_EN / _UA on the
    // backend, which is where posts are actually published.
    for (const [locale, channel] of [
      ["en", "cyberalertx_en"],
      ["ua", "cyberalertx_ua"],
    ] as const) {
      await page.goto(`/${locale}`);
      const link = page
        .getByRole("contentinfo")
        .getByRole("link", { name: /telegram/i });
      await expect(link).toHaveAttribute("href", `https://t.me/${channel}`);
    }
  });

  test("footer links to the RSS feed for the active locale", async ({ page }) => {
    await page.goto("/ua");
    await expect(
      page.getByRole("contentinfo").getByRole("link", { name: /RSS/i }),
    ).toHaveAttribute("href", "/ua/feed.xml");
  });

  test("brand favicon is reachable", async ({ baseURL }) => {
    const ctx = await request.newContext({ baseURL });
    try {
      const resp = await ctx.get("/brand/favicon.svg");
      expect(resp.status()).toBe(200);
      expect(resp.headers()["content-type"] ?? "").toMatch(/svg|xml/i);
    } finally {
      await ctx.dispose();
    }
  });
});
