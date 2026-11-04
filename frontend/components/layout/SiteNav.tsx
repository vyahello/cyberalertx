"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import { TOPIC_SLUGS } from "@/lib/topics";
import type { Locale } from "@/lib/types";

/** Section links. Marks the current section for sighted and AT users. */
export function SiteNav({
  lang,
  className,
  itemClassName,
}: {
  lang: Locale;
  className?: string;
  itemClassName?: string;
}) {
  const s = strings(lang);
  const pathname = usePathname() || "";
  const items = [
    { href: `/${lang}`, label: s.nav_latest, current: pathname === `/${lang}` },
    ...TOPIC_SLUGS.map((slug) => ({
      href: `/${lang}/topic/${slug}`,
      label: s.topic[slug].nav,
      current: pathname.startsWith(`/${lang}/topic/${slug}`),
    })),
  ];
  return (
    <ul className={className}>
      {items.map((item) => (
        <li key={item.href}>
          <Link
            href={item.href}
            prefetch={false}
            aria-current={item.current ? "page" : undefined}
            className={cn(
              "inline-flex items-center font-sans font-semibold transition-colors duration-150",
              item.current ? "text-ink" : "text-ink-muted hover:text-ink",
              itemClassName,
            )}
          >
            <span
              className={cn(
                item.current && "underline decoration-signal decoration-2 underline-offset-[6px]",
              )}
            >
              {item.label}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
