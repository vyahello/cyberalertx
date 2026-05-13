import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import { accentClasses, visualForCategory } from "@/lib/category-visuals";
import type { Category, Locale } from "@/lib/types";

interface Props {
  category: Category | string;
  lang: Locale;
  className?: string;
}

/**
 * Small category icon plate used on feed cards.
 *
 * Design intent: a visual anchor for thumb-scrolling. The eye latches
 * onto the chip and pre-classifies the card before reading the title —
 * fast pattern recognition without surrendering information density.
 *
 * Stays small (32×32) and uses a soft accent tint so the card doesn't
 * read as a colorful tile-grid. Severity is communicated by the
 * ThreatBadge in the header row; this chip carries category only.
 */
export function CategoryIconChip({ category, lang, className }: Props) {
  const s = strings(lang);
  const { icon: Icon, accent } = visualForCategory(category);
  const c = accentClasses(accent);
  const label = s.category[category as Category] ?? s.category.other;

  return (
    <span
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex h-8 w-8 flex-shrink-0 items-center justify-center",
        "rounded-lg border",
        c.bg, c.border,
        className,
      )}
    >
      <Icon className={cn("h-4 w-4", c.fg)} strokeWidth={2} aria-hidden />
    </span>
  );
}
