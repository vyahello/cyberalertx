"use client";

import { useId } from "react";
import { Search } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import {
  PRESETS,
  countActiveFilters,
  presetMatches,
  type PresetId,
} from "@/lib/filters";
import type {
  ActionabilityLevel,
  Audience,
  Category,
  FilterState,
  Locale,
  ThreatLevel,
} from "@/lib/types";

const LEVELS: ThreatLevel[] = ["Critical", "High", "Medium", "Low"];
const ACTIONABILITY: ActionabilityLevel[] = [
  "urgent_action",
  "recommended_action",
  "informational",
];
const PRESET_ORDER: PresetId[] = [
  "all",
  "critical",
  "exploited",
  "everyday",
  "it",
  "developers",
  "mobile",
];

export interface FilterOptions {
  categories: Category[];
  platforms: string[];
  audiences: Audience[];
}

interface Props {
  state: FilterState;
  onChange: (next: FilterState) => void;
  lang: Locale;
  options: FilterOptions;
  /** Hide the search field (the phone toolbar carries its own). */
  withSearch?: boolean;
  className?: string;
}

type ArrayKey = "threat_levels" | "categories" | "platforms" | "audiences" | "actionability";

export function FilterPanel({
  state,
  onChange,
  lang,
  options,
  withSearch = true,
  className,
}: Props) {
  const s = strings(lang);
  const searchId = useId();
  const active = countActiveFilters(state);

  function toggle<T extends string>(key: ArrayKey, value: T) {
    const current = state[key] as readonly string[];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onChange({ ...state, [key]: next });
  }

  const presetLabel: Record<PresetId, string> = {
    all: s.preset_all,
    critical: s.preset_critical,
    exploited: s.preset_exploited,
    everyday: s.preset_everyday,
    it: s.preset_it,
    developers: s.preset_developers,
    mobile: s.preset_mobile,
  };

  return (
    <div className={cn("space-y-7 font-sans", className)}>
      {withSearch && (
        <div>
          <label htmlFor={searchId} className="block text-small font-semibold text-ink mb-2">
            {s.filter_search}
          </label>
          <SearchField
            id={searchId}
            value={state.query}
            placeholder={s.filter_search_placeholder}
            onChange={(query) => onChange({ ...state, query })}
          />
        </div>
      )}

      <Group legend={s.preset_label}>
        {PRESET_ORDER.map((id) => (
          <ToggleButton
            key={id}
            pressed={presetMatches(state, { ...PRESETS[id], query: state.query })}
            onClick={() => onChange({ ...PRESETS[id], query: state.query })}
          >
            {presetLabel[id]}
          </ToggleButton>
        ))}
      </Group>

      <Group legend={s.filter_severity}>
        {LEVELS.map((v) => (
          <ToggleButton
            key={v}
            pressed={state.threat_levels.includes(v)}
            onClick={() => toggle("threat_levels", v)}
          >
            {s.level[v]}
          </ToggleButton>
        ))}
      </Group>

      {options.categories.length > 1 && (
        <Group legend={s.filter_category}>
          {options.categories.map((c) => (
            <ToggleButton
              key={c}
              pressed={state.categories.includes(c)}
              onClick={() => toggle("categories", c)}
            >
              {s.category[c] ?? c}
            </ToggleButton>
          ))}
        </Group>
      )}

      {options.audiences.length > 0 && (
        <Group legend={s.filter_audience}>
          {options.audiences.map((a) => (
            <ToggleButton
              key={a}
              pressed={state.audiences.includes(a)}
              onClick={() => toggle("audiences", a)}
            >
              {s.audience[a] ?? a}
            </ToggleButton>
          ))}
        </Group>
      )}

      {options.platforms.length > 0 && (
        <Group legend={s.filter_platform}>
          {options.platforms.map((p) => (
            <ToggleButton
              key={p}
              pressed={state.platforms.includes(p)}
              onClick={() => toggle("platforms", p)}
            >
              {p}
            </ToggleButton>
          ))}
        </Group>
      )}

      <Group legend={s.filter_actionability}>
        {ACTIONABILITY.map((v) => (
          <ToggleButton
            key={v}
            pressed={state.actionability.includes(v)}
            onClick={() => toggle("actionability", v)}
          >
            {s.actionability[v]}
          </ToggleButton>
        ))}
      </Group>

      {active > 0 && (
        <button
          type="button"
          onClick={() => onChange({ ...PRESETS.all })}
          className="link text-small font-semibold"
        >
          {s.filters_reset}
        </button>
      )}
    </div>
  );
}

export function SearchField({
  id,
  value,
  placeholder,
  onChange,
  label,
}: {
  id?: string;
  value: string;
  placeholder: string;
  onChange: (v: string) => void;
  /** Accessible name when no visible <label> points at the field. */
  label?: string;
}) {
  return (
    <div className="relative">
      <Search
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-faint"
        aria-hidden
      />
      <input
        id={id}
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={label}
        autoComplete="off"
        enterKeyHint="search"
        className="field pl-9"
      />
    </div>
  );
}

function Group({ legend, children }: { legend: string; children: React.ReactNode }) {
  return (
    <fieldset>
      <legend className="text-small font-semibold text-ink mb-2.5">{legend}</legend>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </fieldset>
  );
}

function ToggleButton({
  pressed,
  onClick,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button type="button" aria-pressed={pressed} onClick={onClick} className="toggle">
      {children}
    </button>
  );
}
