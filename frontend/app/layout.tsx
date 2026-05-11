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
    "Real-time cybersecurity awareness for normal users, developers, and IT professionals. Threat intelligence — ranked for impact, written for humans.",
  applicationName: "CyberAlertX",
  authors: [{ name: "CyberAlertX" }],
  openGraph: {
    title: "CyberAlertX",
    description: "Cyber threats. Before they hit you.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#0A0C10",
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
