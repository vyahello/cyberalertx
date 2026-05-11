"use client";

import { RotateCcw, Search } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import type {
  ActionabilityLevel,
  Audience,
  Category,
  FilterState,
  Locale,
  ThreatLevel,
} from "@/lib/types";
import { FilterGroup } from "./FilterGroup";

interface Props {
  state: FilterState;
  onChange: (next: FilterState) => void;
  onReset: () => void;
  lang: Locale;
  /** All categories present in the current dataset — used to drive options. */
  availableCategories: Category[];
  /** Same for platforms / audiences — keeps the panel tight to live data. */
  availablePlatforms: string[];
  availableAudiences: Audience[];
  className?: string;
}

const THREAT_LEVELS: ThreatLevel[] = ["Critical", "High", "Medium", "Low"];
const ACTIONABILITY: ActionabilityLevel[] = [
  "urgent_action",
  "recommended_action",
  "informational",
];

/**
 * Filter logic lives here (and only here). Both the sidebar (desktop) and
 * the drawer (mobile) render this component — the SAME panel; only the
 * outer shell differs. That keeps behavior identical across breakpoints.
 */
export function FilterPanel({
  state,
  onChange,
  onReset,
  lang,
  availableCategories,
  availablePlatforms,
  availableAudiences,
  className,
}: Props) {
  const s = strings(lang);

  // Only allow keys whose value type is a readonly array — keeps us from
  // accidentally trying to toggle into the `query` field.
  type ArrayKeyOf<S> = {
    [K in keyof S]: S[K] extends readonly unknown[] ? K : never;
  }[keyof S];

  function toggleArray<T extends string>(key: ArrayKeyOf<FilterState>, value: T) {
    const current = state[key] as unknown as readonly T[];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onChange({ ...state, [key]: next });
  }

  return (
    <div className={cn("space-y-6", className)}>
      {/* Header — title + reset, both visible at all times on desktop. The
          reset button is suppressed when no filters are applied so it can't
          read as "destroy work". */}
      <header className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text-primary">
          {s.filters_title}
        </h3>
        {hasActiveFilters(state) && (
          <button
            type="button"
            onClick={onReset}
            className="inline-flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            {s.filters_reset}
          </button>
        )}
      </header>

      {/* Search — debounced via parent state, no internal input ref dance. */}
      <div>
        <label
          htmlFor="filter-search"
          className="block text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-2"
        >
          {s.filter_search}
        </label>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" />
          <input
            id="filter-search"
            type="search"
            value={state.query}
            onChange={(e) => onChange({ ...state, query: e.target.value })}
            placeholder={s.filter_search_placeholder}
            className="w-full pl-8 pr-3 py-2 bg-bg-elevated-2 border border-border-subtle rounded-md text-sm
                       text-text-primary placeholder:text-text-tertiary
                       focus:border-border-focus transition-colors"
          />
        </div>
      </div>

      <FilterGroup
        legend={s.filter_threat_level}
        options={THREAT_LEVELS.map((v) => ({ value: v, label: s.level[v] }))}
        selected={state.threat_levels}
        onToggle={(v) => toggleArray("threat_levels", v)}
      />

      <FilterGroup
        legend={s.filter_actionability}
        options={ACTIONABILITY.map((v) => ({ value: v, label: s.actionability[v] }))}
        selected={state.actionability}
        onToggle={(v) => toggleArray("actionability", v)}
      />

      <FilterGroup
        legend={s.filter_category}
        options={availableCategories.map((c) => ({ value: c, label: s.category[c] }))}
        selected={state.categories}
        onToggle={(v) => toggleArray("categories", v)}
      />

      {availablePlatforms.length > 0 && (
        <FilterGroup
          legend={s.filter_platform}
          options={availablePlatforms.map((p) => ({ value: p, label: p }))}
          selected={state.platforms}
          onToggle={(v) => toggleArray("platforms", v)}
        />
      )}

      {availableAudiences.length > 0 && (
        <FilterGroup
          legend={s.filter_audience}
          options={availableAudiences.map((a) => ({
            value: a,
            label: a.replace(/_/g, " "),
          }))}
          selected={state.audiences}
          onToggle={(v) => toggleArray("audiences", v)}
        />
      )}
    </div>
  );
}

export function hasActiveFilters(state: FilterState): boolean {
  return (
    state.threat_levels.length > 0 ||
    state.categories.length > 0 ||
    state.platforms.length > 0 ||
    state.audiences.length > 0 ||
    state.actionability.length > 0 ||
    state.query.trim().length > 0
  );
}

export function countActiveFilters(state: FilterState): number {
  return (
    state.threat_levels.length +
    state.categories.length +
    state.platforms.length +
    state.audiences.length +
    state.actionability.length +
    (state.query.trim().length > 0 ? 1 : 0)
  );
}
