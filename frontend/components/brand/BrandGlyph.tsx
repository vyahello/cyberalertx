import { cn } from "@/lib/cn";

interface Props {
  className?: string;
  /** Rendered pixel size (square). The artwork is drawn on a 100×100 grid
   *  internally and scales fluidly. Default 24px matches the header lockup. */
  size?: number;
  /** Override for the alert-ping color. The concentric rings always inherit
   *  `currentColor` so they theme through the parent's text color; the ping
   *  is the one visual signal that stays bright cyan across contexts. */
  accentColor?: string;
}

/**
 * The CyberAlertX brand glyph — direction 02 "Aperture".
 *
 * Three concentric radar rings + center bullseye + one offset cyan alert ping
 * at the upper-right. Rendered inline as SVG (no <img>, no /brand/glyph.svg
 * HTTP fetch) so the mark theme-inherits via `currentColor` and can be sized
 * fluidly. The same artwork lives on disk at /brand/glyph.svg for embeds,
 * README, and any partner / docs context that needs a standalone file.
 *
 * Story: "We see — and we surface what matters." The radar rings are the
 * noise (the constant scan); the ping is the one event the operator should
 * actually look at. Asymmetry is the whole point — the mark never reads as
 * a Wi-Fi icon, never as a target reticle.
 *
 * Color contract:
 *   - rings + center dot  → `currentColor` (parent owns the chrome tone)
 *   - alert ping          → `accentColor` (cyan, fixed-by-default)
 * The two-color split is what gives Aperture its read at 16px; collapsing
 * everything to one color kills the signal-vs-noise metaphor.
 */
export function BrandGlyph({
  className,
  size = 24,
  accentColor = "#00E5FF",
}: Props) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 100 100"
      width={size}
      height={size}
      role="img"
      aria-label="CyberAlertX"
      className={cn("flex-shrink-0", className)}
    >
      {/* Concentric radar rings — opacity falls off outward so the mark
          reads as a focused gaze, not a sonar pulse. */}
      <g fill="none" stroke="currentColor" strokeWidth={3.5}>
        <circle cx="50" cy="50" r="42" opacity="0.22" />
        <circle cx="50" cy="50" r="30" opacity="0.45" />
        <circle cx="50" cy="50" r="18" opacity="0.7" />
      </g>
      {/* Bullseye — same color family as the rings, fully opaque. The
          "we're locked on" anchor. */}
      <circle cx="50" cy="50" r="5" fill="currentColor" />
      {/* Alert ping — outer ring (translucent) is the broadcast, the
          inner solid disc is the actual hit. Cyan against any chrome. */}
      <circle
        cx="76"
        cy="24"
        r="14"
        fill="none"
        stroke={accentColor}
        strokeWidth={2}
        opacity={0.35}
      />
      <circle cx="76" cy="24" r="9" fill={accentColor} />
    </svg>
  );
}
