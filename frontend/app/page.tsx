import { redirect } from "next/navigation";
import { DEFAULT_LOCALE } from "@/lib/types";

/**
 * Root → default locale. Keep this as the *only* place that decides what
 * the visitor sees when no locale is in the URL — future Accept-Language
 * sniffing or middleware-based redirects land here.
 */
export default function RootPage() {
  redirect(`/${DEFAULT_LOCALE}`);
}
