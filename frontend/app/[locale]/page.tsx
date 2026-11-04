import { notFound } from "next/navigation";
import { FeedSection } from "@/components/feed/FeedSection";
import { LeadStory } from "@/components/home/LeadStory";
import { MethodSection } from "@/components/home/MethodSection";
import { PriorityList } from "@/components/home/PriorityList";
import { countOverview } from "@/components/home/ThreatOverview";
import { FeedJsonLd } from "@/components/seo/JsonLd";
import { fetchPosts } from "@/lib/api";
import { slimForFeed } from "@/lib/feed";
import { strings } from "@/lib/i18n";
import { pickFrontPage } from "@/lib/significance";
import { SUPPORTED_LOCALES, isLocale, postsAvailableIn } from "@/lib/types";

/** ISR. Literal required by Next.js' static analyser. */
export const revalidate = 60;

export function generateStaticParams() {
  return SUPPORTED_LOCALES.map((locale) => ({ locale }));
}

/** Posts shipped to the browser in the filterable feed: about a week. */
const FEED_SIZE = 40;
/** Pool read on the server for the 7-day overview counts (never shipped). */
const OVERVIEW_POOL = 120;

export default async function LocaleHomePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();

  // Only AI-rendered items (cachedOnly) so the rule-based fallback never
  // reaches the public feed; newest first from the API.
  const pool = postsAvailableIn(
    await fetchPosts(locale, OVERVIEW_POOL, { cachedOnly: true }),
    locale,
  );
  const posts = pool.slice(0, FEED_SIZE);
  const now = Date.now();
  const { lead, priority } = pickFrontPage(posts, now);
  const overview = countOverview(pool, now);
  const s = strings(locale);

  return (
    <main>
      <FeedJsonLd posts={posts} lang={locale} />
      <LeadStory lead={lead} total={posts.length} lang={locale} now={now} />
      <PriorityList posts={priority} lang={locale} overview={overview} />
      <FeedSection posts={slimForFeed(posts, locale)} lang={locale} heading={s.section_feed} className="mt-section" />
      <MethodSection posts={posts} lang={locale} />
    </main>
  );
}
