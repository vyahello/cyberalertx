import { expect, test } from "@playwright/test";

/**
 * Media Engine: branded cards are served from stable URLs on the site,
 * localized from each edition's own text, and every article's social
 * metadata points at its own card. Read-only — no state is changed.
 */

const VARIANTS: Record<string, [number, number]> = {
  og: [1200, 630],
  telegram: [1200, 675],
  "threads-portrait": [1080, 1350],
  "threads-square": [1080, 1080],
  preview: [640, 360],
};

function pngSize(buf: Buffer): [number, number] {
  expect(buf.subarray(1, 4).toString("latin1")).toBe("PNG");
  return [buf.readUInt32BE(16), buf.readUInt32BE(20)];
}

async function firstArticle(page: import("@playwright/test").Page, locale: "en" | "ua") {
  await page.goto(`/${locale}`);
  const href = await page.locator(`a[href^="/${locale}/threat/"]`).first().getAttribute("href");
  expect(href).toBeTruthy();
  return href!.split("/")[3];
}

test.describe("branded cards", () => {
  test("every variant renders at its declared size", async ({ page, request }) => {
    const id = await firstArticle(page, "ua");
    for (const [variant, [w, h]] of Object.entries(VARIANTS)) {
      const res = await request.get(`/ua/threat/${id}/card/${variant}.png`);
      expect(res.status(), variant).toBe(200);
      expect(res.headers()["content-type"]).toBe("image/png");
      expect(res.headers()["x-content-type-options"]).toBe("nosniff");
      expect(pngSize(await res.body()), variant).toEqual([w, h]);
    }
    for (const fmt of ["webp", "avif"]) {
      const res = await request.get(`/ua/threat/${id}/card/og.${fmt}`);
      expect(res.status()).toBe(200);
      expect(res.headers()["content-type"]).toBe(`image/${fmt}`);
    }
  });

  test("unknown variants, formats and ids are 404", async ({ page, request }) => {
    const id = await firstArticle(page, "ua");
    for (const path of [
      `/ua/threat/${id}/card/banner.png`,
      `/ua/threat/${id}/card/og.gif`,
      `/ua/threat/${id}/card/constructor.png`,
      `/ua/threat/not-an-id/card/og.png`,
      `/xx/threat/${id}/card/og.png`,
    ]) {
      expect((await request.get(path)).status(), path).toBe(404);
    }
  });

  test("the article's social image is its own localized card", async ({ page }) => {
    const id = await firstArticle(page, "ua");
    await page.goto(`/ua/threat/${id}`);
    const og = await page.locator('meta[property="og:image"]').first().getAttribute("content");
    expect(og).toContain(`/ua/threat/${id}/card/og.png?v=`);
    const tw = await page.locator('meta[name="twitter:image"]').first().getAttribute("content");
    expect(tw).toBe(og);
    const alt = await page.locator('meta[property="og:image:alt"]').first().getAttribute("content");
    expect(alt).toMatch(/[А-ЯІЇЄҐа-яіїєґ]/);
  });

  test("illustration route rejects anything but a known validated asset", async ({ request }) => {
    for (const path of ["/media/0000000000000000/og.png", "/media/../../etc/og.png", "/media/ZZ/og.png", "/media/0000000000000000/constructor.png"]) {
      expect([400, 404]).toContain((await request.get(path)).status());
    }
  });
});
