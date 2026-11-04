"use client";

import { useEffect, useId, useState } from "react";
import { submitFeedback, type FeedbackReason } from "@/lib/api";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

interface Props {
  postId: string;
  lang: Locale;
}

/** The three problem reports, independent of the 👍/👎 usefulness vote. A
 *  factual error is the existing `incorrect` reason, so the editor's
 *  /admin/feedback breakdown keeps one bucket for it. */
const REPORTS: Array<{ reason: FeedbackReason; key: "report_factual" | "report_outdated" | "report_translation" }> = [
  { reason: "incorrect", key: "report_factual" },
  { reason: "outdated", key: "report_outdated" },
  { reason: "translation", key: "report_translation" },
];

function storageKey(lang: Locale, id: string): string {
  return `cax-report:${lang}:${id}`;
}

function readSent(key: string): FeedbackReason[] {
  try {
    const raw = window.localStorage.getItem(key);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? (parsed as FeedbackReason[]) : [];
  } catch {
    return [];
  }
}

function writeSent(key: string, sent: FeedbackReason[]): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(sent));
  } catch {
    /* storage unavailable: the report is still sent, just not remembered */
  }
}

/**
 * "Report a problem": a factual error, outdated information or a translation
 * problem. Kept apart from source attribution and from the usefulness vote,
 * so a reader who found the brief useful can still flag a wrong detail.
 * Each report is sent once per browser; nothing is shown to other readers.
 */
export function ReportProblem({ postId, lang }: Props) {
  const s = strings(lang);
  const headingId = useId();
  const key = storageKey(lang, postId);
  const [sent, setSent] = useState<FeedbackReason[]>([]);

  // After mount only: the server has no localStorage (hydration must match).
  useEffect(() => {
    setSent(readSent(key));
  }, [key]);

  const report = (reason: FeedbackReason) => {
    if (sent.includes(reason)) return;
    const next = [...sent, reason];
    setSent(next);
    writeSent(key, next);
    void submitFeedback({ kind: "reason", id: postId, locale: lang, reason });
  };

  return (
    <div role="group" aria-labelledby={headingId}>
      <h2 id={headingId} className="font-sans text-[1rem] font-semibold text-ink">
        {s.report_prompt}
      </h2>
      <ul className="mt-3 flex flex-wrap gap-1.5">
        {REPORTS.map(({ reason, key: label }) => (
          <li key={reason}>
            <button
              type="button"
              className="toggle"
              aria-pressed={sent.includes(reason)}
              disabled={sent.includes(reason)}
              onClick={() => report(reason)}
            >
              {s[label]}
            </button>
          </li>
        ))}
      </ul>
      <p role="status" aria-live="polite" className="mt-3 min-h-[1.35rem] text-small text-ink-muted">
        {sent.length > 0 && s.report_thanks}
      </p>
    </div>
  );
}
