import { ExternalLink, Newspaper } from "lucide-react";
import { strings } from "@/lib/i18n";
import type { Locale, StoryCoverage as Coverage } from "@/lib/types";

interface Props {
  coverage: Coverage[] | undefined;
  lang: Locale;
  /** The source of the article being shown, so we can list it alongside. */
  currentSource: string;
  currentUrl: string;
}

/**
 * "Original reporting" — every outlet that covered this story.
 *
 * This is the visible payoff of story clustering. The backend recognizes
 * that BleepingComputer, The Hacker News and CISA all published the same
 * zero-day and collapses them into one post; without this block the reader
 * only ever sees the one we picked, and the work of noticing the other two
 * is invisible to them.
 *
 * Showing it turns a deduplication detail into a trust signal — three
 * independent outlets reporting the same thing is far stronger evidence
 * than anything we could assert about ourselves — and it gives the reader
 * a way out to the primary sources, which is what a serious intelligence
 * product owes them.
 *
 * Renders nothing for single-source stories, which are the majority.
 */
export function StoryCoverage({ coverage, lang, currentSource, currentUrl }: Props) {
  const others = (coverage ?? []).filter((c) => c.url && c.source !== currentSource);
  if (others.length === 0) return null;

  const s = strings(lang);
  const all = [
    { source: currentSource, url: currentUrl, primary: true },
    ...others.map((o) => ({ source: o.source, url: o.url, primary: false })),
  ];

  return (
    <section className="border-t border-border-subtle pt-6">
      <h2 className="inline-flex items-center gap-2 text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-1">
        <Newspaper className="w-3.5 h-3.5" aria-hidden />
        {s.story_coverage_heading}
      </h2>
      <p className="text-xs text-text-tertiary mb-3">{s.story_coverage_caption}</p>
      <ul className="flex flex-wrap gap-2">
        {all.map((entry) => (
          <li key={entry.url}>
            <a
              href={entry.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 min-h-[40px] sm:min-h-0
                         px-3 py-1.5 rounded-md border border-border-subtle
                         bg-bg-elevated-2 text-sm text-text-secondary
                         transition-colors duration-150
                         hover:border-border-strong hover:text-text-primary
                         active:border-border-strong"
            >
              {entry.source}
              <ExternalLink className="w-3 h-3 text-text-quaternary" aria-hidden />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
