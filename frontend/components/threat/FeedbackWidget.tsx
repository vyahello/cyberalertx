"use client";

import { useState } from "react";
import {
  AlertCircle,
  CircleSlash,
  ThumbsUp,
  Type,
  WandSparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { submitFeedback } from "@/lib/api";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

interface Props {
  postId: string;
  lang: Locale;
}

type FeedbackSignal =
  | "helpful"
  | "too_vague"
  | "too_technical"
  | "incorrect"
  | "not_relevant";

const OPTIONS: Array<{
  signal: FeedbackSignal;
  icon: LucideIcon;
  i18nKey: keyof ReturnType<typeof strings>;
}> = [
  { signal: "helpful",        icon: ThumbsUp,     i18nKey: "feedback_helpful" },
  { signal: "too_vague",      icon: WandSparkles, i18nKey: "feedback_too_vague" },
  { signal: "too_technical",  icon: Type,         i18nKey: "feedback_too_technical" },
  { signal: "incorrect",      icon: AlertCircle,  i18nKey: "feedback_incorrect" },
  { signal: "not_relevant",   icon: CircleSlash,  i18nKey: "feedback_not_relevant" },
];

/**
 * Inline "was this useful?" widget at the foot of the detail page.
 *
 * Product intent: collect a coarse quality signal we can mine later for
 * prompt tuning + ranking improvements — WITHOUT building a comments
 * surface or public counter. The reader sees nothing about other users'
 * votes; we're not running a popularity contest.
 *
 * UX rules baked in:
 *   * 5 buttons in one row. Mobile wraps to two rows on narrow viewports.
 *   * After one click, the row is replaced with a single thank-you line.
 *     There's no "undo" — the post is fire-and-forget; double-click
 *     would just write a second record.
 *   * Failures are silent — `submitFeedback` returns false, we still
 *     show the thank-you (we'd rather the reader feel acknowledged than
 *     debug a network issue).
 */
export function FeedbackWidget({ postId, lang }: Props) {
  const s = strings(lang);
  const [submitted, setSubmitted] = useState(false);

  const onPick = async (signal: FeedbackSignal) => {
    setSubmitted(true);
    // Fire and forget — the UI commits regardless of network success.
    void submitFeedback({ id: postId, locale: lang, signal });
  };

  if (submitted) {
    return (
      <div
        role="status"
        className="text-sm text-text-secondary text-center py-3"
      >
        {s.feedback_thanks}
      </div>
    );
  }

  return (
    <div className="border-t border-border-subtle pt-6">
      <p className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-3 text-center">
        {s.feedback_prompt}
      </p>
      <ul className="flex flex-wrap justify-center gap-2">
        {OPTIONS.map(({ signal, icon: Icon, i18nKey }) => (
          <li key={signal}>
            <button
              type="button"
              onClick={() => onPick(signal)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full",
                "border border-border-subtle bg-bg-elevated-2",
                "px-3 py-1.5 text-xs font-medium text-text-secondary",
                "transition-colors duration-150",
                "hover:text-text-primary hover:border-border-strong",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-ring",
              )}
            >
              <Icon className="w-3.5 h-3.5" strokeWidth={2.2} aria-hidden />
              {s[i18nKey] as string}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
