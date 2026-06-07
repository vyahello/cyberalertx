import { ObfuscatedEmail } from "./ObfuscatedEmail";

/**
 * Site-wide footer.
 *
 * Low-emphasis, below the main content on every route. A small social row
 * (TikTok + spam-resistant email) sits above the copyright line. The
 * copyright string is identical in both locales (brand name + year), so no
 * i18n indirection.
 */
const TIKTOK_PATH =
  "M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z";

const socialLinkClass =
  "inline-flex items-center gap-1.5 text-text-tertiary transition-colors " +
  "hover:text-text-secondary focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-border-focus rounded-sm";

export function SiteFooter() {
  return (
    <footer
      role="contentinfo"
      className="border-t border-border-subtle mt-auto"
    >
      <div className="mx-auto max-w-6xl px-5 sm:px-8 py-6 text-center text-2xs text-text-tertiary">
        <div className="flex items-center justify-center gap-5 mb-3">
          <a
            href="https://tiktok.com/@vyahello"
            target="_blank"
            rel="noopener noreferrer me"
            className={socialLinkClass}
            aria-label="TikTok"
          >
            <svg
              viewBox="0 0 24 24"
              className="w-4 h-4"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d={TIKTOK_PATH} />
            </svg>
            <span>TikTok</span>
          </a>
          <ObfuscatedEmail className={socialLinkClass} />
        </div>
        © 2026 CyberAlertX. All Rights Reserved.
      </div>
    </footer>
  );
}
