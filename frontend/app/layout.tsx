import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

/**
 * Type stack:
 *   - Inter as the single workhorse (body, headings, badges).
 *   - JetBrains Mono for monospace contexts — only used today for CVE IDs
 *     inside titles via natural inheritance, but registered so future
 *     code samples / fingerprints render correctly.
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
  // Brand identity: filtered-pulse glyph, currentColor-driven SVGs for the
  // browser-tab favicon; Apple touch icon uses a brand-colored variant on
  // a graphite background. The horizontal lockup lives in /brand/logo.svg
  // for embeds (docs, social, partner pages).
  icons: {
    icon: [
      { url: "/brand/icon-16.svg", type: "image/svg+xml", sizes: "16x16" },
      { url: "/brand/icon-32.svg", type: "image/svg+xml", sizes: "32x32" },
      { url: "/brand/favicon.svg", type: "image/svg+xml" },
    ],
    apple: [
      { url: "/brand/icon-180.svg", sizes: "180x180", type: "image/svg+xml" },
    ],
    shortcut: "/brand/favicon.svg",
  },
  openGraph: {
    title: "CyberAlertX",
    description: "Cybersecurity intel — calm, filtered, scannable.",
    type: "website",
    siteName: "CyberAlertX",
    images: [
      {
        url: "/brand/og-mark.svg",
        width: 1200,
        height: 630,
        alt: "CyberAlertX — Cybersecurity intel, calm and filtered",
        type: "image/svg+xml",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "CyberAlertX",
    description: "Cybersecurity intel — calm, filtered, scannable.",
    images: ["/brand/og-mark.svg"],
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

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${sans.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
