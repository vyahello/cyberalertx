import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ThreatDetail } from "@/components/threat/ThreatDetail";
import { RelatedThreats } from "@/components/threat/RelatedThreats";
import { BreadcrumbJsonLd, ThreatJsonLd } from "@/components/seo/JsonLd";
import { fetchPost, fetchPosts } from "@/lib/api";
import { strings } from "@/lib/i18n";
import { absoluteUrl, postUrl } from "@/lib/site";
import { topicForCategory } from "@/lib/topics";
import { contentFor, isLocale, postsAvailableIn } from "@/lib/types";
import { VARIANTS } from "@/lib/media/card";
import { cardPath, cardSpec, specHash } from "@/lib/media/spec";

/** Search snippets cut around 155–160 characters; cut at a word instead. */
function clampDescription(text: string, max = 158): string {
  const t = text.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max);
  return cut.slice(0, cut.lastIndexOf(" ")).replace(/[,;:—–-]$/, "") + "…";
}

/**
 * Detail pages are cached and revalidated, not re-rendered per request.
 *
 * `revalidate` alone did nothing here. A dynamic segment without
 * `generateStaticParams` opts out of the static/ISR path entirely, so
 * `next build` reported this route as fully dynamic with no revalidate
 * window and every visit paid for three API round-trips. Exporting an
 * empty param list is the documented way to say "prerender none of these
 * at build time, but still cache them on first request" — the pages are
 * generated on demand and then served from cache.
 *
 * 300s rather than 60s: a threat brief is written once and not revised,
 * so the only thing a shorter window buys is load.
 */
export const revalidate = 300;

export function generateStaticParams(): { locale: string; id: string }[] {
  return [];
}

/** Fingerprints are 16 hex chars (see `NewsItem.fingerprint`). Anything else
 *  can't exist, so we reject it before spending a backend call on it. */
const FINGERPRINT_RE = /^[0-9a-f]{16}$/;

/**
 * Per-page metadata. Pulls the localized title + summary so social
 * previews and browser tabs read correctly in either language.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}): Promise<Metadata> {
  const { locale, id } = await params;
  if (!isLocale(locale)) return {};
  if (!FINGERPRINT_RE.test(id)) {
    return { title: "Threat not found — CyberAlertX", robots: { index: false } };
  }
  const post = await fetchPost(id);
  // Keep unresolvable ids out of the index — a crawler that finds a stale
  // link shouldn't add an empty page to the search results.
  if (!post) {
    return { title: "Threat not found — CyberAlertX", robots: { index: false } };
  }
  const c = contentFor(post, locale);
  if (!c) {
    return { title: `${post.source} — CyberAlertX` };
  }
  // Per-article, per-locale social card. Without an explicit openGraph here,
  // a shared link would inherit the layout's generic site card (the brand
  // tagline) instead of the article — and in the wrong language. We set the
  // article's own title/summary plus the locale-matched brand image so a
  // shared UA link unfurls in Ukrainian with the actual story.
  // The story's own branded card (localized, versioned by its content hash
  // so a changed headline or a new illustration refreshes social caches).
  // Falls back to the static brand image if the edition has no text.
  const spec = cardSpec(post, locale);
  const art = post.media?.illustration?.asset_id;
  const ogImage = spec
    ? cardPath(locale, id, "og", "png", specHash(spec) + (art ? `-${art.slice(0, 8)}` : ""))
    : locale === "ua" ? "/brand/og-image-ua.png" : "/brand/og-image.png";
  const ogAlt = spec
    ? `${spec.categoryLabel ? `${spec.categoryLabel}: ` : ""}${spec.title}`
    : "CyberAlertX";
  const ogLocale = locale === "ua" ? "uk_UA" : "en_US";

  // Language alternates for THIS story — listing only the locales it was
  // actually rendered in. A UA-sourced story has no English version (we
  // never auto-translate Ukrainian news), and advertising an `en` alternate
  // would point search engines at a "not available in this language" page.
  const languages: Record<string, string> = {};
  if (post.available_locales?.includes("en")) {
    languages["en-US"] = postUrl("en", id);
  }
  if (post.available_locales?.includes("ua")) {
    languages["uk"] = postUrl("ua", id);
  }

  return {
    title: `${c.title} — CyberAlertX`,
    description: clampDescription(c.plain_summary?.trim() || c.short_summary),
    alternates: {
      canonical: postUrl(locale, id),
      ...(Object.keys(languages).length > 1 ? { languages } : {}),
    },
    openGraph: {
      title: c.title,
      description: clampDescription(c.short_summary),
      type: "article",
      publishedTime: post.published_at,
      siteName: "CyberAlertX",
      locale: ogLocale,
      url: `/${locale}/threat/${id}`,
      images: [
        { url: ogImage, width: VARIANTS.og.width, height: VARIANTS.og.height, type: "image/png", alt: ogAlt },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: c.title,
      description: clampDescription(c.short_summary),
      images: [ogImage],
    },
  };
}

export default async function ThreatDetailPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  if (!isLocale(locale)) notFound();
  // Reject malformed ids before touching the backend.
  if (!FINGERPRINT_RE.test(id)) notFound();

  // Parallel fetches: the single post + a small pool for related-threats.
  //
  // Two non-obvious choices in this fetch:
  //   * `limit = 20`, not 50. RelatedThreats picks 4 items from the pool;
  //     20 is plenty of candidates while shrinking the per-render cost
  //     by 60%.
  //   * `cachedOnly: true`. The pool is a *suggestion surface*, not
  //     content the user is asking for. We never want browsing a detail
  //     page to spend AI tokens speculatively-rendering items the user
  //     might not even read. If an item isn't already AI-cached it's
  //     simply skipped from the pool; related-threats will still find
  //     4 good matches because category-only overlap is plentiful.
  const [post, pool] = await Promise.all([
    fetchPost(id),
    fetchPosts(locale, 40, { cachedOnly: true }),
  ]);

  // Header renders in app/[locale]/layout.tsx — persistent app shell.
  if (!post) {
    return <NotFound lang={locale} />;
  }

  const s = strings(locale);
  const c = contentFor(post, locale);
  const topic = topicForCategory(post.category);
  const crumbs = [
    { name: s.edition_title, url: absoluteUrl(`/${locale}`) },
    ...(topic ? [{ name: s.topic[topic].name, url: absoluteUrl(`/${locale}/topic/${topic}`) }] : []),
    ...(c ? [{ name: c.title, url: postUrl(locale, id) }] : []),
  ];

  return (
    <main>
      <ThreatJsonLd post={post} lang={locale} />
      <BreadcrumbJsonLd items={crumbs} />
      <ThreatDetail post={post} lang={locale} />
      <RelatedThreats pool={postsAvailableIn(pool, locale)} current={post} lang={locale} />
    </main>
  );
}

function NotFound({ lang }: { lang: "en" | "ua" }) {
  const s = strings(lang);
  return (
    <main className="page py-section">
      <div className="axis">
        <div className="on-axis">
          <h1 className="t-head text-ink">{s.detail_not_found_title}</h1>
          <p className="mt-4 text-ink-muted max-w-measure">{s.detail_not_found_hint}</p>
          <Link href={`/${lang}`} prefetch={false} className="btn-primary mt-8">
            {s.detail_back_home}
          </Link>
        </div>
      </div>
    </main>
  );
}
