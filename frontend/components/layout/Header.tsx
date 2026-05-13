import Link from "next/link";
import { BrandGlyph } from "../brand/BrandGlyph";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";
import { LivePulse } from "../hero/LivePulse";
import { FeedFreshness } from "./FeedFreshness";
import { LanguageSwitcher } from "./LanguageSwitcher";

interface Props {
  lang: Locale;
}

/**
 * Sticky top bar — server component. The brand lockup is glyph + wordmark
 * (wordmark drops below `sm` to free vertical screen real estate on phones).
 *
 * Layout invariants:
 *   - Lockup height = 24px (glyph), wordmark optical-centered against the
 *     dot via Inter's x-height baseline.
 *   - Sticky with backdrop-blur — bg ramps from transparent at top to
 *     `bg-base/85` on scroll. Single 1px `border-subtle` divider — no
 *     dropshadow chrome.
 *   - Single accent color (azure) — only the glyph wears it. Wordmark
 *     stays in `text-primary` so the eye reads "CyberAlertX" as content,
 *     not as a logo.
 */
export function Header({ lang }: Props) {
  const s = strings(lang);
  return (
    <header
      className="sticky top-0 z-30
                 bg-bg-base/85 backdrop-blur supports-[backdrop-filter]:bg-bg-base/65
                 border-b border-border-subtle"
    >
      <div className="mx-auto max-w-6xl px-5 sm:px-8 h-14 flex items-center justify-between gap-4">
        <Link
          href={`/${lang}`}
          aria-label={`${s.brand} — home`}
          className="inline-flex items-center gap-2.5 text-accent
                     hover:text-accent-hover transition-colors duration-200"
        >
          <BrandGlyph size={24} />
          <span className="font-semibold tracking-tight text-text-primary text-base">
            {s.brand}
          </span>
          {/* Live-pulse + tagline sit on the optical baseline of the
              wordmark. Hidden on phones — the lockup carries enough on its
              own at narrow widths. */}
          <span className="hidden sm:inline-flex items-center gap-1.5 ml-3 text-xs text-text-secondary border-l border-border-subtle pl-3">
            <LivePulse size="sm" />
            {s.tagline_short}
          </span>
        </Link>

        <div className="flex items-center gap-4">
          {/* "Feed updated X min ago" / "Quiet day" indicator. Hidden on
              mobile where header space is precious. */}
          <FeedFreshness lang={lang} />
          <LanguageSwitcher lang={lang} />
        </div>
      </div>
    </header>
  );
}
