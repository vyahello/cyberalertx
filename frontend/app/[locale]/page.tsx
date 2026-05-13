import { notFound } from "next/navigation";
import { HomeShell } from "@/components/layout/HomeShell";
import { fetchPosts } from "@/lib/api";
import { SUPPORTED_LOCALES, isLocale } from "@/lib/types";

/** ISR — same as before. Literal required by Next.js static analyzer. */
export const revalidate = 60;

/** Pre-generate one static page per supported locale at build time. */
export function generateStaticParams() {
  return SUPPORTED_LOCALES.map((locale) => ({ locale }));
}

export default async function LocaleHomePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();

  // Homepage policy: show only AI-rendered items (cachedOnly=true) so the
  // rule-based fallback never leaks into the public feed. The API no
  // longer applies a freshness window — every AI-rendered item is in
  // scope, sorted newest-first. 30 entries gives ~2-3 weeks of typical
  // ingest at a glance without becoming a wall.
  //
  // Operationally: `python -m cyberalertx.main generate --limit N` adds
  // N more posts; they show up here at the top by published_at. Old
  // items don't disappear — they just slide below the limit and remain
  // reachable via direct links (and, eventually, pagination).
  //
  // The empty-state copy ("Threat feed is updating") covers the
  // first-run / no-warm-cache case gracefully.
  const posts = await fetchPosts(locale, 30, { cachedOnly: true });
  return <HomeShell lang={locale} initialPosts={posts} />;
}
