"use client";

import { cn } from "@/lib/cn";

interface Option<T extends string> {
  value: T;
  label: string;
  /** Optional count badge — when present, suffixed to the label. */
  count?: number;
}

interface Props<T extends string> {
  legend: string;
  options: Option<T>[];
  selected: readonly T[];
  onToggle: (value: T) => void;
  className?: string;
}

/**
 * Generic single-group of multi-select pills.
 *
 * Why pills and not checkboxes:
 *   - On phones, checkboxes are tiny tap targets and require label nesting.
 *     Pills get a comfy 32-40px tap height for free.
 *   - The visual "selected" state is unambiguous (filled vs outlined) without
 *     needing a checkmark glyph.
 *
 * The component is generic on the value type so the same primitive renders
 * ThreatLevel, Category, Audience, etc. — keeping the FilterSidebar terse.
 */
export function FilterGroup<T extends string>({
  legend,
  options,
  selected,
  onToggle,
  className,
}: Props<T>) {
  return (
    <fieldset className={cn("space-y-2", className)}>
      <legend className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary">
        {legend}
      </legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt) => {
          const active = selected.includes(opt.value);
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onToggle(opt.value)}
              aria-pressed={active}
              className={cn(
                // 40px tap height on touch layouts, denser 32px from sm+
                // where the pointer is precise. Active ink is dark bg-base
                // on the cyan ground — white-on-cyan fails AA contrast
                // (same rule as .btn-primary).
                "min-h-[40px] sm:min-h-[32px] px-3 py-1 rounded-md text-sm font-medium",
                "transition-colors duration-150 border",
                active
                  ? "bg-accent text-bg-base border-accent font-semibold"
                  : "bg-bg-elevated-2 text-text-secondary border-border-subtle hover:border-border-strong hover:text-text-primary active:border-border-strong",
              )}
            >
              {opt.label}
              {opt.count !== undefined && (
                <span
                  className={cn(
                    "ml-1.5 text-xs tabular-nums",
                    active ? "text-bg-base/70" : "text-text-tertiary",
                  )}
                >
                  {opt.count}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
