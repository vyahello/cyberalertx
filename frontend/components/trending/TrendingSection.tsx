import Link from "next/link";
import { TrendingUp } from "lucide-react";
import { strings } from "@/lib/i18n";
import { contentFor, type Locale, type LocalizedThreatPost } from "@/lib/types";
import { LivePulse } from "../hero/LivePulse";
import { ThreatBadge } from "../threat/ThreatBadge";
import { CredibilityBadge } from "../threat/CredibilityBadge";

interface Props {
  posts: LocalizedThreatPost[];
  lang: Locale;
}

/**
 * Compact horizontal scroller of the highest-signal items. Used above the
 * filter+feed split.
 *
 * Why a separate component (and not just a `compact` variant of the feed):
 *   * Different selection rule — we pick urgent_action + trusted, regardless
 *     of the user's filter state. The "active right now" view doesn't get
 *     hidden by filtering on "informational only".
 *   * Different layout — horizontal scroll with edge mask, not a vertical
 *     stack.
 *   * Different density — each card is intentionally smaller, less crowded.
 */
// Numeric weight per threat level — used to sort "most dangerous" first.
const LEVEL_WEIGHT: Record<string, number> = {
  Critical: 4,
  High: 3,
  Medium: 2,
  Low: 1,
};

export function TrendingSection({ posts, lang }: Props) {
  const s = strings(lang);
  // Trending = the five most-dangerous active items in this locale. We
  // re-sort the homepage's feed (already locale-filtered & fresh-windowed
  // by the API) by a danger-first key so this section reads as
  // "what's most serious right now", not "what's most recent".
  const trending = posts
    .filter(
      (p) =>
        p.actionability_level === "urgent_action" || p.threat_level === "Critical",
    )
    .filter((p) => p.available_locales.includes(lang))
    .sort((a, b) => {
      // Lexicographic: threat level → actionability → freshness.
      const lvl = (LEVEL_WEIGHT[b.threat_level] ?? 0) - (LEVEL_WEIGHT[a.threat_level] ?? 0);
      if (lvl !== 0) return lvl;
      const act = b.actionability_score - a.actionability_score;
      if (act !== 0) return act;
      return new Date(b.published_at).getTime() - new Date(a.published_at).getTime();
    })
    .slice(0, 5);
  if (!trending.length) return null;

  return (
    <section
      aria-labelledby="trending-heading"
      className="mx-auto max-w-6xl px-5 sm:px-8 py-10 sm:py-12"
    >
      <header className="flex items-end justify-between mb-5">
        <div>
          <h2
            id="trending-heading"
            className="inline-flex items-center gap-2 text-xl sm:text-2xl font-semibold text-text-primary"
          >
            <TrendingUp className="w-5 h-5 text-accent" strokeWidth={2.5} />
            {s.section_trending}
            <LivePulse size="sm" className="ml-2" />
          </h2>
          <p className="text-sm text-text-secondary mt-1.5 max-w-xl">
            {s.section_trending_caption}
          </p>
        </div>
      </header>

      <div className="relative">
        <div className="overflow-x-auto -mx-5 sm:-mx-8 px-5 sm:px-8 pb-2 mask-fade-x">
          <ul className="flex gap-3 snap-x snap-mandatory">
            {trending.map((post) => {
              const c = contentFor(post, lang);
              if (!c) return null;
              return (
                <li key={post.id} className="snap-start flex-shrink-0 w-[300px] sm:w-[340px]">
                  <Link
                    href={`/${lang}/threat/${post.id}`}
                    prefetch={false}
                    className="surface-card surface-card-hover p-4 flex flex-col gap-3 h-full
                               focus-visible:ring-2 focus-visible:ring-accent-ring"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <ThreatBadge level={post.threat_level} lang={lang} />
                      <CredibilityBadge
                        tier={post.source_tier}
                        source={post.source}
                        lang={lang}
                      />
                    </div>
                    <h3 className="text-base font-semibold text-text-primary leading-snug line-clamp-3">
                      {c.title}
                    </h3>
                    <p className="text-sm text-text-secondary leading-relaxed line-clamp-3 mt-auto">
                      {c.why_it_matters}
                    </p>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </section>
  );
}
