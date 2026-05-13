"use client";

import { useEffect, useState } from "react";
import { Clock } from "lucide-react";
import { fetchFeedHealth } from "@/lib/api";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

interface Props {
  lang: Locale;
}

/**
 * Subtle "Feed updated X ago" indicator for the header.
 *
 * Polls `/healthz` once on mount and again every 60s. Renders nothing
 * while loading or on failure — the indicator is decorative; missing it
 * never breaks the page.
 *
 * Two-line of intent visible to the reader:
 *   * The TIMESTAMP communicates pipeline aliveness without fake urgency.
 *   * The "Quiet day" annotation appears only when no urgent threat has
 *     landed for >12h — calming, not alarming. We frame the absence of
 *     news as a positive.
 *
 * Client component, but the JS payload is tiny (one fetch + state hook).
 */
export function FeedFreshness({ lang }: Props) {
  const s = strings(lang);
  const [latestPublishedAt, setLatestPublishedAt] = useState<string | null>(null);
  const [minutesSinceUrgent, setMinutesSinceUrgent] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      const health = await fetchFeedHealth({ revalidate: 0, timeoutMs: 4000 });
      if (cancelled || !health) return;
      setLatestPublishedAt(health.latest_published_at);
      setMinutesSinceUrgent(health.minutes_since_last_urgent);
    };
    refresh();
    const id = setInterval(refresh, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (!latestPublishedAt) return null;

  const ago = formatRelative(latestPublishedAt, s);
  const isQuiet = minutesSinceUrgent !== null && minutesSinceUrgent > 720; // 12h

  return (
    <div className="hidden sm:flex items-center gap-1.5 text-2xs text-text-tertiary">
      <Clock className="w-3 h-3" strokeWidth={2} aria-hidden />
      <span>
        <span className="text-text-secondary">{s.freshness_updated_prefix}</span>
        {" "}
        <span className="font-medium text-text-primary tabular-nums">{ago}</span>
      </span>
      {isQuiet && (
        // Calming annotation only — separate visual layer so it doesn't
        // compete with the timestamp. Dot prefix keeps it parsed as
        // metadata rather than as an alert.
        <span
          className="hidden md:inline-flex items-center text-text-tertiary"
          aria-label={s.freshness_quiet_day}
        >
          <span className="mx-2 w-1 h-1 rounded-full bg-border-strong" />
          {s.freshness_quiet_day}
        </span>
      )}
    </div>
  );
}

function formatRelative(
  iso: string,
  s: ReturnType<typeof strings>,
): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "—";
  const diffMin = Math.max(0, Math.floor((Date.now() - then) / 60_000));
  if (diffMin < 1) return s.freshness_just_now;
  if (diffMin < 60) return s.freshness_minutes_ago(diffMin);
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return s.freshness_hours_ago(diffHr);
  const diffDay = Math.floor(diffHr / 24);
  return s.freshness_days_ago(diffDay);
}
