import Link from "next/link";
import { ObfuscatedEmail } from "./ObfuscatedEmail";
import { Wordmark } from "./Wordmark";
import { strings } from "@/lib/i18n";
import { TELEGRAM_CHANNELS } from "@/lib/site";
import { TOPIC_SLUGS } from "@/lib/topics";
import type { Locale } from "@/lib/types";

/**
 * The close of every page: the one whole-field colour section, in a deep,
 * low-saturation teal (`field`) rather than the full brand cyan, which took
 * over the phone screen. Cyan stays as an accent: the link underlines and
 * the glyph's ping.
 */
export function SiteFooter({ lang }: { lang: Locale }) {
  const s = strings(lang);
  const linkClass =
    "inline-flex min-h-[44px] items-center text-field-ink underline decoration-signal/50 decoration-1 " +
    "underline-offset-[4px] transition-colors duration-150 hover:text-signal-hover hover:decoration-signal-hover";
  const headClass = "font-sans text-small font-semibold text-field-faint";

  return (
    <footer className="mt-section bg-field text-field-ink">
      <div className="page pt-10 sm:pt-14 pb-[max(1.5rem,env(safe-area-inset-bottom))]">
        <div className="axis gap-y-8">
          <div className="flex flex-col gap-4">
            <Link
              href={`/${lang}`}
              prefetch={false}
              aria-label={`${s.brand} — ${s.nav_latest}`}
              data-testid="footer-logo"
              className="inline-flex min-h-[44px] items-center self-start text-[1.5rem] sm:text-[1.75rem] text-field-ink"
            >
              <Wordmark accentColor="#22D3EE" />
            </Link>
            <p className="font-serif text-[1rem] leading-relaxed max-w-[38ch] text-field-muted">{s.footer_note}</p>
          </div>
          <div className="on-axis grid grid-cols-2 gap-x-6 gap-y-7 font-sans text-[1rem] sm:grid-cols-3 xl:grid-cols-4">
            <div className="col-span-2 sm:col-span-1">
              <h2 className={headClass}>{s.footer_sections}</h2>
              <ul className="mt-1">
                <li>
                  <Link href={`/${lang}`} prefetch={false} className={linkClass}>
                    {s.nav_latest}
                  </Link>
                </li>
                {TOPIC_SLUGS.map((slug) => (
                  <li key={slug}>
                    <Link href={`/${lang}/topic/${slug}`} prefetch={false} className={linkClass}>
                      {s.topic[slug].name}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h2 className={headClass}>{s.footer_editions}</h2>
              <ul className="mt-1">
                <li>
                  <Link href="/en" prefetch={false} hrefLang="en" className={linkClass}>
                    English
                  </Link>
                </li>
                <li>
                  <Link href="/ua" prefetch={false} hrefLang="uk" className={linkClass}>
                    Українська
                  </Link>
                </li>
              </ul>
            </div>
            <div>
              <h2 className={headClass}>{s.footer_follow}</h2>
              <ul className="mt-1">
                <li>
                  <a
                    href={TELEGRAM_CHANNELS[lang]}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={linkClass}
                  >
                    {s.subscribe_telegram}
                  </a>
                </li>
                <li>
                  <a href={`/${lang}/feed.xml`} className={linkClass}>
                    {s.subscribe_rss}
                  </a>
                </li>
              </ul>
            </div>
            <div className="col-span-2 sm:col-span-3 xl:col-span-1">
              <h2 className={headClass}>{s.footer_contact}</h2>
              <ObfuscatedEmail className={`${linkClass} mt-1 gap-1.5`} />
            </div>
          </div>
        </div>
        <p className="mt-10 font-sans text-small text-field-faint">{s.footer_rights}</p>
      </div>
    </footer>
  );
}
