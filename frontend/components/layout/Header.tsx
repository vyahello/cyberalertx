import Link from "next/link";
import { strings } from "@/lib/i18n";
import { TELEGRAM_CHANNELS } from "@/lib/site";
import type { Locale } from "@/lib/types";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { MobileMenu } from "./MobileMenu";
import { SiteNav } from "./SiteNav";
import { Wordmark } from "./Wordmark";

/**
 * A plain bar: wordmark at the left margin, section links starting on the
 * axis, language and Telegram at the right margin. Solid ground, no blur,
 * no rule; the content scrolls under it.
 */
export function Header({ lang }: { lang: Locale }) {
  const s = strings(lang);
  return (
    <header className="sticky top-0 z-30 bg-ground pt-[env(safe-area-inset-top)]">
      <div className="page relative axis h-16 items-center">
        <div className="flex items-center justify-between">
          <Link
            href={`/${lang}`}
            aria-label={`${s.brand} — ${s.nav_latest}`}
            className="inline-flex items-center text-ink text-[1.25rem] hover:text-ink"
          >
            <Wordmark glyphSize={20} />
          </Link>
          <div className="flex items-center gap-1 lg:hidden">
            <LanguageSwitcher lang={lang} />
            <MobileMenu lang={lang} />
          </div>
        </div>
        <nav aria-label={s.nav_label} className="on-axis hidden lg:flex items-center justify-between gap-6">
          <SiteNav
            lang={lang}
            className="flex items-center gap-x-6 xl:gap-x-8"
            itemClassName="h-11 text-[1rem] whitespace-nowrap"
          />
          <div className="flex items-center gap-2">
            <LanguageSwitcher lang={lang} />
            <a
              href={TELEGRAM_CHANNELS[lang]}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-11 items-center px-2 font-sans text-[1rem] font-semibold text-ink-muted hover:text-ink"
            >
              {s.telegram}
            </a>
          </div>
        </nav>
      </div>
    </header>
  );
}
