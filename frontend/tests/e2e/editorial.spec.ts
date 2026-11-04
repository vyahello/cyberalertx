import { expect, test, type Page } from "@playwright/test";

/**
 * Editorial-quality upgrade: public-facing guarantees that hold for any
 * content (no fixture articles required).
 */

const AI_AUTHORSHIP = /AI editorial|editorial pipeline|written by .{0,20}\bAI\b|на основі ШІ|редакційна система/i;

async function firstArticleHref(page: Page, lang: "en" | "ua"): Promise<string> {
  await page.goto(`/${lang}`);
  const href = await page.locator(`a[href^="/${lang}/threat/"]`).first().getAttribute("href");
  expect(href, "the homepage links at least one brief").toBeTruthy();
  return href!;
}

for (const lang of ["en", "ua"] as const) {
  test.describe(`editorial (${lang})`, () => {
    test("homepage says what the publication is", async ({ page }) => {
      await page.goto(`/${lang}`);
      await expect(page.locator("h1").first()).toHaveText(
        lang === "en" ? "Cyber threat briefing" : "Огляд кіберзагроз",
      );
      await expect(page.locator("body")).not.toContainText(AI_AUTHORSHIP);
    });

    test("article: no AI authorship, no generic background, clear attribution", async ({ page }) => {
      await page.goto(await firstArticleHref(page, lang));
      const body = page.locator("body");
      await expect(body).not.toContainText(AI_AUTHORSHIP);
      await expect(page.getByRole("heading", { name: /Background: this kind of attack|Контекст: такі атаки загалом/ }))
        .toHaveCount(0);
      await expect(page.locator("#sec-sources")).toBeVisible();
      await expect(page.locator("section:has(#sec-sources)")).toContainText(lang === "en" ? "Source:" : "Джерело:");
    });

    test("article: problem reports are separate from attribution and the vote", async ({ page }) => {
      await page.goto(await firstArticleHref(page, lang));
      const group = page.getByRole("group", {
        name: lang === "en" ? "Report a problem with this brief" : "Повідомити про проблему в матеріалі",
      });
      await expect(group.getByRole("button")).toHaveCount(3);
      await expect(page.locator("section:has(#sec-sources)").getByRole("button")).toHaveCount(0);
    });

    test("article: the 'What to do' anchor points at the actions", async ({ page }) => {
      await page.goto(await firstArticleHref(page, lang));
      const anchor = page.locator('a[href="#actions"]');
      if ((await anchor.count()) > 0) {
        await expect(page.locator("#actions")).toHaveCount(1);
      }
    });
  });
}
