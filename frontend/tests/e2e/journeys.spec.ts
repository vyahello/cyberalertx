import { test, expect } from "@playwright/test";
import { badStatuses, collectResponses } from "./helpers";

test.describe("journeys @e2e", () => {
  test("open first article from feed → detail renders → back returns to feed", async ({
    page,
    baseURL,
  }) => {
    await page.goto("/en");

    // ThreatCard wraps each <article> in an outer <Link>; the link
    // doesn't live inside the article. Select by href pattern instead.
    const cardLinks = page.locator('#feed a[href^="/en/threat/"]');
    const cardCount = await cardLinks.count();
    test.skip(cardCount === 0, "feed has no articles in this environment");

    const firstLink = cardLinks.first();
    // The link carries aria-label={title} — most stable handle for the
    // title text, since the <h2> sits inside the same anchor.
    const titleText = (await firstLink.getAttribute("aria-label"))?.trim();
    expect(titleText, "card link should expose an aria-label title").toBeTruthy();

    await firstLink.click();
    await expect(page).toHaveURL(/\/en\/threat\/[^/]+\/?$/);

    // Detail page renders the same title as an h1.
    await expect(
      page.getByRole("heading", { level: 1, name: new RegExp(escapeRegex(titleText!), "i") }),
    ).toBeVisible();

    // Browser back returns to the feed.
    await page.goBack();
    await expect(page).toHaveURL(/\/en\/?$/);
    await expect(page.locator("#feed")).toBeVisible();

    // Detail trip should not have produced 4xx/5xx for our own origin.
    // Replay the click with a fresh response collector so this assertion
    // is scoped to the detail navigation alone.
    const origin = new URL(baseURL!).origin;
    const { responses } = collectResponses(page);
    await cardLinks.first().click();
    await page.waitForLoadState("networkidle");
    expect(badStatuses(responses, origin)).toEqual([]);
  });

  test("trending section is visible and announces its heading", async ({ page }) => {
    await page.goto("/en");
    const trending = page.getByRole("region", { name: /trending/i });
    await expect(trending).toBeVisible();
    await expect(trending.getByRole("heading", { level: 2 })).toBeVisible();
  });

  test("/ua deep-link renders the Ukrainian shell", async ({ page }) => {
    await page.goto("/ua");
    await expect(page).toHaveURL(/\/ua\/?$/);
    // Hero h1 must still be present (text is localized).
    await expect(page.locator("h1#hero-headline")).toBeVisible();
    // Language switcher reflects active locale.
    const langSwitcher = page.getByRole("group", { name: "Language" });
    await expect(langSwitcher.getByRole("link", { name: "UA" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // Note: `<html lang="ua">` is asserted by the dedicated defect spec in
    // smoke.spec.ts — we deliberately don't double-fail here.
  });

  test("exactly one h1 per page (a11y heading order)", async ({ page }) => {
    await page.goto("/en");
    const h1Count = await page.locator("h1").count();
    expect(h1Count, "homepage should have a single h1").toBe(1);
  });

  test("mobile viewport renders core surfaces without layout collapse", async ({
    page,
    isMobile,
  }) => {
    test.skip(!isMobile, "runs in the mobile-chromium project only");

    await page.goto("/en");
    await expect(page.getByRole("banner")).toBeVisible();
    await expect(page.locator("h1#hero-headline")).toBeVisible();
    await expect(page.locator("#feed")).toBeVisible();

    // Mobile layout should keep the feed within the viewport horizontally
    // (i.e. no rogue overflow). Allow a 1px rounding fudge.
    const feedBox = await page.locator("#feed").boundingBox();
    expect(feedBox, "feed should have a bounding box").not.toBeNull();
    expect(feedBox!.x + feedBox!.width).toBeLessThanOrEqual(
      page.viewportSize()!.width + 1,
    );
  });
});

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
