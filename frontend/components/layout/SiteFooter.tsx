import { ObfuscatedEmail } from "./ObfuscatedEmail";

/**
 * Site-wide footer.
 *
 * Low-emphasis, below the main content on every route. A small social row
 * (spam-resistant email) sits above the copyright line. The copyright string
 * is identical in both locales (brand name + year), so no i18n indirection.
 */
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
      {/* Bottom padding clears the iOS home indicator (safe-area inset)
          when the page is scrolled to the very end. */}
      <div className="mx-auto max-w-6xl px-5 sm:px-8 pt-6 pb-[calc(1.5rem+env(safe-area-inset-bottom))] text-center text-2xs text-text-tertiary">
        <div className="flex items-center justify-center gap-5 mb-3">
          <ObfuscatedEmail className={socialLinkClass} />
        </div>
        © 2026 CyberAlertX. All Rights Reserved.
      </div>
    </footer>
  );
}
