import { Crosshair, Target, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import type { Locale, LocalizedThreatPost } from "@/lib/types";
import { CorroborationLine } from "./CorroborationLine";
import { SignalIndicators } from "./SignalIndicators";

interface Props {
  post: LocalizedThreatPost;
  lang: Locale;
  className?: string;
}

/**
 * The intelligence "above-the-fold" block on the detail page.
 *
 * Layout philosophy:
 *   * Three labeled slots — Who should care · Potential impact ·
 *     Corroboration. Each renders only when the underlying data exists.
 *   * Stacks single-column on mobile, becomes a 2-column grid from `sm`+
 *     so the desktop reader sees who-cares and potential-impact side by
 *     side without scrolling.
 *   * No giant headings — this is a snapshot, not a chapter.
 *
 * If the post has none of the enrichment fields populated (older API
 * shape or sparse signals), the whole block collapses to nothing rather
 * than showing empty labels.
 */
export function ThreatSnapshot({ post, lang, className }: Props) {
  const s = strings(lang);
  const audience = post.who_should_care?.[lang];
  const impacts = post.potential_impact?.[lang] ?? [];
  const corroboration = post.corroborating_sources ?? [];
  const hasSignals = post.signals && Object.values(post.signals).some(Boolean);

  // If literally nothing is available, render nothing — no empty headers.
  if (!audience && impacts.length === 0 && corroboration.length === 0 && !hasSignals) {
    return null;
  }

  return (
    <section
      aria-label={s.intel_threat_snapshot}
      className={cn(
        "p-5 sm:p-6 rounded-xl bg-bg-elevated border border-border-subtle",
        "grid gap-5 sm:gap-6 sm:grid-cols-2",
        className,
      )}
    >
      {audience && (
        <div>
          <SnapshotLabel icon={Target} text={s.intel_who_should_care} />
          <p className="text-base sm:text-lg font-medium text-text-primary mt-1.5">
            {audience}
          </p>
        </div>
      )}
      {impacts.length > 0 && (
        <div>
          <SnapshotLabel icon={Crosshair} text={s.intel_potential_impact} />
          <ul className="flex flex-wrap gap-1.5 mt-2">
            {impacts.map((label) => (
              <li
                key={label}
                className={cn(
                  "inline-flex items-center rounded-full",
                  "bg-bg-elevated-2 border border-border-subtle",
                  "px-2.5 py-1 text-xs text-text-primary font-medium",
                )}
              >
                {label}
              </li>
            ))}
          </ul>
        </div>
      )}
      {hasSignals && (
        <div className="sm:col-span-2">
          <SnapshotLabel icon={ShieldCheck} text={s.card_quick_facts} />
          <SignalIndicators
            signals={post.signals}
            lang={lang}
            max={6}
            className="mt-2"
          />
        </div>
      )}
      {corroboration.length > 0 && (
        <div className="sm:col-span-2 pt-3 border-t border-border-subtle">
          <CorroborationLine sources={corroboration} lang={lang} />
        </div>
      )}
    </section>
  );
}

function SnapshotLabel({
  icon: Icon,
  text,
}: {
  icon: typeof Target;
  text: string;
}) {
  return (
    <h3 className="inline-flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-text-tertiary">
      <Icon className="w-3 h-3" strokeWidth={2.2} aria-hidden />
      {text}
    </h3>
  );
}
