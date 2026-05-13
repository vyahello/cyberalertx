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
 * Polls `/healthz` once on mount and every 60s thereafter. Renders nothing
 * while loading or on failure — the indicator is decorative; missing it
 * never breaks the page.
 *
 * Facts-only. An earlier version appended a "Quiet day · no urgent
 * threats in 12h" annotation when `minutes_since_last_urgent > 720`.
 * Removed: the calming meta-message contradicted itself whenever the
 * feed had recent Critical / High items that weren't tagged
 * urgent_action — the card grid showed real threats while the header
 * claimed it was quiet. Card grid speaks for itself; the header should
 * only carry the freshness timestamp.
 */
export function FeedFreshness({ lang }: Props) {
  const s = strings(lang);
  const [latestPublishedAt, setLatestPublishedAt] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      const health = await fetchFeedHealth({ revalidate: 0, timeoutMs: 4000 });
      if (cancelled || !health) return;
      setLatestPublishedAt(health.latest_published_at);
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

  return (
    <div className="hidden sm:flex items-center gap-1.5 text-2xs text-text-tertiary">
      <Clock className="w-3 h-3" strokeWidth={2} aria-hidden />
      <span>
        <span className="text-text-secondary">{s.freshness_updated_prefix}</span>
        {" "}
        <span className="font-medium text-text-primary tabular-nums">{ago}</span>
      </span>
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
