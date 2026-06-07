import Link from "next/link";
import { ArrowLeft, ExternalLink, Clock, Users, FileText } from "lucide-react";
import { ActionPanel } from "./ActionPanel";
import { ActionabilityBadge } from "./ActionabilityBadge";
import { CategoryIconChip } from "./CategoryIconChip";
import { CredibilityBadge } from "./CredibilityBadge";
import { DetailBody } from "./DetailBody";
import { FeedbackWidget } from "./FeedbackWidget";
import { QuickFacts } from "./QuickFacts";
import { References } from "./References";
import { RelativeTime } from "./RelativeTime";
import { ShareBar } from "@/components/share/ShareBar";
import { ThreatBadge } from "./ThreatBadge";
import { ThreatSnapshot } from "./ThreatSnapshot";
import { strings } from "@/lib/i18n";
import { contentFor, type Locale, type LocalizedThreatPost } from "@/lib/types";

interface Props {
  post: LocalizedThreatPost;
  lang: Locale;
}

/**
 * Detail page body. Layout philosophy:
 *
 *   Mobile (single column, stacked):
 *     hero block ↓ summary ↓ quick facts ↓ why it matters ↓ who's affected
 *     ↓ action panel ↓ original source link
 *
 *   Desktop (two columns from `lg` up):
 *     LEFT  = narrative content
 *     RIGHT = sticky action panel — stays in view as you scroll
 *
 * The sticky action panel is the productivity payoff of being on desktop:
 * you can read the analysis while the actions stay one glance away.
 *
 * Reads as a structured intelligence dossier, not a blog post — clean
 * hierarchy, badge-led header, no inline timestamps mid-paragraph.
 */
