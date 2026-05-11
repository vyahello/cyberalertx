import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // No experimental features required for the MVP — the surface is fully
  // server-rendered with a few "use client" islands for filters and locale.
};

export default nextConfig;
