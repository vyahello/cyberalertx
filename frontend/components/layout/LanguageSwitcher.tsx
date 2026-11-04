"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import { HTML_LANG, SUPPORTED_LOCALES, type Locale } from "@/lib/types";

const LABELS: Record<Locale, string> = { en: "EN", ua: "UA" };
const NAMES: Record<Locale, string> = { en: "English", ua: "Українська" };

/**
 * Switches edition while keeping the reader on the same page (same story,
 * same topic). Two plain links; the current one is marked, not hidden.
 */
export function LanguageSwitcher({ lang, className }: { lang: Locale; className?: string }) {
  const pathname = usePathname() || "/";
  const s = strings(lang);

  function pathIn(target: Locale): string {
    const parts = pathname.split("/");
    if (parts[1] && (SUPPORTED_LOCALES as readonly string[]).includes(parts[1])) {
      parts[1] = target;
      return parts.join("/") || `/${target}`;
    }
    return `/${target}`;
  }

  return (
    <div role="group" aria-label={s.language_label} className={cn("flex items-center", className)}>
      {SUPPORTED_LOCALES.map((l) => {
        const active = l === lang;
        return (
          <Link
            key={l}
            href={pathIn(l)}
            hrefLang={HTML_LANG[l]}
            title={NAMES[l]}
            prefetch={false}
            aria-current={active ? "page" : undefined}
            className={cn(
              "inline-flex h-11 min-w-[2.75rem] items-center justify-center px-2 font-sans text-small font-semibold",
              "transition-colors duration-150",
              active ? "text-ink" : "text-ink-faint hover:text-ink",
            )}
          >
            <span className={cn(active && "underline decoration-signal decoration-2 underline-offset-[6px]")}>
              {LABELS[l]}
            </span>
          </Link>
        );
      })}
    </div>
  );
}
