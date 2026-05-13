import {
  AlertOctagon,
  AtSign,
  Banknote,
  Building2,
  Cookie,
  KeyRound,
  ShieldOff,
  User,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import type { Locale, ThreatSignals } from "@/lib/types";

interface Props {
  signals: ThreatSignals | undefined;
  lang: Locale;
  /** Maximum chips to render. Card default: 3. Detail default: all. */
  max?: number;
  className?: string;
}

type SignalKey = keyof ThreatSignals;

/**
 * Ordered list of signal → (icon, i18n key) pairs. The order is the
 * *display priority*: when we trim to `max` chips we keep the most
 * alarming/specific signals and drop the broad-bucket ones.
 *
 * `active_exploitation` gets a tint accent (the only colored chip in
 * the card). Everything else is monochromatic — the goal is "calm
 * intelligence", not "siren UI".
 */
const SIGNAL_ORDER: Array<{
  key: SignalKey;
  icon: LucideIcon;
  i18nKey: keyof ReturnType<typeof strings>;
  alarm?: boolean;
}> = [
  { key: "active_exploitation",  icon: AlertOctagon, i18nKey: "intel_signal_active_exploitation", alarm: true },
  { key: "affects_email_accounts", icon: AtSign,    i18nKey: "intel_signal_email_risk" },
  { key: "credential_theft_risk", icon: KeyRound,   i18nKey: "intel_signal_credential_risk" },
  { key: "steals_sessions",       icon: Cookie,     i18nKey: "intel_signal_session_hijack" },
  { key: "financial_risk",        icon: Banknote,   i18nKey: "intel_signal_financial_risk" },
  { key: "data_exposure_risk",    icon: ShieldOff,  i18nKey: "intel_signal_data_exposure" },
  { key: "malware_delivery",      icon: ShieldOff,  i18nKey: "intel_signal_malware_delivery" },
  { key: "enterprise_risk",       icon: Building2,  i18nKey: "intel_signal_enterprise_risk" },
  { key: "consumer_risk",         icon: User,       i18nKey: "intel_signal_consumer_risk" },
];

/**
 * Subtle row of icon chips describing threat shape — what the threat
 * *does* to the reader, in 2-3 glanceable indicators.
 *
 * Selection: walk the priority order, pick the first `max` signals that
 * fired. `enterprise_risk` and `consumer_risk` come last because they're
 * coarse buckets — if a more specific signal (email, financial, session)
 * fired, we'd rather show that.
 *
 * Visual: low-contrast pills. Only `active_exploitation` gets an accent
 * tint so the user can spot the alarm signal at a glance without the
 * card feeling like a panic dashboard.
 */
export function SignalIndicators({ signals, lang, max = 3, className }: Props) {
  if (!signals) return null;
  const s = strings(lang);
  const lit = SIGNAL_ORDER.filter((entry) => Boolean(signals[entry.key])).slice(0, max);
  if (lit.length === 0) return null;

  return (
    <ul className={cn("flex flex-wrap gap-1.5", className)} aria-label="Threat signals">
      {lit.map(({ key, icon: Icon, i18nKey, alarm }) => {
        const label = s[i18nKey] as string;
        return (
          <li key={key}>
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full",
                "px-2 py-0.5 text-2xs leading-none",
                "border",
                alarm
                  // Alarm chip — uses the existing level-critical token
                  // (dark red surface, light red foreground) so it
                  // matches the rest of the design system without
                  // introducing a new palette.
                  ? "bg-level-critical-bg border-level-critical-border text-level-critical-fg"
                  : "bg-bg-elevated-2 border-border-subtle text-text-tertiary",
              )}
              title={label}
            >
              <Icon className="w-3 h-3" strokeWidth={2.2} aria-hidden />
              <span className="font-medium">{label}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
