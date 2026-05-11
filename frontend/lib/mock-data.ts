import type { LocalizedThreatPost } from "./types";

/**
 * Realistic fixture data — kept for tests, component design previews, and
 * offline development when the Python backend isn't running.
 *
 * Each entry mirrors the backend's `LocalizedThreatPost` shape
 * (see `cyberalertx/api/app.py:_PostService.render`). Some items carry
 * only one translation (their source language); some carry both — those
 * exist to exercise the multilingual UI without needing the LLM path
 * configured.
 */

const HOUR = 60 * 60 * 1000;
const MINUTE = 60 * 1000;
const now = Date.now();
function ago(ms: number): string {
  return new Date(now - ms).toISOString();
}

export const MOCK_POSTS: LocalizedThreatPost[] = [
  {
    id: "ai-2fa-bypass",
    source: "The Hacker News",
    source_url: "https://thehackernews.com/2026/05/ai-2fa-bypass.html",
    source_tier: "trusted",
    source_credibility_score: 0.87,
    published_at: ago(42 * MINUTE),
    threat_level: "Critical",
    category: "zero-day",
    affected_platforms: [],
    audience_targets: ["normal_users", "developers", "sysadmins"],
    actionability_level: "urgent_action",
    actionability_score: 0.93,
    emotional_weight: 0.92,
    available_locales: ["en"],
    translations: {
      en: {
        title:
          "Hackers Used AI to Develop First Known Zero-Day 2FA Bypass for Mass Exploitation",
        short_summary:
          "Google disclosed an unknown threat actor using a zero-day exploit likely developed with an AI system — the first observed in-the-wild AI-assisted exploit generation.",
        why_it_matters:
          "Working exploit, in the wild, today. Patch or mitigate now.",
        affected_users: ["Anyone with 2FA on the affected services"],
        what_to_do: [
          "Watch for the vendor advisory and patch as soon as it ships",
          "Audit recent sign-in events for unexplained sessions",
          "Rotate session tokens on critical accounts",
        ],
        what_not_to_do: [
          "Don't assume 2FA alone is enough — check session activity too",
        ],
        quick_facts: ["Actively exploited", "Active exploit", "The Hacker News"],
        reading_time_seconds: 22,
      },
    },
  },
  {
    id: "outlook-phish-uk",
    source: "Krebs on Security",
    source_url: "https://krebsonsecurity.com/2026/05/outlook-phishing.html",
    source_tier: "trusted",
    source_credibility_score: 0.91,
    published_at: ago(11 * HOUR),
    threat_level: "High",
    category: "phishing",
    affected_platforms: ["Outlook"],
    audience_targets: ["normal_users"],
    actionability_level: "recommended_action",
    actionability_score: 0.62,
    emotional_weight: 0.66,
    available_locales: ["uk"],
    translations: {
      uk: {
        title:
          "Хвиля фішингу маскується під сповіщення Microsoft 365 з фальшивою сторінкою входу",
        short_summary:
          "Зловмисники надсилають листи, що нібито надходять від адміністрації Microsoft 365, та крадуть паролі на схожих доменах.",
        why_it_matters:
          "Жива фішингова хвиля. Секунда сумніву рятує обліковий запис.",
        affected_users: ["Користувачі Outlook", "Звичайні користувачі"],
        what_to_do: [
          "Відкривайте сервіс напряму у браузері — не через посилання з листа",
          "Перевіряйте адресу відправника, а не лише ім'я, що відображається",
          "Увімкніть двофакторну автентифікацію",
        ],
        what_not_to_do: [
          "Не вводьте пароль на сторінці, на яку ви потрапили з листа",
          "Не діліться одноразовими кодами — справжні сервіси не питають",
        ],
        quick_facts: ["Phishing campaign", "Affects Outlook", "Krebs on Security"],
        reading_time_seconds: 30,
      },
    },
  },
  {
    id: "k8s-rbac",
    source: "The Hacker News",
    source_url: "https://thehackernews.com/2026/05/k8s-rbac.html",
    source_tier: "trusted",
    source_credibility_score: 0.82,
    published_at: ago(28 * HOUR),
    threat_level: "Medium",
    category: "vulnerability",
    affected_platforms: ["Kubernetes"],
    audience_targets: ["developers", "sysadmins"],
    actionability_level: "recommended_action",
    actionability_score: 0.5,
    emotional_weight: 0.42,
    // Dual-locale example: both EN and UK content present. In production
    // this only happens when the LLM path is wired up. Useful for verifying
    // the language-switch flow in dev.
    available_locales: ["en", "uk"],
    translations: {
      en: {
        title:
          "Kubernetes RBAC misconfiguration lets attackers escalate from pod to cluster admin",
        short_summary:
          "A common RBAC misconfiguration in self-hosted Kubernetes clusters lets attackers escalate from a compromised pod to cluster-admin via stale ServiceAccount bindings.",
        why_it_matters: "Not a fire drill, but worth handling this week.",
        affected_users: ["Sysadmins running Kubernetes", "DevOps teams"],
        what_to_do: [
          "Audit ClusterRoleBindings for `system:masters` references",
          "Run kubectl-who-can or polaris against your clusters",
          "Rotate any long-lived ServiceAccount tokens",
        ],
        what_not_to_do: [],
        quick_facts: ["Affects Kubernetes", "Vulnerability"],
        reading_time_seconds: 35,
      },
      uk: {
        title:
          "Неправильна конфігурація Kubernetes RBAC дозволяє ескалацію від pod до cluster admin",
        short_summary:
          "Поширена помилка в RBAC у self-hosted Kubernetes-кластерах дає змогу зловмиснику з одного pod дістатися cluster-admin через старі ServiceAccount bindings.",
        why_it_matters: "Не пожежа, але цього тижня варто розібратися.",
        affected_users: ["Адміністратори Kubernetes", "DevOps-команди"],
        what_to_do: [
          "Перегляньте ClusterRoleBindings на згадки `system:masters`",
          "Запустіть kubectl-who-can або polaris у ваших кластерах",
          "Поміняйте довгоживучі ServiceAccount-токени",
        ],
        what_not_to_do: [],
        quick_facts: ["Платформа: Kubernetes", "Вразливість"],
        reading_time_seconds: 38,
      },
    },
  },
];
