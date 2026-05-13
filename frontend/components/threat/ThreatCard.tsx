import Link from "next/link";
import { ArrowUpRight, Clock } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import { contentFor, type Locale, type LocalizedThreatPost } from "@/lib/types";
import { ActionabilityBadge } from "./ActionabilityBadge";
import { AudienceChip } from "./AudienceChip";
import { CategoryIconChip } from "./CategoryIconChip";
import { CorroborationLine } from "./CorroborationLine";
import { CredibilityBadge } from "./CredibilityBadge";
import { QuickFacts } from "./QuickFacts";
import { SignalIndicators } from "./SignalIndicators";
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
 * Compact feed card — tuned for thumb-scrolling on mobile.
 *
 * What's IN the card:
 *   1. Threat-level + actionability badges          ← "should I care?"
 *   2. AudienceChip ("Microsoft 365 users")          ← "is this about ME?"
 *   3. Title — entire card links to /[locale]/threat/[id]
 *   4. CredibilityBadge + (subtle) corroboration    ← "who's saying this?"
 *   5. Short summary (one tight editorial brief)
 *   6. SignalIndicators (max 3 chips)               ← "what does it DO?"
 *   7. Quick facts (chips)
 *
 * What's NOT in the card (moved to detail page exclusively):
 *   * Why-it-matters paragraph
 *   * Affected users list
 *   * What to do / what not to do action panel
 *
 * Rationale: in the feed, a reader scans. They commit to a card by
 * tapping it. The detail page is where actionable content lives. Mixing
 * both layers in the card made every entry 600px tall — bad UX on a
 * phone, and made the feed feel like a wall of repeat content.
 *
 * The `compact` prop is preserved for the Trending strip variant that
 * needs an even tighter card (no summary, no signals).
 */
export function ThreatCard({ post, lang, index = 0, compact = false }: Props) {
  const s = strings(lang);
  const content = contentFor(post, lang);
  // Guard: this component should never be rendered for a post that doesn't
  // have content in `lang` (the parent filters). If it happens anyway,
  // render nothing rather than a partial card.
  if (!content) return null;

  // Defensive normalization — the API contract types these as required,
  // but a degraded backend / partial cache hit could deliver sparse data.
  // We normalize to safe defaults here so a missing field renders as
  // absence (block skipped) instead of "undefined" in the DOM.
  const title = content.title?.trim() || s.empty_locale_unavailable;
  const summary = content.short_summary?.trim() || "";
  const quickFacts = content.quick_facts ?? [];
  const readingTime = Number.isFinite(content.reading_time_seconds)
    ? content.reading_time_seconds
    : 25;

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
          {/* Category icon — visual anchor for thumb-scrolling. Sits
              first in the header so the eye latches onto the chip before
              reading the threat-level badge. Hidden on the compact
              trending variant where vertical space is tighter. */}
          {!compact && (
            <CategoryIconChip category={post.category} lang={lang} />
          )}
          <ThreatBadge level={post.threat_level} lang={lang} />
          <ActionabilityBadge level={post.actionability_level} lang={lang} />
          <div className="ml-auto flex items-center gap-3 text-xs text-text-tertiary">
            <span className="inline-flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {s.card_published_relative(post.published_at)}
            </span>
            <span aria-label={s.card_reading_time(readingTime)}>
              {s.card_reading_time(readingTime)}
            </span>
          </div>
        </header>

        {/* "Is this about me?" line — sits between the severity badges
            and the title so a scanning reader sees audience before
            content. Renders nothing when who_should_care isn't available
            (older API shapes / sparse signals). */}
        <AudienceChip post={post} lang={lang} className="mb-2.5" />

        <h2 className="text-lg sm:text-xl font-semibold text-text-primary leading-snug mb-2 break-words">
          {title}
        </h2>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 mb-4">
          <CredibilityBadge
            tier={post.source_tier}
            source={post.source}
            lang={lang}
            score={post.source_credibility_score}
          />
          {/* Trust anchor — "Also reported by …" appears inline next to
              the source when at least one trusted peer covers the story.
              Compact: same line as credibility when there's room, wraps
              below on narrow viewports. */}
          <CorroborationLine
            sources={post.corroborating_sources}
            lang={lang}
            withIcon={false}
          />
        </div>

        {summary && (
          <p className="text-base text-text-primary leading-relaxed mb-3">
            {summary}
          </p>
        )}

        {/* Signal indicators — at most 3 icon-chips describing what the
            threat actually does to the reader. The only colored chip is
            `active_exploitation`; everything else is monochromatic so
            the card never reads as a panic dashboard. */}
        <SignalIndicators signals={post.signals} lang={lang} max={3} className="mb-4" />

        {!compact && quickFacts.length > 0 && (
          <QuickFacts facts={quickFacts} />
        )}
      </article>
    </Link>
  );
}
