/**
 * Site-wide footer.
 *
 * One line, low-emphasis. Lives below the main content on every route.
 * The copyright string is identical in both locales (brand name + year),
 * so no i18n indirection.
 */
export function SiteFooter() {
  return (
    <footer
      role="contentinfo"
      className="border-t border-border-subtle mt-auto"
    >
      <div className="mx-auto max-w-6xl px-5 sm:px-8 py-6 text-center text-2xs text-text-tertiary">
        © 2026 CyberAlertX. All Rights Reserved.
      </div>
    </footer>
  );
}
