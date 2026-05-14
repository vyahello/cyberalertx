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

export type Locale = "en" | "ua";

export const SUPPORTED_LOCALES: readonly Locale[] = ["en", "ua"] as const;

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
 * Detail-tier fields (optional): detail_body, references.
 */
/** External reference attached to a threat post (CVE, advisory, etc.).
 *  Rendered only on the detail page, never on feed cards. */
export interface ThreatReference {
  /** "cve" | "advisory" | "vendor" | "cert" | "news" — drives the icon. */
  type: string;
  /** Display label (e.g. "CVE-2026-1234", "CISA AA26-001A"). */
  label: string;
  /** Absolute URL. */
  url: string;
}

export interface LocalizedContent {
  title: string;
  short_summary: string;
  why_it_matters: string;
  affected_users: string[];
  what_to_do: string[];
  what_not_to_do: string[];
  quick_facts: string[];
  reading_time_seconds: number;
  /** Multi-paragraph operational analysis for the detail page. Empty
   *  when no expanded body was generated (rule-based path or older
   *  cached posts). */
  detail_body?: string;
  /** External references — CVEs, advisories, vendor blogs, CERT bulletins. */
  references?: ThreatReference[];
}

/** Threat signal bundle (intelligence-layer enrichment, computed at render
 *  time on the backend). Booleans describing the *shape* of the threat —
 *  used by the UI to surface concise indicators ("active exploitation",
 *  "email account risk") and by future personalization to filter without
 *  the user having to think in categories.
 *
 *  Field names match the backend's `ThreatSignals` dataclass byte-for-byte.
 *  All optional so legacy API responses (or test fixtures) that predate
 *  this enrichment still hydrate cleanly. */
export interface ThreatSignals {
  active_exploitation?: boolean;
  credential_theft_risk?: boolean;
  financial_risk?: boolean;
  enterprise_risk?: boolean;
  consumer_risk?: boolean;
  requires_immediate_action?: boolean;
  affects_email_accounts?: boolean;
  steals_sessions?: boolean;
  data_exposure_risk?: boolean;
  malware_delivery?: boolean;
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
  /** Language of the original article body — the canonical "which audience
   *  does this item belong to" signal. The metadata layer (why_it_matters,
   *  what_to_do, etc.) can be rendered in either locale via the rule-based
   *  generator, but the title/summary stay in the source language. Feeds
   *  filter on this so each locale page presents a single-language reading
   *  experience. */
  source_language: Locale;
  /** Locales this post has content for. With locale-aware rule-based
   *  rendering, this is currently always both `en` and `uk`. Kept on the
   *  shape because deep-link routes (`/uk/threat/{id}`) still consult it
   *  to fall back to the "not available in this locale" state. */
  available_locales: Locale[];
  /** Locale → text content. Partial because not every post is multilingual. */
  translations: Partial<Record<Locale, LocalizedContent>>;
  // ----- intelligence-layer enrichment (optional for back-compat) -----
  /** Boolean signals describing the threat's shape — see `ThreatSignals`. */
  signals?: ThreatSignals;
  /** One-line "does this affect me?" label, per locale. */
  who_should_care?: Partial<Record<Locale, string>>;
  /** Ranked list of realistic-impact labels ("Account takeover",
   *  "Credential compromise"), per locale, capped at ~3 entries. */
  potential_impact?: Partial<Record<Locale, string[]>>;
  /** Names of OTHER trusted sources reporting the same story.
   *  Empty for single-source items. */
  corroborating_sources?: string[];
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
  return x === "en" || x === "ua";
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
