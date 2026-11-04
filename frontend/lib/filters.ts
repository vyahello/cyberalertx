/**
 * Feed filtering — pure functions shared by the home feed and topic pages.
 * Every group is "any of"; groups combine with AND.
 */
import {
  EMPTY_FILTERS,
  type FilterState,
  type Locale,
  type LocalizedThreatPost,
} from "./types";

export function applyFilters(
  posts: LocalizedThreatPost[],
  f: FilterState,
  lang: Locale,
): LocalizedThreatPost[] {
  const q = f.query.trim().toLowerCase();
  return posts.filter((p) => {
    if (f.threat_levels.length && !f.threat_levels.includes(p.threat_level)) return false;
    if (f.categories.length && !f.categories.includes(p.category)) return false;
    if (f.actionability.length && !f.actionability.includes(p.actionability_level)) return false;
    if (f.platforms.length && !f.platforms.some((x) => p.affected_platforms.includes(x))) return false;
    if (f.audiences.length && !f.audiences.some((a) => p.audience_targets.includes(a))) return false;
    if (f.exploited_only && !p.signals?.active_exploitation) return false;
    if (q) {
      const c = p.translations[lang];
      if (!c) return false;
      // Title, both summaries, the outlet and the platforms: what a reader
      // would type ("ivanti", "CVE-2026-", "android", "bleeping").
      const hay = [
        c.title,
        c.short_summary,
        c.plain_summary ?? "",
        p.source,
        p.affected_platforms.join(" "),
        (c.references ?? []).map((r) => r.label).join(" "),
      ]
        .join("\n")
        .toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export function countActiveFilters(f: FilterState): number {
  return (
    f.threat_levels.length +
    f.categories.length +
    f.platforms.length +
    f.audiences.length +
    f.actionability.length +
    (f.exploited_only ? 1 : 0) +
    (f.query.trim() ? 1 : 0)
  );
}

export type PresetId =
  | "all"
  | "critical"
  | "exploited"
  | "everyday"
  | "it"
  | "developers"
  | "mobile";

export const PRESETS: Record<PresetId, FilterState> = {
  all: { ...EMPTY_FILTERS },
  critical: { ...EMPTY_FILTERS, threat_levels: ["Critical", "High"] },
  exploited: { ...EMPTY_FILTERS, exploited_only: true },
  everyday: { ...EMPTY_FILTERS, audiences: ["normal_users", "mobile_users", "crypto_users"] },
  it: { ...EMPTY_FILTERS, audiences: ["enterprise", "sysadmins"] },
  developers: { ...EMPTY_FILTERS, audiences: ["developers"] },
  mobile: { ...EMPTY_FILTERS, audiences: ["mobile_users"] },
};

const sameSet = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((x) => b.includes(x));

export function presetMatches(current: FilterState, preset: FilterState): boolean {
  return (
    sameSet(current.threat_levels, preset.threat_levels) &&
    sameSet(current.categories, preset.categories) &&
    sameSet(current.platforms, preset.platforms) &&
    sameSet(current.audiences, preset.audiences) &&
    sameSet(current.actionability, preset.actionability) &&
    current.exploited_only === preset.exploited_only &&
    current.query.trim() === preset.query.trim()
  );
}

/** Day key and heading for grouping the newest-first feed. */
const ZONE: Record<Locale, string> = { en: "UTC", ua: "Europe/Kyiv" };

export function dayKey(iso: string, lang: Locale): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: ZONE[lang],
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(iso));
}

export function dayLabel(key: string, lang: Locale, now: Date = new Date()): string {
  const today = dayKey(now.toISOString(), lang);
  const yesterday = dayKey(new Date(now.getTime() - 86_400_000).toISOString(), lang);
  if (key === today) return lang === "ua" ? "Сьогодні" : "Today";
  if (key === yesterday) return lang === "ua" ? "Учора" : "Yesterday";
  // Noon UTC on that calendar day formats to the same date in both zones.
  const d = new Date(`${key}T12:00:00Z`);
  return new Intl.DateTimeFormat(lang === "ua" ? "uk-UA" : "en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: ZONE[lang],
  }).format(d);
}
