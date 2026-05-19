import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "../globals.css";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { SUPPORTED_LOCALES, isLocale } from "@/lib/types";

/**
 * Type stack:
 *   - Inter as the single workhorse (body, headings, badges).
 *   - Space Grotesk for the brand wordmark only — its tight tracking and
 *     uppercase "X" pair with the Aperture mark in the header lockup.
 *     Loaded with weight 600 only to keep the second-font cost small.
 *   - JetBrains Mono for monospace contexts — CVE IDs inside titles via
 *     natural inheritance and any future code samples / fingerprints.
 *
 * `display: "swap"` keeps the first paint instant (system fallback) and
 * swaps the custom font in once it loads — matters on mobile data.
 */
const sans = Inter({
  subsets: ["latin", "cyrillic"],
  display: "swap",
  variable: "--font-sans",
  weight: ["400", "500", "600", "700"],
});

const display = Space_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
  weight: ["600"],
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "CyberAlertX — Cyber threats. Before they hit you.",
  description:
    "Today's cybersecurity threats in plain English. What happened, who it hits, and what to do — without the panic or the jargon.",
  applicationName: "CyberAlertX",
  authors: [{ name: "CyberAlertX" }],
  // Required by Next.js to convert relative OG / Twitter image URLs into
  // absolute ones for social-media crawlers (LinkedIn, Twitter, Facebook,
  // Slack unfurls all need absolute https URLs). In dev this falls back to
  // localhost; override with NEXT_PUBLIC_SITE_URL when deploying.
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000",
  ),
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
    description: "We see — and we surface what matters.",
    type: "website",
    siteName: "CyberAlertX",
    // PNG — every social-card crawler (Twitter, LinkedIn, Slack, Facebook,
    // Discord) prefers raster over SVG. Regenerate via the npm script:
    //   cd frontend && npm run brand:png
    images: [
      {
        url: "/brand/og-image.png",
        width: 1200,
        height: 630,
        alt: "CyberAlertX — We see and we surface what matters",
        type: "image/png",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "CyberAlertX",
    description: "We see — and we surface what matters.",
    images: ["/brand/og-image.png"],
  },
};

export const viewport: Viewport = {
  // Matches `--brand-bg` in globals.css. Used by mobile browsers for the
  // status-bar tint and the PWA splash background.
  themeColor: "#0E1116",
  width: "device-width",
  initialScale: 1,
  // Allow user zoom; never trap accessibility for visual control.
  maximumScale: 5,
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
      lang={locale}
      className={`${sans.variable} ${display.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen flex flex-col">
        <div className="flex-1">{children}</div>
        <SiteFooter />
      </body>
    </html>
  );
}
