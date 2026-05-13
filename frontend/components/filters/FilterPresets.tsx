"use client";

import {
  Briefcase,
  Building2,
  KeyRound,
  Layers,
  ShieldAlert,
  Smartphone,
  Sparkles,
  User,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import {
  EMPTY_FILTERS,
  type FilterState,
  type Locale,
} from "@/lib/types";

interface Props {
  state: FilterState;
  onChange: (next: FilterState) => void;
  lang: Locale;
}

/**
 * Curated quick-pick presets that snap the filter state to a useful slice
 * of the feed without the user having to think in raw filter chips.
 *
 * Each preset is a *partial* `FilterState` — applying one resets to
 * `EMPTY_FILTERS` first so presets don't stack accidentally. "All threats"
 * is the explicit reset target.
 *
 * Design constraints:
 *   * Single horizontal scrollable row — fits on mobile without modals.
 *   * Active preset uses the same accent treatment as filter chips, NOT a
 *     new color — preserves the calm intelligence aesthetic.
 *   * Icons are deliberately monochromatic; we use color only for the
 *     active state. This stays in the "subtle, restrained" lane.
 */
const PRESETS: Array<{
  id: string;
  i18nKey: keyof ReturnType<typeof strings>;
  icon: LucideIcon;
  build: () => FilterState;
}> = [
  {
    id: "most_relevant",
    i18nKey: "preset_most_relevant",
    icon: Sparkles,
    // Empty filters == default ranking from the API.
    build: () => ({ ...EMPTY_FILTERS }),
  },
  {
    id: "critical",
    i18nKey: "preset_critical",
    icon: ShieldAlert,
    build: () => ({ ...EMPTY_FILTERS, threat_levels: ["Critical", "High"] }),
  },
  {
    id: "scams_phishing",
    i18nKey: "preset_scams_phishing",
    icon: KeyRound,
    build: () => ({
      ...EMPTY_FILTERS,
      categories: ["phishing", "scam", "social engineering"],
    }),
  },
  {
    id: "normal_users",
    i18nKey: "preset_normal_users",
    icon: User,
    build: () => ({
      ...EMPTY_FILTERS,
      audiences: ["normal_users", "mobile_users", "crypto_users"],
    }),
  },
  {
    id: "enterprise",
    i18nKey: "preset_enterprise",
    icon: Building2,
    build: () => ({
      ...EMPTY_FILTERS,
      audiences: ["enterprise", "sysadmins"],
    }),
  },
  {
    id: "mobile",
    i18nKey: "preset_mobile",
    icon: Smartphone,
    build: () => ({
      ...EMPTY_FILTERS,
      audiences: ["mobile_users"],
      platforms: ["Android", "iOS"],
    }),
  },
  {
    id: "account_security",
    i18nKey: "preset_account_security",
    icon: Briefcase,
    build: () => ({
      ...EMPTY_FILTERS,
      categories: ["phishing", "breach", "data leak"],
    }),
  },
];

/**
 * Test whether `current` is structurally identical to the result of
 * preset `id`. Used to highlight the active preset chip. Cheap because
 * the comparison is per-field and we never deep-compare arrays larger
 * than ~5 entries.
 */
function isPresetActive(current: FilterState, target: FilterState): boolean {
  const sameSet = (a: string[], b: string[]) =>
    a.length === b.length && a.every((x) => b.includes(x));
  return (
    sameSet(current.threat_levels, target.threat_levels) &&
    sameSet(current.categories, target.categories) &&
    sameSet(current.platforms, target.platforms) &&
    sameSet(current.audiences, target.audiences) &&
    sameSet(current.actionability, target.actionability) &&
    current.query.trim() === target.query.trim()
  );
}

export function FilterPresets({ state, onChange, lang }: Props) {
  const s = strings(lang);
  return (
    <div className="mb-6 sm:mb-7">
      <div className="flex items-center gap-2 mb-2.5">
        <Layers className="w-3.5 h-3.5 text-text-tertiary" aria-hidden />
        <p className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary">
          {s.preset_label}
        </p>
      </div>
      {/* Horizontal scroller — fits 7 presets on mobile without wrapping. */}
      <ul
        className="flex gap-2 overflow-x-auto -mx-5 sm:-mx-0 px-5 sm:px-0 pb-1 mask-fade-x sm:mask-none"
        role="list"
      >
        {PRESETS.map(({ id, i18nKey, icon: Icon, build }) => {
          const target = build();
          const active = isPresetActive(state, target);
          return (
            <li key={id} className="flex-shrink-0">
              <button
                type="button"
                onClick={() => onChange(target)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full",
                  "border px-3 py-1.5 text-xs font-medium",
                  "transition-colors duration-150",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-ring",
                  active
                    ? "bg-accent-soft border-accent/50 text-accent"
                    : "bg-bg-elevated-2 border-border-subtle text-text-secondary hover:text-text-primary hover:border-border-strong",
                )}
                aria-pressed={active}
              >
                <Icon className="w-3.5 h-3.5" strokeWidth={2.2} aria-hidden />
                {s[i18nKey] as string}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
