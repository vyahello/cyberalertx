import { expect, test, type Locator } from "@playwright/test";

/**
 * Brand lockup and the mobile header: the wordmark reads "cyberalertx" in
 * the header and the footer; on phones the logo sits left, the language
 * switch next, the menu button at the far right; every control is a 44 px
 * target; the menu opens and closes in place and groups its links.
 */

const NARROW = [320, 360, 375, 390, 414, 768];

async function box(l: Locator) {
  const b = await l.boundingBox();
  expect(b, "element is rendered").not.toBeNull();
  return b!;
}

function wordmarkText(scope: Locator) {
  return scope.locator("[data-wordmark-text]").first();
}

for (const lang of ["en", "ua"] as const) {
  test(`wordmark reads "cyberalertx" in header and footer (${lang})`, async ({ page }) => {
    await page.goto(`/${lang}`);
    for (const scope of [page.locator("body > header"), page.locator("body > footer")]) {
      const text = wordmarkText(scope);
      await expect(text).toBeVisible();
      // Exactly the full name: never the old "cyberalert" with a glyph for X.
      expect((await text.textContent())?.trim()).toBe("cyberalertx");
      // The aperture glyph is part of the same lockup.
      await expect(scope.locator("[data-wordmark] svg")).toHaveCount(1);
    }
    // The logotype face covers every letter of the lockup, the final x included.
    const family = await wordmarkText(page.locator("body > header")).evaluate(
      (el) => getComputedStyle(el).fontFamily,
    );
    expect(family).toMatch(/Space_Grotesk|Space Grotesk|__Space/i);
    // Textual brand name is unchanged for metadata.
    await expect(page.locator('meta[property="og:site_name"]')).toHaveAttribute("content", "CyberAlertX");
  });
}

