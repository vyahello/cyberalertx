import Link from "next/link";
import { ArrowUpRight, CheckCircle2, Clock } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import { HTML_LANG, contentFor, type Locale, type LocalizedThreatPost } from "@/lib/types";
import { ActionabilityBadge } from "./ActionabilityBadge";
import { AudienceChip } from "./AudienceChip";
import { CategoryIconChip } from "./CategoryIconChip";
import { CredibilityBadge } from "./CredibilityBadge";
import { RelativeTime } from "./RelativeTime";
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
 * What's IN the card, in reading order:
 *   1. Category chip + threat level (+ urgency only when there IS urgency)
 *      and the timestamp                            ← "should I care?"
 *   2. AudienceChip ("Microsoft 365 users")          ← "is this about ME?"
 *   3. Title, clamped to 3 lines — the whole card links to the detail page
 *   4. Plain-language lead, clamped                  ← "what happened?"
 *   5. Footer: source credibility, source count, ≤2 signal chips
 *                                                    ← "who says so?"
 *
 * What's NOT in the card (detail page only):
 *   * Why-it-matters paragraph, affected-users list, action panel
 *   * Quick facts — a spec sheet belongs where the reader has committed
 *   * Reading time — it measured the card's own text, so it said the same
 *     thing on every card and changed nobody's decision to tap
 *
 * Rationale: in the feed, a reader scans and commits by tapping. Every
 * object competing above the headline delays that decision. The clamps
 * matter for the same reason — uniform card height gives the column a
 * rhythm to scan down, where variable height makes the eye re-anchor on
 * each entry.
 *
 * The `compact` prop is preserved for the Trending strip variant that
 * needs an even tighter card.
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
  // Plain-language first: lead with the everyday-language line when the post
  // has one, falling back to the editorial summary for older cached posts
  // that predate `plain_summary`.
  const lead = content.plain_summary?.trim() || content.short_summary?.trim() || "";
  // How many outlets covered this story, counting the one we're showing.
  // Falls back to the corroboration list for API responses that predate
  // `story_source_count`.
  const sourceCount =
    post.story_source_count ?? (post.corroborating_sources?.length ?? 0) + 1;

  // Entrance stagger capped tight — beyond ~250ms the tail of the feed
  // reads as "content arriving late" rather than as choreography.
  const delay = `${Math.min(index, 5) * 50}ms`;

  return (
    <Link
      href={`/${lang}/threat/${post.id}`}
      prefetch={false}
      aria-label={content.title}
      // The focus ring lives on the anchor — the actual focusable element —
      // with a matching radius. Previously the <article> also drew one, so
      // a keyboard user got two nested rings on every card.
      className="block group rounded-lg"
    >
      <article
        lang={HTML_LANG[lang]}
        className={cn(
          "surface-card surface-card-hover relative",
          "p-5 sm:p-6 animate-fade-up",
        )}
        style={{ animationDelay: delay }}
      >
        {/* Subtle "open detail" affordance. Hover can never fire on touch,
            so it's hidden below sm entirely rather than reserving space for
            an affordance a thumb will never trigger. */}
        <ArrowUpRight
          className="hidden sm:block absolute top-4 right-4 w-4 h-4 text-text-tertiary
                     opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100
                     group-hover:text-text-secondary
                     transition-opacity duration-150 pointer-events-none"
          aria-hidden
          strokeWidth={2}
        />

        <header className="flex flex-wrap items-center gap-x-2 gap-y-2 mb-3 pr-0 sm:pr-6">
          {/* Category icon — visual anchor for thumb-scrolling. Sits
              first in the header so the eye latches onto the chip before
              reading the threat-level badge. Hidden on the compact
              trending variant where vertical space is tighter. */}
          {!compact && (
            <CategoryIconChip category={post.category} lang={lang} />
          )}
          <ThreatBadge level={post.threat_level} lang={lang} />
          {/* Only when there's actually something to do. "Informational"
              was rendering a badge on most cards to say "no action" —
              weight spent on the absence of news. On a Critical + urgent
              card this and ThreatBadge also emit identical colour tokens,
              so suppressing the common case removes a duplicated red
              smear as well as a redundant word. */}
          {post.actionability_level !== "informational" && (
            <ActionabilityBadge level={post.actionability_level} lang={lang} />
          )}
          <div className="ml-auto flex items-center gap-3 text-xs text-text-tertiary">
            {/* Reading time is gone from the card. It measured the card's
                own text, so it always said the same thing, and "20 sec"
                never changed anyone's decision to tap. */}
            <time dateTime={post.published_at} className="inline-flex items-center gap-1">
              <Clock className="w-3 h-3 text-text-quaternary" aria-hidden />
              <RelativeTime iso={post.published_at} lang={lang} />
            </time>
          </div>
        </header>

        {/* "Is this about me?" line — sits between the severity badges
            and the title so a scanning reader sees audience before
            content. Renders nothing when who_should_care isn't available
            (older API shapes / sparse signals). */}
        <AudienceChip post={post} lang={lang} className="mb-2.5" />

        {/* Clamped so card height stays roughly uniform down the feed.
            Unclamped, height tracked whatever length the model happened to
            write and the column lost its rhythm. */}
        <h2 className="text-lg sm:text-xl font-semibold text-text-primary leading-snug mb-2 break-words line-clamp-3">
          {title}
        </h2>

        {lead && (
          <p className="lead-text measure mb-3 line-clamp-2 sm:line-clamp-3">
            {lead}
          </p>
        )}

        {/* Footer: who says so, how many outlets, and at most two signal
            chips. Quick facts moved to the detail page — a card carrying
            audience chips, signal chips AND fact chips was asking the
            reader to parse three chip vocabularies before the headline. */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <CredibilityBadge
            tier={post.source_tier}
            source={post.source}
            lang={lang}
            score={post.source_credibility_score}
          />
          {/* Multi-source coverage, compressed to a count. The full list of
              outlets lives on the detail page; here it only needs to say
              "more than one newsroom confirmed this". */}
          {sourceCount > 1 && (
            <span className="inline-flex items-center gap-1 text-xs text-text-tertiary">
              <CheckCircle2 className="w-3.5 h-3.5 text-trust-trusted-fg/80" aria-hidden />
              {s.story_sources_count(sourceCount)}
            </span>
          )}
          <SignalIndicators signals={post.signals} lang={lang} max={2} />
        </div>
      </article>
    </Link>
  );
}
