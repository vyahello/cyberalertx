import Script from "next/script";

/**
 * Umami Cloud analytics — privacy-friendly, cookieless page-view tracking.
 *
 * Renders nothing unless `NEXT_PUBLIC_UMAMI_WEBSITE_ID` is set, so the site
 * builds and runs fine before analytics is configured. To activate:
 *
 *   1. Create the site at https://cloud.umami.is (domain: cyberalertx.com)
 *   2. Copy its "Website ID"
 *   3. Set NEXT_PUBLIC_UMAMI_WEBSITE_ID in frontend/.env.production
 *   4. Rebuild (`npm run build`) + restart the frontend service
 *
 * NEXT_PUBLIC_* vars are inlined at BUILD time, so a rebuild is required —
 * editing the env on a running server alone does nothing.
 *
 * `NEXT_PUBLIC_UMAMI_SRC` is optional; override it only if you self-host the
 * Umami tracker on a custom domain. Defaults to Umami Cloud.
 */
export function UmamiAnalytics() {
  const websiteId = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID;
  if (!websiteId) return null;

  const src =
    process.env.NEXT_PUBLIC_UMAMI_SRC ?? "https://cloud.umami.is/script.js";

  return (
    <Script
      src={src}
      data-website-id={websiteId}
      strategy="afterInteractive"
      defer
    />
  );
}
