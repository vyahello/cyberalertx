import { SITE_NAME, SITE_URL, absoluteUrl, postUrl } from "@/lib/site";
import { contentFor, type Locale, type LocalizedThreatPost } from "@/lib/types";

/**
 * JSON-LD structured data.
 *
 * Three audiences read this and none of them read our CSS:
 *   * Google — `NewsArticle` is the gate for Top Stories and Discover
 *     eligibility; `ItemList` helps the feed page be understood as a list of
 *     stories rather than one long document.
 *   * AI assistants — ChatGPT, Perplexity and Claude preferentially cite
 *     pages where authorship, publication date and the claim itself are
 *     machine-readable. For a threat-intel product, being the citable source
 *     is the whole distribution strategy.
 *   * Social and link unfurlers, as a fallback when OG tags are thin.
 *
 * Emitted via `<script type="application/ld+json">` inside a Server
 * Component, so it costs zero client JavaScript.
 */

function JsonLdScript({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      // The payload is our own structured object, not user input, and JSON
      // serialization already neutralizes markup. We additionally escape "<"
      // so a title containing "</script>" can't break out of the tag.
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(data).replace(/</g, "\\u003c"),
      }}
    />
  );
}

const PUBLISHER = {
  "@type": "Organization",
  name: SITE_NAME,
  url: SITE_URL,
  logo: {
    "@type": "ImageObject",
    url: absoluteUrl("/brand/og-image.png"),
  },
};

/**
 * Site-level identity, emitted once per page from the locale layout.
 *
 * `WebSite` + `Organization` together are what let a search engine show a
 * site name and logo next to results instead of a bare domain.
 */
export function SiteJsonLd({ lang }: { lang: Locale }) {
  return (
    <JsonLdScript
      data={{
        "@context": "https://schema.org",
        "@graph": [
          {
            "@type": "WebSite",
            "@id": `${SITE_URL}/#website`,
            url: `${SITE_URL}/${lang}`,
            name: SITE_NAME,
            inLanguage: lang === "ua" ? "uk" : "en",
            publisher: { "@id": `${SITE_URL}/#organization` },
          },
          {
            ...PUBLISHER,
            "@id": `${SITE_URL}/#organization`,
          },
        ],
      }}
    />
  );
}

/**
 * The feed page as an ordered list of stories.
 *
 * Capped at the first 20 — beyond that the payload grows faster than its
 * usefulness, and the sitemap already covers the long tail.
 */
export function FeedJsonLd({
  posts,
  lang,
}: {
  posts: LocalizedThreatPost[];
  lang: Locale;
}) {
  const items = posts.slice(0, 20).flatMap((post, index) => {
    const content = contentFor(post, lang);
    if (!content) return [];
    return [
      {
        "@type": "ListItem",
        position: index + 1,
        url: postUrl(lang, post.id),
        name: content.title,
      },
    ];
  });

  if (items.length === 0) return null;

  return (
    <JsonLdScript
      data={{
        "@context": "https://schema.org",
        "@type": "ItemList",
        name: lang === "ua" ? "Актуальні кіберзагрози" : "Current cyber threats",
        itemListOrder: "https://schema.org/ItemListOrderDescending",
        numberOfItems: items.length,
        itemListElement: items,
      }}
    />
  );
}

/**
 * One threat brief as a `NewsArticle`.
 *
 * Notes on the field choices, because several are easy to get subtly wrong:
 *   * `dateModified` mirrors `datePublished`. A brief is written once;
 *     claiming a fresher modification date to look current is the kind of
 *     thing that gets a site demoted, not promoted.
 *   * `isBasedOn` credits the original reporting we summarized. It is both
 *     honest attribution and a signal that this page is derived analysis
 *     rather than scraped duplicate content.
 *   * `about` carries the threat as a `Thing` with the severity, so an
 *     assistant answering "what's critical today" has something to match on.
 *   * No `author` person — these briefs are generated and reviewed by the
 *     system, and inventing a byline would be a fabrication.
 */
export function ThreatJsonLd({
  post,
  lang,
}: {
  post: LocalizedThreatPost;
  lang: Locale;
}) {
  const content = contentFor(post, lang);
  if (!content) return null;

  const url = postUrl(lang, post.id);
  const image = absoluteUrl(
    lang === "ua" ? "/brand/og-image-ua.png" : "/brand/og-image.png",
  );

  return (
    <JsonLdScript
      data={{
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "@id": url,
        mainEntityOfPage: { "@type": "WebPage", "@id": url },
        headline: content.title,
        description: content.plain_summary?.trim() || content.short_summary,
        articleSection:
          lang === "ua" ? "Кібербезпека" : "Cybersecurity",
        inLanguage: lang === "ua" ? "uk" : "en",
        datePublished: post.published_at,
        dateModified: post.published_at,
        publisher: PUBLISHER,
        image: [image],
        url,
        // Credit the reporting this brief is derived from.
        isBasedOn: post.source_url || undefined,
        creditText: post.source,
        about: {
          "@type": "Thing",
          name: content.title,
          description: content.why_it_matters || content.short_summary,
        },
        keywords: [
          post.category,
          ...(post.affected_platforms ?? []),
          post.threat_level,
        ]
          .filter(Boolean)
          .join(", "),
      }}
    />
  );
}
