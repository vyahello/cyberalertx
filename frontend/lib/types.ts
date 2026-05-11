/**
 * Frontend domain types.
 *
 * Mirrors the backend's `LocalizedThreatPost` shape (see
 * `cyberalertx/api/app.py:_PostService.render`). The cardinal rule:
 *
 *   * **Shared** metadata lives at the top level — `threat_level`,
 *     `category`, `source`, `platforms`, etc. Same regardless of locale.
 *   * **Text** content lives inside `translations[locale]` — title,
 *     summary, the do/don't lists, etc.
 *
 * Locale switching = pick a different key out of `translations`. We
 * never show an item in a locale it doesn't have content for, so
 * "mixed-language" cards are structurally impossible.
 */

export type ThreatLevel = "Critical" | "High" | "Medium" | "Low";

export type ActionabilityLevel =
  | "urgent_action"
  | "recommended_action"
  | "informational";

export type SourceTier = "trusted" | "verified" | "unverified";

export type Locale = "en" | "uk";

export const SUPPORTED_LOCALES: readonly Locale[] = ["en", "uk"] as const;

export const DEFAULT_LOCALE: Locale = "en";

export type Category =
  | "phishing"
  | "ransomware"
  | "vulnerability"
  | "breach"
  | "data leak"
  | "exploit"
  | "zero-day"
  | "malware"
  | "spyware"
  | "scam"
  | "botnet"
  | "social engineering"
  | "other";

export type Audience =
  | "normal_users"
  | "developers"
  | "sysadmins"
  | "enterprise"
  | "mobile_users"
  | "crypto_users";

/** All locale-dependent fields. One of these per available locale per post.
 *
 * Card-tier fields (always present): title, short_summary, why_it_matters,
 * affected_users, what_to_do, what_not_to_do, quick_facts, reading_time.
 *
 * Detail-tier fields (optional): how_it_works, who_is_affected,
 * attacker_motivation, realistic_impact. Populated server-side from a
 * category × locale table; absent for categories without a context entry.
 * The detail page renders each section only when its field is non-empty.
 */
export interface LocalizedContent {
  title: string;
  short_summary: string;
  why_it_matters: string;
  affected_users: string[];
  what_to_do: string[];
  what_not_to_do: string[];
  quick_facts: string[];
  reading_time_seconds: number;
  /** Detail-page context (optional). */
  how_it_works?: string;
  who_is_affected?: string;
  attacker_motivation?: string;
  realistic_impact?: string;
}

/** A threat post with translations for one or more locales. */
export interface LocalizedThreatPost {
  id: string;
  source: string;
  source_url: string;
  source_tier: SourceTier;
  source_credibility_score: number;
  published_at: string; // ISO 8601
  threat_level: ThreatLevel;
  category: Category;
  affected_platforms: string[];
  audience_targets: Audience[];
  actionability_level: ActionabilityLevel;
  actionability_score: number;
  emotional_weight: number;
  /** Locales this post has content for. Filtering ensures no mixed text. */
  available_locales: Locale[];
  /** Locale → text content. Partial because not every post is multilingual. */
  translations: Partial<Record<Locale, LocalizedContent>>;
}

/** Filter state. All arrays act as "any of" filters. */
export interface FilterState {
  threat_levels: ThreatLevel[];
  categories: Category[];
  platforms: string[];
  audiences: Audience[];
  actionability: ActionabilityLevel[];
  query: string;
}

export const EMPTY_FILTERS: FilterState = {
  threat_levels: [],
  categories: [],
  platforms: [],
  audiences: [],
  actionability: [],
  query: "",
};

// ----------------------- helpers --------------------------------------

/** Type guard for locale strings (used to validate URL params). */
export function isLocale(x: string | undefined): x is Locale {
  return x === "en" || x === "uk";
}

/** Pick a post's content for a locale, or return null if absent. */
export function contentFor(
  post: LocalizedThreatPost,
  locale: Locale,
): LocalizedContent | null {
  return post.translations[locale] ?? null;
}

/** Posts the user can actually see in the active locale.
 *
 *  Defensive: tolerates malformed items (`available_locales` undefined or
 *  not an array) by treating them as "not available in this locale" rather
 *  than crashing the page render. The backend contract guarantees the
 *  field, but a build that races a backend restart can momentarily ship
 *  stale shapes — we'd rather degrade gracefully. */
export function postsAvailableIn(
  posts: LocalizedThreatPost[],
  locale: Locale,
): LocalizedThreatPost[] {
  return posts.filter(
    (p) => Array.isArray(p?.available_locales) && p.available_locales.includes(locale),
  );
}
