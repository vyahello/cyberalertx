import { BrandGlyph } from "../brand/BrandGlyph";
import { cn } from "@/lib/cn";

/**
 * The brand lockup: the Aperture glyph followed by lowercase "cyberalertx"
 * in the logotype face (the same order as /brand/logo.svg). Space Grotesk is
 * loaded for the logotype only; it is part of the logo, not of the type
 * system. The textual brand name stays "CyberAlertX" everywhere else.
 *
 * One lockup everywhere (header, open menu, footer). The glyph is sized in
 * em, so the mark scales as one piece with the font size of its parent.
 * Decorative: the surrounding link or landmark carries the accessible name.
 */
export function Wordmark({
  className,
  accentColor,
}: {
  className?: string;
  accentColor?: string;
}) {
  return (
    <span
      data-wordmark=""
      className={cn("inline-flex items-center gap-[0.32em] whitespace-nowrap", className)}
      aria-hidden
    >
      <BrandGlyph
        accentColor={accentColor}
        className="h-[1.05em] w-[1.05em] -translate-y-[0.02em]"
      />
      <span
        data-wordmark-text=""
        className="font-logo font-semibold tracking-[-0.03em] leading-none -translate-y-[0.04em]"
      >
        cyberalertx
      </span>
    </span>
  );
}
