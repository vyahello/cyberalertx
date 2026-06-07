import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ArrowLeft } from "lucide-react";
import { Header } from "@/components/layout/Header";
import { ThreatDetail } from "@/components/threat/ThreatDetail";
import { RelatedThreats } from "@/components/threat/RelatedThreats";
import { fetchPost, fetchPosts } from "@/lib/api";
import { strings } from "@/lib/i18n";
import { contentFor, isLocale, postsAvailableIn } from "@/lib/types";

/** Same ISR window as the homepage — detail content shouldn't go stale
 *  faster than the feed it belongs to. */
export const revalidate = 60;

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
  const post = await fetchPost(id);
  if (!post) return { title: "Threat not found — CyberAlertX" };
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
  return {
    title: `${c.title} — CyberAlertX`,
    description: c.short_summary,
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

  if (!post) {
    return (
      <>
        <Header lang={locale} />
        <NotFound lang={locale} />
      </>
    );
  }

  return (
    <>
      <Header lang={locale} />
      <main className="min-h-screen">
        <ThreatDetail post={post} lang={locale} />
        <div className="mx-auto max-w-6xl px-5 sm:px-8 pb-20">
          <RelatedThreats
            pool={postsAvailableIn(pool, locale)}
            current={post}
            lang={locale}
          />
        </div>
      </main>
    </>
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
