import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";
import { JetBrains_Mono, Literata, Fira_Sans_Condensed, Space_Grotesk } from "next/font/google";
import "../globals.css";
import { Header } from "@/components/layout/Header";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { UmamiAnalytics } from "@/components/analytics/UmamiAnalytics";
import { SiteJsonLd } from "@/components/seo/JsonLd";
import { strings } from "@/lib/i18n";
import { SITE_URL, localeAlternates } from "@/lib/site";
import { HTML_LANG, SUPPORTED_LOCALES, isLocale } from "@/lib/types";

/**
 * Type system (docs/design/DESIGN_SYSTEM.md):
 *   - Literata: the reading face. Headlines, standfirsts, article text.
 *     Variable with an optical-size axis, so one family is a crisp display
 *     face at 88px and a sturdy text face at 17px. Latin + Cyrillic.
 *   - Fira Sans Condensed: field marks, navigation, controls. Narrow enough
 *     to keep a story's metadata on one line; standard (Russian/Ukrainian)
 *     Cyrillic forms. Sofia Sans was dropped: its default Cyrillic draws
 *     Bulgarian shapes (т as "m", д as "g"), wrong for Ukrainian readers.
 *   - Space Grotesk 600: the logotype only ("cyberalert"). Latin, one weight.
 *   - JetBrains Mono: code, commands and indicators only. Not preloaded;
 *     most pages never show code.
 */
const serif = Literata({
  subsets: ["latin", "latin-ext", "cyrillic"],
  display: "swap",
  variable: "--font-serif",
  axes: ["opsz"],
});

const sans = Fira_Sans_Condensed({
  subsets: ["latin", "latin-ext", "cyrillic"],
  display: "swap",
  variable: "--font-sans",
  weight: ["400", "500", "600"],
});

const logo = Space_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-logo",
  weight: ["600"],
});

const mono = JetBrains_Mono({
  subsets: ["latin", "cyrillic"],
  display: "swap",
  variable: "--font-mono",
  weight: ["400"],
  preload: false,
});

// Per-locale Open Graph card. The image, OG locale tag, and social
// description all switch by locale so a shared UA link renders a Ukrainian
// preview (image + copy) instead of the English default. Regenerate the PNGs
// from the SVG masters with `npm run brand:png` (og-mark.svg → og-image.png,
// og-mark-ua.svg → og-image-ua.png).
const OG_BY_LOCALE: Record<
  string,
  { image: string; ogLocale: string; description: string; alt: string }
