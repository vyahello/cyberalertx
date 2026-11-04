import Link from "next/link";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import { severitySegments } from "@/lib/significance";
import { TOPIC_CATEGORIES, TOPIC_SLUGS, type TopicSlug } from "@/lib/topics";
import type { Locale, LocalizedThreatPost, ThreatLevel } from "@/lib/types";

const LEVELS: ThreatLevel[] = ["Critical", "High", "Medium", "Low"];
const FILL: Record<ThreatLevel, string> = {
  Critical: "bg-sev-critical",
  High: "bg-sev-high",
  Medium: "bg-sev-medium",
  Low: "bg-sev-low",
};

export interface OverviewCounts {
  total: number;
  byLevel: Record<ThreatLevel, number>;
  exploited: number;
  byTopic: Record<TopicSlug, number>;
}

/** Counts over the last `days` days of the pool. Pure, server-side. */
export function countOverview(
  posts: LocalizedThreatPost[],
  now: number,
  days = 7,
): OverviewCounts {
  const since = now - days * 86_400_000;
  const recent = posts.filter((p) => new Date(p.published_at).getTime() >= since);
  const byLevel = { Critical: 0, High: 0, Medium: 0, Low: 0 } as Record<ThreatLevel, number>;
  const byTopic = Object.fromEntries(TOPIC_SLUGS.map((t) => [t, 0])) as Record<TopicSlug, number>;
  let exploited = 0;
  for (const p of recent) {
    byLevel[p.threat_level] += 1;
    if (p.signals?.active_exploitation) exploited += 1;
    for (const t of TOPIC_SLUGS) {
      if ((TOPIC_CATEGORIES[t] as readonly string[]).includes(p.category)) byTopic[t] += 1;
    }
  }
  return { total: recent.length, byLevel, exploited, byTopic };
}

/**
 * The week in one glance: how many briefs, how they split by severity, how
 * many involve active exploitation, and which families they fall into. A
 * labelled bar list rather than one stacked bar: each value carries its own
 * word and number, so identity never depends on telling amber from yellow.
 * Every row is a way into the matching slice of the feed.
 */
export function ThreatOverview({
  counts,
  lang,
  className,
}: {
  counts: OverviewCounts;
  lang: Locale;
  className?: string;
}) {
  const s = strings(lang);
  if (counts.total === 0) return null;
  const max = Math.max(1, ...LEVELS.map((l) => counts.byLevel[l]));

  return (
    <div className={cn("font-sans", className)}>
      <h3 className="text-small font-semibold text-ink">
        {s.overview_heading}
        <span className="text-ink-faint font-normal"> · {s.overview_total(counts.total)}</span>
      </h3>

      <ul className="mt-4 space-y-1" aria-label={s.overview_by_severity}>
        {LEVELS.map((level) => {
          const n = counts.byLevel[level];
          const label = s.level[level];
          return (
            <li key={level}>
              <Link
                href={`/${lang}?level=${level}#feed`}
                prefetch={false}
                aria-label={s.overview_show(label, n)}
                className="group grid grid-cols-[6.5rem_minmax(0,1fr)_2.25rem] items-center gap-3 min-h-[36px]
                           text-small text-ink-muted hover:text-ink"
              >
                <span className="inline-flex items-center gap-2">
                  <span aria-hidden className="inline-flex items-end gap-[2px]">
                    {[1, 2, 3, 4].map((i) => (
                      <span
                        key={i}
                        className={cn("w-[4px]", i <= severitySegments(level) ? FILL[level] : "bg-ground-high")}
                        style={{ height: `${5 + i * 2}px` }}
                      />
                    ))}
                  </span>
                  {label}
                </span>
                <span className="h-2 bg-ground-raised">
                  <span
                    className={cn("block h-full rounded-r-[2px] transition-opacity group-hover:opacity-80", FILL[level])}
                    style={{ width: `${(n / max) * 100}%` }}
                  />
                </span>
                <span className="text-right text-ink tnum">{n}</span>
              </Link>
            </li>
          );
        })}
      </ul>

      {counts.exploited > 0 && (
        <Link
          href={`/${lang}?exploited=1#feed`}
          prefetch={false}
          className="mt-3 flex items-baseline justify-between gap-3 text-small text-sev-critical hover:underline underline-offset-4"
        >
          <span>{s.overview_exploited}</span>
          <span className="tnum font-semibold">{counts.exploited}</span>
        </Link>
      )}

      <h3 className="mt-6 text-small font-semibold text-ink">{s.overview_by_topic}</h3>
      <ul className="mt-2 space-y-1">
        {TOPIC_SLUGS.filter((t) => counts.byTopic[t] > 0).map((t) => (
          <li key={t}>
            <Link
              href={`/${lang}/topic/${t}`}
              prefetch={false}
              className="flex min-h-[32px] items-baseline justify-between gap-3 text-small text-ink-muted hover:text-ink"
            >
              <span className="underline decoration-ink-faint/40 underline-offset-4">{s.topic[t].name}</span>
              <span className="tnum text-ink">{counts.byTopic[t]}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
