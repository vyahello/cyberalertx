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
 * Sticky top bar — server component. The brand lockup is "cyberalert" set
 * in Space Grotesk + the Aperture glyph sitting in the X position, so the
 * brand reads as one continuous word with the radar mark as its terminal
 * letter — exactly the way the Aperture direction was designed.
 *
 * Layout invariants:
 *   - Lockup height = 24px (glyph), wordmark baseline-aligned against the
 *     glyph's center via Space Grotesk's x-height.
 *   - Sticky with backdrop-blur — bg ramps from transparent at top to
 *     `bg-base/85` on scroll. Single 1px `border-subtle` divider — no
 *     dropshadow chrome.
 *   - Aria-label still says "CyberAlertX — home" so screen readers and
 *     site search hear the full brand string even though the visible
 *     text is "cyberalert" + a graphic glyph.
 *   - Only the glyph's alert ping wears the cyan accent. Wordmark stays
 *     in `text-primary` so the eye reads "cyberalert" as content, not as
 *     a logo.
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
          className="group inline-flex items-baseline gap-1.5 text-text-primary
                     hover:text-text-primary transition-colors duration-200"
        >
          {/* "cyberalert" in the brand display face. The wordmark inherits
              text-primary so it reads as the page title, not a colored badge.
              `font-display` is wired in tailwind.config.ts → Space Grotesk
              with Inter fallback. */}
          <span
            className="font-display font-semibold tracking-[-0.025em] text-[1.05rem] sm:text-base leading-none"
            aria-hidden
          >
            cyberalert
          </span>
          {/* Glyph in the X position — sized to match the cap-height of the
              wordmark so the lockup reads as one continuous string. The
              container uses text-text-secondary as currentColor (so the
              rings feel like part of the wordmark chrome), while the ping
              inside the SVG stays cyan as the only bright signal. The
              glyph rises slightly to optically center against the lowercase
              baseline. */}
          <span
            className="text-text-secondary group-hover:text-text-primary
                       transition-colors duration-200 -translate-y-[1px]"
            aria-hidden
          >
            <BrandGlyph size={20} />
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