> = {
  en: {
    image: "/brand/og-image.png",
    ogLocale: "en_US",
    description: "Which vulnerabilities are being exploited, which breaches matter and what to do about them.",
    alt: "CyberAlertX — cyber threat brief",
  },
  ua: {
    image: "/brand/og-image-ua.png",
    ogLocale: "uk_UA",
    description: "Які вразливості вже використовують в атаках, які витоки важливі і що з цим робити.",
    alt: "CyberAlertX — зведення кіберзагроз",
  },
};

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const og = OG_BY_LOCALE[locale] ?? OG_BY_LOCALE.en;
  const meta = strings(isLocale(locale) ? locale : "en");
  return {
  title: meta.meta_title,
  description: meta.meta_description,
  applicationName: "CyberAlertX",
  authors: [{ name: "CyberAlertX" }],
  // Required by Next.js to convert relative OG / Twitter image URLs into
  // absolute ones for social-media crawlers (LinkedIn, Twitter, Facebook,
  // Slack unfurls all need absolute https URLs). In dev this falls back to
  // localhost; override with NEXT_PUBLIC_SITE_URL when deploying.
  metadataBase: new URL(SITE_URL),
  // Canonical + hreflang. Without the canonical, every query-string variant
  // of the feed competes with itself in the index; without the language
  // alternates, the EN and UA pages look like duplicate content instead of
  // translations, and neither gets served to the right audience.
  alternates: {
    canonical: `${SITE_URL}/${locale}`,
    ...localeAlternates(),
    types: {
      // Feed-reader autodiscovery: browsers and readers look for this to
      // offer "subscribe" without the user hunting for a URL.
      "application/rss+xml": [
        { url: `${SITE_URL}/${locale}/feed.xml`, title: `CyberAlertX (${locale.toUpperCase()})` },
      ],
    },
  },
  // Brand identity: Aperture glyph (radar rings + cyan alert ping).
  // currentColor-driven SVGs power the browser-tab favicon; Apple touch
  // icon is a navy-on-cyan variant. PNG fallbacks ship for every spot a
  // platform might reject SVG: Twitter / LinkedIn / Slack unfurls insist
  // on PNG, and iOS < 12 doesn't honor SVG apple-touch-icons. The
  // horizontal lockup lives in /brand/logo.svg for embeds.
  icons: {
    icon: [
      { url: "/brand/icon-16.svg", type: "image/svg+xml", sizes: "16x16" },
      { url: "/brand/icon-32.svg", type: "image/svg+xml", sizes: "32x32" },
      // 32×32 PNG fallback for any browser that can't render the SVG
      // favicon (rare on modern desktop, common on older mobile UAs).
      { url: "/brand/favicon-32.png", type: "image/png", sizes: "32x32" },
      { url: "/brand/favicon.svg", type: "image/svg+xml" },
    ],
    apple: [
      // PNG first — iOS rendering of SVG apple-touch-icons is uneven
      // across versions; the 180×180 PNG is always honored.
      { url: "/brand/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
      { url: "/brand/icon-180.svg", sizes: "180x180", type: "image/svg+xml" },
    ],
    shortcut: "/brand/favicon.svg",
  },
  openGraph: {
    title: "CyberAlertX",
    description: og.description,
    type: "website",
    siteName: "CyberAlertX",
    locale: og.ogLocale,
    // PNG — every social-card crawler (Twitter, LinkedIn, Slack, Facebook,
    // Discord) prefers raster over SVG. Regenerate via the npm script:
    //   cd frontend && npm run brand:png
    images: [
      {
        url: og.image,
        width: 1200,
        height: 630,
        alt: og.alt,
        type: "image/png",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "CyberAlertX",
    description: og.description,
    images: [og.image],
  },
  };
}

export const viewport: Viewport = {
  // Matches `--brand-bg` in globals.css. Used by mobile browsers for the
  // status-bar tint and the PWA splash background.
  themeColor: "#0e1116",
  width: "device-width",
  initialScale: 1,
  // Allow user zoom; never trap accessibility for visual control.
  maximumScale: 5,
  // Draw edge-to-edge on notched phones; safe-area insets in globals.css
  // (body gutters, header top pad, FAB / drawer bottom pads) keep content
  // clear of the sensor housing and home indicator.
  viewportFit: "cover",
};

/** Pre-render one shell per supported locale at build time. */
export function generateStaticParams() {
  return SUPPORTED_LOCALES.map((locale) => ({ locale }));
}

export default async function LocaleRootLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  // Defensive: if the URL holds an unknown locale, render nothing at this
  // layer and let Next.js' notFound boundary take over. Otherwise we'd
  // emit `<html lang="xx">` for any garbage segment, defeating the point
  // of moving lang into this layout.
  if (!isLocale(locale)) notFound();

  return (
    <html
      lang={HTML_LANG[locale]}
      className={`${serif.variable} ${sans.variable} ${logo.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen flex flex-col">
        {/* Site identity for search engines and AI assistants. Server-
            rendered <script type="application/ld+json">, no client cost. */}
        <SiteJsonLd lang={locale} />
        {/* Keyboard-user escape hatch — first tab stop on every page.
            Visually hidden until focused, then surfaces as a floating
            accent chip above the sticky header. */}
        <a href="#main-content" className="skip-link">
          {strings(locale).skip_to_content}
        </a>
        {/* Header lives in the LAYOUT, not in each page: it persists
            across route transitions (feed → detail), so navigation swaps
            only the content region while the brand bar stays put — and
            loading.tsx skeletons render beneath a stable header instead
            of a blank viewport. */}
        <Header lang={locale} />
        <div id="main-content" className="flex-1">
          {children}
        </div>
        <SiteFooter lang={locale} />
        <UmamiAnalytics />
      </body>
    </html>
  );
}
