import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Security (docs/release/SECURITY_REMEDIATION.md): the app never uses
  // next/image — cards and media are pre-rendered variants served by their
  // own routes — so the public /_next/image optimizer is switched off and its
  // image decoders are no longer an unauthenticated attack surface.
  images: { unoptimized: true },
  // No experimental features required for the MVP — the surface is fully
  // server-rendered with a few "use client" islands for filters and locale.

  // The product previously used `uk` (BCP-47 language code) for Ukrainian
  // routes; we've moved to `ua` (ISO country code) for consistency with
  // how the audience refers to it. Permanent redirects preserve every
  // existing bookmark, share link, and inbound search-engine signal.
  async redirects() {
    return [
      { source: "/uk", destination: "/ua", permanent: true },
      { source: "/uk/:path*", destination: "/ua/:path*", permanent: true },
    ];
  },
};

export default nextConfig;
