import { fetchPosts } from "@/lib/api";
import { SITE_NAME, SITE_URL, postUrl } from "@/lib/site";
import { strings } from "@/lib/i18n";
import { contentFor, isLocale, type Locale, type LocalizedThreatPost } from "@/lib/types";

/**
 * RSS 2.0 feed, one per locale: /en/feed.xml and /ua/feed.xml.
 *
 * Security practitioners live in feed readers — it is the native
 * distribution channel for this audience, and it costs one route to serve.
 * It also gives aggregators (Feedly, Inoreader, NewsBlur) and AI assistants
 * a machine-readable view of the whole feed rather than one scraped page.
 *
 * Editorial choice: the description carries the plain-language summary and
 * the concrete actions, not the full analysis. A feed entry should let the
 * reader decide "does this affect me, and what do I do about it" without
 * leaving their reader, while the detail page remains where the full brief
 * lives.
 */
export const revalidate = 900;

const FEED_LIMIT = 40;

/** Escape the five characters that are special in XML character data. */
function xml(text: string): string {
  return (text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function itemXml(post: LocalizedThreatPost, locale: Locale): string | null {
  const content = contentFor(post, locale);
  if (!content) return null;

  const s = strings(locale);
  const url = postUrl(locale, post.id);
  const lead = content.plain_summary?.trim() || content.short_summary?.trim() || "";

  const actions = (content.what_to_do ?? []).filter((a) => a.trim());
  const actionBlock = actions.length
    ? `<p><strong>${xml(s.card_what_to_do)}</strong></p><ul>${actions
        .map((a) => `<li>${xml(a)}</li>`)
        .join("")}</ul>`
    : "";

  // Severity and category ride along as categories so readers that support
  // filtering can build rules like "only Critical" without parsing prose.
  const categories = [
    s.level[post.threat_level],
    s.category[post.category] ?? post.category,
  ]
    .map((c) => `<category>${xml(c)}</category>`)
    .join("");

  return `    <item>
      <title>${xml(content.title)}</title>
      <link>${xml(url)}</link>
      <guid isPermaLink="true">${xml(url)}</guid>
      <pubDate>${new Date(post.published_at).toUTCString()}</pubDate>
      <source url="${xml(post.source_url)}">${xml(post.source)}</source>
      ${categories}
      <description><![CDATA[<p>${lead}</p>${actionBlock}]]></description>
    </item>`;
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ locale: string }> },
) {
  const { locale } = await params;
  if (!isLocale(locale)) {
    return new Response("Not found", { status: 404 });
  }

  const s = strings(locale);
  const posts = await fetchPosts(locale, FEED_LIMIT, { revalidate });
  const items = posts
    .map((p) => itemXml(p, locale))
    .filter((x): x is string => x !== null)
    .join("\n");

  const self = `${SITE_URL}/${locale}/feed.xml`;
  const lastBuild = posts.length
    ? new Date(posts[0].published_at).toUTCString()
    : new Date().toUTCString();

  const body = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>${xml(SITE_NAME)}${locale === "ua" ? " — Кіберзагрози" : " — Cyber threats"}</title>
    <link>${SITE_URL}/${locale}</link>
    <description>${xml(s.hero_subhead)}</description>
    <language>${locale === "ua" ? "uk" : "en"}</language>
    <lastBuildDate>${lastBuild}</lastBuildDate>
    <atom:link href="${xml(self)}" rel="self" type="application/rss+xml" />
${items}
  </channel>
</rss>`;

  return new Response(body, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
      // Let a CDN or reverse proxy serve the cached copy while it refreshes
      // in the background — feed readers poll far more often than content
      // actually changes.
      "Cache-Control": `public, max-age=0, s-maxage=${revalidate}, stale-while-revalidate=${revalidate * 4}`,
    },
  });
}
