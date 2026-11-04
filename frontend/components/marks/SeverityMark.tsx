import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import { severitySegments } from "@/lib/significance";
import type { Locale, ThreatLevel } from "@/lib/types";

const FILL: Record<ThreatLevel, string> = {
  Critical: "bg-sev-critical",
  High: "bg-sev-high",
  Medium: "bg-sev-medium",
  Low: "bg-sev-low",
};

const TEXT: Record<ThreatLevel, string> = {
  Critical: "text-sev-critical",
  High: "text-sev-high",
  Medium: "text-sev-medium",
  Low: "text-ink-muted",
};

interface Props {
  level: ThreatLevel;
  lang: Locale;
  className?: string;
}

/**
 * Severity as three redundant signals: the word, the number of filled
 * segments (1–4) and the colour. A reader who can't tell red from amber
 * still reads "Critical" and sees four bars out of four.
 */
export function SeverityMark({ level, lang, className }: Props) {
  const s = strings(lang);
  const filled = severitySegments(level);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 font-sans text-small font-semibold whitespace-nowrap",
        TEXT[level],
        className,
      )}
    >
      <span aria-hidden className="inline-flex items-end gap-[3px]">
        {[1, 2, 3, 4].map((i) => (
          <span
            key={i}
            className={cn("w-[5px]", i <= filled ? FILL[level] : "bg-ground-high")}
            style={{ height: `${6 + i * 2}px` }}
          />
        ))}
      </span>
      <span>
        <span className="sr-only">{s.mark_severity}: </span>
        {s.level[level]}
      </span>
    </span>
  );
}
