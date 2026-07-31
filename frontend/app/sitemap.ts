import type { MetadataRoute } from "next";
import { fetchPosts } from "@/lib/api";
import { SITE_URL } from "@/lib/site";
import { SUPPORTED_LOCALES, contentFor, type Locale } from "@/lib/types";

/**
 * /sitemap.xml — every locale home page plus every threat detail page.
 *
 * Why this matters more than usual here: the homepage only renders the most
 * recent items, so a crawler following links alone can never reach a story
 * that has scrolled off the feed. The archive is real — the API serves any
 * post by id indefinitely — but without a sitemap it is invisible to search.
 *
 * Each entry carries `alternates.languages` so the EN and UA versions of a
 * story are declared as translations rather than competing near-duplicates.
 * A post only lists the locales it actually has content for: the product
 * never auto-translates Ukrainian-sourced news into English, so claiming an
 * `en` alternate for a UA-only story would advertise a page that renders an
 * empty state.
 *
 * Revalidated on the same hourly cadence as the feed. Regenerating on every
 * request would mean two API round-trips per crawler hit.
 */
export const revalidate = 3600;

const SITEMAP_POST_LIMIT = 200;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();

  const entries: MetadataRoute.Sitemap = SUPPORTED_LOCALES.map((locale) => ({
    url: `${SITE_URL}/${locale}`,
    lastModified: now,
    changeFrequency: "hourly" as const,
    priority: 1.0,
    alternates: {
      languages: {
        "en-US": `${SITE_URL}/en`,
        uk: `${SITE_URL}/ua`,
      },
    },
  }));

  // Fetch both locales in parallel, then union by post id. An EN-sourced
  // story appears in both responses; a UA-sourced one only in the UA feed.
  const perLocale = await Promise.all(
    SUPPORTED_LOCALES.map(async (locale) => ({
      locale,
      posts: await fetchPosts(locale, SITEMAP_POST_LIMIT, {
        revalidate,
        // A crawler request must never be the thing that stalls on a slow
        // backend — better a short sitemap than a timed-out one.
        timeoutMs: 8000,
      }),
    })),
  );

  const localesById = new Map<string, { locales: Locale[]; published: string }>();
  for (const { locale, posts } of perLocale) {
    for (const post of posts) {
      if (!contentFor(post, locale)) continue;
      const seen = localesById.get(post.id);
      if (seen) {
        if (!seen.locales.includes(locale)) seen.locales.push(locale);
      } else {
        localesById.set(post.id, { locales: [locale], published: post.published_at });
      }
    }
  }

  for (const [id, { locales, published }] of localesById) {
    const languages: Record<string, string> = {};
    if (locales.includes("en")) languages["en-US"] = `${SITE_URL}/en/threat/${id}`;
    if (locales.includes("ua")) languages["uk"] = `${SITE_URL}/ua/threat/${id}`;

    for (const locale of locales) {
      entries.push({
        url: `${SITE_URL}/${locale}/threat/${id}`,
        lastModified: new Date(published),
        // A threat brief is written once and not revised. Telling crawlers
        // otherwise wastes their budget re-fetching unchanged pages.
        changeFrequency: "weekly",
        priority: 0.7,
        alternates: { languages },
      });
    }
  }

  return entries;
}
