import { Bug, ExternalLink, FileSearch, Newspaper, ShieldAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import type { Locale, ThreatReference } from "@/lib/types";

interface Props {
  refs: ThreatReference[] | undefined;
  lang: Locale;
  className?: string;
}

/**
 * Per-reference-type icon. Picked for at-a-glance recognizability:
 *   cve       → Bug      (vulnerability ID)
 *   advisory  → ShieldAlert
 *   vendor    → FileSearch
 *   cert      → ShieldAlert  (national CERT bulletin)
 *   news      → Newspaper   (fallback for press references)
 */
const TYPE_ICONS: Record<string, LucideIcon> = {
  cve: Bug,
  advisory: ShieldAlert,
  cert: ShieldAlert,
  vendor: FileSearch,
  news: Newspaper,
};

/**
 * Compact references list — only on the detail page.
 *
 * Visual: small block at the bottom of the narrative. Each item is a
 * clickable link with an icon, type label, and the actual reference
 * label (e.g. "CVE-2026-1234"). External-link icon hints the link
 * leaves the site.
 *
 * Renders nothing when `refs` is empty / undefined.
 */
export function References({ refs, lang, className }: Props) {
  if (!refs || refs.length === 0) return null;
  const s = strings(lang);
  return (
    <section
      aria-labelledby="references-heading"
      className={cn("border-t border-border-subtle pt-6", className)}
    >
      <h3
        id="references-heading"
        className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-3"
      >
        {s.references_heading}
      </h3>
      <ul className="grid gap-2 sm:grid-cols-2">
        {refs.map((ref, i) => {
          const Icon = TYPE_ICONS[ref.type] ?? Newspaper;
          return (
            <li key={`${ref.type}:${ref.label}:${i}`}>
              <a
                href={ref.url}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  "inline-flex items-center gap-2 text-sm rounded-md",
                  "px-2.5 py-1.5 border border-border-subtle bg-bg-elevated-2",
                  "text-text-secondary hover:text-text-primary",
                  "hover:border-border-strong transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-ring",
                )}
              >
                <Icon className="w-3.5 h-3.5 text-text-tertiary" aria-hidden strokeWidth={2.2} />
                <span className="font-medium">{ref.label}</span>
                <ExternalLink className="w-3 h-3 text-text-tertiary ml-auto" aria-hidden />
              </a>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