export function ThreatDetail({ post, lang }: Props) {
  const s = strings(lang);
  const c = contentFor(post, lang);

  // This shouldn't happen — the page-level route already verified availability.
  // But guard anyway so a stale link can't crash the layout.
  if (!c) {
    return (
      <NotAvailableInLocale lang={lang} post={post} />
    );
  }

  return (
    <article lang={lang} className="mx-auto max-w-6xl px-5 sm:px-8 py-8 sm:py-12">
      {/* Back link — small, no chrome, lives in its own row above the title.
          Treated like a breadcrumb rather than a button to avoid competing
          with the hero. */}
      <Link
        href={`/${lang}#feed`}
        className="inline-flex items-center gap-1.5 text-sm text-text-secondary
                   hover:text-text-primary transition-colors mb-6 group"
      >
        <ArrowLeft className="w-4 h-4 transition-transform group-hover:-translate-x-0.5" />
        {s.detail_back_to_feed}
      </Link>

      {/* Header block — badge row, title, source line. The title size jumps
          one rung above the card to anchor the page. */}
      <header className="mb-8 sm:mb-10">
        <div className="flex flex-wrap items-center gap-2 mb-4">
          {/* Category chip — same small plate as the feed card so the
              visual identity stays consistent between feed and detail.
              No standalone hero block: a wide gradient banner above the
              title felt too heavy for what is an information-dense page. */}
          <CategoryIconChip category={post.category} lang={lang} />
          <ThreatBadge level={post.threat_level} lang={lang} />
          <ActionabilityBadge level={post.actionability_level} lang={lang} />
          <span className="text-xs text-text-tertiary inline-flex items-center gap-1.5 ml-1">
            <Clock className="w-3 h-3" />
            <RelativeTime iso={post.published_at} lang={lang} />
          </span>
          <span className="text-xs text-text-tertiary">
            {s.card_reading_time(c.reading_time_seconds)}
          </span>
        </div>

        <h1 className="text-2xl sm:text-3xl lg:text-[2.125rem] font-semibold
                       text-text-primary tracking-tight leading-[1.15] mb-4 max-w-4xl">
          {c.title}
        </h1>

        {/* Just the credibility badge in the hero. The "Read on source"
            CTA is intentionally NOT rendered here — it appears once at
            the bottom of the article, in the footer slot, so the reader
            finishes the brief before deciding to leave for the source. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <CredibilityBadge
            tier={post.source_tier}
            source={post.source}
            lang={lang}
            score={post.source_credibility_score}
          />
        </div>
      </header>

      {/* Threat snapshot — the above-the-fold intelligence block. Sits
          BETWEEN the hero (badges + title + source) and the narrative.
          The reader sees "who's affected" and "what can happen" before
          scrolling into the editorial summary. */}
      <ThreatSnapshot post={post} lang={lang} className="mb-8 sm:mb-10" />

      {/* Two-column grid from lg+: narrative left, sticky action panel right.
          Below lg the action panel slots inline after the narrative — see
          the second ActionPanel render below. */}
      <div className="grid gap-10 lg:gap-12 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="space-y-7">
          {/* "At a glance" block — short summary + quick facts grouped, so
              the user can decide whether to keep reading in <5 seconds. */}
          <div>
            <h2 className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-3">
              {s.detail_at_a_glance}
            </h2>
            <p className="text-base sm:text-lg text-text-primary leading-relaxed mb-4">
              {c.short_summary}
            </p>
            {c.quick_facts.length > 0 && <QuickFacts facts={c.quick_facts} />}
          </div>

          {/* Why it matters — the single line that translates technical risk
              into human impact. Pull-quote treatment with an accent rule. */}
          {c.why_it_matters && (
            <div className="border-l-2 border-accent/50 pl-4 py-1">
              <p className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-1">
                {s.card_why_it_matters}
              </p>
              <p className="text-base text-text-primary leading-relaxed">
                {c.why_it_matters}
              </p>
            </div>
          )}

          {/* AI-generated operational analysis — 2-4 short paragraphs,
              120-220 words, structured around: what happened / why this
              matters / what's still unknown / what defenders should do.
              Present only when the journalist layer ran (cache hits from
              the AI path). Rule-based renders leave this empty.
              Heading is hidden when there's no body so we don't show
              an empty "Analysis" label. */}
          {c.detail_body && c.detail_body.trim() && (
            <div>
              <h2 className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-3">
                {s.detail_analysis_heading}
              </h2>
              <DetailBody body={c.detail_body} />
            </div>
          )}

          {/* Who's affected — list, not paragraph. Easier to scan, and the
              shape matches the data we have. */}
          {c.affected_users.length > 0 && (
            <div>
              <h2 className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-2 inline-flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5" /> {s.card_affected_users}
              </h2>
              <ul className="space-y-1.5">
                {c.affected_users.map((u) => (
                  <li key={u} className="text-sm text-text-primary leading-relaxed">
                    {u}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Action panel — mobile placement. Hidden on lg+ because the
              sticky right column already has it. The inner panel already
              labels its What to do / What to avoid columns; we don't need
              an outer "Take action" heading on top of those. */}
          <div className="lg:hidden border-t border-border-subtle pt-6">
            <ActionPanel
              toDo={c.what_to_do}
              notToDo={c.what_not_to_do}
              lang={lang}
            />
          </div>

          {/* "Read on source" link rendered again here, in mobile too, so
              it's reachable without scrolling back up. */}
          {post.source_url && (
            <div className="border-t border-border-subtle pt-6">
              <a
                href={post.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm font-medium
                           text-accent hover:underline"
              >
                <FileText className="w-4 h-4" />
                {s.detail_original_source}
                <ExternalLink className="w-3.5 h-3.5 text-accent/70" />
              </a>
            </div>
          )}

          {/* Share row — copy link + Telegram / WhatsApp / X intents, plus
              the native share sheet on mobile. */}
          <div className="border-t border-border-subtle pt-6">
            <ShareBar title={c.title} lang={lang} />
          </div>

          {/* External references — CVE, CISA, vendor, CERT bulletins.
              Compact grid, opens in new tab. Only present on detail
              pages; cards never carry references. */}
          <References refs={c.references} lang={lang} />

          {/* Internal feedback loop — collects a coarse quality signal
              for prompt/ranking tuning. Lightweight: 5 chips, one click,
              no public counter. Placed below "Read on source" so it
              sits at the natural end of the reading flow. */}
          <FeedbackWidget postId={post.id} lang={lang} />
        </section>

        {/* Right column — sticky action panel. `top-20` accounts for the
            sticky 56px header + breathing room. Not rendered on mobile
            (the inline copy above takes over). */}
        <aside className="hidden lg:block">
          <div className="sticky top-20">
            <div className="surface-card p-5">
              {/* The sidebar's What to do / What to avoid subheadings already
                  identify the panel. An outer "Take action" header would be
                  a third stacked label on top of those — visually noisy. */}
              <SidebarActions
                toDo={c.what_to_do}
                notToDo={c.what_not_to_do}
                lang={lang}
              />
            </div>
          </div>
        </aside>
      </div>
    </article>
  );
}

// -------------------- internals ------------------------------------------

/**
 * Stacked action list optimized for a narrow sidebar. The full ActionPanel
 * uses a grid that's too wide here; we render two simple lists with the
 * same iconography for consistency.
 */
function SidebarActions({
  toDo,
  notToDo,
  lang,
}: {
  toDo: string[];
  notToDo: string[];
  lang: Locale;
}) {
  const s = strings(lang);
  return (
    <div className="space-y-5">
      {toDo.length > 0 && (
        <div>
          <h3 className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-2">
            {s.card_what_to_do}
          </h3>
          <ul className="space-y-2">
            {toDo.map((t) => (
              <li
                key={t}
                className="flex items-start gap-2 text-sm text-text-primary leading-relaxed"
              >
                <span className="w-1 h-1 rounded-full bg-trust-trusted-fg mt-2 flex-shrink-0" />
                <span>{t}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {notToDo.length > 0 && (
        <div>
          <h3 className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-2">
            {s.card_what_not_to_do}
          </h3>
          <ul className="space-y-2">
            {notToDo.map((t) => (
              <li
                key={t}
                className="flex items-start gap-2 text-sm text-text-secondary leading-relaxed"
              >
                <span className="w-1 h-1 rounded-full bg-level-critical-fg/70 mt-2 flex-shrink-0" />
                <span>{t}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Empty state when the post exists but doesn't have content in this locale. */
function NotAvailableInLocale({
  lang,
  post,
}: {
  lang: Locale;
  post: LocalizedThreatPost;
}) {
  const s = strings(lang);
  return (
    <div className="mx-auto max-w-2xl px-5 sm:px-8 py-16 text-center">
      <h1 className="text-xl font-semibold text-text-primary mb-2">
        {s.detail_not_available_in_locale}
      </h1>
      <p className="text-sm text-text-secondary mb-6">
        {s.detail_not_available_hint}
      </p>
      {post.available_locales.length > 0 && (
        <Link
          href={`/${post.available_locales[0]}/threat/${post.id}`}
          className="btn-primary"
        >
          {post.available_locales[0].toUpperCase()}
        </Link>
      )}
    </div>
  );
}
