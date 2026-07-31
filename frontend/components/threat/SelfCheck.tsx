import { CircleHelp, LifeBuoy } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

interface Props {
  /** Steps the reader performs themselves to find out if they're affected. */
  checks: string[] | undefined;
  /** Recovery steps for someone who is already past prevention. */
  recovery: string[] | undefined;
  lang: Locale;
  className?: string;
}

/**
 * "Am I affected?" — the block that answers the question a non-expert
 * actually opens the page for.
 *
 * Everything else on the page describes the threat in the third person:
 * who it affects, what it does, what defenders should do. None of that
 * tells a specific reader whether it is about THEM. These are the steps
 * they run on their own machine to find out, and — when the answer is
 * "yes, and I already clicked it" — what to do about that.
 *
 * Given prominence above the narrative because a reader whose answer is
 * "no" should be able to stop reading right there, and one whose answer is
 * "yes" should not have to scroll past analysis to reach the recovery steps.
 *
 * Renders nothing when the post has neither list. Older cached posts
 * predate these fields, and a threat with no meaningful self-check
 * shouldn't get an empty heading.
 */
export function SelfCheck({ checks, recovery, lang, className }: Props) {
  const steps = (checks ?? []).filter((c) => c.trim());
  const recoverySteps = (recovery ?? []).filter((r) => r.trim());
  if (steps.length === 0 && recoverySteps.length === 0) return null;

  const s = strings(lang);

  return (
    <section
      className={cn("surface-card p-5 sm:p-6", className)}
      aria-labelledby="self-check-heading"
    >
      {steps.length > 0 && (
        <>
          <h2
            id="self-check-heading"
            className="inline-flex items-center gap-2 text-base font-semibold text-text-primary"
          >
            <CircleHelp className="w-4 h-4 text-accent" aria-hidden />
            {s.detail_am_i_affected}
          </h2>
          <p className="text-xs text-text-tertiary mt-1 mb-4">
            {s.detail_am_i_affected_hint}
          </p>
          {/* Numbered, because these are performed in order and a reader
              coming back to the page needs to know where they left off. */}
          <ol className="space-y-3">
            {steps.map((step, i) => (
              <li key={step} className="flex items-start gap-3">
                <span
                  className="flex-shrink-0 mt-0.5 w-5 h-5 rounded-full
                             bg-accent-soft border border-accent/30
                             text-2xs font-semibold text-accent
                             inline-flex items-center justify-center tabular-nums"
                  aria-hidden
                >
                  {i + 1}
                </span>
                <span className="text-sm sm:text-base text-text-primary leading-relaxed">
                  {step}
                </span>
              </li>
            ))}
          </ol>
        </>
      )}

      {recoverySteps.length > 0 && (
        <div
          className={cn(
            "border-l-2 border-level-critical-border pl-4 py-1",
            steps.length > 0 && "mt-6 pt-5 border-t border-border-subtle border-l-2",
          )}
        >
          <h3 className="inline-flex items-center gap-2 text-2xs font-semibold uppercase tracking-wider text-level-critical-fg mb-2">
            <LifeBuoy className="w-3.5 h-3.5" aria-hidden />
            {s.detail_if_already_affected}
          </h3>
          <ul className="space-y-2">
            {recoverySteps.map((step) => (
              <li
                key={step}
                className="flex items-start gap-2 text-sm text-text-primary leading-relaxed"
              >
                <span
                  className="w-1 h-1 rounded-full bg-level-critical-fg mt-2 flex-shrink-0"
                  aria-hidden
                />
                <span>{step}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
