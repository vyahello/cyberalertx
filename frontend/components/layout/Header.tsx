import Link from "next/link";
import { Shield } from "lucide-react";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";
import { LivePulse } from "../hero/LivePulse";
import { LanguageSwitcher } from "./LanguageSwitcher";

interface Props {
  lang: Locale;
}

/**
 * Sticky top bar. Server component — only `LanguageSwitcher` is a client
 * island (it reads the current URL to compute its links).
 */
export function Header({ lang }: Props) {
  const s = strings(lang);
  return (
    <header
      className="sticky top-0 z-30
                 bg-bg-base/85 backdrop-blur supports-[backdrop-filter]:bg-bg-base/65
                 border-b border-border-subtle"
    >
      <div className="mx-auto max-w-6xl px-5 sm:px-8 h-14 flex items-center justify-between gap-4">
        <Link href={`/${lang}`} className="inline-flex items-center gap-2 text-text-primary">
          <span className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-accent-soft">
            <Shield className="w-4 h-4 text-accent" strokeWidth={2.5} />
          </span>
          <span className="font-semibold tracking-tight">{s.brand}</span>
          <span className="hidden sm:inline-flex items-center gap-1.5 ml-2 text-xs text-text-secondary border-l border-border-subtle pl-2">
            <LivePulse size="sm" />
            {s.tagline_short}
          </span>
        </Link>

        <LanguageSwitcher lang={lang} />
      </div>
    </header>
  );
}
