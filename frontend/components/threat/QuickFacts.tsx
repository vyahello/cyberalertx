import { cn } from "@/lib/cn";

interface Props {
  facts: string[];
  className?: string;
}

/**
 * Horizontal row of mobile-scannable chips.
 *
 * Two notes on the visual treatment:
 *   - background instead of border — fewer pixels on a dense card
 *   - flex-wrap on small screens, single line on >=sm — the most common
 *     mobile mistake is forcing horizontal scroll for content the user
 *     definitely wants to see in one glance.
 */
export function QuickFacts({ facts, className }: Props) {
  if (!facts.length) return null;
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)} role="list">
      {facts.map((fact) => (
        <span
          key={fact}
          role="listitem"
          className="inline-flex items-center px-2 py-0.5 rounded-md
                     bg-bg-elevated-2 text-text-secondary text-xs
                     border border-transparent
                     transition-colors duration-150"
        >
          {fact}
        </span>
      ))}
    </div>
  );
}
