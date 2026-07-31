import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ArrowLeft } from "lucide-react";
import { ThreatDetail } from "@/components/threat/ThreatDetail";
import { RelatedThreats } from "@/components/threat/RelatedThreats";
import { ThreatJsonLd } from "@/components/seo/JsonLd";
import { fetchPost, fetchPosts } from "@/lib/api";
import { strings } from "@/lib/i18n";
import { postUrl } from "@/lib/site";
import { contentFor, isLocale, postsAvailableIn } from "@/lib/types";

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
  const ogImage = locale === "ua" ? "/brand/og-image-ua.png" : "/brand/og-image.png";
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
    description: c.plain_summary?.trim() || c.short_summary,
    alternates: {
      canonical: postUrl(locale, id),
      ...(Object.keys(languages).length > 1 ? { languages } : {}),
    },
    openGraph: {
      title: c.title,
      description: c.short_summary,
      type: "article",
      siteName: "CyberAlertX",
      locale: ogLocale,
      url: `/${locale}/threat/${id}`,
      images: [
        { url: ogImage, width: 1200, height: 630, type: "image/png" },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: c.title,
      description: c.short_summary,
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
    fetchPosts(locale, 20, { cachedOnly: true }),
  ]);

  // Header renders in app/[locale]/layout.tsx — persistent app shell.
  if (!post) {
    return <NotFound lang={locale} />;
  }

  return (
    <main className="min-h-screen">
      {/* NewsArticle structured data — the gate for Google Top Stories /
          Discover eligibility, and what makes the brief citable by AI
          assistants rather than merely readable. */}
      <ThreatJsonLd post={post} lang={locale} />
      <ThreatDetail post={post} lang={locale} />
      <div className="mx-auto max-w-6xl px-5 sm:px-8 pb-20">
        <RelatedThreats
          pool={postsAvailableIn(pool, locale)}
          current={post}
          lang={locale}
        />
      </div>
    </main>
  );
}

function NotFound({ lang }: { lang: "en" | "ua" }) {
  const s = strings(lang);
  return (
    <main className="mx-auto max-w-2xl px-5 sm:px-8 py-24 text-center">
      <h1 className="text-2xl font-semibold text-text-primary mb-2">
        {s.detail_not_found_title}
      </h1>
      <p className="text-sm text-text-secondary mb-6">{s.detail_not_found_hint}</p>
      <Link href={`/${lang}`} className="btn-primary">
        <ArrowLeft className="w-4 h-4" />
        {s.detail_back_to_feed}
      </Link>
    </main>
  );
}
