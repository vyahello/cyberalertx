import { cn } from "@/lib/cn";

interface Props {
  /** Optional override for the pulse color — defaults to signal-live green. */
  color?: string;
  className?: string;
  size?: "sm" | "md";
}

/**
 * The signature "we're alive" indicator.
 *
 * Two concentric circles:
 *   - inner = solid dot, gently fades in/out (pulse-live keyframe)
 *   - outer = expanding ring (pulse-ring keyframe) that radiates outward
 *
 * The ring deliberately fades to 0 before the next iteration, so the
 * indicator never feels frantic — it's a "heartbeat", not a strobe.
 * The two animations share the same 2.4s duration to stay in phase.
 */
export function LivePulse({ className, size = "md" }: Props) {
  const dim = size === "sm" ? "w-2 h-2" : "w-2.5 h-2.5";
  return (
    <span className={cn("relative inline-flex", dim, className)} aria-hidden>
      <span
        className={cn(
          "absolute inset-0 rounded-full bg-signal-live opacity-40 animate-pulse-ring",
        )}
      />
      <span
        className={cn(
          "relative inline-flex rounded-full bg-signal-live animate-pulse-live",
          dim,
        )}
      />
    </span>
  );
}
