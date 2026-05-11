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
  return {
    title: `${c.title} — CyberAlertX`,
    description: c.short_summary,
  };
}

export default async function ThreatDetailPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  if (!isLocale(locale)) notFound();

  // Parallel fetches: the single post + the full pool for related-threats.
  // The pool fetch is cheap (ISR-cached at 60s) and reused across detail pages.
  const [post, pool] = await Promise.all([fetchPost(id), fetchPosts(50)]);

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

function NotFound({ lang }: { lang: "en" | "uk" }) {
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
