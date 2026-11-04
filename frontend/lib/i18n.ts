import type {
  ActionabilityLevel,
  Audience,
  Category,
  Locale,
  SourceTier,
  ThreatLevel,
} from "./types";
import type { TopicSlug } from "./topics";

/**
 * Interface copy for both editions.
 *
 * Two locales, one table each. The Ukrainian table is written for Ukrainian
 * readers, not translated line by line from the English one, following
 * docs/editorial/UKRAINIAN_STYLE_GUIDE.md (sentence case, «» quotes,
 * apostrophe ʼ, no calques). Every counted Ukrainian string goes through
 * `plural3`.
 */

type TopicCopy = {
  /** Page title (h1) and footer label. */
  name: string;
  /** Short label for the header navigation. */
  nav: string;
  /** One sentence under the h1 and the meta description. */
  description: string;
};

type StringTable = {
  brand: string;
  skip_to_content: string;

  // Navigation
  nav_label: string;
  nav_latest: string;
  menu_open: string;
  menu_close: string;
  language_label: string;
  telegram: string;

  // Masthead (home)
  edition_title: string;
  edition_standfirst: string;
  edition_latest: string;
  edition_count: (n: number) => string;

  // Lead story
  lead_read: string;
  lead_original: (source: string) => string;
  severity_reason: (level: string) => string;

  // Overview (home)
  overview_heading: string;
  overview_total: (n: number) => string;
  overview_by_severity: string;
  overview_exploited: string;
  overview_by_topic: string;
  overview_show: (label: string, n: number) => string;

  // Sections
  section_priority: string;
  section_feed: string;
  feed_count: (shown: number, total: number) => string;

  // Filters
  filters_title: string;
  filters_button: string;
  filters_apply: (n: number) => string;
  filters_reset: string;
  filters_active: (n: number) => string;
  filter_search: string;
  filter_search_placeholder: string;
  filter_severity: string;
  filter_category: string;
  filter_platform: string;
  filter_audience: string;
  filter_actionability: string;
  preset_label: string;
  preset_all: string;
  preset_critical: string;
  preset_exploited: string;
  preset_everyday: string;
  preset_it: string;
  preset_developers: string;
  preset_mobile: string;

  // Field marks
  mark_severity: string;
  mark_status: string;
  mark_exploited: string;
  mark_affects: string;
  mark_for: string;
  mark_source: string;
  mark_published: string;
  mark_reading: string;
  mark_more_outlets: (n: number) => string;
  mark_trust: Record<SourceTier, string>;

  // Method (home)
  method_heading: string;
  method_body: string;
  method_sources: string;
  method_sources_value: (n: number) => string;
  method_editions: string;
  method_cadence: string;
  method_cadence_value: string;
  method_outlets_heading: string;

  // Footer
  footer_sections: string;
  footer_editions: string;
  footer_follow: string;
  footer_contact: string;
  footer_note: string;
  footer_rights: string;
  subscribe_telegram: string;
  subscribe_rss: string;

  // Article
  breadcrumb_label: string;
  detail_what_happened: string;
  detail_why: string;
  detail_affected: string;
  detail_who_affected: string;
  detail_checks_hint: string;
  detail_what_to_do: string;
  detail_avoid: string;
  detail_already: string;
  detail_key_facts: string;
  detail_sources: string;
  detail_original: string;
  detail_coverage: string;
  detail_references: string;
  detail_related: string;
  detail_jump_actions: string;
  detail_provenance: (source: string) => string;
  illustration_caption: string;
  detail_not_available_in_locale: string;
  detail_not_available_hint: string;
  detail_not_found_title: string;
  detail_not_found_hint: string;
  detail_back_home: string;

  context_heading: string;
  context_how_it_works: string;
  context_who_is_affected: string;
  context_attacker_motivation: string;
  context_realistic_impact: string;

  // Share + feedback
  share_label: string;
  share_copy: string;
  share_copied: string;
  share_native: string;
  feedback_prompt: string;
  feedback_yes: string;
  feedback_no: string;
  feedback_thanks: string;
  feedback_follow_up: string;
  feedback_thanks_reason: string;
  feedback_reason_too_vague: string;
  feedback_reason_too_technical: string;
  feedback_reason_incorrect: string;
  feedback_reason_not_relevant: string;

  // Empty / error states
  empty_feed: string;
  empty_filter_hint: string;
  empty_backend_updating: string;
  empty_no_data_hint: string;
  empty_locale_unavailable: string;

  // Labels
  level: Record<ThreatLevel, string>;
  actionability: Record<ActionabilityLevel, string>;
  category: Record<Category, string>;
  audience: Record<Audience, string>;
  topic: Record<TopicSlug, TopicCopy>;

  // Time
  published_relative: (iso: string) => string;
  published_absolute: (iso: string) => string;
  edition_date: (date: Date) => string;
  reading_time: (seconds: number) => string;

  // Metadata
  meta_title: string;
  meta_description: string;
};

