import { CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

interface Props {
  sources: string[] | undefined;
  lang: Locale;
  className?: string;
  /** When true, prefix with a check-circle icon. Card default: yes. */
  withIcon?: boolean;
}

/**
 * Trust-anchor line: "Also reported by CISA, Microsoft".
 *
 * Surfaces the corroboration data the credibility analyzer extracts —
 * other TRUSTED sources covering the same story. We render this line
 * only when there's at least one corroborator; otherwise it would just
 * be visual weight without information.
 *
 * Visual style: small, calm, text-tertiary. The check-circle icon hints
 * at confirmation without screaming "VERIFIED". Sources are joined with
 * a · separator — the reader scans them as a brief list, not as labels.
 */
export function CorroborationLine({
  sources,
  lang,
  className,
  withIcon = true,
}: Props) {
  if (!sources || sources.length === 0) return null;
  const s = strings(lang);
  // Cap at 3 — anything beyond is noise on a feed card; the detail page
  // shows the full list.
  const shown = sources.slice(0, 3);
  return (
    <p
      className={cn(
        "inline-flex items-center gap-1.5 text-xs text-text-tertiary",
        className,
      )}
    >
      {withIcon && (
        <CheckCircle2 className="w-3.5 h-3.5 text-trust-trusted-fg/80" aria-hidden />
      )}
      <span>
        <span className="text-text-secondary">{s.intel_also_reported_by}</span>
        {" "}
        <span className="font-medium text-text-primary">{shown.join(" · ")}</span>
        {sources.length > shown.length && (
          <span className="text-text-tertiary">
            {" "}
            +{sources.length - shown.length}
          </span>
        )}
      </span>
    </p>
  );
}
