import { UserCheck } from "lucide-react";
import { cn } from "@/lib/cn";
import type { Locale, LocalizedThreatPost } from "@/lib/types";

interface Props {
  post: LocalizedThreatPost;
  lang: Locale;
  className?: string;
}

/**
 * One-line "does this affect me?" chip — the most-scannable element on
 * a card. We surface this prominently because every other badge on the
 * card answers "how dangerous is it?" but only this one answers the
 * even-more-basic question "is this even about me?".
 *
 * Visual style: low-contrast pill, single icon, single line of text.
 * We DO NOT color this chip by severity — the threat-level badge does
 * that job. The audience chip is calm, informational, never alarming.
 *
 * Resolution: takes the backend-derived `who_should_care[lang]` if
 * present; otherwise the chip renders nothing (the older shape didn't
 * carry this field and we'd rather omit than hallucinate).
 */
export function AudienceChip({ post, lang, className }: Props) {
  const label = post.who_should_care?.[lang];
  if (!label) return null;
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full",
        "bg-bg-elevated-2 border border-border-subtle",
        "px-2.5 py-1 text-2xs sm:text-xs",
        "text-text-secondary",
        className,
      )}
    >
      <UserCheck className="w-3 h-3 text-text-tertiary" aria-hidden />
      <span className="font-medium leading-none">{label}</span>
    </div>
  );
}
