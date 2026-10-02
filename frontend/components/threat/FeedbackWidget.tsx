"use client";

import { useEffect, useId, useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { submitFeedback, type FeedbackReason, type FeedbackVote } from "@/lib/api";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

interface Props {
  postId: string;
  lang: Locale;
}

interface Stored {
  vote: FeedbackVote;
  reasoned: boolean;
}

const REASONS: Array<{ reason: FeedbackReason; key: "feedback_reason_too_vague"
  | "feedback_reason_too_technical" | "feedback_reason_incorrect"
  | "feedback_reason_not_relevant" }> = [
  { reason: "too_vague", key: "feedback_reason_too_vague" },
  { reason: "too_technical", key: "feedback_reason_too_technical" },
  { reason: "incorrect", key: "feedback_reason_incorrect" },
  { reason: "not_relevant", key: "feedback_reason_not_relevant" },
];

const storageKey = (lang: Locale, postId: string) => `cax:feedback:${lang}:${postId}`;

function readStored(key: string): Stored | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Stored>;
    if (parsed.vote === "up" || parsed.vote === "down") {
      return { vote: parsed.vote, reasoned: Boolean(parsed.reasoned) };
    }
  } catch {
    /* private mode, blocked storage, or a corrupt value: start fresh */
  }
  return null;
}

function writeStored(key: string, value: Stored | null): void {
  try {
    if (value) window.localStorage.setItem(key, JSON.stringify(value));
    else window.localStorage.removeItem(key);
  } catch {
    /* storage unavailable — the vote is still sent, it just isn't remembered */
  }
}

/**
 * "Was this helpful?" — 👍 / 👎 at the foot of the detail page.
 *
 * Binary first, detail second. The previous version offered five buttons at
 * once (helpful, too vague, too technical, incorrect, not relevant), which is
 * four ways to say no and one way to say yes, and a choice that heavy is one
 * most readers skip. A single yes/no is the cheapest possible answer; the
 * reasons only appear after a 👎, and they are optional.
 *
 * The vote is remembered in this browser and can be changed: click the other
 * thumb to switch, or the pressed one again to take it back. Each request
 * says what it replaces, so the server keeps exact counts without any reader
 * identifier (see `cyberalertx/feedback.py`).
 *
 * Nothing is shown to other readers. The editor reads the results at
 * /admin/feedback.
 */
export function FeedbackWidget({ postId, lang }: Props) {
  const s = strings(lang);
  const promptId = useId();
  const key = storageKey(lang, postId);
  const [state, setState] = useState<Stored | null>(null);

  // Read after mount, not during render: the server has no localStorage, and
  // reading it in the initial render would make the HTML differ on hydration.
  useEffect(() => {
    setState(readStored(key));
  }, [key]);

  const vote = (next: FeedbackVote) => {
    const previous: FeedbackVote = state?.vote ?? "none";
    // Clicking the pressed thumb again takes the vote back.
    const target: FeedbackVote = previous === next ? "none" : next;
    const updated = target === "none" ? null : { vote: target, reasoned: false };
    setState(updated);
    writeStored(key, updated);
    void submitFeedback({ kind: "vote", id: postId, locale: lang, vote: target, previous });
  };

  const giveReason = (reason: FeedbackReason) => {
    const updated: Stored = { vote: "down", reasoned: true };
    setState(updated);
    writeStored(key, updated);
    void submitFeedback({ kind: "reason", id: postId, locale: lang, reason });
  };

  const current = state?.vote ?? "none";

  return (
    <div className="border-t border-border-subtle pt-6 text-center">
      <div
        role="group"
        aria-labelledby={promptId}
        className="flex flex-wrap items-center justify-center gap-x-4 gap-y-3"
      >
        <p id={promptId} className="text-sm font-medium text-text-secondary">
          {s.feedback_prompt}
        </p>
        <div className="flex gap-2">
          <ThumbButton
            icon={ThumbsUp}
            label={s.feedback_yes}
            pressed={current === "up"}
            onClick={() => vote("up")}
          />
          <ThumbButton
            icon={ThumbsDown}
            label={s.feedback_no}
            pressed={current === "down"}
            onClick={() => vote("down")}
          />
        </div>
      </div>

      {/* One live region holding only text, so a screen reader announces the
          outcome of whichever button was pressed. The reason buttons sit
          outside it — controls inside a live region get read out wholesale. */}
      <p role="status" aria-live="polite" className="mt-3 min-h-[1.25rem] text-sm text-text-secondary">
        {current === "up" && s.feedback_thanks}
        {current === "down" && (state?.reasoned ? s.feedback_thanks_reason : s.feedback_follow_up)}
      </p>

      {current === "down" && !state?.reasoned && (
        <ul className="mt-3 flex flex-wrap justify-center gap-2" aria-label={s.feedback_follow_up}>
          {REASONS.map(({ reason, key: labelKey }) => (
            <li key={reason}>
              <button
                type="button"
                onClick={() => giveReason(reason)}
                className={cn(
                  "inline-flex items-center rounded-full",
                  "border border-border-subtle bg-bg-elevated-2",
                  "min-h-[40px] sm:min-h-0 px-3.5 sm:px-3 py-1.5",
                  "text-xs font-medium text-text-secondary",
                  "transition-colors duration-150",
                  "hover:text-text-primary hover:border-border-strong",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-ring",
                )}
              >
                {s[labelKey]}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ThumbButton({
  icon: Icon,
  label,
  pressed,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  pressed: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border",
        // 40px tap lane on phones, compact from sm+.
        "min-h-[40px] sm:min-h-[34px] px-4 text-sm font-medium",
        "transition-colors duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-ring",
        pressed
          ? "border-accent/50 bg-accent-soft text-accent"
          : "border-border-subtle bg-bg-elevated-2 text-text-secondary hover:text-text-primary hover:border-border-strong",
      )}
    >
      <Icon
        className="w-4 h-4"
        strokeWidth={2.2}
        fill={pressed ? "currentColor" : "none"}
        aria-hidden
      />
      {label}
    </button>
  );
}
