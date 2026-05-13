import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
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
