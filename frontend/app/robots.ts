import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

/**
 * /robots.txt
 *
 * Everything reader-facing is open. The two disallows are deliberate:
 *   * `/admin/` — the API's metrics and source-health JSON. Not secret, but
 *     it has no reader value and would dilute the crawl budget.
 *   * `/api/` — reserved; nothing there should ever appear in a result page.
 *
 * The sitemap reference is what actually gets new threat pages discovered
 * quickly. Without it a crawler only finds a detail page by following a link
 * from the feed, and the feed only shows the most recent items — so older
 * stories would never be crawled at all.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/admin/", "/api/"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
