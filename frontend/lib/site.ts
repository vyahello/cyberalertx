/**
 * Canonical site identity.
 *
 * Every absolute URL the product emits — sitemap entries, RSS links,
 * JSON-LD `@id`s, canonical tags, hreflang alternates — has to agree on one
 * origin, or search engines treat the variants as separate pages and split
 * the ranking signal between them.
 *
 * `NEXT_PUBLIC_SITE_URL` is the override for staging and preview builds.
 * The production default is hard-coded rather than left undefined so that a
 * deploy which forgets the env var still emits correct absolute URLs instead
 * of silently publishing `http://localhost:3000` links to Google.
 */
import type { Locale } from "./types";

export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL ?? "https://cyberalertx.com"
).replace(/\/$/, "");

export const SITE_NAME = "CyberAlertX";

/**
 * Telegram channels, per locale.
 *
 * These MUST match `CYBERALERTX_TELEGRAM_CHANNEL_EN` / `_UA` in the
 * backend's environment — that's where the publisher actually sends. They
 * are duplicated here rather than read from the API because the footer is a
 * static server component and a whole endpoint for two constants isn't
 * worth it; the tradeoff is that they have to be changed in both places.
 *
 * Both locales use the `_xx` suffix. There is no bare `@cyberalertx`
 * channel — linking to one sent readers to Telegram's "username not found"
 * dialog.
 */
export const TELEGRAM_CHANNELS: Record<Locale, string> = {
  en: "https://t.me/cyberalertx_en",
  ua: "https://t.me/cyberalertx_ua",
};

/** Absolute URL for a path that already starts with "/". */
export function absoluteUrl(path: string): string {
  return `${SITE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

/** Canonical detail-page URL for one post in one locale. */
export function postUrl(locale: Locale, id: string): string {
  return absoluteUrl(`/${locale}/threat/${id}`);
}

/**
 * `alternates` block shared by every page's metadata.
 *
 * Two things happen here and both matter for how the site is indexed:
 *   * `canonical` names the single authoritative URL for this page, so query
 *     strings and trailing-slash variants don't fragment ranking.
 *   * `languages` declares the EN/UA pair as translations of one another.
 *     `x-default` points at English, which is what a search engine serves
 *     when it can't infer the visitor's language.
 *
 * The BCP-47 tag for Ukrainian is `uk`, while our route segment is `ua`.
 * Conflating them is the usual way hreflang silently stops working, so the
 * mapping is explicit here.
 */
export function localeAlternates(pathAfterLocale = "") {
  const suffix = pathAfterLocale.replace(/^\/?/, (m) => (m ? m : ""));
  const path = (locale: Locale) =>
    absoluteUrl(`/${locale}${suffix ? `/${suffix.replace(/^\//, "")}` : ""}`);
  return {
    languages: {
      "en-US": path("en"),
      uk: path("ua"),
      "x-default": path("en"),
    },
  };
}
