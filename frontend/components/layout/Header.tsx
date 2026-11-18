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
 *
 * Below `lg`: wordmark left; language, then the menu button at the far
 * right. Every control is a 44 px target; the row fits at 320 px.
 */
export function Header({ lang }: { lang: Locale }) {
  const s = strings(lang);
  return (
    <header className="sticky top-0 z-30 bg-ground pt-[env(safe-area-inset-top)]">
      <div className="page relative axis h-16 items-center">
        <div className="flex min-w-0 items-center justify-between gap-2">
          <Link
            href={`/${lang}`}
            aria-label={`${s.brand} — ${s.nav_latest}`}
            data-testid="header-logo"
            className="inline-flex h-11 min-w-0 shrink items-center text-ink text-[1.125rem] min-[360px]:text-[1.25rem] lg:text-[1.375rem] hover:text-ink"
          >
            <Wordmark />
          </Link>
          <div data-testid="header-controls" className="flex shrink-0 items-center gap-1 lg:hidden">
            <LanguageSwitcher lang={lang} />
            <MobileMenu lang={lang} />
          </div>
        </div>
        <nav aria-label={s.nav_label} className="on-axis hidden lg:flex items-center justify-between gap-6">
          <SiteNav
            lang={lang}
            className="flex items-center gap-x-4 xl:gap-x-8"
            itemClassName="h-11 text-[1rem] whitespace-nowrap"
          />
          <div className="flex items-center gap-2">
            <LanguageSwitcher lang={lang} />
            <a
              href={TELEGRAM_CHANNELS[lang]}
              target="_blank"
              rel="noopener noreferrer"
              className="hidden xl:inline-flex h-11 items-center px-2 font-sans text-[1rem] font-semibold text-ink-muted hover:text-ink"
            >
              {/* Between lg and xl the bar has no room for it (it overflowed at
                  1024 px); the menu and the footer still link the channel. */}
              {s.telegram}
            </a>
          </div>
        </nav>
      </div>
    </header>
  );
}
