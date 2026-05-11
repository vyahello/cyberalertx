import type { Locale, ThreatLevel, ActionabilityLevel, SourceTier, Category } from "./types";

/**
 * Light-weight i18n.
 *
 * Two locales only (EN primary, UK secondary). We deliberately avoid
 * `next-intl` for MVP — it adds routing complexity we don't need. When
 * a third locale lands we can swap this for a real solution; every
 * consumer goes through the `t()` function, so the swap is localized.
 */

type StringTable = {
  // Header / brand
  brand: string;
  tagline_short: string;

  // Hero
  hero_eyebrow: string;
  hero_headline: string;
  hero_subhead: string;
  hero_cta: string;
  hero_pulse_label: (n: number) => string;

  // Sections
  section_trending: string;
  section_trending_caption: string;
  section_feed: string;
  section_feed_caption: string;

  // Filters
  filters_title: string;
  filter_threat_level: string;
  filter_category: string;
  filter_platform: string;
  filter_audience: string;
  filter_actionability: string;
  filters_reset: string;
  filters_apply: string;
  filters_active: (n: number) => string;
  filters_button: string;
  filter_search: string;
  filter_search_placeholder: string;

  // Card
  card_why_it_matters: string;
  card_what_to_do: string;
  card_what_not_to_do: string;
  card_affected_users: string;
  card_quick_facts: string;
  card_reading_time: (s: number) => string;
  card_published_relative: (s: string) => string;

  // Threat level labels
  level: Record<ThreatLevel, string>;

  // Actionability labels
  actionability: Record<ActionabilityLevel, string>;

  // Trust tier labels
  trust: Record<SourceTier, string>;

  // Category labels (display)
  category: Record<Category, string>;

  // Common
  view_source: string;
  empty_feed: string;
  empty_no_data: string;
  empty_no_data_hint: string;
  language_label: string;

  // Detail page
  detail_back_to_feed: string;
  detail_at_a_glance: string;
  detail_original_source: string;
  detail_related: string;
  detail_related_caption: string;
  detail_published: string;
  detail_not_available_in_locale: string;
  detail_not_available_hint: string;
  detail_not_found_title: string;
  detail_not_found_hint: string;
  detail_action_panel_title: string;
  detail_how_it_works: string;
  detail_who_is_affected: string;
  detail_attacker_motivation: string;
  detail_realistic_impact: string;
};

/**
 * Time formatting strategy:
 *
 *   * **Today / yesterday** → relative ("just now", "2h ago", "yesterday")
 *     because absolute dates read awkward for very recent items.
 *   * **Anything older** → absolute date ("May 10, 2026" / "10 травня 2026 р.")
 *     so the reader sees the actual publication day and can judge staleness
 *     without doing arithmetic.
 *
 * Always parsed in UTC and rendered with the device locale so the date
 * matches what the reader expects to see.
 */
