"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Languages } from "lucide-react";
import { cn } from "@/lib/cn";
import { SUPPORTED_LOCALES, type Locale } from "@/lib/types";

interface Props {
  lang: Locale;
}

const LABELS: Record<Locale, string> = { en: "EN", ua: "UA" };

/**
 * Two-state language toggle.
 *
 * Switching navigates to the same page in the other locale (e.g.
 * `/en/threat/abc` ↔ `/ua/threat/abc`). The URL is the source of truth
 * — no client state, no flash-of-wrong-locale on refresh, every page is
 * bookmarkable per language.
 *
 * Prefetch strategy: we explicitly prefetch the INACTIVE locale's URL
 * once the switcher is in the viewport. That trades one extra RSC fetch
 * per page load for a near-instant tap on the language toggle — critical
 * on mobile where every SSR roundtrip feels like a stall. We do NOT
 * prefetch the active locale (we're already on it). Earlier versions used
 * `prefetch={false}` to save bandwidth; the resulting UX hang on locale
 * switch was worse than the cost of one extra payload.
 */
export function LanguageSwitcher({ lang }: Props) {
  const pathname = usePathname() || "/";

  function pathInLocale(target: Locale): string {
    // Replace the leading locale segment. The pathname is always
    // `/<locale>/...` here because middleware/redirect guarantees it.
    const parts = pathname.split("/");
    if (parts[1] && SUPPORTED_LOCALES.includes(parts[1] as Locale)) {
      parts[1] = target;
      return parts.join("/") || `/${target}`;
    }
    return `/${target}`;
  }

  return (
    <div
      role="group"
      aria-label="Language"
      className="inline-flex items-center gap-0.5 p-0.5 rounded-md bg-bg-elevated-2 border border-border-subtle"
    >
      <Languages className="w-3.5 h-3.5 text-text-tertiary mx-1.5" aria-hidden />
      {SUPPORTED_LOCALES.map((l) => {
        const active = lang === l;
        return (
          <Link
            key={l}
            href={pathInLocale(l)}
            // Prefetch ONLY the inactive locale — we never need the
            // active one preloaded. `undefined` (Next default) → intent-
            // based prefetch when the link is visible; matches our need.
            prefetch={active ? false : undefined}
            aria-current={active ? "page" : undefined}
            className={cn(
              "px-2.5 py-1 rounded text-xs font-semibold tracking-wider",
              "transition-colors duration-150",
              active
                ? "bg-bg-base text-text-primary"
                : "text-text-secondary hover:text-text-primary",
            )}
          >
            {LABELS[l]}
          </Link>
        );
      })}
    </div>
  );
}
