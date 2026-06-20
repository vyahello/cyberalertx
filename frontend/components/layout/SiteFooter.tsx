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
      <div className="mx-auto max-w-6xl px-5 sm:px-8 py-6 text-center text-2xs text-text-tertiary">
        <div className="flex items-center justify-center gap-5 mb-3">
          <ObfuscatedEmail className={socialLinkClass} />
        </div>
        © 2026 CyberAlertX. All Rights Reserved.
      </div>
    </footer>
  );
}
