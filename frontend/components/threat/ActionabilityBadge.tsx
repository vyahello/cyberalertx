import { Zap, ArrowRight, BookOpen } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import type { ActionabilityLevel, Locale } from "@/lib/types";

interface Props {
  level: ActionabilityLevel;
  lang: Locale;
  className?: string;
}

const STYLES: Record<
  ActionabilityLevel,
  { fg: string; bg: string; Icon: typeof Zap }
> = {
  urgent_action: {
    fg: "text-level-critical-fg",
    bg: "bg-level-critical-bg",
    Icon: Zap,
  },
  recommended_action: {
    fg: "text-accent",
    bg: "bg-accent-soft",
    Icon: ArrowRight,
  },
  informational: {
    fg: "text-text-secondary",
    bg: "bg-bg-elevated-2",
    Icon: BookOpen,
  },
};

export function ActionabilityBadge({ level, lang, className }: Props) {
  const s = STYLES[level];
  return (
    <span className={cn("badge", s.fg, s.bg, className)}>
      <s.Icon className="w-3 h-3" strokeWidth={2.5} />
      {strings(lang).actionability[level]}
    </span>
  );
}