// ---------------------------------------------------------------- helpers

/** Ukrainian has three plural forms; 11–14 always take the many-form. */
function plural3(n: number, one: string, few: string, many: string): string {
  const mod100 = Math.abs(n) % 100;
  if (mod100 >= 11 && mod100 <= 14) return many;
  switch (Math.abs(n) % 10) {
    case 1:
      return one;
    case 2:
    case 3:
    case 4:
      return few;
    default:
      return many;
  }
}

/** Kyiv time for the Ukrainian edition, UTC for the English one: one
 *  explicit zone per edition so server and client render the same date. */
const ZONE: Record<Locale, string> = { en: "UTC", ua: "Europe/Kyiv" };

/**
 * Today / yesterday read relative ("2 h ago"); anything older shows the
 * date, so a reader can judge staleness without arithmetic.
 */
function formatRelative(iso: string, lang: Locale): string {
  const then = new Date(iso);
  if (!Number.isFinite(then.getTime())) return "";
  const diffMs = Math.max(0, Date.now() - then.getTime());
  const min = Math.floor(diffMs / 60_000);
  const hours = diffMs / 3_600_000;
  if (lang === "ua") {
    if (min < 1) return "щойно";
    if (min < 60) return `${min} хв тому`;
    if (hours < 24) return `${Math.round(hours)} год тому`;
    if (hours < 48) return "учора";
    return new Intl.DateTimeFormat("uk-UA", {
      day: "numeric",
      month: "long",
      timeZone: ZONE.ua,
    }).format(then);
  }
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  if (hours < 24) return `${Math.round(hours)} h ago`;
  if (hours < 48) return "yesterday";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: ZONE.en,
  }).format(then);
}

function formatAbsolute(iso: string, lang: Locale): string {
  const then = new Date(iso);
  if (!Number.isFinite(then.getTime())) return "";
  if (lang === "ua") {
    return new Intl.DateTimeFormat("uk-UA", {
      day: "numeric",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: ZONE.ua,
    }).format(then);
  }
  return (
    new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: ZONE.en,
    }).format(then) + " UTC"
  );
}

function formatEditionDate(date: Date, lang: Locale): string {
  return new Intl.DateTimeFormat(lang === "ua" ? "uk-UA" : "en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: ZONE[lang],
  }).format(date);
}

function formatReadingTime(total: number, lang: Locale): string {
  const minutes = Math.max(1, Math.round(total / 60));
  return lang === "ua" ? `${minutes} хв читання` : `${minutes} min read`;
}

// ---------------------------------------------------------------- English

