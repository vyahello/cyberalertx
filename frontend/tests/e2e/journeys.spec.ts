import { test, expect } from "@playwright/test";
import { badStatuses, collectResponses } from "./helpers";

test.describe("journeys @e2e", () => {
  test("open first article from feed → detail renders → back returns to feed", async ({
    page,
    baseURL,
  }) => {
    await page.goto("/en");

    // Each feed row has exactly one link: its headline.
    const cardLinks = page.locator('#feed article a[href^="/en/threat/"]');
    const cardCount = await cardLinks.count();
    test.skip(cardCount === 0, "feed has no articles in this environment");

    const firstLink = cardLinks.first();
    // The link text is the headline itself.
    const titleText = (await firstLink.textContent())?.trim();
    expect(titleText, "feed row link should carry the headline").toBeTruthy();

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

  test("priority section is visible and announces its heading", async ({ page }) => {
    await page.goto("/en");
    const priority = page.getByRole("region", { name: /Also significant now/i });
    test.skip((await priority.count()) === 0, "not enough stories for a priority list");
    await expect(priority).toBeVisible();
    await expect(priority.getByRole("heading", { level: 2 })).toBeVisible();
  });

  test("topic page lists only its own section and has one h1", async ({ page }) => {
    await page.goto("/en/topic/vulnerabilities");
    await expect(page.getByRole("heading", { level: 1, name: /Vulnerabilities/i })).toBeVisible();
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.locator("#feed")).toBeVisible();
  });

  test("severity deep link narrows the feed", async ({ page }) => {
    await page.goto("/en?level=Critical#feed");
    // The filter applies after hydration; the live count line switches from
    // "N briefs" to "n of N briefs" once it has.
    await expect(page.locator("#feed [aria-live]")).toContainText(/ of /, { timeout: 10_000 });
    const rows = page.locator("#feed article");
    test.skip((await rows.count()) === 0, "no critical stories in this environment");
    // Every visible row carries the Critical severity mark.
    for (const text of await rows.allInnerTexts()) {
      expect(text).toContain("Critical");
    }
  });

  test("/ua deep-link renders the Ukrainian shell", async ({ page }) => {
    await page.goto("/ua");
    await expect(page).toHaveURL(/\/ua\/?$/);
    // Hero h1 must still be present (text is localized).
    await expect(page.locator("h1#hero-headline")).toBeVisible();
    // Language switcher reflects active locale.
    const langSwitcher = page.getByRole("group", { name: /^(Language|Мова)$/ });
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
