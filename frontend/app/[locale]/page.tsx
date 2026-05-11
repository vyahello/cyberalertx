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

  // 15 = the curated MVP feed size. The backend enforces freshness +
  // ranking; we ask for exactly what we render. Keeps payload small and
  // the homepage feeling intentional rather than firehose-y.
  const posts = await fetchPosts(15);
  return <HomeShell lang={locale} initialPosts={posts} />;
}
