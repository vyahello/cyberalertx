/**
 * The feed's client payload.
 *
 * FeedSection is a client component, so every post handed to it is
 * serialised into the page. A full post carries both editions' text, the
 * analysis, coverage and background context — none of which a feed row or a
 * filter reads. This keeps only what rows, filters and search use, for the
 * one locale being rendered.
 */
import type { Locale, LocalizedThreatPost } from "./types";

export function slimForFeed(
  posts: LocalizedThreatPost[],
  lang: Locale,
): LocalizedThreatPost[] {
  return posts.flatMap((p) => {
    const c = p.translations[lang];
    if (!c) return [];
    return [
      {
        id: p.id,
        source: p.source,
        source_url: "",
        source_tier: p.source_tier,
        source_credibility_score: p.source_credibility_score,
        published_at: p.published_at,
        threat_level: p.threat_level,
        category: p.category,
        affected_platforms: p.affected_platforms,
        audience_targets: p.audience_targets,
        actionability_level: p.actionability_level,
        actionability_score: p.actionability_score,
        emotional_weight: 0,
        source_language: p.source_language,
        available_locales: p.available_locales,
        story_source_count: p.story_source_count,
        signals: p.signals?.active_exploitation ? { active_exploitation: true } : undefined,
        // Only the status fields the feed rows show (not the unknowns list).
        evidence: p.evidence
          ? { ...p.evidence, unknowns: [] }
          : undefined,
        // The row's thumbnail: the story's canonical illustration (id + alt only).
        media: p.media?.illustration ? { illustration: p.media.illustration } : undefined,
        translations: {
          [lang]: {
            title: c.title,
            short_summary: c.short_summary,
            plain_summary: c.plain_summary,
            why_it_matters: "",
            affected_users: [],
            what_to_do: [],
            what_not_to_do: [],
            quick_facts: [],
            reading_time_seconds: 0,
            // Labels only: search matches "CVE-2026-…" without shipping URLs.
            references: (c.references ?? []).map((r) => ({ type: r.type, label: r.label, url: "" })),
          },
        },
      } satisfies LocalizedThreatPost,
    ];
  });
}
