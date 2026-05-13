import Link from "next/link";
import { Sparkles, TrendingUp } from "lucide-react";
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

/**
 * Compose a one-line "why this is trending" rationale from the post's
 * intelligence fields. We walk a priority ladder and pick the FIRST
 * thing that fires — the goal is one specific reason, not a list. If
 * none of the signals are present, return null and the card just shows
 * its summary.
 */
function whyTrending(post: LocalizedThreatPost, lang: Locale): string | null {
  const s = strings(lang);
  const sig = post.signals;
  const corroborated = post.corroborating_sources?.length ?? 0;

  if (sig?.active_exploitation) return s.trending_reason_active_exploitation;
  if (post.threat_level === "Critical") return s.trending_reason_critical;
  if (post.actionability_level === "urgent_action") return s.trending_reason_urgent;
  if (corroborated > 0) return s.trending_reason_corroborated(corroborated);
  if (sig?.affects_email_accounts) return s.trending_reason_email_accounts;
  if (sig?.credential_theft_risk) return s.trending_reason_credentials;
  return null;
}

export function TrendingSection({ posts, lang }: Props) {
  const s = strings(lang);
  // Trending = top-5 most-dangerous items in this locale's feed.
  //
  // Input `posts` is the locale-scoped homepage feed. The dangerSort key
  // (level → actionability → freshness) bubbles severe items to the top
  // regardless of publication date.
  //
  // The previous implementation applied a strict filter (urgent_action OR
  // Critical) and only fell back to the full pool when strict was empty.
  // That produced asymmetric counts across locales — EN had 1 strict match
  // and showed 1 item; UA had 5 strict matches and showed 5. Readers saw
  // it as a sync bug. We now always sort the full pool and slice top-5,
  // so both locales render the same shape (up to data availability).
  // Items that AREN'T critical / urgent simply read as "highest-signal in
  // this language right now" — which is what Trending Now means anyway.
  const dangerSort = (a: LocalizedThreatPost, b: LocalizedThreatPost) => {
    const lvl = (LEVEL_WEIGHT[b.threat_level] ?? 0) - (LEVEL_WEIGHT[a.threat_level] ?? 0);
    if (lvl !== 0) return lvl;
    const act = b.actionability_score - a.actionability_score;
    if (act !== 0) return act;
    return new Date(b.published_at).getTime() - new Date(a.published_at).getTime();
  };
  const trending = posts.slice().sort(dangerSort).slice(0, 5);
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
              const reason = whyTrending(post, lang);
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
                    {/* "Why trending" rationale. Renders only when one of
                        the heuristics fires; otherwise the slot is empty
                        and the why_it_matters line carries the meaning. */}
                    {reason && (
                      <p className="inline-flex items-center gap-1.5 text-2xs uppercase tracking-wider text-accent/90 font-semibold">
                        <Sparkles className="w-3 h-3" strokeWidth={2.4} aria-hidden />
                        {reason}
                      </p>
                    )}
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
