import { Rss, Send } from "lucide-react";
import { ObfuscatedEmail } from "./ObfuscatedEmail";
import { strings } from "@/lib/i18n";
import { TELEGRAM_CHANNELS } from "@/lib/site";
import type { Locale } from "@/lib/types";

/**
 * Site-wide footer.
 *
 * Low-emphasis, below the main content on every route. Carries the two
 * subscription channels, because until now the product had no return path
 * at all: a visitor read one brief and left with no way to hear about the
 * next one. The Telegram channel and the RSS feed both already existed —
 * they were simply never linked from the site.
 *
 * Both are deliberately low-key rather than a modal or a sticky bar. The
 * audience is people checking whether something affects them; interrupting
 * that to ask for a subscription is how you lose the reading.
 */
const socialLinkClass =
  "inline-flex items-center gap-1.5 min-h-[40px] sm:min-h-0 px-2 -mx-2 " +
  "text-text-tertiary transition-colors rounded-md " +
  "hover:text-text-secondary active:text-text-secondary";

export function SiteFooter({ lang }: { lang: Locale }) {
  const s = strings(lang);
  const telegram = TELEGRAM_CHANNELS[lang];

  return (
    <footer
      role="contentinfo"
      className="border-t border-border-subtle mt-auto"
    >
      {/* Bottom padding clears the iOS home indicator (safe-area inset)
          when the page is scrolled to the very end. */}
      <div className="mx-auto max-w-6xl px-5 sm:px-8 pt-8 pb-[calc(1.5rem+env(safe-area-inset-bottom))] text-center text-2xs text-text-tertiary">
        <p className="text-xs text-text-secondary mb-3">{s.subscribe_heading}</p>
        <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1 mb-4">
          {telegram && (
            <a
              href={telegram}
              target="_blank"
              rel="noopener noreferrer"
              className={socialLinkClass}
            >
              <Send className="w-3.5 h-3.5" aria-hidden />
              {s.subscribe_telegram}
            </a>
          )}
          <a href={`/${lang}/feed.xml`} className={socialLinkClass}>
            <Rss className="w-3.5 h-3.5" aria-hidden />
            {s.subscribe_rss}
          </a>
          <ObfuscatedEmail className={socialLinkClass} />
        </div>
        © 2026 CyberAlertX. All Rights Reserved.
      </div>
    </footer>
  );
}
