import { cn } from "@/lib/cn";

interface Props {
  /** Multi-paragraph operational analysis. Paragraphs are separated by
   *  blank lines (`\n\n`). Empty / undefined → component renders nothing. */
  body: string | undefined;
  className?: string;
}

/**
 * Expanded analysis block — only on the detail page. Splits on blank
 * lines, renders each chunk as a `<p>` so paragraph spacing is
 * controlled by CSS rather than by inline `<br>` tags.
 *
 * No markdown rendering: the AI is instructed to produce plain text
 * paragraphs only. Markdown libraries would add ~50kb of JS for almost
 * no editorial benefit.
 */
export function DetailBody({ body, className }: Props) {
  const cleaned = (body ?? "").trim();
  if (!cleaned) return null;
  const paragraphs = cleaned
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (paragraphs.length === 0) return null;
  return (
    <div className={cn("space-y-4", className)}>
      {paragraphs.map((p, i) => (
        <p
          key={i}
          className="text-base text-text-primary leading-relaxed"
        >
          {p}
        </p>
      ))}
    </div>
  );
}
