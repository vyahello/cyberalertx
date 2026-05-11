import { ShieldAlert, AlertTriangle, Info, CircleDot } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import type { Locale, ThreatLevel } from "@/lib/types";

interface Props {
  level: ThreatLevel;
  lang: Locale;
  className?: string;
  /** When true, render only the dot — no label, no icon. Used in dense card headers. */
  iconOnly?: boolean;
}

/**
 * Visual weight by level — restrained on purpose.
 *
 * The biggest UX risk for a threat-feed product is alarm fatigue: if every
 * card screams Critical-red, the user stops trusting the signal. We use
 * color sparingly — Critical and High get warm tones with low saturation;
 * Medium uses a muted yellow; Low is a neutral slate that visually recedes.
 */
const LEVEL_STYLES: Record<ThreatLevel, { fg: string; bg: string; border: string; Icon: typeof Info }> = {
  Critical: {
    fg: "text-level-critical-fg",
    bg: "bg-level-critical-bg",
    border: "border-level-critical-border",
    Icon: ShieldAlert,
  },
  High: {
    fg: "text-level-high-fg",
    bg: "bg-level-high-bg",
    border: "border-level-high-border",
    Icon: AlertTriangle,
  },
  Medium: {
    fg: "text-level-medium-fg",
    bg: "bg-level-medium-bg",
    border: "border-level-medium-border",
    Icon: CircleDot,
  },
  Low: {
    fg: "text-level-low-fg",
    bg: "bg-level-low-bg",
    border: "border-level-low-border",
    Icon: Info,
  },
};

export function ThreatBadge({ level, lang, className, iconOnly }: Props) {
  const s = LEVEL_STYLES[level];
  const label = strings(lang).level[level];
  return (
    <span
      className={cn(
        "badge border",
        s.fg,
        s.bg,
        s.border,
        iconOnly && "px-1.5",
        className,
      )}
      aria-label={label}
    >
      <s.Icon className="w-3 h-3" strokeWidth={2.5} />
      {!iconOnly && <span>{label}</span>}
    </span>
  );
}
