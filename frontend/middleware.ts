import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { DEFAULT_LOCALE } from "@/lib/types";

/**
 * Edge redirect: bare "/" → "/${DEFAULT_LOCALE}". Runs before the App
 * Router resolves a page, so the visitor never sees a flash of the root
 * route. Replaces the old `app/page.tsx` which did the same redirect at
 * render-time; moving it into middleware lets us delete the root
 * `app/layout.tsx` and have `app/[locale]/layout.tsx` be the only root
 * layout, which is what allows `<html lang={locale}>` to be dynamic.
 *
 * Scope is intentionally narrow (matcher: "/") so static assets, the
 * /healthz endpoint, the [locale] routes, and the /uk → /ua redirect
 * configured in next.config.ts all pass through untouched.
 */
export function middleware(req: NextRequest) {
  return NextResponse.redirect(new URL(`/${DEFAULT_LOCALE}`, req.url));
}

export const config = {
  matcher: ["/"],
};