test.describe("mobile header", () => {
  for (const width of NARROW) {
    test(`logo left, language, menu button far right at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto("/en");
      const logo = page.getByTestId("header-logo");
      const lang = page.locator("body > header").getByRole("group", { name: "Language" }).first();
      const menu = page.getByTestId("menu-button");
      const [l, g, m] = [await box(logo), await box(lang), await box(menu)];

      // Order and no overlap.
      expect(l.x + l.width).toBeLessThanOrEqual(g.x + 0.5);
      expect(g.x + g.width).toBeLessThanOrEqual(m.x + 0.5);
      // Hamburger at the far right, inside the viewport.
      expect(m.x + m.width).toBeLessThanOrEqual(width);
      expect(width - (m.x + m.width)).toBeLessThan(32);
      // One row: vertical centres agree within 2 px.
      const cy = (b: { y: number; height: number }) => b.y + b.height / 2;
      expect(Math.abs(cy(l) - cy(m))).toBeLessThanOrEqual(2);
      expect(Math.abs(cy(g) - cy(m))).toBeLessThanOrEqual(2);
      // No horizontal page scroll.
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    });
  }

  test("touch targets are at least 44x44 CSS px", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 800 });
    await page.goto("/ua");
    const header = page.locator("body > header");
    const targets = [
      page.getByTestId("header-logo"),
      header.getByRole("link", { name: "EN" }),
      header.getByRole("link", { name: "UA" }),
      page.getByTestId("menu-button"),
    ];
    for (const t of targets) {
      const b = await box(t);
      expect(b.width, await t.evaluate((e) => e.outerHTML.slice(0, 80))).toBeGreaterThanOrEqual(44);
      expect(b.height).toBeGreaterThanOrEqual(44);
    }
    // Active language is marked for AT and visibly distinct.
    const active = header.getByRole("link", { name: "UA" });
    await expect(active).toHaveAttribute("aria-current", "page");
    const colour = (l: Locator) => l.evaluate((e) => getComputedStyle(e).color);
    expect(await colour(active)).not.toBe(await colour(header.getByRole("link", { name: "EN" })));

    await page.getByTestId("menu-button").click();
    for (const a of await page.locator('[data-testid="menu-primary"] a, [data-testid="menu-secondary"] a').all()) {
      const b = await box(a);
      expect(b.height).toBeGreaterThanOrEqual(44);
    }
  });

  test("menu opens and closes in place; Escape closes and restores focus", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    await page.goto("/en");
    const button = page.getByTestId("menu-button");
    const closed = await box(button);
    await expect(button).toHaveAccessibleName("Open navigation menu");
    await expect(button).toHaveAttribute("aria-expanded", "false");

    await button.click();
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(button).toHaveAccessibleName("Close navigation menu");
    // The X sits exactly where the hamburger was.
    const opened = await box(button);
    expect(Math.abs(opened.x - closed.x)).toBeLessThanOrEqual(1);
    expect(Math.abs(opened.y - closed.y)).toBeLessThanOrEqual(1);
    const panel = page.locator(`[id="${await button.getAttribute("aria-controls")}"]`);
    await expect(panel).toBeVisible();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");
    // The header (wordmark, language, X) stays visible above the sheet.
    await expect(page.getByTestId("header-logo")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
    await expect(button).toBeFocused();
    await expect(button).toHaveAttribute("aria-expanded", "false");
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("");

    // The X closes it too.
    await button.click();
    await expect(panel).toBeVisible();
    await button.click();
    await expect(panel).toBeHidden();
  });

  test("Tab stays inside the header while the menu is open", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/en");
    await page.getByTestId("menu-button").click();
    for (let i = 0; i < 14; i++) {
      await page.keyboard.press("Tab");
      expect(await page.evaluate(() => !!document.activeElement?.closest("body > header"))).toBe(true);
    }
  });

  for (const lang of ["en", "ua"] as const) {
    test(`menu groups: primary sections, then Telegram and RSS (${lang})`, async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 812 });
      await page.goto(`/${lang}`);
      await page.getByTestId("menu-button").click();
      const primary = page.getByTestId("menu-primary");
      const secondary = page.getByTestId("menu-secondary");
      await expect(primary).toBeVisible();
      await expect(secondary).toBeVisible();

      const names =
        lang === "en"
          ? ["Latest", "Vulnerabilities", "Malware and ransomware", "Data breaches", "Phishing and scams"]
          : ["Головне", "Вразливості", "Шкідливе ПЗ і вимагачі", "Витоки даних", "Фішинг і шахрайство"];
      expect((await primary.locator("li a").allInnerTexts()).map((t) => t.trim())).toEqual(names);
      await expect(primary.locator('a[aria-current="page"]')).toHaveAttribute("href", `/${lang}`);

      // Secondary: a labelled group with exactly Telegram and RSS, below the sections.
      await expect(secondary).toHaveAttribute("role", "group");
      const links = secondary.getByRole("link");
      await expect(links).toHaveCount(2);
      await expect(links.nth(0)).toHaveAttribute("href", `https://t.me/cyberalertx_${lang}`);
      await expect(links.nth(1)).toHaveAttribute("href", `/${lang}/feed.xml`);
      const p = await box(primary);
      const s = await box(secondary);
      expect(s.y).toBeGreaterThanOrEqual(p.y + p.height - 1);
      // The sheet is as tall as its content: no empty panel to the bottom.
      const sheet = await box(secondary.locator(".."));
      expect(sheet.y + sheet.height).toBeLessThan(812);
    });
  }
});

test("footer keeps every destination", async ({ page }) => {
  await page.goto("/en");
  const footer = page.locator("body > footer");
  const hrefs = await footer.locator("a[href]").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  for (const h of [
    "/en",
    "/en/topic/vulnerabilities",
    "/en/topic/malware",
    "/en/topic/breaches",
    "/en/topic/phishing",
    "/ua",
    "https://t.me/cyberalertx_en",
    "/en/feed.xml",
  ]) {
    expect(hrefs, h).toContain(h);
  }
  await expect(footer.locator('a[href^="mailto:"]')).toHaveCount(1);
  await expect(footer).toContainText("© 2026 CyberAlertX");
});
