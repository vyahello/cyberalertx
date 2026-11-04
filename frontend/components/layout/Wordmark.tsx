import { BrandGlyph } from "../brand/BrandGlyph";
import { cn } from "@/lib/cn";

/**
 * The brand lockup: lowercase "cyberalert" in the logotype face with the
 * Aperture glyph standing in for the X. Space Grotesk is loaded for these
 * ten letters only; it is part of the logo, not of the type system.
 *
 * `glyphSize` in px for the header; omit it to size the glyph in em so the
 * lockup scales as one piece (footer).
 */
export function Wordmark({
  className,
  glyphSize,
  accentColor,
}: {
  className?: string;
  glyphSize?: number;
  accentColor?: string;
}) {
  return (
    <span className={cn("inline-flex items-baseline gap-[0.16em] whitespace-nowrap", className)} aria-hidden>
      <span className="font-logo font-semibold tracking-[-0.03em] leading-none">cyberalert</span>
      <span className="self-center -translate-y-[0.06em] opacity-85">
        <BrandGlyph
          size={glyphSize ?? 20}
          accentColor={accentColor}
          className={glyphSize ? undefined : "h-[0.7em] w-[0.7em]"}
        />
      </span>
    </span>
  );
}
