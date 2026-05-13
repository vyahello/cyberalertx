import { cn } from "@/lib/cn";

interface Props {
  className?: string;
  /** Override pixel size. Defaults to 24px (matches /brand/glyph.svg viewBox). */
  size?: number;
}

/**
 * The CyberAlertX brand glyph — three stepped concentric arcs + accent dot.
 *
 * Rendered inline as SVG (no <img>, no /brand/glyph.svg HTTP fetch) so the
 * mark theme-inherits via `currentColor` and can be sized fluidly. The same
 * artwork lives on disk at /brand/glyph.svg for embeds, README, and any
 * partner / docs context that needs a standalone file.
 *
 * Concept: "Filtered Pulse". The arcs are the noise; the dot is the
 * signal that mattered. Deliberately asymmetric (dot offset from the arc
 * origin) so the mark never reads as a Wi-Fi icon.
 *
 * Color is inherited from the parent text color via `currentColor`. Wrap
 * in a `text-accent` element to get the brand azure; in `text-text-primary`
 * to render in the neutral text color (e.g. footer, monochrome contexts).
 */
export function BrandGlyph({ className, size = 24 }: Props) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      role="img"
      aria-label="CyberAlertX"
      className={cn("flex-shrink-0", className)}
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M3 4 A8 8 0 0 1 3 20" opacity="0.30" />
        <path d="M5 7 A5 5 0 0 1 5 17" opacity="0.55" />
        <path d="M7 9.5 A2.5 2.5 0 0 1 7 14.5" opacity="0.85" />
      </g>
      <circle cx="16" cy="12" r="2.5" fill="currentColor" />
    </svg>
  );
}
