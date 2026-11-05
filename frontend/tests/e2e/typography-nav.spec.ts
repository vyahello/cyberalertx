import { expect, test, type Page } from "@playwright/test";

/**
 * Headline descenders (g y j p q, у р д ц щ ф) must never be clipped, and the
 * mobile header uses a hamburger that becomes an X.
 */

const HARD_TITLES = [
  "Spyware quietly hijacks unpatched gateways, typing passwords by proxy",
  "Хакери у Грузії підробляють урядову пошту й доправляють шпигунську програму у смартфони",
  "Шифрувальник уразив ЦОД: щоденні резервні копії фірм під загрозою",
];
const WIDTHS = [375, 390, 430, 768, 1280, 1440, 1920];

async function firstArticle(page: Page, locale: "en" | "ua"): Promise<string> {
  await page.goto(`/${locale}`);
  const href = await page.locator(`a[href^="/${locale}/threat/"]`).first().getAttribute("href");
  expect(href).toBeTruthy();
  return href as string;
}

/** Nothing between the headline and the page may clip its glyph overflow. */
async function clippingProblems(page: Page, selector: string): Promise<string[]> {
  return page.locator(selector).first().evaluate(async (h) => {
    // The headline's own entrance only: the page also runs endless animations.
    await Promise.all(h.getAnimations().map((a) => a.finished.catch(() => undefined)));
    const out: string[] = [];
    const own = getComputedStyle(h);
    if (own.clipPath !== "none") out.push(`headline clip-path ${own.clipPath}`);
    if (own.overflow !== "visible" || own.webkitLineClamp !== "none") out.push(`headline overflow ${own.overflow}`);
    const lh = parseFloat(own.lineHeight) / parseFloat(own.fontSize);
    if (!(lh >= 1.05) && own.lineHeight !== "normal") out.push(`line-height ${lh.toFixed(2)}`);
    for (let el = h.parentElement; el && el !== document.body; el = el.parentElement) {
      const cs = getComputedStyle(el);
      if (cs.clipPath !== "none") out.push(`ancestor clip-path ${cs.clipPath}`);
      if ((cs.overflowY === "hidden" || cs.overflowY === "clip") &&
          el.getBoundingClientRect().bottom < h.getBoundingClientRect().bottom + 12) {
        out.push(`ancestor clips below the headline (${el.tagName})`);
      }
    }
    return out;
  });
}

for (const locale of ["en", "ua"] as const) {
  test(`article headline is never clipped (${locale})`, async ({ page }) => {
    test.setTimeout(180_000);
    const href = await firstArticle(page, locale);
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(href);
      for (const title of HARD_TITLES) {
        await page.locator("main h1").first().evaluate((h, t) => { h.textContent = t; }, title);
        expect(await clippingProblems(page, "main h1"), `${width}px: ${title}`).toEqual([]);
      }
    }
  });
}

test.describe("mobile navigation", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("hamburger opens a full panel, X closes it, Escape and links close it", async ({ page }) => {
    await page.goto("/en");
    const button = page.getByRole("button", { name: "Open navigation menu" });
    await expect(button).toBeVisible();
    const box = await button.boundingBox();
    expect(box && box.width >= 44 && box.height >= 44).toBeTruthy();
    const panelId = await button.getAttribute("aria-controls");
    expect(panelId).toBeTruthy();
    await expect(button).toHaveAttribute("aria-expanded", "false");

    await button.click();
    const close = page.getByRole("button", { name: "Close navigation menu" });
    await expect(close).toHaveAttribute("aria-expanded", "true");
    const panel = page.locator(`[id="${panelId}"]`);
    await expect(panel).toBeVisible();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");
    await expect(panel.locator("a").first()).toBeFocused();
    const labels = await panel.locator("nav li a").allInnerTexts();
    expect(labels.length).toBeGreaterThan(3);

    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
    await expect(page.getByRole("button", { name: "Open navigation menu" })).toBeFocused();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("");

    await page.getByRole("button", { name: "Open navigation menu" }).click();
    await panel.locator("nav li a").first().click();
    await expect(panel).toBeHidden();
  });

  test("the same items in the same order as the desktop navigation", async ({ page }) => {
    await page.goto("/ua");
    await page.getByRole("button", { name: "Відкрити меню навігації" }).click();
    const mobile = await page.locator("header [id] nav li a").allInnerTexts();
    await page.setViewportSize({ width: 1280, height: 800 });
    const desktop = await page.locator("header nav.hidden li a").allInnerTexts();
    expect(mobile.map((s) => s.trim())).toEqual(desktop.map((s) => s.trim()));
  });
});
