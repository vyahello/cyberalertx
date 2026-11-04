/**
 * Front-page ordering.
 *
 * The feed itself is newest-first. The lead story and the "also significant
 * now" list are chosen by significance: how severe, whether it is being
 * exploited, whether the reader has to act, how many outlets confirmed it,
 * discounted by age so a three-day-old critical item doesn't sit on top all
 * week. Every input is a field the pipeline really produces; nothing here is
 * invented for display.
 */
import type { LocalizedThreatPost, ThreatLevel } from "./types";

const LEVEL_WEIGHT: Record<ThreatLevel, number> = {
  Critical: 4,
  High: 3,
  Medium: 2,
  Low: 1,
};

function recencyFactor(publishedAt: string, now: number): number {
  const ageHours = (now - new Date(publishedAt).getTime()) / 3_600_000;
  if (!Number.isFinite(ageHours)) return 0.2;
  if (ageHours <= 24) return 1;
  if (ageHours <= 48) return 0.8;
  if (ageHours <= 96) return 0.5;
  return 0.25;
}

export function significance(post: LocalizedThreatPost, now: number): number {
  let score = LEVEL_WEIGHT[post.threat_level] * 2;
  if (post.signals?.active_exploitation) score += 2;
  if (post.actionability_level === "urgent_action") score += 1.5;
  const outlets = post.story_source_count ?? 1;
  if (outlets > 1) score += Math.min(2, (outlets - 1) * 0.75);
  return score * recencyFactor(post.published_at, now);
}

export interface FrontPage {
  lead: LocalizedThreatPost | null;
  priority: LocalizedThreatPost[];
}

export function pickFrontPage(
  posts: LocalizedThreatPost[],
  now: number,
  priorityCount = 5,
): FrontPage {
  const ranked = posts
    .map((post) => ({ post, score: significance(post, now) }))
    .sort(
      (a, b) =>
        b.score - a.score ||
        new Date(b.post.published_at).getTime() - new Date(a.post.published_at).getTime(),
    )
    .map((x) => x.post);
  return { lead: ranked[0] ?? null, priority: ranked.slice(1, 1 + priorityCount) };
}

/** Severity as a count of filled segments, for the four-step SeverityMark. */
export function severitySegments(level: ThreatLevel): number {
  return LEVEL_WEIGHT[level];
}