function formatPublished(iso: string, lang: Locale): string {
  const then = new Date(iso);
  const now = new Date();
  const diffMs = Math.max(0, now.getTime() - then.getTime());
  const diffHours = diffMs / 3600_000;

  if (lang === "uk") {
    if (diffHours < 1) return "щойно";
    if (diffHours < 24) return `${Math.round(diffHours)} год тому`;
    if (diffHours < 48) return "вчора";
    return new Intl.DateTimeFormat("uk-UA", {
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(then);
  }
  if (diffHours < 1) return "just now";
  if (diffHours < 24) return `${Math.round(diffHours)}h ago`;
  if (diffHours < 48) return "yesterday";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(then);
}

const EN: StringTable = {
  brand: "CyberAlertX",
  tagline_short: "Threat intelligence for everyone",

  hero_eyebrow: "Real-time cybersecurity awareness",
  hero_headline: "Cyber threats. Before they hit you.",
  hero_subhead:
    "A calm, filtered view of what's actually happening — ranked for impact, written for humans, fast to scan.",
  hero_cta: "View Live Threats",
  hero_pulse_label: (n) => `${n} active threats now`,

  section_trending: "Trending now",
  section_trending_caption: "Actively exploited or widely reported in the last 24h.",
  section_feed: "Live feed",
  section_feed_caption: "Ranked by urgency, credibility, and your filters.",

  filters_title: "Refine the feed",
  filter_threat_level: "Threat level",
  filter_category: "Category",
  filter_platform: "Platform",
  filter_audience: "Audience",
  filter_actionability: "Actionability",
  filter_search: "Search",
  filter_search_placeholder: "Search threats…",
  filters_reset: "Reset",
  filters_apply: "Apply",
  filters_active: (n) => (n === 1 ? "1 filter" : `${n} filters`),
  filters_button: "Filters",

  card_why_it_matters: "Why it matters",
  card_what_to_do: "What to do",
  card_what_not_to_do: "What to avoid",
  card_affected_users: "Who's affected",
  card_quick_facts: "Quick facts",
  card_reading_time: (s) => `${s}s read`,
  card_published_relative: (s) => formatPublished(s, "en"),

  level: {
    Critical: "Critical",
    High: "High",
    Medium: "Medium",
    Low: "Low",
  },
  actionability: {
    urgent_action: "Urgent action",
    recommended_action: "Recommended",
    informational: "Informational",
  },
  trust: {
    trusted: "Trusted source",
    verified: "Verified",
    unverified: "Unverified",
  },
  category: {
    phishing: "Phishing",
    ransomware: "Ransomware",
    vulnerability: "Vulnerability",
    breach: "Data breach",
    "data leak": "Data leak",
    exploit: "Active exploit",
    "zero-day": "Zero-day",
    malware: "Malware",
    spyware: "Spyware",
    scam: "Scam",
    botnet: "Botnet",
    "social engineering": "Social engineering",
    other: "Other",
  },

  view_source: "View source",
  empty_feed: "No threats match your filters.",
  empty_no_data: "No threats to show right now.",
  empty_no_data_hint:
    "The feed is empty — either the pipeline hasn't run yet, or the backend is unreachable. The page will refresh on its own.",
  language_label: "Language",

  detail_back_to_feed: "Back to feed",
  detail_at_a_glance: "At a glance",
  detail_original_source: "Read on source",
  detail_related: "Related threats",
  detail_related_caption: "Other items in the same category and language.",
  detail_published: "Published",
  detail_not_available_in_locale: "This threat isn't translated yet.",
  detail_not_available_hint:
    "We don't show partially translated content. Try switching languages — or come back later if a translation lands.",
  detail_not_found_title: "Threat not found",
  detail_not_found_hint:
    "This item may have been replaced, archived, or never existed.",
  detail_action_panel_title: "Take action",
  detail_how_it_works: "How it works",
  detail_who_is_affected: "Who is realistically affected",
  detail_attacker_motivation: "Why attackers use this",
  detail_realistic_impact: "Realistic impact",
};

const UK: StringTable = {
  brand: "CyberAlertX",
  tagline_short: "Розвідка загроз для кожного",

  hero_eyebrow: "Кіберобізнаність у реальному часі",
  hero_headline: "Кіберзагрози. Перш ніж вони дістануться вас.",
  hero_subhead:
    "Спокійний, відфільтрований огляд того, що дійсно відбувається — за впливом, людською мовою, швидко проглядається.",
  hero_cta: "Переглянути загрози",
  hero_pulse_label: (n) => `${n} активних загроз зараз`,

  section_trending: "У тренді",
  section_trending_caption: "Активно експлуатуються або широко висвітлювалися за 24 год.",
  section_feed: "Стрічка",
  section_feed_caption: "За терміновістю, довірою та вашими фільтрами.",

  filters_title: "Уточнити стрічку",
  filter_threat_level: "Рівень загрози",
  filter_category: "Категорія",
  filter_platform: "Платформа",
  filter_audience: "Аудиторія",
  filter_actionability: "Дія",
  filter_search: "Пошук",
  filter_search_placeholder: "Шукати загрози…",
  filters_reset: "Скинути",
  filters_apply: "Застосувати",
  filters_active: (n) => (n === 1 ? "1 фільтр" : `${n} фільтрів`),
  filters_button: "Фільтри",

  card_why_it_matters: "Чому це важливо",
  card_what_to_do: "Що робити",
  card_what_not_to_do: "Чого не робити",
  card_affected_users: "Кого це стосується",
  card_quick_facts: "Коротко",
  card_reading_time: (s) => `${s} с читання`,
  card_published_relative: (s) => formatPublished(s, "uk"),

  level: {
    Critical: "Критично",
    High: "Високий",
    Medium: "Середній",
    Low: "Низький",
  },
  actionability: {
    urgent_action: "Терміново",
    recommended_action: "Рекомендовано",
    informational: "Інформаційно",
  },
  trust: {
    trusted: "Довірене",
    verified: "Перевірене",
    unverified: "Неперевірене",
  },
  category: {
    phishing: "Фішинг",
    ransomware: "Програма-вимагач",
    vulnerability: "Вразливість",
    breach: "Витік даних",
    "data leak": "Злив даних",
    exploit: "Активна атака",
    "zero-day": "Нульовий день",
    malware: "Шкідливе ПЗ",
    spyware: "Шпигунське ПЗ",
    scam: "Шахрайство",
    botnet: "Ботнет",
    "social engineering": "Соціальна інженерія",
    other: "Інше",
  },

  view_source: "Джерело",
  empty_feed: "За вашими фільтрами немає загроз.",
  empty_no_data: "Зараз немає загроз для показу.",
  empty_no_data_hint:
    "Стрічка порожня — або конвеєр ще не запускався, або бекенд недоступний. Сторінка оновиться автоматично.",
  language_label: "Мова",

  detail_back_to_feed: "Назад до стрічки",
  detail_at_a_glance: "Коротко",
  detail_original_source: "Першоджерело",
  detail_related: "Схожі загрози",
  detail_related_caption: "Інші матеріали тієї ж категорії та мови.",
  detail_published: "Опубліковано",
  detail_not_available_in_locale: "Цю загрозу ще не перекладено.",
  detail_not_available_hint:
    "Ми не показуємо частково перекладений матеріал. Спробуйте іншу мову — або зайдіть пізніше, якщо переклад зʼявиться.",
  detail_not_found_title: "Загрозу не знайдено",
  detail_not_found_hint:
    "Можливо, її замінили, заархівували, або такої ніколи не існувало.",
  detail_action_panel_title: "Що зробити",
  detail_how_it_works: "Як це працює",
  detail_who_is_affected: "Кого це реально стосується",
  detail_attacker_motivation: "Чому атакують саме так",
  detail_realistic_impact: "Реальний вплив",
};

const TABLES: Record<Locale, StringTable> = { en: EN, uk: UK };

export function strings(lang: Locale): StringTable {
  return TABLES[lang] ?? EN;
}
