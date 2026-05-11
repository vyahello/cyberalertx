import { ShieldCheck, Shield, ShieldQuestion } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import type { Locale, SourceTier } from "@/lib/types";

interface Props {
  tier: SourceTier;
  source: string;
  lang: Locale;
  /** Score in [0,1]. When >= 0.85, we render a slightly heavier weight. */
  score?: number;
  className?: string;
}

const TIER_STYLES: Record<SourceTier, { fg: string; bg: string; Icon: typeof Shield }> = {
  trusted: { fg: "text-trust-trusted-fg", bg: "bg-trust-trusted-bg", Icon: ShieldCheck },
  verified: { fg: "text-trust-verified-fg", bg: "bg-trust-verified-bg", Icon: Shield },
  unverified: { fg: "text-trust-unverified-fg", bg: "bg-trust-unverified-bg", Icon: ShieldQuestion },
};

/**
 * Renders as "<tier-icon> <source-name>" — the source name itself is the
 * primary credibility signal for a regular reader. The tier icon is the
 * supporting cue. We do NOT show the numeric score on the badge; it would
 * read as a stat to debate rather than a reassurance.
 */
export function CredibilityBadge({ tier, source, lang, className }: Props) {
  const s = TIER_STYLES[tier];
  const label = strings(lang).trust[tier];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs",
        s.fg,
        className,
      )}
      title={label}
      aria-label={`${source} — ${label}`}
    >
      <span className={cn("inline-flex items-center justify-center w-5 h-5 rounded-full", s.bg)}>
        <s.Icon className="w-3 h-3" strokeWidth={2.5} />
      </span>
      <span className="font-medium">{source}</span>
    </span>
  );
}
