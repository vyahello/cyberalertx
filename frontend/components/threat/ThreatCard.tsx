import Link from "next/link";
import { ArrowUpRight, Clock, Users } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import { contentFor, type Locale, type LocalizedThreatPost } from "@/lib/types";
import { ActionPanel } from "./ActionPanel";
import { ActionabilityBadge } from "./ActionabilityBadge";
import { CredibilityBadge } from "./CredibilityBadge";
import { QuickFacts } from "./QuickFacts";
import { ThreatBadge } from "./ThreatBadge";

interface Props {
  post: LocalizedThreatPost;
  lang: Locale;
  /** Stagger index for the entrance animation. */
  index?: number;
  /** Compact = trending row. Hides action panel + why-it-matters. */
  compact?: boolean;
}

/**
 * Mobile-first card hierarchy (top → bottom, in order of "what the user
 * needs to know first"):
 *
 *   1. Threat-level + actionability badges      ← "should I care?"
 *   2. Title (clickable — entire card links to /[locale]/threat/[id])
 *   3. Source + relative time + reading time
 *   4. Short summary
 *   5. Quick facts (chips)
 *   6. Why-it-matters
 *   7. Affected users
 *   8. Action panel (do / don't)
 *
 * Linking strategy: the entire card is wrapped in a <Link> so any tap
 * navigates to the detail page. A small "open" affordance sits in the
 * top-right corner as a visual cue; we don't add it as a separate target
 * (the whole card is the target) but the icon hints at clickability.
 */
export function ThreatCard({ post, lang, index = 0, compact = false }: Props) {
  const s = strings(lang);
  const content = contentFor(post, lang);
  // Guard: this component should never be rendered for a post that doesn't
  // have content in `lang` (the parent filters). If it happens anyway,
  // render nothing rather than a partial card.
  if (!content) return null;

  const delay = `${Math.min(index, 8) * 60}ms`;

  return (
    <Link
      href={`/${lang}/threat/${post.id}`}
      prefetch={false}
      aria-label={content.title}
      className="block group"
    >
      <article
        lang={lang}
        className={cn(
          "surface-card surface-card-hover relative",
          "p-5 sm:p-6 animate-fade-up",
          "group-focus-visible:ring-2 group-focus-visible:ring-accent-ring",
        )}
        style={{ animationDelay: delay }}
      >
        {/* Subtle "open detail" affordance — visible on hover/focus. */}
        <ArrowUpRight
          className="absolute top-4 right-4 w-4 h-4 text-text-tertiary
                     opacity-0 group-hover:opacity-100 group-hover:text-text-secondary
                     transition-opacity duration-150"
          aria-hidden
          strokeWidth={2}
        />

        <header className="flex flex-wrap items-center gap-x-2 gap-y-2 mb-3 pr-6">
          <ThreatBadge level={post.threat_level} lang={lang} />
          <ActionabilityBadge level={post.actionability_level} lang={lang} />
          <div className="ml-auto flex items-center gap-3 text-xs text-text-tertiary">
            <span className="inline-flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {s.card_published_relative(post.published_at)}
            </span>
            <span aria-label={s.card_reading_time(content.reading_time_seconds)}>
              {s.card_reading_time(content.reading_time_seconds)}
            </span>
          </div>
        </header>

        <h2 className="text-lg sm:text-xl font-semibold text-text-primary leading-snug mb-2 break-words">
          {content.title}
        </h2>

        <div className="mb-4">
          <CredibilityBadge
            tier={post.source_tier}
            source={post.source}
            lang={lang}
            score={post.source_credibility_score}
          />
        </div>

        <p className="text-base text-text-primary leading-relaxed mb-4">
          {content.short_summary}
        </p>

        {content.quick_facts.length > 0 && (
          <QuickFacts facts={content.quick_facts} className="mb-5" />
        )}

        {!compact && (
          <>
            {content.why_it_matters && (
              <div className="border-l-2 border-accent/40 pl-3 mb-5">
                <p className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-1">
                  {s.card_why_it_matters}
                </p>
                <p className="text-sm text-text-primary leading-relaxed">
                  {content.why_it_matters}
                </p>
              </div>
            )}

            {content.affected_users.length > 0 && (
              <div className="flex items-start gap-2 text-sm text-text-secondary mb-5">
                <Users className="w-4 h-4 mt-0.5 flex-shrink-0 text-text-tertiary" />
                <span>{content.affected_users.join(" · ")}</span>
              </div>
            )}

            <hr className="border-border-subtle mb-5" />

            <ActionPanel
              toDo={content.what_to_do}
              notToDo={content.what_not_to_do}
              lang={lang}
            />
          </>
        )}
      </article>
    </Link>
  );
}
