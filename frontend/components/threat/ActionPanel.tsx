import { Check, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

interface Props {
  toDo: string[];
  notToDo: string[];
  lang: Locale;
  className?: string;
}

/**
 * The "act on this" block at the bottom of a card.
 *
 * Decisions:
 *   - Two columns on desktop (do / don't side-by-side), stacked on mobile.
 *     Side-by-side comparison is the natural way to scan an action list,
 *     but two columns are unreadable in a narrow phone column.
 *   - Icons are foreground-tinted ONLY, never on a colored chip. This
 *     keeps the row visually quiet — the wording does the work.
 *   - "What to avoid" section is omitted entirely if empty (rather than
 *     showing an empty header) — silence is information.
 */
export function ActionPanel({ toDo, notToDo, lang, className }: Props) {
  const s = strings(lang);
  return (
    <div className={cn("grid gap-5 sm:grid-cols-[1fr_auto_1fr] sm:gap-6", className)}>
      <section aria-labelledby="action-do">
        <h4
          id="action-do"
          className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-2"
        >
          {s.card_what_to_do}
        </h4>
        <ul className="space-y-1.5">
          {toDo.map((item) => (
            <li
              key={item}
              className="flex items-start gap-2 text-sm text-text-primary leading-relaxed"
            >
              <Check
                className="w-4 h-4 mt-0.5 flex-shrink-0 text-trust-trusted-fg"
                strokeWidth={2.5}
              />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>
      {notToDo.length > 0 && (
        <>
          <div className="hidden sm:block w-px bg-border-subtle" aria-hidden />
          <section aria-labelledby="action-dont">
            <h4
              id="action-dont"
              className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-2"
            >
              {s.card_what_not_to_do}
            </h4>
            <ul className="space-y-1.5">
              {notToDo.map((item) => (
                <li
                  key={item}
                  className="flex items-start gap-2 text-sm text-text-primary leading-relaxed"
                >
                  <X
                    className="w-4 h-4 mt-0.5 flex-shrink-0 text-level-critical-fg opacity-80"
                    strokeWidth={2.5}
                  />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