const EN: StringTable = {
  brand: "CyberAlertX",
  skip_to_content: "Skip to content",

  nav_label: "Sections",
  nav_latest: "Latest",
  menu_open: "Menu",
  menu_close: "Close",
  language_label: "Language",
  telegram: "Telegram",

  edition_title: "Threat brief",
  edition_standfirst:
    "What attackers are exploiting, who is affected and what to do, written from trusted security reporting with a link to every source.",
  edition_latest: "Latest brief",
  edition_count: (n) => (n === 1 ? "1 brief in this edition" : `${n} briefs in this edition`),

  lead_read: "Read the brief",
  lead_original: (source) => `Original report: ${source}`,
  severity_reason: (level) => `Why ${level.toLowerCase()}`,

  overview_heading: "Last 7 days",
  overview_total: (n) => (n === 1 ? "1 brief" : `${n} briefs`),
  overview_by_severity: "By severity",
  overview_exploited: "Exploited in attacks",
  overview_by_topic: "By topic",
  overview_show: (label, n) => `Show ${n} ${label.toLowerCase()} ${n === 1 ? "brief" : "briefs"}`,

  section_priority: "Also significant now",
  section_feed: "Every brief, newest first",
  feed_count: (shown, total) => (shown === total ? `${total} briefs` : `${shown} of ${total} briefs`),

  filters_title: "Narrow the feed",
  filters_button: "Filter",
  filters_apply: (n) => (n === 1 ? "Show 1 brief" : `Show ${n} briefs`),
  filters_reset: "Clear all",
  filters_active: (n) => (n === 1 ? "1 filter on" : `${n} filters on`),
  filter_search: "Search briefs",
  filter_search_placeholder: "Product, CVE, company…",
  filter_severity: "Severity",
  filter_category: "Topic",
  filter_platform: "Platform",
  filter_audience: "Who it's for",
  filter_actionability: "Action needed",
  preset_label: "Quick views",
  preset_all: "Everything",
  preset_critical: "Critical and high",
  preset_exploited: "Under active attack",
  preset_everyday: "Everyday users",
  preset_it: "IT and security teams",
  preset_developers: "Developers",
  preset_mobile: "Phones",

  mark_severity: "Severity",
  mark_status: "Status",
  mark_exploited: "Exploited in attacks",
  mark_affects: "Affects",
  mark_for: "Who should care",
  mark_source: "Reported by",
  mark_published: "Published",
  mark_reading: "Length",
  mark_more_outlets: (n) => (n === 1 ? "+1 outlet" : `+${n} outlets`),
  mark_trust: {
    trusted: "trusted outlet",
    verified: "verified outlet",
    unverified: "unverified outlet",
  },

  method_heading: "How CyberAlertX works",
  method_body:
    "We read security reporting from established outlets and official advisories, group coverage of the same incident, and rate each story's severity by rule. An AI editorial pipeline then writes a short brief from the source facts: what happened, who is affected, how serious it is and what to do. Every brief links to the original reporting. The Ukrainian edition is written separately for Ukrainian readers, not translated from English.",
  method_sources: "Outlets in this edition",
  method_sources_value: (n) => `${n}`,
  method_editions: "Editions",
  method_cadence: "Updates",
  method_cadence_value: "Sources every 30 min, briefs hourly",
  method_outlets_heading: "Reporting in this edition",

  footer_sections: "Sections",
  footer_editions: "Editions",
  footer_follow: "Follow",
  footer_contact: "Contact",
  footer_note:
    "Briefs are written by an AI editorial pipeline from the linked reporting. Check the original source before acting on critical systems.",
  footer_rights: "© 2026 CyberAlertX",
  subscribe_telegram: "Telegram channel",
  subscribe_rss: "RSS feed",

  breadcrumb_label: "Breadcrumb",
  detail_what_happened: "What happened",
  detail_why: "Why it matters",
  detail_affected: "Are you affected?",
  detail_who_affected: "Who is affected",
  detail_checks_hint: "Each check ends in a yes or a no.",
  detail_what_to_do: "What to do",
  detail_avoid: "What to avoid",
  detail_already: "If you're already affected",
  detail_key_facts: "Key facts",
  detail_sources: "Sources",
  detail_original: "Original report",
  detail_coverage: "Also covered by",
  detail_references: "Advisories and identifiers",
  detail_related: "More on this topic",
  detail_jump_actions: "Skip to what to do",
  detail_provenance: (source) =>
    `Written by the CyberAlertX AI editorial pipeline from ${source}'s reporting, linked below. If something looks wrong, tell us with the feedback buttons.`,
  illustration_caption:
    "Illustration created for CyberAlertX. It is not a photograph or a screenshot of the incident.",
  detail_not_available_in_locale: "This brief isn't available in English.",
  detail_not_available_hint:
    "Stories from Ukrainian outlets are published in the Ukrainian edition only. You can read it there.",
  detail_not_found_title: "Brief not found",
  detail_not_found_hint: "It may have been merged into another story or removed.",
  detail_back_home: "Back to the threat brief",

  context_heading: "Background: this kind of attack",
  context_how_it_works: "How it works",
  context_who_is_affected: "Who is usually affected",
  context_attacker_motivation: "Why attackers do it",
  context_realistic_impact: "What actually happens",

  share_label: "Share",
  share_copy: "Copy link",
  share_copied: "Link copied",
  share_native: "More options",
  feedback_prompt: "Was this brief useful?",
  feedback_yes: "Yes",
  feedback_no: "No",
  feedback_thanks: "Thanks for telling us.",
  feedback_follow_up: "Thanks. What was wrong with it?",
  feedback_thanks_reason: "Thanks, that helps us fix it.",
  feedback_reason_too_vague: "Too vague",
  feedback_reason_too_technical: "Too technical",
  feedback_reason_incorrect: "Something is wrong",
  feedback_reason_not_relevant: "Not relevant to me",

  empty_feed: "No briefs match these filters.",
  empty_filter_hint: "Try another quick view or clear the filters.",
  empty_backend_updating: "The brief is updating.",
  empty_no_data_hint: "New stories appear here within the hour. Refresh in a moment.",
  empty_locale_unavailable: "This story isn't available in this edition yet.",

  level: { Critical: "Critical", High: "High", Medium: "Medium", Low: "Low" },
  actionability: {
    urgent_action: "Act now",
    recommended_action: "Action recommended",
    informational: "For awareness",
  },
  category: {
    phishing: "Phishing",
    ransomware: "Ransomware",
    vulnerability: "Vulnerability",
    breach: "Data breach",
    "data leak": "Data leak",
    exploit: "Exploited vulnerability",
    "zero-day": "Zero-day",
    malware: "Malware",
    spyware: "Spyware",
    scam: "Scam",
    botnet: "Botnet",
    "social engineering": "Social engineering",
    other: "Other",
  },
  audience: {
    normal_users: "Everyday users",
    developers: "Developers",
    sysadmins: "System administrators",
    enterprise: "Enterprise IT",
    mobile_users: "Phone users",
    crypto_users: "Crypto holders",
  },
  topic: {
    vulnerabilities: {
      name: "Vulnerabilities",
      nav: "Vulnerabilities",
      description:
        "Security flaws in software and devices, which ones attackers are already exploiting, and the patches that close them.",
    },
    malware: {
      name: "Malware and ransomware",
      nav: "Malware",
      description:
        "Ransomware, spyware, botnets and other malicious software: who is behind them, how they spread and how to recover.",
    },
    breaches: {
      name: "Data breaches",
      nav: "Breaches",
      description:
        "Break-ins and leaks that exposed personal or company data, what was taken and what the people affected should do.",
    },
    phishing: {
      name: "Phishing and scams",
      nav: "Scams",
      description:
        "Fake messages, lookalike sites and social-engineering schemes, and how to recognise them before you click.",
    },
  },

  published_relative: (iso) => formatRelative(iso, "en"),
  published_absolute: (iso) => formatAbsolute(iso, "en"),
  edition_date: (d) => formatEditionDate(d, "en"),
  reading_time: (s) => formatReadingTime(s, "en"),

  meta_title: "CyberAlertX — Cyber threat brief",
  meta_description:
    "Which vulnerabilities are being exploited, which breaches matter and what to do about them. Short, sourced cybersecurity briefs, updated hourly.",
};

