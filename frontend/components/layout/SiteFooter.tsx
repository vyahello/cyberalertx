import Link from "next/link";
import { ObfuscatedEmail } from "./ObfuscatedEmail";
import { Wordmark } from "./Wordmark";
import { strings } from "@/lib/i18n";
import { TELEGRAM_CHANNELS } from "@/lib/site";
import { TOPIC_SLUGS } from "@/lib/topics";
import type { Locale } from "@/lib/types";

/**
 * The close: the one whole-field colour section on every page. Ground and
 * ink invert onto the brand cyan; the wordmark returns at full width.
 */
export function SiteFooter({ lang }: { lang: Locale }) {
  const s = strings(lang);
  const linkClass =
    "inline-flex min-h-[40px] items-center text-signal-ink underline decoration-signal-deep/50 " +
    "decoration-1 underline-offset-[4px] hover:decoration-signal-ink";

  return (
    <footer className="mt-section bg-signal text-signal-ink">
      <div className="page pt-14 pb-[max(1.5rem,env(safe-area-inset-bottom))]">
        <div className="axis gap-y-10">
          <p className="font-serif text-body text-signal-deep max-w-[34ch]">{s.footer_note}</p>
          <div className="on-axis grid grid-cols-2 gap-x-6 gap-y-8 font-sans text-[1rem] sm:grid-cols-4">
            <div>
              <h2 className="font-semibold mb-2">{s.footer_sections}</h2>
              <ul>
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
              <h2 className="font-semibold mb-2">{s.footer_editions}</h2>
              <ul>
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
              <h2 className="font-semibold mb-2">{s.footer_follow}</h2>
              <ul>
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
            <div>
              <h2 className="font-semibold mb-2">{s.footer_contact}</h2>
              <ObfuscatedEmail className={`${linkClass} gap-1.5`} />
            </div>
          </div>
        </div>

        <div className="mt-16 sm:mt-24 [container-type:inline-size]" aria-hidden>
          <Wordmark className="text-[15.2cqw] text-signal-ink" accentColor="#071318" />
        </div>
        <p className="mt-4 font-sans text-small text-signal-deep">{s.footer_rights}</p>
      </div>
    </footer>
  );
}
