import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { FeedSection } from "@/components/feed/FeedSection";
import { BreadcrumbJsonLd, FeedJsonLd } from "@/components/seo/JsonLd";
import { fetchPosts } from "@/lib/api";
import { slimForFeed } from "@/lib/feed";
import { strings } from "@/lib/i18n";
import { SITE_URL, absoluteUrl } from "@/lib/site";
import { TOPIC_CATEGORIES, TOPIC_SLUGS, isTopic } from "@/lib/topics";
import { SUPPORTED_LOCALES, isLocale, postsAvailableIn } from "@/lib/types";

export const revalidate = 300;

/** The API's largest page; topics filter it down to their categories. */
const TOPIC_POOL = 200;

export function generateStaticParams() {
  return SUPPORTED_LOCALES.flatMap((locale) =>
    TOPIC_SLUGS.map((slug) => ({ locale, slug })),
  );
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale) || !isTopic(slug)) return {};
  const s = strings(locale);
  const topic = s.topic[slug];
  return {
    title: `${topic.name} — CyberAlertX`,
    description: topic.description,
    alternates: {
      canonical: `${SITE_URL}/${locale}/topic/${slug}`,
      languages: {
        "en-US": `${SITE_URL}/en/topic/${slug}`,
        uk: `${SITE_URL}/ua/topic/${slug}`,
        "x-default": `${SITE_URL}/en/topic/${slug}`,
      },
    },
    openGraph: {
      title: `${topic.name} — CyberAlertX`,
      description: topic.description,
      type: "website",
      siteName: "CyberAlertX",
      url: `/${locale}/topic/${slug}`,
    },
  };
}

export default async function TopicPage({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}) {
  const { locale, slug } = await params;
  if (!isLocale(locale) || !isTopic(slug)) notFound();

  const s = strings(locale);
  const categories = TOPIC_CATEGORIES[slug] as readonly string[];
  const posts = postsAvailableIn(
    await fetchPosts(locale, TOPIC_POOL, { cachedOnly: true, revalidate }),
    locale,
  ).filter((p) => categories.includes(p.category));

  return (
    <main className="pt-8 sm:pt-12 lg:pt-16">
      <BreadcrumbJsonLd
        items={[
          { name: s.edition_title, url: absoluteUrl(`/${locale}`) },
          { name: s.topic[slug].name, url: absoluteUrl(`/${locale}/topic/${slug}`) },
        ]}
      />
      <FeedJsonLd posts={posts} lang={locale} />
      <FeedSection
        posts={slimForFeed(posts, locale)}
        lang={locale}
        heading={s.topic[slug].name}
        headingLevel={1}
        description={s.topic[slug].description}
      />
    </main>
  );
}