// ---------------------------------------------------------------- Ukrainian

const UK: StringTable = {
  brand: "CyberAlertX",
  skip_to_content: "Перейти до змісту",

  nav_label: "Розділи",
  nav_latest: "Головне",
  menu_open: "Меню",
  menu_close: "Закрити",
  language_label: "Мова",
  telegram: "Telegram",

  edition_title: "Зведення загроз",
  edition_standfirst:
    "Що зараз атакують, кого це зачіпає і що робити. Кожен матеріал спирається на звіти перевірених видань і має посилання на першоджерело.",
  edition_latest: "Останній матеріал",
  edition_count: (n) =>
    `${n} ${plural3(n, "матеріал", "матеріали", "матеріалів")} у зведенні`,

  lead_read: "Читати матеріал",
  lead_original: (source) => `Першоджерело: ${source}`,
  severity_reason: (level) => `Чому рівень «${level.toLowerCase()}»`,

  overview_heading: "За останні 7 днів",
  overview_total: (n) => `${n} ${plural3(n, "матеріал", "матеріали", "матеріалів")}`,
  overview_by_severity: "За рівнем загрози",
  overview_exploited: "Уже використовують в атаках",
  overview_by_topic: "За темою",
  overview_show: (label, n) =>
    `Показати ${n} ${plural3(n, "матеріал", "матеріали", "матеріалів")}: ${label.toLowerCase()}`,

  section_priority: "Також важливо зараз",
  section_feed: "Усі матеріали, від найновіших",
  feed_count: (shown, total) =>
    shown === total
      ? `${total} ${plural3(total, "матеріал", "матеріали", "матеріалів")}`
      : `${shown} з ${total}`,

  filters_title: "Звузити стрічку",
  filters_button: "Фільтри",
  filters_apply: (n) => `Показати ${n} ${plural3(n, "матеріал", "матеріали", "матеріалів")}`,
  filters_reset: "Скинути все",
  filters_active: (n) => `${n} ${plural3(n, "фільтр", "фільтри", "фільтрів")}`,
  filter_search: "Пошук",
  filter_search_placeholder: "Продукт, CVE, компанія…",
  filter_severity: "Рівень загрози",
  filter_category: "Тема",
  filter_platform: "Платформа",
  filter_audience: "Для кого",
  filter_actionability: "Чи потрібні дії",
  preset_label: "Швидкі добірки",
  preset_all: "Усе",
  preset_critical: "Критичні й високі",
  preset_exploited: "Уже атакують",
  preset_everyday: "Звичайним користувачам",
  preset_it: "ІТ та безпековим командам",
  preset_developers: "Розробникам",
  preset_mobile: "Смартфони",

  mark_severity: "Рівень загрози",
  mark_status: "Стан",
  mark_exploited: "Уже використовують в атаках",
  mark_affects: "Зачіпає",
  mark_for: "Кого стосується",
  mark_source: "Повідомляє",
  mark_published: "Опубліковано",
  mark_reading: "Обсяг",
  mark_more_outlets: (n) => `+${n} ${plural3(n, "видання", "видання", "видань")}`,
  mark_trust: {
    trusted: "надійне видання",
    verified: "перевірене видання",
    unverified: "неперевірене видання",
  },

  method_heading: "Як працює CyberAlertX",
  method_body:
    "Ми стежимо за публікаціями відомих видань і офіційними бюлетенями з безпеки, обʼєднуємо повідомлення про той самий інцидент і визначаємо рівень загрози за чіткими правилами. Потім редакційна система на основі ШІ пише стислий матеріал з фактів першоджерела: що сталося, кого це зачіпає, наскільки це серйозно і що робити. До кожного матеріалу додаємо посилання на оригінальну публікацію. Українська версія пишеться окремо для українських читачів, а не перекладається з англійської.",
  method_sources: "Видань у зведенні",
  method_sources_value: (n) => `${n}`,
  method_editions: "Версії",
  method_cadence: "Оновлення",
  method_cadence_value: "Джерела щопівгодини, матеріали щогодини",
  method_outlets_heading: "Звідки новини в цьому зведенні",

  footer_sections: "Розділи",
  footer_editions: "Версії",
  footer_follow: "Стежити",
  footer_contact: "Звʼязок",
  footer_note:
    "Матеріали готує редакційна система на основі ШІ з публікацій, на які ми посилаємося. Перш ніж змінювати критичні системи, звірте дані з першоджерелом.",
  footer_rights: "© 2026 CyberAlertX",
  subscribe_telegram: "Канал у Telegram",
  subscribe_rss: "RSS-стрічка",

  breadcrumb_label: "Навігаційний ланцюжок",
  detail_what_happened: "Що сталося",
  detail_why: "Чому це важливо",
  detail_affected: "Чи стосується це вас?",
  detail_who_affected: "Кого це зачіпає",
  detail_checks_hint: "Кожна перевірка закінчується відповіддю «так» або «ні».",
  detail_what_to_do: "Що робити",
  detail_avoid: "Чого не робити",
  detail_already: "Якщо вас це вже зачепило",
  detail_key_facts: "Ключові факти",
  detail_sources: "Джерела",
  detail_original: "Першоджерело",
  detail_coverage: "Також писали",
  detail_references: "Бюлетені та ідентифікатори",
  detail_related: "Більше на цю тему",
  detail_jump_actions: "Одразу до порад",
  detail_provenance: (source) =>
    `Матеріал підготувала редакційна система CyberAlertX на основі ШІ за публікацією ${source}; посилання нижче. Якщо помітили неточність, повідомте нам кнопками відгуку.`,
  illustration_caption:
    "Ілюстрацію створено для CyberAlertX. Це не фото й не знімок екрана з інциденту.",
  detail_not_available_in_locale: "Цей матеріал недоступний українською.",
  detail_not_available_hint:
    "Ми не публікуємо частково перекладених матеріалів. Його можна прочитати англійською.",
  detail_not_found_title: "Матеріал не знайдено",
  detail_not_found_hint: "Можливо, його обʼєднали з іншою новиною або вилучили.",
  detail_back_home: "До зведення загроз",

  context_heading: "Контекст: такі атаки загалом",
  context_how_it_works: "Як це працює",
  context_who_is_affected: "Кого зачіпає найчастіше",
  context_attacker_motivation: "Навіщо це зловмисникам",
  context_realistic_impact: "Що відбувається насправді",

  share_label: "Поділитися",
  share_copy: "Скопіювати посилання",
  share_copied: "Посилання скопійовано",
  share_native: "Інші способи",
  feedback_prompt: "Чи був цей матеріал корисним?",
  feedback_yes: "Так",
  feedback_no: "Ні",
  feedback_thanks: "Дякуємо за відгук.",
  feedback_follow_up: "Дякуємо. Що з ним не так?",
  feedback_thanks_reason: "Дякуємо, це допоможе виправити.",
  feedback_reason_too_vague: "Надто загально",
  feedback_reason_too_technical: "Надто технічно",
  feedback_reason_incorrect: "Є помилка",
  feedback_reason_not_relevant: "Мене не стосується",

  empty_feed: "Немає матеріалів за цими фільтрами.",
  empty_filter_hint: "Спробуйте іншу добірку або скиньте фільтри.",
  empty_backend_updating: "Зведення оновлюється.",
  empty_no_data_hint: "Нові матеріали зʼявляються тут щогодини. Оновіть сторінку трохи згодом.",
  empty_locale_unavailable: "Цього матеріалу ще немає в цій версії.",

  level: { Critical: "Критичний", High: "Високий", Medium: "Середній", Low: "Низький" },
  actionability: {
    urgent_action: "Діяти негайно",
    recommended_action: "Варто вжити заходів",
    informational: "До відома",
  },
  category: {
    phishing: "Фішинг",
    ransomware: "Програма-вимагач",
    vulnerability: "Вразливість",
    breach: "Злам і витік даних",
    "data leak": "Витік даних",
    exploit: "Атаки через вразливість",
    "zero-day": "Уразливість нульового дня",
    malware: "Шкідливе ПЗ",
    spyware: "Шпигунське ПЗ",
    scam: "Шахрайство",
    botnet: "Ботнет",
    "social engineering": "Соціальна інженерія",
    other: "Інше",
  },
  audience: {
    normal_users: "Звичайні користувачі",
    developers: "Розробники",
    sysadmins: "Системні адміністратори",
    enterprise: "Корпоративні ІТ",
    mobile_users: "Власники смартфонів",
    crypto_users: "Власники криптовалют",
  },
  topic: {
    vulnerabilities: {
      name: "Вразливості",
      nav: "Вразливості",
      description:
        "Вразливості в програмах і пристроях: які з них уже використовують в атаках і які оновлення їх закривають.",
    },
    malware: {
      name: "Шкідливе ПЗ і вимагачі",
      nav: "Шкідливе ПЗ",
      description:
        "Програми-вимагачі, шпигунське ПЗ, ботнети та інше шкідливе ПЗ: хто за ними стоїть, як вони поширюються і як відновитися.",
    },
    breaches: {
      name: "Витоки даних",
      nav: "Витоки",
      description:
        "Злами й витоки, через які розкрито особисті чи корпоративні дані: що саме викрали і що робити тим, кого це зачепило.",
    },
    phishing: {
      name: "Фішинг і шахрайство",
      nav: "Шахрайство",
      description:
        "Підроблені повідомлення, сайти-двійники та схеми соціальної інженерії і як розпізнати їх, перш ніж натиснути посилання.",
    },
  },

  published_relative: (iso) => formatRelative(iso, "ua"),
  published_absolute: (iso) => formatAbsolute(iso, "ua"),
  edition_date: (d) => formatEditionDate(d, "ua"),
  reading_time: (s) => formatReadingTime(s, "ua"),

  meta_title: "CyberAlertX — Зведення кіберзагроз",
  meta_description:
    "Які вразливості вже використовують в атаках, які витоки важливі і що з цим робити. Стислі матеріали з посиланнями на джерела, оновлення щогодини.",
};

const TABLES: Record<Locale, StringTable> = { en: EN, ua: UK };

export function strings(lang: Locale): StringTable {
  return TABLES[lang] ?? EN;
}
