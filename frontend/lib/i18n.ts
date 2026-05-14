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
  // Intelligence layer (signals + corroboration + presets)
  intel_who_should_care: string;
  intel_potential_impact: string;
  intel_threat_snapshot: string;
  intel_also_reported_by: string;
  intel_signal_active_exploitation: string;
  intel_signal_credential_risk: string;
  intel_signal_email_risk: string;
  intel_signal_financial_risk: string;
  intel_signal_enterprise_risk: string;
  intel_signal_consumer_risk: string;
  intel_signal_session_hijack: string;
  intel_signal_data_exposure: string;
  intel_signal_malware_delivery: string;
  trending_why_label: string;
  trending_reason_active_exploitation: string;
  trending_reason_corroborated: (n: number) => string;
  trending_reason_critical: string;
  trending_reason_urgent: string;
  trending_reason_email_accounts: string;
  trending_reason_credentials: string;
  // Filter presets
  preset_label: string;
  preset_clear: string;
  preset_most_relevant: string;
  preset_critical: string;
  preset_scams_phishing: string;
  preset_normal_users: string;
  preset_enterprise: string;
  preset_mobile: string;
  preset_account_security: string;
  // Freshness + stale-feed indicators
  freshness_updated_prefix: string;
  freshness_quiet_day: string;
  freshness_just_now: string;
  freshness_hours_ago: (n: number) => string;
  freshness_minutes_ago: (n: number) => string;
  freshness_days_ago: (n: number) => string;
  // Feedback widget
  feedback_prompt: string;
  feedback_helpful: string;
  feedback_too_vague: string;
  feedback_too_technical: string;
  feedback_incorrect: string;
  feedback_not_relevant: string;
  feedback_thanks: string;
  // Additional empty / unavailable copy
  empty_filter_hint: string;
  empty_backend_updating: string;
  empty_locale_unavailable: string;
  // Detail-page extras
  references_heading: string;
  detail_analysis_heading: string;
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
  const diffMin = Math.floor(diffMs / 60_000);
  const diffHours = diffMs / 3600_000;

  if (lang === "ua") {
    if (diffMin < 1) return "щойно";
    if (diffMin < 60) return `${diffMin} хв тому`;
    if (diffHours < 24) return `${Math.round(diffHours)} год тому`;
    if (diffHours < 48) return "вчора";
    return new Intl.DateTimeFormat("uk-UA", {
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(then);
  }
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin} min ago`;
  if (diffHours < 24) return `${Math.round(diffHours)}h ago`;
  if (diffHours < 48) return "yesterday";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(then);
}

/**
 * Reading-time formatter.
 *
 * Splits seconds into minutes + remainder seconds and drops the empty
 * unit. Why: a single "85 с" reads like a stopwatch, not a hint. Showing
 * "1 хв 25 с" / "1 min 25 sec" matches how humans estimate time.
 *
 *   12  → "12 с"           / "12 sec"
 *   60  → "1 хв"           / "1 min"
 *   85  → "1 хв 25 с"      / "1 min 25 sec"
 *   180 → "3 хв"           / "3 min"
 *
 * Anything below 1 second is clamped to 1 — the value comes from the
 * backend rounded to 5s already, so the clamp is defensive.
 */
function formatReadingTime(total: number, lang: Locale): string {
  const seconds = Math.max(1, Math.round(total));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (lang === "ua") {
    if (m === 0) return `${s} с`;
    if (s === 0) return `${m} хв`;
    return `${m} хв ${s} с`;
  }
  if (m === 0) return `${s} sec`;
  if (s === 0) return `${m} min`;
  return `${m} min ${s} sec`;
}

const EN: StringTable = {
  brand: "CyberAlertX",
  tagline_short: "Threat intelligence for everyone",

  hero_eyebrow: "Real-time cybersecurity awareness",
  hero_headline: "Cyber threats. Before they hit you.",
  hero_subhead:
    "What matters in cybersecurity right now — explained clearly, ranked by real-world impact.",
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
  card_reading_time: (s) => formatReadingTime(s, "en"),
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
  // --- intelligence layer ---
  intel_who_should_care: "Who should care",
  intel_potential_impact: "Potential impact",
  intel_threat_snapshot: "Threat snapshot",
  intel_also_reported_by: "Also reported by",
  intel_signal_active_exploitation: "Active exploitation",
  intel_signal_credential_risk: "Credential theft",
  intel_signal_email_risk: "Email account risk",
  intel_signal_financial_risk: "Financial risk",
  intel_signal_enterprise_risk: "Enterprise risk",
  intel_signal_consumer_risk: "Consumer risk",
  intel_signal_session_hijack: "Session hijacking",
  intel_signal_data_exposure: "Data exposure",
  intel_signal_malware_delivery: "Malware delivery",
  trending_why_label: "Why trending",
  trending_reason_active_exploitation: "Active exploitation detected",
  trending_reason_corroborated: (n) =>
    n === 1 ? "Confirmed by 1 other trusted source"
            : `Confirmed by ${n} trusted sources`,
  trending_reason_critical: "Critical-tier threat",
  trending_reason_urgent: "Urgent action required",
  trending_reason_email_accounts: "Impacts email accounts",
  trending_reason_credentials: "Credential compromise risk",
  // --- filter presets ---
  preset_label: "Quick views",
  preset_clear: "All threats",
  preset_most_relevant: "Most relevant today",
  preset_critical: "Critical threats",
  preset_scams_phishing: "Scams & phishing",
  preset_normal_users: "For everyday users",
  preset_enterprise: "Enterprise threats",
  preset_mobile: "Mobile threats",
  preset_account_security: "Account security",
  // --- freshness ---
  freshness_updated_prefix: "Feed updated",
  // Subtle annotation when no urgent threat has landed for >12h. NOT an
  // alarm — the reader should take comfort, not panic.
  freshness_quiet_day: "Quiet so far · no urgent threats in the last 12h",
  freshness_just_now: "just now",
  freshness_minutes_ago: (n) => `${n} min ago`,
  freshness_hours_ago: (n) => (n === 1 ? "1 hr ago" : `${n} hrs ago`),
  freshness_days_ago: (n) => (n === 1 ? "1 day ago" : `${n} days ago`),
  // --- feedback ---
  feedback_prompt: "Was this brief useful?",
  feedback_helpful: "Helpful",
  feedback_too_vague: "Too vague",
  feedback_too_technical: "Too technical",
  feedback_incorrect: "Incorrect",
  feedback_not_relevant: "Not relevant to me",
  feedback_thanks: "Thanks — your signal helps us tune the briefings.",
  // --- empty states (additions) ---
  empty_filter_hint: "Try a different quick-view or clear the filters.",
  empty_backend_updating:
    "Threat feed is updating. Try again in a moment.",
  empty_locale_unavailable:
    "This story is not yet available in your selected language.",
  references_heading: "References",
  detail_analysis_heading: "Analysis",
};

const UK: StringTable = {
  brand: "CyberAlertX",
  tagline_short: "Розвідка загроз для кожного",

  hero_eyebrow: "Кіберобізнаність у реальному часі",
  hero_headline: "Кіберзагрози. Перш ніж вони дістануться вас.",
  hero_subhead:
    "Найважливіше у кібербезпеці прямо зараз — пояснено просто та відсортовано за реальним впливом.",
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
  card_reading_time: (s) => formatReadingTime(s, "ua"),
  card_published_relative: (s) => formatPublished(s, "ua"),

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
  // --- intelligence layer ---
  intel_who_should_care: "Кого це стосується",
  intel_potential_impact: "Потенційний вплив",
  intel_threat_snapshot: "Огляд загрози",
  intel_also_reported_by: "Також повідомили",
  intel_signal_active_exploitation: "Активна експлуатація",
  intel_signal_credential_risk: "Крадіжка облікових даних",
  intel_signal_email_risk: "Ризик для пошти",
  intel_signal_financial_risk: "Фінансовий ризик",
  intel_signal_enterprise_risk: "Корпоративний ризик",
  intel_signal_consumer_risk: "Особистий ризик",
  intel_signal_session_hijack: "Перехоплення сесії",
  intel_signal_data_exposure: "Розкриття даних",
  intel_signal_malware_delivery: "Шкідливе ПЗ",
  trending_why_label: "Чому в тренді",
  trending_reason_active_exploitation: "Виявлено активну експлуатацію",
  trending_reason_corroborated: (n) =>
    n === 1 ? "Підтверджено ще 1 довіреним джерелом"
            : `Підтверджено ${n} довіреними джерелами`,
  trending_reason_critical: "Критичний рівень загрози",
  trending_reason_urgent: "Потрібна термінова дія",
  trending_reason_email_accounts: "Уражає поштові акаунти",
  trending_reason_credentials: "Ризик компрометації паролів",
  // --- filter presets ---
  preset_label: "Швидкі підбірки",
  preset_clear: "Усі загрози",
  preset_most_relevant: "Найважливіше сьогодні",
  preset_critical: "Критичні загрози",
  preset_scams_phishing: "Шахрайство і фішинг",
  preset_normal_users: "Для звичайних користувачів",
  preset_enterprise: "Корпоративні загрози",
  preset_mobile: "Мобільні загрози",
  preset_account_security: "Безпека акаунтів",
  // --- freshness ---
  freshness_updated_prefix: "Стрічка оновлена",
  freshness_quiet_day:
    "Спокійно — за останні 12 год термінових загроз не було",
  freshness_just_now: "щойно",
  freshness_minutes_ago: (n) => `${n} хв тому`,
  freshness_hours_ago: (n) => `${n} год тому`,
  freshness_days_ago: (n) => (n === 1 ? "1 день тому" : `${n} дн тому`),
  // --- feedback ---
  feedback_prompt: "Чи був цей огляд корисним?",
  feedback_helpful: "Корисно",
  feedback_too_vague: "Надто загально",
  feedback_too_technical: "Надто технічно",
  feedback_incorrect: "Неточно",
  feedback_not_relevant: "Не моя тема",
  feedback_thanks:
    "Дякуємо — ваш сигнал допомагає налаштувати огляди.",
  // --- empty states ---
  empty_filter_hint:
    "Спробуйте іншу підбірку або очистіть фільтри.",
  empty_backend_updating:
    "Стрічка оновлюється. Спробуйте за хвилину.",
  empty_locale_unavailable:
    "Цей матеріал ще не доступний обраною мовою.",
  references_heading: "Посилання",
  detail_analysis_heading: "Аналіз",
};

const TABLES: Record<Locale, StringTable> = { en: EN, ua: UK };

export function strings(lang: Locale): StringTable {
  return TABLES[lang] ?? EN;
}
